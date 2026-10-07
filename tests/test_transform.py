import csv

import duckdb
import pytest

from nad_pipeline import ingest
from nad_pipeline.rules.city import PlaceNames, choose_city, city_key
from nad_pipeline.transform import osm_glob, report_dir, transform_dir

from conftest import FIXTURE_ROWS

NAMES = PlaceNames([
    ("MA", "Bourne", "census_cousub"),
    ("MA", "Bourne", "gnis"),
    ("MO", "St. Louis", "census_place"),
    ("MO", "Saint Louis", "gnis"),
    ("MO", "St. Louis", "wikidata"),
    ("TX", "McAllen", "census_place"),
    ("IL", "O'Fallon", "census_place"),
    ("KY", "La Grange", "census_place"),
])


@pytest.mark.parametrize("a, b", [
    ("ST LOUIS", "St. Louis"), ("SAINT LOUIS", "St. Louis"), ("O FALLON", "O'Fallon"),
    ("LAGRANGE", "La Grange"), ("WINSTON SALEM", "Winston-Salem"), ("MT VERNON", "Mount Vernon"),
])
def test_city_key_ignores_spelling_conventions(a, b):
    assert city_key(a) == city_key(b)


@pytest.mark.parametrize("fields, state, expected, flags", [
    (("MCALLEN", "Unincorporated", None), "TX", "McAllen", []),
    (("Not stated", "BOURNE", "BOURNE"), "MA", "Bourne", ["city_from_inc_muni"]),
    (("Not stated", "UNINCORPORATED", "Sagamore Beach"), "MA", "Sagamore Beach",
     ["city_from_uninc_comm", "city_not_in_reference"]),
    (("ST LOUIS", None, None), "MO", "St. Louis", []),
    (("LAGRANGE", None, None), "KY", "La Grange", []),
    # Unknown in its own state, but spelled one way everywhere else.
    (("MCALLEN", None, None), "NM", "McAllen", []),
    (("EAST NOWHERE", None, None), "TX", "East Nowhere",
     ["city_not_in_reference", "city_cased_by_rule"]),
    (("Not stated", "Unincorporated", "<Null>"), "TX", None, ["no_city"]),
    ((None, None, None), "RI", None, ["no_city"]),
])
def test_choose_city(fields, state, expected, flags):
    assert choose_city(*fields, state, NAMES) == (expected, flags)


NAMES_AZ = PlaceNames([
    ("AZ", "Mesa", "census_place"), ("TX", "El Paso", "census_place"),
    ("WI", "Green Bay", "census_place"), ("KY", "Covington", "census_place"),
    ("WI", "West Bend", "census_place"), ("NE", "Omaha", "census_place"),
    ("TX", "Denton", "census_place"), ("MD", "North East", "census_place"),
])


