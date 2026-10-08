import json

import duckdb
import pytest

from nad_pipeline.coverage import write_coverage
from nad_pipeline.sources import Source

from test_backfill_dedup import geojson, square

LICENCE = {"name": "CC0 1.0", "class": "cc0", "source": "test", "quote": "CC0",
           "verified": "2026-10-07"}
EXTRA = Source("in-test-city", "IN", "Test City addresses", "Test City", "arcgis",
               "https://example/FeatureServer/0", LICENCE, {}, page="https://example/item")


def write_points(path, rows):
    """Kept and dropped points as (nad_source, lon, lat, drop_reason)."""
    con = duckdb.connect()
    con.execute("CREATE TABLE t (nad_source VARCHAR, lon DOUBLE, lat DOUBLE, drop_reason VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", rows)
    path.mkdir(parents=True)
    con.execute(f"COPY t TO '{(path / 'points.parquet').as_posix()}' (FORMAT parquet)")
    return path


@pytest.fixture
def counties(tmp_path):
    return geojson(tmp_path / "counties.geojson", [
        square(-87, 40, -86, 41, GEOID="18001", NAMELSAD="West County", STUSPS="IN"),
        square(-86, 40, -85, 41, GEOID="18003", NAMELSAD="East County", STUSPS="IN"),
        square(-85, 40, -84, 41, GEOID="18005", NAMELSAD="Empty County", STUSPS="IN"),
    ])


def build(tmp_path, counties, rows):
    addresses = write_points(tmp_path / "addresses", rows)
    out = write_coverage(addresses, counties, [EXTRA], "r99", tmp_path / "out" / "cov.geojson")
    data = json.loads(out.read_text(encoding="utf-8"))
    return data, {f["properties"]["geoid"]: f["properties"] for f in data["features"]}


def test_counts_points_per_county_and_source(tmp_path, counties):
    data, by_geoid = build(tmp_path, counties, [
        ("State of Indiana", -86.5, 40.5, None),
        ("State of Indiana", -86.5, 40.5, None),
        ("State of Indiana", -86.4, 40.6, "duplicate"),
        ("State of Indiana", -85.5, 40.5, None),
        ("in-test-city", -85.5, 40.5, None),
        ("in-test-city", -85.4, 40.4, None),
    ])
    assert set(by_geoid) == {"18001", "18003"}
    west, east = by_geoid["18001"], by_geoid["18003"]
    assert (west["name"], west["state"], west["points"], west["nad"], west["other"]) == \
        ("West County", "IN", 2, 2, 0)
    assert west["origin"] == "nad"
    assert (east["points"], east["nad"], east["other"], east["origin"]) == (3, 1, 2, "mixed")
    assert east["sources"] == [{"id": "in-test-city", "points": 2},
                               {"id": "State of Indiana", "points": 1}]
    assert data["release"] == "r99" and data["points"] == 5 and data["unassigned"] == 0
    assert data["sources"]["State of Indiana"] == {"kind": "nad", "name": "State of Indiana",
                                                   "points": 3}
    extra = data["sources"]["in-test-city"]
    assert extra["kind"] == "other" and extra["name"] == "Test City addresses"
    assert extra["licence"] == "CC0 1.0" and extra["page"] == "https://example/item"


def test_only_extra_sources_is_other(tmp_path, counties):
    _, by_geoid = build(tmp_path, counties, [("in-test-city", -86.5, 40.5, None)])
    assert by_geoid["18001"]["origin"] == "other"


def test_a_few_leaked_points_do_not_make_a_county_mixed(tmp_path, counties):
    rows = [("in-test-city", -86.5, 40.5, None)] * 40 + [("State of Indiana", -86.5, 40.5, None)]
    rows += [("State of Indiana", -85.5, 40.5, None)] * 40 + [("in-test-city", -85.5, 40.5, None)]
    _, by_geoid = build(tmp_path, counties, rows)
    assert (by_geoid["18001"]["origin"], by_geoid["18001"]["nad"]) == ("other", 1)
    assert (by_geoid["18003"]["origin"], by_geoid["18003"]["other"]) == ("nad", 1)


def test_points_just_outside_every_county_snap_to_the_nearest(tmp_path, counties):
    data, by_geoid = build(tmp_path, counties, [
        ("State of Indiana", -86.5, 40.5, None),
        ("State of Indiana", -86.5, 39.98, None),   # in the "water" just south of West County
        ("State of Indiana", -80.0, 30.0, None),    # nowhere near any county
    ])
    assert by_geoid["18001"]["points"] == 2
    assert data["points"] == 3 and data["unassigned"] == 1


def test_geometry_is_the_county_polygon(tmp_path, counties):
    data, _ = build(tmp_path, counties, [("State of Indiana", -86.5, 40.5, None)])
    geometry = data["features"][0]["geometry"]
    assert geometry["type"] in ("Polygon", "MultiPolygon")
    ring = geometry["coordinates"][0] if geometry["type"] == "Polygon" else geometry["coordinates"][0][0]
    assert {tuple(p) for p in ring} == {(-87, 40), (-86, 40), (-86, 41), (-87, 41)}
