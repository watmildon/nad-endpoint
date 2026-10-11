"""Monthly history of OpenStreetMap address counts per Census county, from ohsome.

A one-off backfill behind the weekly Layercake counts of `nad osm-counts`. HeiGIT's ohsome
API answers "how many elements had addr:housenumber at each of these dates" for many
polygons in one request. Its v1 endpoint, the only one that takes many polygons at once
without an API key, closes on 2026-11-30 and its data stops at 2026-07-27, so the series
ends with July 2026.

ohsome counts a little differently from Layercake: open ways and every relation type are
included, and an element crossing a county line can count in each county it touches. The
two agree to within about 1% on the counties compared, but the series is kept in its own
file, labelled with its source, rather than spliced onto the weekly counts.

A request's time follows how much history its polygons hold more than how many dates it
asks for, so counties are batched by their current Layercake count. Polygons are the Census
counties simplified as one coverage, so neighbours still share their edges. Each batch's
answer is cached under data/osm-counts/ohsome/, so a run that stops part way resumes where
it left off. A batch the server says it cannot finish in time (413) is split in two and
retried: by counties, or for a single county by dates. Timeouts and 5xx answers are taken
for load instead, since the public server queues requests when busy, and are waited out.
"""

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import duckdb

from . import refdata
from .osmcount import counts_dir

URL = "https://api.ohsome.org/v1/elements/count/groupBy/boundary"
USER_AGENT = "nad-pipeline/0.1 (OSM address history backfill)"
FILTER = "addr:housenumber=*"
# The first of each month up to ohsome v1's last full month.
DATES = [f"{y}-{m:02d}-01" for y in range(2008, 2027) for m in range(1, 13) if (y, m) <= (2026, 7)]
SIMPLIFY = 0.001        # degrees; coverage simplification tolerance (~100 m)
PRECISION = 0.00001     # degrees; output coordinate grid (~1 m)
BUDGET = 500_000        # current addresses per request; ~2 min + ~0.3 s per 1k addresses
MAX_VERTICES = 100_000  # polygon vertices per request
RETRIES = 5
WAIT = 300              # seconds before a retry, times the attempt number
HISTORY = "osm-counts-history.json"


def history_path() -> Path:
    return counts_dir() / HISTORY


def osm_history(post=None, log=print) -> Path:
    ref = refdata.reference_dir()
    refdata.download_boundaries(ref, ["county"])
    shapes = county_shapes(refdata.boundary_file(ref, "county"))
    current = latest_counts()
    series = fetch_all(batches(shapes, current), DATES, post or post_ohsome,
                       counts_dir() / "ohsome", log)
    return write_history(history_path(), series)


def latest_counts() -> dict[str, int]:
    found = sorted(counts_dir().glob("osm-counts-2*.json"))
    if not found:
        raise FileNotFoundError("no OSM counts to size the batches by; run `nad osm-counts` first")
    return json.loads(found[-1].read_text(encoding="utf-8"))["counties"]


def county_shapes(counties: Path) -> list[tuple[str, dict, int]]:
    """(GEOID, GeoJSON geometry, vertex count) per county, in GEOID order."""
    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    con.execute(
        f"""
        CREATE TABLE county AS
        SELECT row_number() OVER (ORDER BY GEOID) AS i, GEOID AS geoid, geom::GEOMETRY AS geom
        FROM ST_Read('{counties.as_posix()}')
        """
    )
    rows = con.execute(
        f"""
        WITH merged AS (SELECT ST_CoverageSimplify(list(geom ORDER BY i), {SIMPLIFY}) AS g FROM county),
             parts AS (SELECT unnest(ST_Dump(g)) AS part FROM merged),
             simple AS (SELECT part.path[1] AS i,
                               ST_ReducePrecision(ST_Union_Agg(part.geom), {PRECISION}) AS geom
                        FROM parts GROUP BY 1)
        SELECT c.geoid, ST_AsGeoJSON(s.geom), ST_NPoints(s.geom)
        FROM county c JOIN simple s USING (i) ORDER BY c.geoid
        """
    ).fetchall()
    return [(geoid, json.loads(geometry), vertices) for geoid, geometry, vertices in rows]


def batches(shapes, current: dict[str, int], budget=BUDGET, max_vertices=MAX_VERTICES):
    """Runs of neighbouring counties (by GEOID) within the address and vertex budgets."""
    batch, load, vertices = [], 0, 0
    for shape in shapes:
        n = current.get(shape[0], 0)
        if batch and (load + n > budget or vertices + shape[2] > max_vertices):
            yield batch
            batch, load, vertices = [], 0, 0
        batch.append(shape)
        load += n
        vertices += shape[2]
    if batch:
        yield batch


