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


OHSOME = {"source": "ohsome", "url": "https://ohsome", "interval": "monthly",
          "from": "2026-06-01", "to": "2026-07-01"}


def history(**extra):
    return {"filter": "addr:housenumber=*", "segments": [dict(OHSOME)],
            "dates": ["2026-06-01", "2026-07-01"],
            "counties": {"18001": [1, 2], "18003": [3, 4]}, **extra}


def week(day, counties=None, newest_edit=True):
    return {"url": osmcount.URL, "published": "2026-10-04",
            "newest_edit": f"{day}T09:57:35Z" if newest_edit else None,
            "counties": counties or {"18001": 5, "18003": 6}}


def test_a_week_is_added_after_the_monthly_history():
    before = history()
    after = osmcount.append_to_history(before, week("2026-10-03"))
    assert after["dates"] == ["2026-06-01", "2026-07-01", "2026-10-03"]
    assert after["counties"] == {"18001": [1, 2, 5], "18003": [3, 4, 6]}
    assert after["segments"] == [OHSOME, {"source": osmcount.SOURCE, "url": osmcount.URL,
                                          "interval": "weekly", "from": "2026-10-03",
                                          "to": "2026-10-03"}]
    assert before == history()  # the caller's copy is untouched


def test_later_weeks_extend_the_weekly_segment():
    h = osmcount.append_to_history(history(), week("2026-10-03"))
    h = osmcount.append_to_history(h, week("2026-10-10", {"18001": 7, "18003": 8}))
    assert h["dates"][-2:] == ["2026-10-03", "2026-10-10"]
    assert h["counties"]["18001"][-2:] == [5, 7]
    assert len(h["segments"]) == 2 and h["segments"][1]["to"] == "2026-10-10"


def test_the_same_week_again_replaces_its_counts():
    h = osmcount.append_to_history(history(), week("2026-10-03"))
    h = osmcount.append_to_history(h, week("2026-10-03", {"18001": 9, "18003": 9}))
    assert h["dates"] == ["2026-06-01", "2026-07-01", "2026-10-03"]
    assert h["counties"] == {"18001": [1, 2, 9], "18003": [3, 4, 9]}


def test_the_publication_date_stands_in_without_a_newest_edit():
    h = osmcount.append_to_history(history(), week("ignored", newest_edit=False))
    assert h["dates"][-1] == "2026-10-04"


@pytest.mark.parametrize("day, message", [
    ("2026-07-01", "already in the history from ohsome"),
    ("2026-06-15", "older than"),
])
def test_the_past_is_not_rewritten(day, message):
    with pytest.raises(ValueError, match=message):
        osmcount.append_to_history(history(), week(day))


def test_counties_must_match_the_history():
    with pytest.raises(ValueError, match=r"missing \['18003'\], extra \['18005'\]"):
        osmcount.append_to_history(history(), week("2026-10-03", {"18001": 1, "18005": 1}))


def test_a_history_without_segments_gets_one_for_its_source():
    legacy = history()
    del legacy["segments"]
    legacy.update(source="ohsome", url="https://ohsome")
    h = osmcount.append_to_history(legacy, week("2026-10-03"))
    assert "source" not in h and "url" not in h
    assert h["segments"][0] == OHSOME
