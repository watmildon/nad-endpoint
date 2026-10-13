import csv

import duckdb
import pytest

from nad_pipeline import ingest
from nad_pipeline.rules.city import (
    ACTIONS, Override, PlaceNames, choose_city, city_key, county_key, edit_distance,
    load_city_overrides,
)
from nad_pipeline.transform import osm_glob, report_dir, transform_dir

from conftest import FIXTURE_ROWS

# The placeholders every state drops ("Unincorporated", "Matched"), from the overrides file.
PLACEHOLDERS = [o for o in load_city_overrides() if o.state == "*"]

NAMES = PlaceNames([
    ("MA", "Bourne", "census_cousub"),
    ("MA", "Bourne", "gnis"),
    ("MO", "St. Louis", "census_place"),
    ("MO", "Saint Louis", "gnis"),
    ("MO", "St. Louis", "wikidata"),
    ("TX", "McAllen", "census_place"),
    ("IL", "O'Fallon", "census_place"),
    ("KY", "La Grange", "census_place"),
], overrides=PLACEHOLDERS)


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
    # Unknown in its own state, but spelled one way everywhere else: that spelling, flagged.
    (("MCALLEN", None, None), "NM", "McAllen", ["city_not_in_reference"]),
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
    ("GA", "Atlanta", "census_place"),
], overrides=PLACEHOLDERS + [o for o in load_city_overrides() if (o.state, o.value) == ("GA", "ATL")])


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
    # An office code fixed by the overrides file, statewide.
    (("ATL", None, None), "GA", "Fulton", "Atlanta", ["city_typo_fixed"]),
    (("HILL AFB", None, None), "UT", "Davis", "Hill AFB",
     ["city_not_in_reference", "city_cased_by_rule"]),
    (("MATCHED", "Unincorporated", None), "ME", "Aroostook", None, ["no_city"]),
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


@pytest.mark.parametrize("a, b", [
    ("ESPANOLA", "Española"), ("PENASCO", "Peñasco"), ("CANONES", "Cañones"),
    ("E CARONDELET", "East Carondelet"), ("S. Paris", "South Paris"),
    ("THOMPSONS STATION", "Thompson's Station"), ("S.N.P.J.", "SNPJ"),
])
def test_city_key_folds_accents_and_leading_directions(a, b):
    assert city_key(a) == city_key(b)


@pytest.mark.parametrize("a, b", [
    # A trailing possessive "s" is not South; an initialism's first letter is not either.
    ("THOMPSONS STATION", "Thompson South Station"), ("S.N.P.J.", "South NPJ"),
])
def test_city_key_keeps_possessives_and_initialisms(a, b):
    assert city_key(a) != city_key(b)


@pytest.mark.parametrize("a, b, distance", [
    ("misison", "mission", 1), ("coben", "cobden", 1), ("frazysburg", "frazeysburg", 1),
    ("plain", "plains", 1), ("hartsville", "hartselle", 2), ("adk", "atlanta", 6),
    ("", "abc", 3),
])
def test_edit_distance(a, b, distance):
    assert edit_distance(a, b) == distance == edit_distance(b, a)


NAMES_POSTAL = PlaceNames([
    ("NM", "Española", "census_place"), ("NM", "Hernandez", "census_place"),
    ("PA", "Whitemarsh Township", "census_cousub"), ("NY", "Cortlandt", "census_cousub"),
    ("NY", "Harrison", "census_cousub"), ("IN", "West Harrison", "census_place"),
    ("AR", "Hot Springs", "census_place"), ("AZ", "Phoenix", "census_place"),
    ("IL", "Cobden", "census_place"), ("IL", "East Carondelet", "census_place"),
    ("MT", "Plains", "census_place"), ("WA", "Plain", "gnis"), ("GA", "Atlanta", "census_place"),
    ("SD", "Mission", "census_place"), ("SD", "Antelope", "census_place"),
    ("KY", "Wayland", "census_place"),
], overrides=PLACEHOLDERS)


