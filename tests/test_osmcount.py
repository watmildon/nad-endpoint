import json

import duckdb
import pytest

from nad_pipeline import config, osmcount, refdata

from test_backfill_dedup import geojson, square

REGIONS = {"test": (-88.0, 39.0, -83.0, 42.0)}


def write_layer(path, rows):
    """A Layercake-shaped addresses file from (type, id, housenumber, lon, lat, timestamp)."""
    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    con.execute("CREATE TABLE t (type VARCHAR, id BIGINT, hn VARCHAR, x DOUBLE, y DOUBLE, ts VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.execute(
        f"""
        COPY (
            SELECT type, id, hn AS "addr:housenumber", ts::TIMESTAMPTZ AS timestamp,
                   {{'xmin': x::FLOAT, 'ymin': y::FLOAT, 'xmax': x::FLOAT, 'ymax': y::FLOAT}} AS bbox,
                   ST_Point(x, y) AS geometry
            FROM t
        ) TO '{path.as_posix()}' (FORMAT parquet)
        """
    )
    return path.as_posix()


@pytest.fixture
def counties(tmp_path):
    return geojson(tmp_path / "counties.geojson", [
        square(-87, 40, -86, 41, GEOID="18001"),
        square(-86, 40, -85, 41, GEOID="18003"),
        square(-85, 40, -84, 41, GEOID="18005"),
    ])


T = "2026-10-01 12:00:00+00"


def test_counts_elements_with_a_housenumber_per_county(tmp_path, counties):
    layer = write_layer(tmp_path / "addresses.parquet", [
        ("node", 1, "12", -86.5, 40.5, T),
        ("way", 1, "14", -86.5, 40.6, T),
        ("relation", 1, "16", -86.4, 40.5, "2026-10-03 09:57:35+00"),
        ("node", 2, None, -86.5, 40.5, T),        # addr:housename only
        ("node", 3, "20", -85.5, 40.5, T),
        ("node", 4, "22", -87.5, 40.5, T),        # in the region, in no county
    ])
    counts, newest = osmcount.count_addresses(layer, counties, REGIONS)
    assert counts == {"18001": 3, "18003": 1, "18005": 0}
    assert newest == "2026-10-03T09:57:35Z"


def test_point_on_a_county_line_counts_once(tmp_path, counties):
    layer = write_layer(tmp_path / "addresses.parquet", [("node", 1, "1", -86.0, 40.5, T)])
    counts, _ = osmcount.count_addresses(layer, counties, REGIONS)
    assert sum(counts.values()) == 1


def test_county_outside_the_regions_fails(tmp_path, counties):
    layer = write_layer(tmp_path / "addresses.parquet", [("node", 1, "1", -86.5, 40.5, T)])
    with pytest.raises(ValueError, match="18005"):
        osmcount.count_addresses(layer, counties, {"west": (-88.0, 39.0, -84.5, 42.0)})


@pytest.fixture
def county_ref(tmp_path, monkeypatch, counties):
    """Point the stage at a test county file in place of the Census download."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(refdata, "download_boundaries", lambda ref, kinds: None)
    monkeypatch.setattr(refdata, "boundary_file", lambda ref, kind: counties)
    monkeypatch.setattr(osmcount, "REGIONS", REGIONS)


def test_osm_counts_writes_a_file_named_by_publication_date(tmp_path, county_ref):
    layer = write_layer(tmp_path / "addresses.parquet", [("node", 1, "1", -86.5, 40.5, T)])
    version = {"etag": '"abc"', "published": "2026-10-04"}
    out = osmcount.osm_counts(layer, version=lambda url: version)
    assert out == tmp_path / "data" / "osm-counts" / "osm-counts-2026-10-04.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["counties"] == {"18001": 1, "18003": 0, "18005": 0}
    assert data["addresses"] == 1
    assert (data["etag"], data["published"], data["url"]) == ('"abc"', "2026-10-04", layer)
    assert data["newest_edit"] == "2026-10-01T12:00:00Z"
    assert data["attribution"] == "© OpenStreetMap contributors"


def test_osm_counts_fails_when_the_file_is_replaced_during_the_read(tmp_path, county_ref):
    layer = write_layer(tmp_path / "addresses.parquet", [("node", 1, "1", -86.5, 40.5, T)])
    versions = iter([{"etag": '"old"', "published": "2026-10-04"},
                     {"etag": '"new"', "published": "2026-10-11"}])
    with pytest.raises(RuntimeError, match="replaced"):
        osmcount.osm_counts(layer, version=lambda url: next(versions))
    assert not (tmp_path / "data" / "osm-counts").exists()