def fetch_all(groups, dates: list[str], post, cache: Path, log) -> dict:
    """{'dates': [...], 'counties': {geoid: [count per date]}} over every batch."""
    cache.mkdir(parents=True, exist_ok=True)
    series: dict[str, list[int]] = {}
    for batch in groups:
        for geoid, counts in fetch_batch(batch, dates, post, cache, log).items():
            if [d for d, _ in counts] != dates:
                raise ValueError(f"ohsome returned other dates than asked for {geoid}")
            series[geoid] = [n for _, n in counts]
    return {"dates": dates, "counties": dict(sorted(series.items()))}


def fetch_batch(batch, dates: list[str], post, cache: Path, log) -> dict[str, list]:
    geoids = [geoid for geoid, _, _ in batch]
    key = hashlib.sha1(json.dumps([URL, FILTER, dates, SIMPLIFY, geoids]).encode()).hexdigest()
    cached = cache / f"{geoids[0]}-{key[:12]}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    features = [{"type": "Feature", "properties": {"id": geoid}, "geometry": geometry}
                for geoid, geometry, _ in batch]
    started = time.monotonic()
    try:
        result = parse(_retry(lambda: post(features, dates), log), geoids)
    except urllib.error.HTTPError as err:
        # ohsome answers 413 when a request would run past its time limit. Its queue can also
        # keep a request waiting well past that, but that is load, which _retry waits out.
        if err.code != 413 or len(batch) == len(dates) == 1:
            raise
        # Fewer counties first; a county too big on its own asks for fewer dates.
        if len(batch) > 1:
            log(f"  {geoids[0]}..{geoids[-1]}: {err}; splitting the counties")
            half = len(batch) // 2
            result = {**fetch_batch(batch[:half], dates, post, cache, log),
                      **fetch_batch(batch[half:], dates, post, cache, log)}
        else:
            log(f"  {geoids[0]} {dates[0]}..{dates[-1]}: {err}; splitting the dates")
            half = len(dates) // 2
            early = fetch_batch(batch, dates[:half], post, cache, log)[geoids[0]]
            late = fetch_batch(batch, dates[half:], post, cache, log)[geoids[0]]
            result = {geoids[0]: early + late}
    else:
        log(f"  {geoids[0]}..{geoids[-1]} ({len(batch)} counties): "
            f"{time.monotonic() - started:.0f} s")
    # A split batch is cached whole too, so a resumed run does not try it whole again.
    cached.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    return result


def _retry(call, log):
    """Wait out a busy server: timeouts, rate limiting, 5xx and dropped connections."""
    for attempt in range(RETRIES):
        try:
            return call()
        except urllib.error.HTTPError as err:
            # 4xx other than rate limiting will not get better by waiting.
            if err.code < 500 and err.code != 429 or attempt == RETRIES - 1:
                raise
            reason = err
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt == RETRIES - 1:
                raise
            reason = err
        wait = WAIT * (attempt + 1)
        log(f"  {reason}; waiting {wait} s")
        time.sleep(wait)


def parse(response: dict, geoids: list[str]) -> dict[str, list[tuple[str, int]]]:
    result = {
        group["groupByObject"]: [(r["timestamp"][:10], round(r["value"])) for r in group["result"]]
        for group in response["groupByResult"]
    }
    if sorted(result) != sorted(geoids):
        raise ValueError(f"ohsome answered for {sorted(result)}, asked for {sorted(geoids)}")
    return result


def post_ohsome(features: list[dict], dates: list[str]) -> dict:
    body = urllib.parse.urlencode({
        "bpolys": json.dumps({"type": "FeatureCollection", "features": features},
                             separators=(",", ":")),
        "filter": FILTER, "time": ",".join(dates), "format": "json",
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"User-Agent": USER_AGENT})
    # ohsome stops a request after 600 s of work, but a busy server queues it first.
    with urllib.request.urlopen(req, timeout=1800) as resp:
        return json.load(resp)


def write_history(out: Path, series: dict) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "source": "ohsome API v1, HeiGIT (https://ohsome.org)",
        "url": URL, "filter": FILTER, "built": date.today().isoformat(),
        "attribution": "© OpenStreetMap contributors",
        **series,
    }, separators=(",", ":")), encoding="utf-8")
    return out
