import csv
import json

import duckdb
import pytest

from nad_pipeline import config, sources
from nad_pipeline.sources import Source, fetch_arcgis, load_sources, to_raw

from test_backfill_dedup import geojson, square

LICENCE = {"name": "CC0 1.0", "class": "cc0", "source": "test", "quote": "CC0",
           "verified": "2026-10-07"}


def test_registry_loads_and_every_entry_is_in_bounds():
    loaded = load_sources()
    assert len(loaded) >= 10
    for s in loaded:
        assert s.licence["class"] in sources.ALLOWED_CLASSES
        assert s.licence["quote"] and s.licence["source"] and s.licence["verified"]
        assert s.protocol in ("arcgis", "socrata") and s.url.startswith("https://") or "jeffparish" in s.url
        assert {"Add_Number", "St_Name"} <= set(s.fields)
        assert {"Longitude", "Latitude"} <= set(s.fields) or "Point_WKT" in s.fields


def test_get_json_retries_then_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(sources.time, "sleep", lambda s: calls.append(s))

    def failing(req, timeout):
        raise OSError("HTTP Error 403")
    monkeypatch.setattr(sources.urllib.request, "urlopen", failing)
    with pytest.raises(IOError, match="after 3 attempts"):
        sources._get_json("https://x/query", {"f": "json"}, attempts=3)
    assert calls == [10, 30]


def test_registry_rejects_out_of_bounds_licence(tmp_path):
    (tmp_path / "bad.toml").write_text(
        'state = "TX"\nname = "x"\npublisher = "y"\n[access]\nprotocol = "arcgis"\nurl = "https://x"\n'
        '[licence]\nname = "CC BY 4.0"\nclass = "cc-by"\nsource = "s"\nquote = "q"\nverified = 2026-10-07\n'
        '[fields]\nAdd_Number = "n"\nSt_Name = "s"\nLongitude = "x"\nLatitude = "y"\n'
    )
    with pytest.raises(ValueError, match="not in bounds"):
        load_sources(tmp_path)


def test_registry_requires_a_position(tmp_path):
    (tmp_path / "bad.toml").write_text(
        'state = "TX"\nname = "x"\npublisher = "y"\n[access]\nprotocol = "arcgis"\nurl = "https://x"\n'
        '[licence]\nname = "CC0"\nclass = "cc0"\nsource = "s"\nquote = "q"\nverified = 2026-10-07\n'
        '[fields]\nAdd_Number = "n"\nSt_Name = "s"\n'
    )
    with pytest.raises(ValueError, match="Point_WKT"):
        load_sources(tmp_path)


def test_to_raw_takes_position_from_wkt(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    path = tmp_path / "raw.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rid", "num", "name", "the_geom"])
        w.writerow(["1", "721", "ROBERT ST", "POINT (-90.109036 29.918809)"])
        w.writerow(["2", "5", "NOWHERE", ""])
    source = Source("la-test", "LA", "t", "p", "socrata", "https://x", LICENCE,
                    {"Add_Number": "num", "St_Name": "name", "Point_WKT": "the_geom"}, "rid")
    out = to_raw(source, path, tmp_path / "raw_extra")
    rows = duckdb.sql(f"SELECT Add_Number, Longitude, Latitude FROM "
                      f"read_parquet('{(out / 'State=LA' / 'la-test.parquet').as_posix()}')").fetchall()
    assert rows == [("721", "-90.109036", "29.918809")]


def test_registry_rejects_unknown_field(tmp_path):
    (tmp_path / "bad.toml").write_text(
        'state = "TX"\nname = "x"\npublisher = "y"\n[access]\nprotocol = "arcgis"\nurl = "https://x"\n'
        '[licence]\nname = "CC0"\nclass = "cc0"\nsource = "s"\nquote = "q"\nverified = 2026-10-07\n'
        '[fields]\nAdd_Number = "n"\nSt_Name = "s"\nLongitude = "x"\nLatitude = "y"\nFloor = "f"\n'
    )
    with pytest.raises(ValueError, match="Floor"):
        load_sources(tmp_path)


