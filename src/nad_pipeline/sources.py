"""Extra address sources beyond NAD, declared in sources/*.toml.

Each file records where the data comes from, its licence and where that licence was read,
and how its fields map onto the NAD columns. `nad sources` fetches every source and writes
rows in the NAD raw layout to data/<release>/raw_extra/, which the transform stage reads
alongside NAD's own rows. The rest of the pipeline then treats them like any other source:
`NAD_Source` carries the source id so provenance survives to the audit output.

Only sources whose licence is explicitly in bounds for OSM belong here (see docs/
coverage-candidates.md, "Policy"); `load_sources` refuses anything else.
"""

import csv
import hashlib
import json
import time
import tomllib
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from . import config, refdata

SOURCES_DIR = config.REPO_ROOT / "sources"
ALLOWED_CLASSES = {"cc0", "public-domain", "pddl", "osm-waiver", "osm-permission"}
PAGE_SIZE = 2000
WORKERS = 4
USER_AGENT = "nad-pipeline/0.1 (extra sources)"
# The NAD columns an extra source can fill; everything else is left empty.
NAD_FIELDS = [
    "AddNum_Pre", "Add_Number", "AddNum_Suf", "St_PreDir", "St_PreTyp", "St_Name",
    "St_PosTyp", "St_PosDir", "Unit", "Post_City", "Inc_Muni", "Zip_Code", "Longitude",
    "Latitude",
]
# A WKT point column (Socrata's the_geom) can stand in for Longitude and Latitude.
POINT_WKT = "Point_WKT"


@dataclass(frozen=True)
class Source:
    id: str
    state: str
    name: str
    publisher: str
    protocol: str               # "arcgis" or "socrata"
    url: str
    licence: dict               # name, class, source, quote, verified, osm_clearance(_url)
    fields: dict                # NAD column -> source column, or list of columns to join
    record_id: str | None = None
    notes: str = ""
    page: str = ""              # human-readable landing page for the dataset
    workers: int = WORKERS      # parallel page requests; 1 for servers that rate-limit

    @property
    def dir(self) -> Path:
        return config.DATA_DIR / "sources" / self.id


def load_sources(directory: Path = SOURCES_DIR) -> list[Source]:
    sources = []
    for path in sorted(directory.glob("*.toml")):
        with open(path, "rb") as f:
            t = tomllib.load(f)
        licence = t["licence"]
        if licence["class"] not in ALLOWED_CLASSES:
            raise ValueError(f"{path.name}: licence class {licence['class']!r} is not in bounds")
        for key in ("name", "source", "quote", "verified"):
            if not licence.get(key):
                raise ValueError(f"{path.name}: licence.{key} is required")
        if licence["class"] in ("osm-waiver", "osm-permission") and not licence.get("osm_clearance_url"):
            raise ValueError(f"{path.name}: an OSM waiver needs licence.osm_clearance_url")
        unknown = set(t["fields"]) - set(NAD_FIELDS) - {"id", POINT_WKT}
        if unknown:
            raise ValueError(f"{path.name}: unknown field mapping {sorted(unknown)}")
        if not ({"Longitude", "Latitude"} <= set(t["fields"]) or POINT_WKT in t["fields"]):
            raise ValueError(f"{path.name}: map Longitude and Latitude, or {POINT_WKT}")
        sources.append(Source(
            id=path.stem, state=t["state"], name=t["name"], publisher=t["publisher"],
            protocol=t["access"]["protocol"], url=t["access"]["url"], licence=licence,
            fields={k: v for k, v in t["fields"].items() if k != "id"},
            record_id=t["fields"].get("id"), notes=t.get("notes", ""),
            page=t["access"].get("page", ""),
            workers=int(t["access"].get("workers", WORKERS)),
        ))
    return sources


def _get_json(url: str, params: dict, attempts: int = 4) -> dict:
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.load(resp)
            if "error" not in data:
                return data
            error = data["error"]
        except (OSError, ValueError) as exc:  # HTTP errors, timeouts, non-JSON (WAF) pages
            error = exc
        if attempt + 1 < attempts:
            time.sleep(10 * 3 ** attempt)  # 10 s, 30 s, 90 s: long enough for a rate limit
    raise IOError(f"{url} failed after {attempts} attempts: {error}")


