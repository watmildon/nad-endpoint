"""Stage 8b: county coverage polygons for the web viewer.

The tileset starts at zoom 10, so on its own a viewer cannot answer "is there data in
Florida?" or "which of this is NAD and which came from sources/*.toml?". This stage counts
the kept points per Census county and per source and writes a GeoJSON of the counties that
have any, which the viewer draws at low zooms and `nad publish` uploads next to the tileset.

Points are binned to a 0.01 degree grid per source before the county lookup, which turns
~100M point-in-polygon tests into ~2M. Each bin goes to the county containing the mean
position of its points; a bin whose mean lies outside every county (coast, open water) goes
to the nearest county within SNAP degrees. County polygons are simplified as one coverage
so neighbouring counties still share their borders exactly.
"""

import json
from datetime import date
from pathlib import Path

import duckdb

from . import config, refdata
from .export import export_dir
from .sources import Source, load_sources
from .transform import osm_glob

GRID = 100          # bins per degree
SNAP = 0.05         # degrees; how far a bin outside every county may be snapped
SIMPLIFY = 0.01     # degrees; coverage simplification tolerance
PRECISION = 0.0001  # degrees; output coordinate grid (~10 m)


def coverage_path(release: str) -> Path:
    return export_dir(release) / f"nad-{release}-coverage.geojson"


def coverage(release: str) -> Path:
    ref = refdata.reference_dir()
    refdata.download_boundaries(ref)
    return write_coverage(
        config.release_dir(release) / "addresses", refdata.boundary_file(ref, "county"),
        load_sources(), release, coverage_path(release),
    )


def write_coverage(addresses_dir: Path, counties: Path, extra: list[Source], release: str,
                   out: Path) -> Path:
    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    con.execute("SET preserve_insertion_order = false")
    con.execute(
        f"""
        CREATE TABLE county AS
        SELECT row_number() OVER (ORDER BY GEOID) AS i, GEOID AS geoid, NAMELSAD AS name,
               STUSPS AS state, geom::GEOMETRY AS geom
        FROM ST_Read('{counties.as_posix()}')
        """
    )
    con.execute(
        f"""
        CREATE TABLE bins AS
        SELECT nad_source AS source, round(lon * {GRID})::INT AS gx, round(lat * {GRID})::INT AS gy,
               ST_Point(avg(lon), avg(lat)) AS pt, count(*) AS points
        FROM read_parquet('{osm_glob(addresses_dir)}', hive_partitioning = false)
        WHERE drop_reason IS NULL
        GROUP BY ALL
        """
    )
    con.execute(
        """
        CREATE TABLE bin_county AS
        SELECT b.source, b.gx, b.gy, min(c.i) AS i
        FROM bins b JOIN county c ON ST_Contains(c.geom, b.pt)
        GROUP BY ALL
        """
    )
    con.execute(
        f"""
        INSERT INTO bin_county
        SELECT b.source, b.gx, b.gy, arg_min(c.i, ST_Distance(c.geom, b.pt))
        FROM bins b ANTI JOIN bin_county USING (source, gx, gy)
        JOIN county c ON ST_DWithin(c.geom, b.pt, {SNAP})
        GROUP BY ALL
        """
    )
    unassigned = con.execute(
        "SELECT coalesce(sum(points), 0) FROM bins ANTI JOIN bin_county USING (source, gx, gy)"
    ).fetchone()[0]
    counts = con.execute(
        """
        SELECT bc.i, b.source, sum(b.points)::BIGINT AS points
        FROM bins b JOIN bin_county bc USING (source, gx, gy)
        GROUP BY ALL ORDER BY bc.i, points DESC, b.source
        """
    ).fetchall()
    con.execute(
        f"""
        CREATE TABLE simple AS
        WITH merged AS (SELECT ST_CoverageSimplify(list(geom ORDER BY i), {SIMPLIFY}) AS g FROM county),
             parts AS (SELECT unnest(ST_Dump(g)) AS part FROM merged)
        SELECT part.path[1] AS i, ST_ReducePrecision(ST_Union_Agg(part.geom), {PRECISION}) AS geom
        FROM parts GROUP BY 1
        """
    )
    covered = sorted({i for i, _, _ in counts})
    shapes = {
        i: (geoid, name, state, json.loads(geometry))
        for i, geoid, name, state, geometry in con.execute(
            f"""SELECT c.i, c.geoid, c.name, c.state, ST_AsGeoJSON(s.geom)
                FROM county c JOIN simple s USING (i)
                WHERE c.i IN ({", ".join(map(str, covered)) or "NULL"})"""
        ).fetchall()
    }
    return _write(out, release, counts, shapes, extra, unassigned)


def _write(out: Path, release: str, counts, shapes, extra: list[Source], unassigned: int) -> Path:
    extra_by_id = {s.id: s for s in extra}
    by_county: dict[int, list[tuple[str, int]]] = {}
    totals: dict[str, int] = {}
    for i, source, points in counts:
        by_county.setdefault(i, []).append((source, points))
        totals[source] = totals.get(source, 0) + points

    features = []
    for i, rows in by_county.items():
        geoid, name, state, geometry = shapes[i]
        other = sum(p for s, p in rows if s in extra_by_id)
        total = sum(p for _, p in rows)
        nad = total - other
        features.append({
            "type": "Feature",
            "properties": {
                "geoid": geoid, "name": name, "state": state, "points": total,
                "nad": nad, "other": other,
                "origin": "mixed" if nad and other else "other" if other else "nad",
                "sources": [{"id": s, "points": p} for s, p in rows],
            },
            "geometry": geometry,
        })

    sources = {}
    for source, points in sorted(totals.items(), key=lambda kv: -kv[1]):
        s = extra_by_id.get(source)
        if s is None:
            sources[source] = {"kind": "nad", "name": source, "points": points}
        else:
            sources[source] = {
                "kind": "other", "name": s.name, "publisher": s.publisher, "state": s.state,
                "licence": s.licence["name"], "page": s.page or s.url, "points": points,
            }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "type": "FeatureCollection",
        "release": release, "built": date.today().isoformat(),
        "points": sum(totals.values()) + unassigned, "unassigned": unassigned,
        "sources": sources, "features": features,
    }, separators=(",", ":")), encoding="utf-8")
    return out