def test_fetch_arcgis_pages_and_writes_wgs84(tmp_path):
    source = Source("x-test", "IN", "t", "p", "arcgis", "https://example/FeatureServer/0", LICENCE,
                    {"Add_Number": "num"}, "oid")
    features = {
        1: {"attributes": {"oid": 1, "num": "10"}, "geometry": {"x": -86.0, "y": 40.0}},
        2: {"attributes": {"oid": 2, "num": "11"}},  # no geometry
        3: {"attributes": {"oid": 3, "num": "12"}, "geometry": {"x": -86.1, "y": 40.1}},
    }

    def fake_get(url, params):
        if url.endswith("/0"):
            return {"maxRecordCount": 2, "objectIdField": "oid",
                    "fields": [{"name": "oid", "type": "esriFieldTypeOID"}, {"name": "num", "type": "x"}]}
        if "outStatistics" in params:
            return {"features": [{"attributes": {"LO": 1.0, "HI": 3.0}}]}  # MapServer floats
        assert params["outSR"] == 4326
        start = int(params["where"].split("BETWEEN ")[1].split(" ")[0])
        assert "<" not in params["where"] and ">" not in params["where"]
        return {"features": [features[i] for i in (start, start + 1) if i in features]}

    dest = fetch_arcgis(source, tmp_path / "raw.csv", get_json=fake_get)
    with open(dest, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows == [["oid", "num", "_lon", "_lat"], ["1", "10", "-86.0", "40.0"],
                    ["2", "11", "", ""], ["3", "12", "-86.1", "40.1"]]


@pytest.fixture
def raw_csv(tmp_path):
    path = tmp_path / "raw.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rid", "num", "frac", "pdir", "name", "typ", "unit_t", "unit_n", "zip", "_lon", "_lat"])
        w.writerow(["a1", "123", "", "N", "MAIN", "ST", "APT", "4", "47201", "-86.0", "40.0"])
        w.writerow(["a2", "125", "1/2", "", "OAK", "AVE", "", "", "", "-86.0", "40.0"])
        w.writerow(["a3", "9", "", "", "NOWHERE", "", "", "", "", "", ""])      # no coordinates
        w.writerow(["a4", "7", "", "", "FAR", "RD", "", "", "", "-80.0", "30.0"])  # outside the county
        w.writerow(["", "20", "", "", "NOID", "ST", "", "", "", "-86.0", "40.0"])    # no record id
        w.writerow(["a4", "7", "", "", "FAR", "RD", "", "", "", "-80.0", "30.0"])  # id reused
    return path


def test_to_raw_maps_fields_into_nad_layout(tmp_path, raw_csv, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    source = Source("in-test-city", "IN", "Test City addresses", "Test", "arcgis", "https://x",
                    LICENCE, {"Add_Number": "num", "AddNum_Suf": "frac", "St_PreDir": "pdir",
                              "St_Name": "name", "St_PosTyp": "typ", "Unit": ["unit_t", "unit_n"],
                              "Zip_Code": "zip", "Longitude": "_lon", "Latitude": "_lat"}, "rid")
    counties = geojson(tmp_path / "counties.geojson", [
        square(-86.1, 39.9, -85.9, 40.1, STUSPS="IN", NAME="Bartholomew"),
        square(-80.1, 29.9, -79.9, 30.1, STUSPS="FL", NAME="Elsewhere"),
    ])
    out = to_raw(source, raw_csv, tmp_path / "raw_extra", counties)
    rows = duckdb.sql(
        f"""SELECT OID_, UUID, Add_Number, AddNum_Suf, St_PreDir, St_Name, St_PosTyp, Unit, Zip_Code,
                   State, County, NAD_Source, Placement, Longitude, Latitude
            FROM read_parquet('{(out / "State=IN" / "in-test-city.parquet").as_posix()}')
            ORDER BY OID_"""
    ).fetchall()
    oids = [r[0] for r in rows]
    assert oids[:3] == ["in-test-city:a1", "in-test-city:a2", "in-test-city:a4"]
    assert "in-test-city:a4#2" in oids and len(oids) == 5 and len(set(r[1] for r in rows)) == 5
    assert rows[0][2:] == ("123", None, "N", "MAIN", "ST", "APT 4", "47201", "IN", "Bartholomew",
                           "in-test-city", "Unknown", "-86.0", "40.0")
    assert rows[1][3] == "1/2" and rows[1][7] is None and rows[1][8] is None
    assert rows[2][10] is None  # outside every Indiana county polygon
    # UUIDs are deterministic and look like NAD's.
    assert rows[0][1] == sources.record_uuid(source, "a1")
    assert rows[0][1].startswith("{") and len(rows[0][1]) == 38
    columns = duckdb.sql(
        f"SELECT * FROM read_parquet('{(out / 'State=IN' / 'in-test-city.parquet').as_posix()}') LIMIT 0"
    ).columns
    assert columns == config.NAD_COLUMNS


def test_transform_reads_extra_sources(tmp_path, raw_csv, monkeypatch, data_dir, nad_zip):
    from nad_pipeline import ingest
    from nad_pipeline.rules.city import PlaceNames
    from nad_pipeline.transform import osm_glob, transform_dir

    ingest.ingest(nad_zip)
    source = Source("in-test-city", "IN", "t", "p", "arcgis", "https://x", LICENCE,
                    {"Add_Number": "num", "St_PreDir": "pdir", "St_Name": "name", "St_PosTyp": "typ",
                     "Longitude": "_lon", "Latitude": "_lat"}, "rid")
    extra = to_raw(source, raw_csv, data_dir / "r99" / "raw_extra")
    out = transform_dir(data_dir / "r99" / "raw", data_dir / "r99" / "osm", PlaceNames([]), extra)
    rows = duckdb.sql(
        f"""SELECT nad_source, addr_street, addr_state FROM read_parquet('{osm_glob(out)}',
            hive_partitioning = false) WHERE nad_source = 'in-test-city' ORDER BY nad_oid"""
    ).fetchall()
    assert [r[1] for r in rows] == ["North Main Street", "Oak Avenue", "Far Road", "Far Road",
                                     "Noid Street"]
    total = duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{osm_glob(out)}', hive_partitioning = false)").fetchone()[0]
    assert total == 300 + 5