def fetch_arcgis(source: Source, dest: Path, get_json=_get_json) -> Path:
    """Page a feature layer into a CSV of attributes plus WGS84 lon/lat."""
    meta = get_json(source.url, {"f": "json"})
    oid = meta.get("objectIdField") or next(
        f["name"] for f in meta["fields"] if f["type"] == "esriFieldTypeOID")
    size = min(PAGE_SIZE, meta.get("maxRecordCount") or PAGE_SIZE)
    stats = json.dumps([
        {"statisticType": "min", "onStatisticField": oid, "outStatisticFieldName": "lo"},
        {"statisticType": "max", "onStatisticField": oid, "outStatisticFieldName": "hi"},
    ])
    span = get_json(source.url + "/query", {"where": "1=1", "outStatistics": stats, "f": "json"})
    # MapServer layers report the statistics as floats.
    span = {k.lower(): int(v) for k, v in span["features"][0]["attributes"].items()}
    columns = [f["name"] for f in meta["fields"]]

    def page(start):
        data = get_json(source.url + "/query", {
            # BETWEEN rather than >= and <: some web application firewalls reject
            # comparison operators in the query string (Jefferson Parish answers 403).
            "where": f"{oid} BETWEEN {start} AND {start + size - 1}",
            "outFields": "*", "outSR": 4326, "returnGeometry": "true", "f": "json",
        })
        rows = []
        for feature in data["features"]:
            geometry = feature.get("geometry") or {}
            rows.append([feature["attributes"].get(c) for c in columns]
                        + [geometry.get("x"), geometry.get("y")])
        return rows

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with open(part, "w", encoding="utf-8", newline="") as f,             ThreadPoolExecutor(source.workers) as pool:
        writer = csv.writer(f)
        writer.writerow(columns + ["_lon", "_lat"])
        for rows in pool.map(page, range(span["lo"], span["hi"] + 1, size)):
            writer.writerows(rows)
    part.replace(dest)
    return dest


def fetch_socrata(source: Source, dest: Path, urlopen=urllib.request.urlopen) -> Path:
    """Download a Socrata CSV export as is; lon/lat come from its own columns."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(source.url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=600) as resp, open(part, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    part.replace(dest)
    return dest


def fetch(source: Source, **kw) -> Path:
    dest = source.dir / "raw.csv"
    if dest.exists():
        return dest
    if source.protocol == "arcgis":
        return fetch_arcgis(source, dest, **kw)
    if source.protocol == "socrata":
        return fetch_socrata(source, dest, **kw)
    raise ValueError(f"{source.id}: unknown protocol {source.protocol}")


def _column_sql(mapping) -> str:
    """SQL for one NAD column from a source column, or several joined with spaces."""
    cols = mapping if isinstance(mapping, list) else [mapping]
    parts = [f'nullif(trim(cast("{c}" AS VARCHAR)), \'\')' for c in cols]
    return parts[0] if len(parts) == 1 else f"nullif(concat_ws(' ', {', '.join(parts)}), '')"


def to_raw(source: Source, raw_csv: Path, out_dir: Path, counties: Path | None = None) -> Path:
    """Write the source's rows in the NAD raw layout, partitioned by State."""
    con = duckdb.connect()
    con.execute("LOAD spatial")
    con.execute("SET preserve_insertion_order = false")
    con.execute(
        f"""CREATE VIEW src AS SELECT * FROM read_csv('{raw_csv.as_posix()}', header = true,
            all_varchar = true, delim = ',', quote = '"', escape = '"')"""
    )
    mapped = {col: _column_sql(m) for col, m in source.fields.items() if col != POINT_WKT}
    if POINT_WKT in source.fields:
        point = f"ST_GeomFromText({_column_sql(source.fields[POINT_WKT])})"
        mapped["Longitude"] = f"CAST(ST_X({point}) AS VARCHAR)"
        mapped["Latitude"] = f"CAST(ST_Y({point}) AS VARCHAR)"
    record = _column_sql(source.record_id) if source.record_id else "NULL"
    columns = ", ".join(
        f"{mapped[c]} AS {c}" if c in mapped else f"NULL::VARCHAR AS {c}"
        for c in config.NAD_COLUMNS
        if c not in ("OID_", "UUID", "DataSet_ID", "State", "County", "NAD_Source",
                     "Placement", "AddrClass")
    )
    # Ids must be unique and stable between runs. The source's record id is used when it
    # has one; rows without one, or sharing one, get a key from their content instead.
    con.execute(
        f"""
        CREATE TABLE mapped AS
        WITH rows AS (
            SELECT {record} AS record_id, {columns} FROM src
            WHERE try_cast(Longitude AS DOUBLE) IS NOT NULL
              AND try_cast(Latitude AS DOUBLE) IS NOT NULL
        ), keyed AS (
            SELECT *, coalesce(record_id,
                               md5(concat_ws('|', Add_Number, St_Name, Unit, Longitude, Latitude)))
                      AS base_key,
                   row_number() OVER (PARTITION BY coalesce(record_id,
                       md5(concat_ws('|', Add_Number, St_Name, Unit, Longitude, Latitude)))
                       ORDER BY Longitude, Latitude, Add_Number, St_Name, Unit) AS copy
            FROM rows
        )
        SELECT '{source.id}:' || base_key || CASE WHEN copy > 1 THEN '#' || copy ELSE '' END AS OID_,
               {_uuid_sql(source)} AS UUID,
               keyed.* EXCLUDE (record_id, base_key, copy),
               '{source.state}' AS State, NULL::VARCHAR AS County,
               '{source.id}' AS NAD_Source, 'Unknown' AS Placement,
               'Numbered Thoroughfare Address' AS AddrClass
        FROM keyed
        """
    )
    if counties:
        con.execute(
            f"""CREATE TABLE county AS SELECT STUSPS AS state, NAME AS name, geom
                FROM ST_Read('{counties.as_posix()}') WHERE STUSPS = '{source.state}'"""
        )
        con.execute(
            """CREATE TABLE county_of AS
               SELECT m.OID_, min(c.name) AS County FROM mapped m JOIN county c
                 ON ST_Contains(c.geom, ST_Point(try_cast(m.Longitude AS DOUBLE),
                                                 try_cast(m.Latitude AS DOUBLE)))
               GROUP BY m.OID_"""
        )
    else:
        con.execute("CREATE TABLE county_of (OID_ VARCHAR, County VARCHAR)")
    (out_dir / f"State={source.state}").mkdir(parents=True, exist_ok=True)
    order = ", ".join(config.NAD_COLUMNS)
    con.execute(
        f"""
        COPY (
            SELECT {order} FROM (
                SELECT m.* EXCLUDE (County), m.UUID AS DataSet_ID, co.County
                FROM mapped m LEFT JOIN county_of co USING (OID_)
            )
        ) TO '{(out_dir / f"State={source.state}").as_posix()}/{source.id}.parquet'
          (FORMAT parquet, COMPRESSION zstd)
        """
    )
    return out_dir


