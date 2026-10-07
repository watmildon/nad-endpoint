"""Stage 5: fill missing cities from the original state datasets.

NAD's schema has no column for the MSAG community (the 911 community name), so that value
is lost when a state's data is loaded into NAD. Where NAD has no usable city, the state's
own dataset often still has this field. This stage fetches it and fills addr:city for rows
that have none, flagged city_from_source_msag.

Only sources published under terms that allow reuse without conditions are listed here.
"""

import csv
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import duckdb

from . import config
from .refdata import load_place_names
from .rules import clean
from .rules.city import PlaceNames
from .transform import osm_glob

PAGE_SIZE = 2000
WORKERS = 4
MATCH_METERS = 15
USER_AGENT = "nad-pipeline/0.1 (source supplement)"


@dataclass(frozen=True)
class Source:
    """An ArcGIS feature layer holding a state's address points."""

    url: str
    oid: str
    number: str
    community: str
    licence: str


SOURCES = {
    "KY": Source(
        url=("https://services3.arcgis.com/ghsX9CKghMvyYjBU/arcgis/rest/services/"
             "Ky_911_Site_Structure_Address_Points_gdb/FeatureServer/1"),
        oid="OBJECTID", number="Add_Number", community="MSAGComm",
        licence="CC0 1.0, stated on the dataset page (Kentucky DGI / 911 Services Board)",
    ),
    "IN": Source(
        url=("https://gisdata.in.gov/server/rest/services/Hosted/"
             "Address_Points_of_Indiana_Current/FeatureServer/0"),
        oid="objectid", number="add_number", community="msagcomm",
        licence="Credit requested but not required; provided as is (Indiana GIO)",
    ),
}


def _get_json(url: str, params: dict) -> dict:
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.load(resp)
            if "error" not in data:
                return data
            error = data["error"]
        except OSError as exc:
            error = exc
        time.sleep(5 * (attempt + 1))
    raise IOError(f"{url} failed after retries: {error}")


def source_dir(state: str) -> Path:
    return config.DATA_DIR / "sources" / state.lower()


def download_source(state: str, dest: Path | None = None, get_json=_get_json) -> Path:
    """Page through a source layer and save number, community and position as CSV.

    Rows with no community or no geometry are skipped: they cannot fill anything.
    """
    source = SOURCES[state]
    dest = dest or source_dir(state) / "communities.csv"
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    stats = json.dumps([
        {"statisticType": "min", "onStatisticField": source.oid, "outStatisticFieldName": "lo"},
        {"statisticType": "max", "onStatisticField": source.oid, "outStatisticFieldName": "hi"},
    ])
    span = get_json(source.url + "/query", {"where": "1=1", "outStatistics": stats, "f": "json"})
    span = {k.lower(): v for k, v in span["features"][0]["attributes"].items()}

    def page(start: int) -> list[tuple]:
        data = get_json(source.url + "/query", {
            "where": f"{source.oid} >= {start} AND {source.oid} < {start + PAGE_SIZE}",
            "outFields": f"{source.number},{source.community}",
            "outSR": 4326, "f": "json",
        })
        rows = []
        for feature in data["features"]:
            attributes, geometry = feature["attributes"], feature.get("geometry")
            community = clean(attributes.get(source.community))
            number = attributes.get(source.number)
            if community and geometry and number is not None:
                rows.append((number, community, geometry["x"], geometry["y"]))
        return rows

    part = dest.with_name(dest.name + ".part")
    with open(part, "w", encoding="utf-8", newline="") as f, \
            ThreadPoolExecutor(WORKERS) as pool:
        writer = csv.writer(f)
        writer.writerow(["number", "community", "lon", "lat"])
        for rows in pool.map(page, range(span["lo"], span["hi"] + 1, PAGE_SIZE)):
            writer.writerows(rows)
    part.replace(dest)
    return dest


def supplement(release: str, states=tuple(SOURCES)) -> Path:
    rel = config.release_dir(release)
    files = {state: download_source(state) for state in states}
    return supplement_dir(rel / "osm", rel / "supplemented", files, load_place_names(),
                          report=rel / "supplement_report.csv")


