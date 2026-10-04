import pytest

from nad_pipeline.rules.fields import (
    build_housenumber, clean_postcode, clean_unit, lifecycle_drop_reason,
)


@pytest.mark.parametrize("prefix, number, suffix, expected", [
    (None, "114", None, "114"),
    (None, "102", "C", "102 C"),
    (None, "102", "c", "102 C"),
    (None, "607", "1/2", "607 1/2"),
    (None, "431", ".5", "431.5"),
    (None, "12", "-A", "12-A"),
    (None, "17822", "<Null>", "17822"),
    ("89-", "2", None, "89-02"),
    ("89-", "15", None, "89-15"),
    ("N", "123", None, "N123"),
    ("W", "235", "A", "W235 A"),
    ("0N", "456", None, "0N456"),
    (None, "55", "LOT", "55"),
])
def test_build_housenumber(prefix, number, suffix, expected):
    value, _, drop = build_housenumber(prefix, number, suffix)
    assert (value, drop) == (expected, None)


@pytest.mark.parametrize("prefix, number, suffix, reason", [
    (None, None, None, "no_housenumber"),
    (None, "0", None, "zero_housenumber"),
    ("Milepost", "116", ".7", "milepost_address"),
    (None, "100", "BLK", "block_address"),
])
def test_housenumber_drops(prefix, number, suffix, reason):
    assert build_housenumber(prefix, number, suffix) == (None, [], reason)


@pytest.mark.parametrize("unit, expected", [
    ("2", "2"),
    ("a", "A"),
    ("R2", "R2"),
    ("r-40", "R-40"),
    ("APT A", "Apt A"),
    ("uNIT A", "Unit A"),
    ("APARTMENT  #6", "Apartment #6"),
    ("APT. 3", "Apt 3"),
    ("#  405", "#405"),
    ("Lot 1", "Lot 1"),
    ("BLDG B STE 3", "Bldg B Ste 3"),
    ("REAR", "Rear"),
    ("12-16", "12-16"),
    ("A-B", "A-B"),
    ("TRLR", None),
    ("APT", None),
    ("#", None),
    ("????", None),
    ("<Null>", None),
    (None, None),
])
def test_clean_unit(unit, expected):
    assert clean_unit(unit)[0] == expected


def test_unit_falls_back_to_building():
    assert clean_unit(None, "B") == ("B", [])
    assert clean_unit("Apartment 1", "Apartment 1") == ("Apartment 1", [])
    assert clean_unit("6", "B") == ("6", ["building_not_in_unit"])
    assert clean_unit("APT") == (None, ["unit_designator_only"])


@pytest.mark.parametrize("zip_code, state, expected, flags", [
    ("02559", "MA", "02559", []),
    ("85007-1234", "AZ", "85007", []),
    ("850071234", "AZ", "85007", []),
    ("2559", "MA", "02559", ["postcode_zero_restored"]),
    ("2559", "TX", None, ["bad_postcode"]),
    ("0", "TX", None, []),
    ("00000", "TX", None, []),
    ("99999", "TX", None, ["bad_postcode"]),
    ("5151436", "IA", None, ["bad_postcode"]),
    ("WISE", "TX", None, ["bad_postcode"]),
    (None, "TX", None, []),
])
def test_clean_postcode(zip_code, state, expected, flags):
    assert clean_postcode(zip_code, state) == (expected, flags)


@pytest.mark.parametrize("lifecycle, dropped", [
    ("Active", False), ("ACTIVE", False), ("Current", False), (None, False), ("V", False),
    ("PROPOSED", True), ("Retired", True), ("Not Active", True), ("DUBIOUS", True),
])
def test_lifecycle(lifecycle, dropped):
    assert (lifecycle_drop_reason(lifecycle) is not None) is dropped