def _uuid_sql(source: Source) -> str:
    """SQL for a UUID-shaped id derived from the row key, in NAD's braced upper-case form."""
    h = f"md5('{source.id}:' || base_key || CASE WHEN copy > 1 THEN '#' || copy ELSE '' END)"
    return ("'{' || upper(" + " || '-' || ".join(
        f"substr({h}, {start}, {length})" for start, length in ((1, 8), (9, 4), (13, 4), (17, 4), (21, 12))
    ) + ") || '}'")


def record_uuid(source: Source, key: str) -> str:
    """The UUID `_uuid_sql` produces for a row key (record id or content hash)."""
    h = hashlib.md5(f"{source.id}:{key}".encode()).hexdigest()
    return "{" + f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}".upper() + "}"


def raw_extra_dir(release: str) -> Path:
    return config.release_dir(release) / "raw_extra"


def build(release: str, only: list[str] | None = None) -> list[Path]:
    """Fetch every registered source and write its rows for the given release."""
    ref = refdata.reference_dir()
    refdata.download_boundaries(ref)
    counties = refdata.boundary_file(ref, "county")
    out = raw_extra_dir(release)
    written = []
    for source in load_sources():
        if only and source.id not in only:
            continue
        raw_csv = fetch(source)
        written.append(to_raw(source, raw_csv, out, counties))
        _write_manifest(source, raw_csv, out)
    return written


def _write_manifest(source: Source, raw_csv: Path, out: Path):
    rows = duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{(out / f'State={source.state}' / f'{source.id}.parquet').as_posix()}')"
    ).fetchone()[0]
    (source.dir / "manifest.json").write_text(json.dumps({
        "id": source.id, "name": source.name, "publisher": source.publisher,
        "licence": source.licence, "url": source.url, "rows": rows,
        "fetched": raw_csv.stat().st_mtime,
    }, indent=2, default=str))