def supplement_dir(osm_dir: Path, out_dir: Path, source_files: dict[str, Path],
                   names: PlaceNames, report: Path | None = None) -> Path:
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    con.execute(
        f"""
        CREATE VIEW osm AS
        SELECT * FROM read_parquet('{osm_glob(osm_dir)}', hive_partitioning = false)
        """
    )
    con.execute(
        """CREATE TABLE source (state VARCHAR, number BIGINT, community VARCHAR,
                                lon DOUBLE, lat DOUBLE)"""
    )
    for state, path in source_files.items():
        con.execute(
            f"""
            INSERT INTO source
            SELECT '{state}', try_cast(number AS BIGINT), community, lon, lat
            FROM read_csv('{path.as_posix()}', header = true, delim = ',', quote = '"',
                          escape = '"', all_varchar = true)
            WHERE try_cast(number AS BIGINT) IS NOT NULL
            """
        )
    # A community is used only if it is a known place in that state; the reference also
    # supplies its proper spelling.
    con.execute("CREATE TABLE community_city (state VARCHAR, community VARCHAR, city VARCHAR)")
    communities = con.execute("SELECT DISTINCT state, community FROM source").fetchall()
    known = [(s, c, names.lookup(s, c, national=False)) for s, c in communities]
    if known:
        con.executemany("INSERT INTO community_city VALUES (?, ?, ?)", known)

    # Match a row to the source point with the same house number within MATCH_METERS,
    # nearest first. Grid cells of about 110 m keep the join small.
    degrees = MATCH_METERS / 111_320
    con.execute(
        f"""
        CREATE TABLE fill AS
        WITH need AS (
            SELECT nad_oid, addr_state AS state, lon, lat,
                   try_cast(regexp_extract(addr_housenumber, '(\\d+)', 1) AS BIGINT) AS number
            FROM osm WHERE drop_reason IS NULL AND addr_city IS NULL
        ), cells AS (
            SELECT s.*, floor(s.lat * 1000)::BIGINT + dy AS cy, floor(s.lon * 1000)::BIGINT + dx AS cx
            FROM source s, (VALUES (-1), (0), (1)) y(dy), (VALUES (-1), (0), (1)) x(dx)
        )
        SELECT n.nad_oid,
               arg_min(c.community, abs(c.lat - n.lat) + abs(c.lon - n.lon)) AS community,
               n.state
        FROM need n JOIN cells c
          ON c.state = n.state AND c.number = n.number
         AND c.cy = floor(n.lat * 1000)::BIGINT AND c.cx = floor(n.lon * 1000)::BIGINT
         AND abs(c.lat - n.lat) <= {degrees}
         AND abs(c.lon - n.lon) * cos(radians(n.lat)) <= {degrees}
        GROUP BY n.nad_oid, n.state
        """
    )
    con.execute(
        f"""
        COPY (
            SELECT osm.* REPLACE (
                coalesce(osm.addr_city, cc.city) AS addr_city,
                CASE WHEN osm.addr_city IS NULL AND cc.city IS NOT NULL
                     THEN list_sort(list_filter(osm.flags, f -> f <> 'no_city')
                                    || ['city_from_source_msag'])
                     ELSE osm.flags END AS flags
            )
            FROM osm
            LEFT JOIN fill USING (nad_oid)
            LEFT JOIN community_city cc
              ON cc.state = fill.state AND cc.community = fill.community
        ) TO '{out_dir.as_posix()}' (
            FORMAT parquet, COMPRESSION zstd, PARTITION_BY (addr_state),
            WRITE_PARTITION_COLUMNS true, OVERWRITE_OR_IGNORE
        )
        """
    )
    if report:
        con.execute(
            f"""
            COPY (
                SELECT fill.state, fill.community, cc.city AS filled_as, count(*) AS n_rows
                FROM fill LEFT JOIN community_city cc
                  ON cc.state = fill.state AND cc.community = fill.community
                GROUP BY ALL ORDER BY fill.state, n_rows DESC
            ) TO '{report.as_posix()}' (HEADER, DELIMITER ',')
            """
        )
    return out_dir
