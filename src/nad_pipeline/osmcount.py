"""OpenStreetMap address counts per Census county, for the web viewer.

Counts the OSM elements with addr:housenumber in each county, so the viewer can show how far
OSM has come and where the most addresses are still missing. The source is the addresses
layer of OSM US's Layercake (https://layercake.openstreetmap.us/layers/addresses/): one
GeoParquet file, rebuilt weekly, with a point per address node and per address area (closed
ways and multipolygons, reduced to a point on their surface). Open ways and other relation
types are not in it, and an address on a building and on a node inside it counts twice, so
the numbers are element counts, not distinct addresses.

The file is world wide but sorted along a Hilbert curve, so filtering on its bbox column
reads only the row groups around the US (about a quarter of its 5 GB). A point counts for a
county only when the county polygon contains it. Unlike `coverage`, strays are not snapped
to the nearest county: within snapping distance of the land borders lie ~100k Canadian and
Mexican addresses, against a few thousand US ones on piers and shores outside the
generalised polygons.

Counts do not depend on a NAD release, so they are kept under data/osm-counts/ by the date
Layercake published the file.
"""

import json
import urllib.request
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

import duckdb

from . import config, refdata

URL = "https://data.openstreetmap.us/layercake/addresses.parquet"
USER_AGENT = "nad-pipeline/0.1 (OSM address counts)"
# Boxes (west, south, east, north) holding every Census county; only these are read from the
# file. A county reaching outside them fails the run rather than being undercounted.
REGIONS = {
    "lower 48": (-124.9, 24.4, -66.8, 49.5),
    "alaska": (-180.0, 51.1, -129.8, 71.5),
    "aleutians west of 180": (172.3, 51.2, 180.0, 53.2),
    "hawaii": (-178.5, 18.8, -154.7, 28.5),
    "puerto rico and virgin islands": (-68.1, 17.6, -64.4, 18.6),
    "guam and northern marianas": (144.5, 13.1, 146.2, 20.7),
    "american samoa": (-171.2, -14.7, -168.0, -10.9),
}
CURRENT = "osm-counts-current.json"
HISTORY = "osm-counts-history.json"
SOURCE = "OpenStreetMap US Layercake, addresses layer"


def counts_dir() -> Path:
    return config.DATA_DIR / "osm-counts"