@pytest.mark.parametrize("fields, state, county, expected, flags", [
    # Post office branch name in the postal city; the municipality is a known place.
    (("MESA FOUR PEAKS", "MESA", None), "AZ", "Maricopa", "Mesa",
     ["city_from_inc_muni", "unknown_post_city_skipped"]),
    # A name known only in another state does not outrank a local known place.
    (("NORTHEAST", "MESA", None), "AZ", "Maricopa", "Mesa",
     ["city_from_inc_muni", "unknown_post_city_skipped"]),
    (("CITY OF EL PASO", None, None), "TX", "El Paso", "El Paso", []),
    (("City of Green Bay", None, None), "WI", "Brown", "Green Bay", []),
    (("COVINGTON KY", None, None), "KY", "Kenton", "Covington", []),
    (("West Bend, WI", None, None), "WI", "Washington", "West Bend", []),
    # County names are not cities.
    (("DENTON COUNTY", "Unincorporated", None), "TX", "Denton", None, ["no_city"]),
    (("SARPY", None, None), "NE", "Sarpy", None, ["no_city"]),
    (("DOUGLAS COUNTY", "OMAHA", None), "NE", "Douglas", "Omaha", ["city_from_inc_muni"]),
    (("BRAZOS CO", None, None), "TX", "Brazos", None, ["no_city"]),
    (("75654", None, None), "TX", "Rusk", None, ["no_city"]),
    (("INCORPORATED", None, None), "ID", "Ada", None, ["no_city"]),
    # Descriptors appended to a known place name are removed.
    (("MESA CITY", None, None), "AZ", "Maricopa", "Mesa", []),
    (("Mesa 85201", None, None), "AZ", "Maricopa", "Mesa", []),
    (("971Xx", "MESA", None), "AZ", "Maricopa", "Mesa", ["city_from_inc_muni"]),
    (("Us 12 W", None, None), "WA", "Lewis", None, ["no_city"]),
    (("T1 R9 WELS", None, None), "ME", "Penobscot", "T1 R9 Wels",
     ["city_not_in_reference", "city_cased_by_rule"]),
    (("Omaha Area", None, None), "NE", "Douglas", "Omaha", []),
    # ...unless the city really shares the county's name.
    (("DENTON", None, None), "TX", "Denton", "Denton", []),
    (("ATL", None, None), "GA", "Fulton", "Atlanta", []),
    (("HOT SPRINGS NATIONAL PARK", None, None), "AR", "Garland", "Hot Springs National Park",
     ["city_not_in_reference", "city_cased_by_rule"]),
    (("ISLE OF PALMS", None, None), "SC", "Charleston", "Isle of Palms",
     ["city_not_in_reference", "city_cased_by_rule"]),
    (("LOMA DE LA CRUZ", None, None), "NM", "Taos", "Loma De La Cruz",
     ["city_not_in_reference", "city_cased_by_rule"]),
])
def test_choose_city_multi_input(fields, state, county, expected, flags):
    assert choose_city(*fields, state, NAMES_AZ, county) == (expected, flags)


def test_reference_conflict_resolved_by_vote():
    assert NAMES.lookup("MO", "SAINT LOUIS") == "St. Louis"
    assert NAMES.conflicts == [("MO", "St. Louis", {"St. Louis": 2, "Saint Louis": 1})]


@pytest.fixture
def osm(data_dir, nad_zip):
    ingest.ingest(nad_zip)
    out = transform_dir(data_dir / "r99" / "raw", data_dir / "r99" / "osm", NAMES)
    duckdb.execute(
        f"CREATE OR REPLACE VIEW osm AS SELECT * FROM "
        f"read_parquet('{osm_glob(out)}', hive_partitioning = false)"
    )
    return out


def test_transform_keeps_every_row(osm):
    assert duckdb.sql("SELECT count(*), count(DISTINCT nad_uuid) FROM osm").fetchall() == [
        (FIXTURE_ROWS, FIXTURE_ROWS)
    ]


def test_transform_first_row(osm):
    row = duckdb.sql(
        """SELECT addr_housenumber, addr_street, addr_unit, addr_city, addr_state,
                  addr_postcode, round(lon, 5), round(lat, 5), flags, drop_reason
           FROM osm WHERE nad_oid = '1'"""
    ).fetchone()
    assert row == ("114", "South Road", None, "Bourne", "MA", "02559", -70.64536, 41.68532,
                   ["city_from_inc_muni"], None)


def test_transform_output_is_clean(osm):
    all_caps_streets, all_caps_cities, kept = duckdb.sql(
        """SELECT count(*) FILTER (addr_street = upper(addr_street)
                                   AND regexp_matches(addr_street, '[A-Za-z]{3}')),
                  count(*) FILTER (addr_city = upper(addr_city)),
                  count(*) FILTER (drop_reason IS NULL)
           FROM osm"""
    ).fetchone()
    assert all_caps_streets == 0
    assert all_caps_cities == 0
    assert kept == FIXTURE_ROWS


def test_report_counts_outcomes(osm, tmp_path):
    paths = report_dir(osm, tmp_path / "report")
    with open(paths[0], newline="", encoding="utf-8") as f:
        drops = list(csv.DictReader(f))
    assert [(r["outcome"], int(r["n"])) for r in drops] == [("kept", FIXTURE_ROWS)]
