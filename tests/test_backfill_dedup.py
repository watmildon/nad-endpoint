import json

import duckdb
import pytest

from nad_pipeline.backfill import backfill_dir, place_city_name
from nad_pipeline.dedup import dedup_dir
from nad_pipeline.transform import osm_glob

COLUMNS = ("nad_oid", "lon", "lat", "addr_housenumber", "addr_street", "addr_unit",
           "addr_city", "addr_state", "addr_postcode", "county", "placement", "date_update",
           "flags", "drop_reason")


def row(oid, lon=-86.0, lat=40.0, number="1", street="Oak Street", unit=None, city="Columbus",
        state="IN", postcode="47201", county="Bartholomew", placement="Unknown",
        updated="2020-01-01", flags=(), drop=None):
    return (str(oid), lon, lat, number, street, unit, city, state, postcode, county, placement,
            updated, list(flags), drop)


def write_points(path, rows):
    con = duckdb.connect()
    con.execute(
        """CREATE TABLE t (nad_oid VARCHAR, lon DOUBLE, lat DOUBLE, addr_housenumber VARCHAR,
               addr_street VARCHAR, addr_unit VARCHAR, addr_city VARCHAR, addr_state VARCHAR,
               addr_postcode VARCHAR, county VARCHAR, placement VARCHAR, date_update VARCHAR,
               flags VARCHAR[], drop_reason VARCHAR)"""
    )
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    path.mkdir(parents=True)
    con.execute(f"COPY t TO '{(path / 'points.parquet').as_posix()}' (FORMAT parquet)")
    return path


def read_points(path, columns):
    rows = duckdb.sql(
        f"SELECT {columns} FROM read_parquet('{osm_glob(path)}', hive_partitioning = false) "
        "ORDER BY try_cast(nad_oid AS INT) NULLS LAST, nad_oid"
    ).fetchall()
    return rows


def square(west, south, east, north, **properties):
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"type": "Feature", "properties": properties,
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