def layer_version(url: str = URL) -> dict:
    """ETag and publication date of the remote file."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        published = parsedate_to_datetime(resp.headers["Last-Modified"]).date()
        return {"etag": resp.headers["ETag"], "published": published.isoformat()}


def osm_counts(url: str = URL, version=layer_version) -> Path:
    ref = refdata.reference_dir()
    refdata.download_boundaries(ref, ["county"])
    before = version(url)
    counts, newest = count_addresses(url, refdata.boundary_file(ref, "county"))
    # Layercake replaces the file in place; a read that spans a rebuild mixes two weeks.
    if version(url)["etag"] != before["etag"]:
        raise RuntimeError(f"{url} was replaced while it was being read; run again")
    out = counts_dir() / f"osm-counts-{before['published']}.json"
    return write_counts(out, counts, newest, url, before)


def count_addresses(source: str, counties: Path, regions=REGIONS) -> tuple[dict[str, int], str | None]:
    """Elements with a house number per county GEOID (zero included), and the newest edit."""
    con = duckdb.connect()
    for extension in ("httpfs", "spatial"):
        con.execute(f"INSTALL {extension}")
        con.execute(f"LOAD {extension}")
    con.execute("SET preserve_insertion_order = false")
    con.execute(
        f"""
        CREATE TABLE county AS
        SELECT GEOID AS geoid, geom::GEOMETRY AS geom FROM ST_Read('{counties.as_posix()}')
        """
    )
    _check_regions(con, regions)
    # Points have xmin = xmax, so the lower corner is the point; these filters are what
    # let DuckDB skip the row groups outside the US.
    inside = " OR ".join(
        f"(bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s} AND {n})"
        for w, s, e, n in regions.values()
    )
    # A point on a shared county line goes to one of the two counties.
    con.execute(
        f"""
        CREATE TABLE hit AS
        SELECT min(c.geoid) AS geoid, any_value(a.timestamp) AS ts
        FROM read_parquet('{source}') a
        JOIN county c ON ST_Intersects(c.geom, a.geometry::GEOMETRY)
        WHERE a."addr:housenumber" IS NOT NULL AND ({inside})
        GROUP BY a.type, a.id
        """
    )
    counts = dict(con.execute(
        """
        SELECT c.geoid, count(h.geoid)
        FROM (SELECT DISTINCT geoid FROM county) c LEFT JOIN hit h USING (geoid)
        GROUP BY ALL ORDER BY ALL
        """
    ).fetchall())
    con.execute("SET TimeZone = 'UTC'")
    newest = con.execute("SELECT strftime(max(ts), '%Y-%m-%dT%H:%M:%SZ') FROM hit").fetchone()[0]
    return counts, newest


def _check_regions(con, regions):
    within = " OR ".join(
        f"(ST_XMin(g) >= {w} AND ST_YMin(g) >= {s} AND ST_XMax(g) <= {e} AND ST_YMax(g) <= {n})"
        for w, s, e, n in regions.values()
    )
    outside = [geoid for geoid, in con.execute(
        f"""
        SELECT DISTINCT geoid FROM (SELECT geoid, unnest(ST_Dump(geom)).geom AS g FROM county)
        WHERE NOT ({within}) ORDER BY 1
        """
    ).fetchall()]
    if outside:
        raise ValueError(f"counties reach outside REGIONS and would be undercounted: "
                         f"{', '.join(outside)}")


def write_counts(out: Path, counts: dict[str, int], newest: str | None, url: str,
                 version: dict) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "source": SOURCE,
        "url": url, "etag": version["etag"], "published": version["published"],
        "newest_edit": newest, "built": date.today().isoformat(),
        "attribution": "© OpenStreetMap contributors",
        "addresses": sum(counts.values()),
        "counties": counts,
    }, separators=(",", ":")), encoding="utf-8")
    return out


def append_to_history(history: dict, counts: dict) -> dict:
    """The history (from `nad osm-history`) with a week's counts added as its latest date.

    The date is that of the newest edit in the counts, the "as of" the viewer shows. Running
    the same week again replaces that week's counts; a week older than the history's latest
    date, or one landing on a date from another source, is refused rather than rewriting the
    past. The history's "segments" record which source covers which dates.
    """
    history = json.loads(json.dumps(history))  # a copy; the caller's stays as it was
    if "segments" not in history:
        # Written before segments existed: all of it is the one source named at the top.
        history["segments"] = [{
            "source": history.pop("source"), "url": history.pop("url"), "interval": "monthly",
            "from": history["dates"][0], "to": history["dates"][-1],
        }]
    day = (counts["newest_edit"] or counts["published"])[:10]
    dates, series = history["dates"], history["counties"]
    if set(counts["counties"]) != set(series):
        missing = sorted(set(series) - set(counts["counties"]))
        extra = sorted(set(counts["counties"]) - set(series))
        raise ValueError(f"the counts' counties differ from the history's: "
                         f"missing {missing[:10]}, extra {extra[:10]}")
    last = history["segments"][-1]
    weekly = last["source"] == SOURCE
    if day in dates:
        if not (weekly and last["from"] <= day):
            raise ValueError(f"{day} is already in the history from {last['source']}")
        i = dates.index(day)
        for geoid, n in counts["counties"].items():
            series[geoid][i] = n
    elif day > dates[-1]:
        dates.append(day)
        for geoid, n in counts["counties"].items():
            series[geoid].append(n)
        if weekly:
            last["to"] = day
        else:
            history["segments"].append({"source": SOURCE, "url": counts["url"],
                                        "interval": "weekly", "from": day, "to": day})
    else:
        raise ValueError(f"{day} is older than the history's latest date, {dates[-1]}")
    history["built"] = date.today().isoformat()
    return history