@pytest.mark.parametrize("fields, state, expected, flags", [
    # Accents: the postal city is a known place, so the community does not replace it.
    (("ESPANOLA", "ESPANOLA", "HERNANDEZ"), "NM", "Española", []),
    # Real USPS names missing from the reference are kept, not replaced by the municipality.
    (("Lafayette Hill", "Whitemarsh Township", None), "PA", "Lafayette Hill",
     ["city_not_in_reference"]),
    (("Cortlandt Manor", "Cortlandt", None), "NY", "Cortlandt Manor", ["city_not_in_reference"]),
    (("CORTLANDT MANOR", "CORTLANDT", None), "NY", "Cortlandt Manor",
     ["city_not_in_reference", "city_cased_by_rule"]),
    (("West Harrison", "Harrison", None), "NY", "West Harrison", ["city_not_in_reference"]),
    (("Hot Springs National Park", "Hot Springs", None), "AR", "Hot Springs National Park",
     ["city_not_in_reference"]),
    (("Hueysville", "UNINCORPORATED", "Wayland"), "KY", "Hueysville", ["city_not_in_reference"]),
    # Arizona's postal city holds station names, with or without the city's name in them.
    (("SOUTH MOUNTAIN", "PHOENIX", None), "AZ", "Phoenix",
     ["city_from_inc_muni", "unknown_post_city_skipped"]),
    # Misspellings of the municipality, even one that is a place elsewhere ("Plain", WA).
    (("COBEN", "COBDEN", None), "IL", "Cobden",
     ["city_from_inc_muni", "unknown_post_city_skipped"]),
    (("Plain", "Plains", None), "MT", "Plains",
     ["city_from_inc_muni", "unknown_post_city_skipped"]),
    # A misspelling of another place in the state.
    # A one-edit resemblance to another place is not enough to replace a postal city.
    (("MISISON", "Unincorporated", "ANTELOPE"), "SD", "Misison",
     ["city_not_in_reference", "city_cased_by_rule"]),
    # Office codes.
    (("ADK", "ATLANTA", None), "GA", "Atlanta",
     ["city_from_inc_muni", "unknown_post_city_skipped"]),
    (("E CARONDELET", "EAST CARONDELET", None), "IL", "East Carondelet", []),
])
def test_choose_city_unknown_postal_city(fields, state, expected, flags):
    assert choose_city(*fields, state, NAMES_POSTAL) == (expected, flags)


NAMES_TYPOS = PlaceNames([
    ("TX", "Weatherford", "census_place"), ("TX", "Whitney", "census_place"),
    ("TX", "Walnut Springs", "census_place"), ("LA", "Arnaudville", "census_place"),
    ("TX", "Saint Lawrence", "gnis"), ("TX", "St. Lawrence", "census_place"),
], overrides=[
    Override("TX", "Weatherord", "fix", "Parker", "Weatherford"),
    # The same typo standing for different places in different counties.
    Override("TX", "Whtney", "fix", "Hill", "Whitney"),
    Override("TX", "Whtney", "fix", "Bosque", "Walnut Springs"),
    # A typo that is a place in the state is never applied.
    Override("TX", "Whitney", "fix", "Parker", "Weatherford"),
    Override("LA", "Arnadville", "fix", "St. Landry", "Arnaudville"),
    Override("TX", "St Lawrenc", "fix", "Glasscock", "Saint Lawrence"),
])


@pytest.mark.parametrize("fields, state, county, expected, flags", [
    (("WEATHERORD", None, None), "TX", "Parker", "Weatherford", ["city_typo_fixed"]),
    (("Weatherord", None, None), "TX", "Parker County", "Weatherford", ["city_typo_fixed"]),
    ((None, "WEATHERORD", None), "TX", "Parker", "Weatherford",
     ["city_from_inc_muni", "city_typo_fixed"]),
    # Only in the county the typo was found in.
    (("WEATHERORD", None, None), "TX", "Tarrant", "Weatherord",
     ["city_not_in_reference", "city_cased_by_rule"]),
    (("WEATHERORD", None, None), "TX", None, "Weatherord",
     ["city_not_in_reference", "city_cased_by_rule"]),
    (("WHTNEY", None, None), "TX", "Hill", "Whitney", ["city_typo_fixed"]),
    (("WHTNEY", None, None), "TX", "Bosque", "Walnut Springs", ["city_typo_fixed"]),
    (("WHITNEY", None, None), "TX", "Parker", "Whitney", []),
    (("ARNADVILLE", None, None), "LA", "St. Landry Parish", "Arnaudville", ["city_typo_fixed"]),
    # The target takes the reference's spelling.
    (("ST LAWRENC", None, None), "TX", "Glasscock", "St. Lawrence", ["city_typo_fixed"]),
    # A typo in the postal city does not hide a known municipality.
    (("WEATHERORD", "WEATHERFORD", None), "TX", "Parker", "Weatherford", ["city_typo_fixed"]),
])
def test_choose_city_fixes_reviewed_typos(fields, state, county, expected, flags):
    assert choose_city(*fields, state, NAMES_TYPOS, county) == (expected, flags)