def geojson(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return path


@pytest.mark.parametrize("name, expected", [
    ("Richmond", "Richmond"),
    ("Winston-Salem", "Winston-Salem"),
    ("Indianapolis city (balance)", "Indianapolis"),
    ("Nashville-Davidson metropolitan government (balance)", "Nashville"),
    ("Louisville/Jefferson County metro government (balance)", "Louisville"),
    ("Athens-Clarke County unified government (balance)", "Athens"),
])
def test_place_city_name(name, expected):
    assert place_city_name(name) == expected


@pytest.fixture
def boundaries(tmp_path):
    return dict(
        places=geojson(tmp_path / "places.geojson", [
            square(-86.1, 39.9, -85.9, 40.1, STUSPS="IN", NAME="Columbus"),
            square(-71.5, 41.4, -71.3, 41.6, STUSPS="RI", NAME="Newport"),
        ]),
        cousubs=geojson(tmp_path / "cousubs.geojson", [
            square(-71.7, 41.2, -71.2, 41.8, STUSPS="RI", NAME="Middletown",
                   NAMELSAD="Middletown town"),
            square(-87.0, 39.0, -85.0, 41.0, STUSPS="IN", NAME="Columbus",
                   NAMELSAD="Columbus township"),
        ]),
        zctas=geojson(tmp_path / "zctas.geojson", [
            square(-86.1, 39.9, -85.9, 40.1, ZCTA5CE20="47201"),
        ]),
    )


def test_backfill_fills_only_missing_values(tmp_path, boundaries):
    src = write_points(tmp_path / "osm", [
        row(1, city=None, postcode=None, flags=["no_city"]),            # inside Columbus
        row(2, city="Elsewhere", postcode="99999"),                     # already has both
        row(3, lon=-86.5, city=None, flags=["no_city"]),                # outside any place
        row(4, lon=-71.4, lat=41.5, state="RI", city=None, postcode=None, flags=["no_city"]),
        row(5, lon=-71.6, lat=41.3, state="RI", city=None, flags=["no_city"]),  # town only
        row(6, city=None, drop="inactive_lifecycle", flags=["no_city"]),
        row(7, state="KY", city=None, flags=["no_city"]),               # place of another state
    ])
    out = backfill_dir(src, tmp_path / "filled", **boundaries)
    assert read_points(out, "addr_city, addr_postcode, flags") == [
        ("Columbus", "47201", ["city_from_census_place", "postcode_from_zcta"]),
        ("Elsewhere", "99999", []),
        (None, "47201", ["no_city"]),
        ("Newport", None, ["city_from_census_place"]),
        ("Middletown", "47201", ["city_from_census_cousub"]),
        (None, "47201", ["no_city"]),
        (None, "47201", ["no_city"]),
    ]


def test_dedup_keeps_best_nearby_copy(tmp_path):
    src = write_points(tmp_path / "filled", [
        row(1, placement="Unknown", updated="2024-01-01"),
        row(2, placement="Structure - Rooftop", updated="2019-01-01"),   # best placement
        row(3, placement="Structure - Rooftop", updated="2015-01-01"),
        row(4, lat=40.0005),                                              # 55 m away
        row(5, unit="A"),                                                 # different unit
        row(6, street="Elm Street"),
        row(7, drop="inactive_lifecycle"),
        row(8, number="1", street="OAK STREET", county="Brown"),          # another county
    ])
    out = dedup_dir(src, tmp_path / "addresses")
    assert read_points(out, "nad_oid, drop_reason, flags") == [
        ("1", "duplicate", []),
        ("2", None, []),
        ("3", "duplicate", []),
        ("4", "duplicate", []),
        ("5", None, []),
        ("6", None, []),
        ("7", "inactive_lifecycle", []),
        ("8", None, []),
    ]


def test_dedup_ignores_county_descriptor(tmp_path):
    src = write_points(tmp_path / "filled", [
        row(1, state="LA", county="Orleans Parish", placement="Site"),
        row("la-new-orleans:9", state="LA", county="Orleans", lat=40.0001),
        row(2, state="AK", county="Anchorage Municipality"),
        row(3, state="AK", county="Anchorage", number="1", lat=40.0002),
    ])
    out = dedup_dir(src, tmp_path / "addresses")
    assert sorted(read_points(out, "nad_oid, drop_reason")) == [
        ("1", None), ("2", None), ("3", "duplicate"), ("la-new-orleans:9", "duplicate"),
    ]


def test_dedup_prefers_nad_over_an_extra_source_copy(tmp_path):
    # Extra sources carry text ids ("ca-fresno-county:12"); NAD's numeric ids win a tie.
    src = write_points(tmp_path / "filled", [
        row("ca-fresno-county:12", lat=40.0001),
        row(5),
    ])
    out = dedup_dir(src, tmp_path / "addresses")
    assert sorted(read_points(out, "nad_oid, drop_reason")) == [
        ("5", None), ("ca-fresno-county:12", "duplicate"),
    ]


def test_dedup_flags_same_address_far_apart(tmp_path):
    src = write_points(tmp_path / "filled", [
        row(1, placement="Site"),
        row(2, lat=40.02),              # about 2.2 km away: kept and flagged
        row(3, lat=40.0001),            # nearby copy of row 1
        row(4, number="9"), row(5, number="9"),   # plain duplicate pair, nothing far away
    ])
    out = dedup_dir(src, tmp_path / "addresses")
    assert read_points(out, "nad_oid, drop_reason, flags") == [
        ("1", None, ["same_address_elsewhere"]),
        ("2", None, ["same_address_elsewhere"]),
        ("3", "duplicate", []),
        ("4", None, []),
        ("5", "duplicate", []),
    ]


def test_same_address_in_another_city_is_normal(tmp_path):
    src = write_points(tmp_path / "filled", [
        row(1, city="Dickinson"),
        row(2, lat=40.2, city="Galveston"),          # same county, different city: fine
        row(3, lat=40.00001, city="DICKINSON TX"),   # same spot, sources disagree on city
        row(4, lat=40.2001, city="Galveston"),       # nearby copy of row 2
    ])
    out = dedup_dir(src, tmp_path / "addresses")
    assert read_points(out, "nad_oid, drop_reason, flags") == [
        ("1", None, []),
        ("2", None, []),
        ("3", "duplicate", []),
        ("4", "duplicate", []),
    ]