NAMES_DROPS = PlaceNames([
    ("WA", "Pomeroy", "census_place"), ("TX", "Snyder", "census_place"),
    ("OR", "County N", "gnis"),
], overrides=[Override("*", "Unkown", "drop"), Override("WA", "County N", "drop"),
                Override("TX", "Tx", "drop"), Override("OR", "County N", "drop")])


@pytest.mark.parametrize("fields, state, expected, flags", [
    (("Unkown", None, None), "NM", None, ["no_city"]),
    (("UNKOWN", None, None), "WA", None, ["no_city"]),
    (("County N", None, None), "WA", None, ["no_city"]),
    (("COUNTY N", "Pomeroy", None), "WA", "Pomeroy", ["city_from_inc_muni"]),
    (("TX", None, None), "TX", None, ["no_city"]),
    (("Tx", "SNYDER", None), "TX", "Snyder", ["city_from_inc_muni"]),
    # Only in the state it is listed for.
    (("County N", None, None), "ID", "County N", ["city_not_in_reference"]),
    # A value that is a place in the state is never dropped.
    (("County N", None, None), "OR", "County N", []),
])
def test_choose_city_drops_reviewed_non_places(fields, state, expected, flags):
    assert choose_city(*fields, state, NAMES_DROPS) == (expected, flags)


NAMES_GNIS = PlaceNames([
    ("AL", "Jon", "gnis"), ("AL", "Jones", "gnis"), ("AL", "Pine Hill", "gnis"),
    ("AL", "Pine Level", "census_place"),
], overrides=[
    Override("AL", "Jon", "fix", "Autauga", "Jones"),
    # Statewide fixes never replace a known name, even one only GNIS knows.
    Override("AL", "Pine Hill", "fix", "*", "Pine Level"),
])


@pytest.mark.parametrize("fields, county, expected, flags", [
    # A county's code that collides with a GNIS-only hamlet elsewhere in the state.
    (("JON", "JON", None), "Autauga", "Jones", ["city_typo_fixed"]),
    (("JON", None, None), "Coosa", "Jon", []),
    (("PINE HILL", None, None), "Wilcox", "Pine Hill", []),
])
def test_county_fix_may_replace_a_gnis_only_name(fields, county, expected, flags):
    assert choose_city(*fields, "AL", NAMES_GNIS, county) == (expected, flags)


NAMES_KEEPS = PlaceNames([
    ("AR", "Hot Springs", "census_place"), ("TX", "Llano", "census_place"),
], overrides=[
    Override("AR", "Hot Springs National Park", "keep", "Garland"),
    Override("TX", "Sunrise Beach", "keep", "Llano"),
    Override("TX", "Malcom", "hold", note="spelled like Malcolm; ZIP says McIntosh"),
])


@pytest.mark.parametrize("fields, state, county, expected, flags", [
    # Vouched for in its county: no flag, and the entry's spelling.
    (("HOT SPRINGS NATIONAL PARK", None, None), "AR", "Garland", "Hot Springs National Park", []),
    # A kept postal city does not give way to the municipality.
    (("Sunrise Beach", "LLANO", None), "TX", "Llano", "Sunrise Beach", []),
    # Only in that county.
    (("HOT SPRINGS NATIONAL PARK", None, None), "AR", "Saline", "Hot Springs National Park",
     ["city_not_in_reference", "city_cased_by_rule"]),
    # A hold changes nothing in the output.
    (("MALCOM", None, None), "TX", "Washington", "Malcom",
     ["city_not_in_reference", "city_cased_by_rule"]),
])
def test_choose_city_applies_keep_and_ignores_hold(fields, state, county, expected, flags):
    assert choose_city(*fields, state, NAMES_KEEPS, county) == (expected, flags)


def test_held_values_report_their_note():
    assert NAMES_KEEPS.held("TX", "Washington", "Malcom") == "spelled like Malcolm; ZIP says McIntosh"
    assert NAMES_KEEPS.held("TX", "Washington", "Malcolm") is None


def test_city_overrides_file_is_consistent():
    overrides = load_city_overrides()
    assert {o.action for o in overrides} <= set(ACTIONS)
    seen = {}
    for o in overrides:
        assert (o.state == "*" or len(o.state) == 2) and o.value
        key = (o.state, county_key(o.county) if o.county and o.county != "*" else "*",
               city_key(o.value))
        assert key not in seen, f"{key} is listed as both {seen[key]} and {o.action}"
        seen[key] = o.action
        if o.action == "fix":
            assert city_key(o.value) != city_key(o.city)
    statewide = {key[2] for key in seen if key[0] == "*"}
    assert not [k for k in seen if k[0] != "*" and k[2] in statewide], "also listed under *"


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
