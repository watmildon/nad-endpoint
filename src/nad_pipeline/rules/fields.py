"""House number, unit, postcode and lifecycle rules."""

import re

from . import clean
from .casing import smart_title_token

# States and territories whose ZIP codes start with 0, where a 4-digit value lost its zero.
LEADING_ZERO_ZIP_STATES = {"CT", "MA", "ME", "NH", "NJ", "RI", "VT", "PR", "VI"}

UNIT_DESIGNATORS = {
    "APARTMENT", "APT", "UNIT", "SUITE", "STE", "LOT", "SPACE", "SPC", "BLDG", "BUILDING",
    "SITE", "TRLR", "TRAILER", "CONDO", "ROOM", "RM", "SLIP", "CABIN", "FLOOR", "FL",
    "CAMPSITE", "PENTHOUSE", "PH", "OFFICE", "OFC", "DEPT", "HANGAR", "PIER", "STOP",
}

# Lifecycle values meaning the address is not (or not yet, or no longer) in use.
INACTIVE_LIFECYCLES = {
    "PROPOSED", "POTENTIAL", "PENDING", "PRELIMINARY", "PREASSIGNED", "TEMPORARY",
    "RETIRED", "INACTIVE", "NOT ACTIVE", "DORMANT", "MOVED", "DUBIOUS",
}


def build_housenumber(prefix, number, suffix):
    """Return (addr:housenumber, flags, drop_reason)."""
    prefix, number, suffix = clean(prefix), clean(number), clean(suffix)
    if number is None:
        return None, [], "no_housenumber"
    if prefix and prefix.casefold() in ("milepost", "mile post", "mile marker", "mp", "mm"):
        return None, [], "milepost_address"
    if (suffix and suffix.upper() == "BLK") or (prefix and prefix.casefold() == "block"):
        return None, [], "block_address"
    if prefix and len(prefix) > 4 and not any(c.isdigit() for c in prefix):
        # Words in the prefix field ("BILLBD", a street name) are not part of a number.
        return None, [], "unparsed_housenumber"
    flags = []
    if number.isdigit():
        number = number.lstrip("0") or "0"
    if not prefix and not number.strip("0") and (not suffix or suffix.isalpha()):
        return None, [], "zero_housenumber"
    if prefix and prefix.endswith("-"):
        # Queens-style hyphenated numbers keep two digits after the hyphen (89-02).
        value = prefix + number.zfill(2)
    elif prefix and len(prefix) <= 6 and " " not in prefix:
        value = prefix + number  # grid prefixes such as N, W, 0N, W156N
    elif prefix:
        value = f"{prefix} {number}"
    else:
        value = number
    if suffix and suffix.upper() == "LOT":
        flags.append("dropped_number_suffix")
    elif suffix and suffix[0] in ".-":
        value += suffix
    elif suffix:
        value += f" {suffix.upper() if len(suffix) <= 2 else suffix}"
    return value, flags, None


def _unit_token(token: str) -> str:
    bare = token.rstrip(".").upper()
    if bare in UNIT_DESIGNATORS:
        return bare.capitalize()
    if token.isalpha() and len(token) >= 3:
        return smart_title_token(token.upper())
    return token.upper()


def clean_unit(unit, building=None):
    """Return (addr:unit, flags): light cleanup of the delivered value, not a re-parse."""
    unit, building = clean(unit), clean(building)
    flags = []
    if unit and building and unit.casefold() != building.casefold():
        flags.append("building_not_in_unit")
    value = unit or building
    if value is None:
        return None, flags
    value = re.sub(r"#\s+", "#", value)
    tokens = [_unit_token(t) for t in value.split()]
    if all(t.rstrip(".").upper() in UNIT_DESIGNATORS or t == "#" for t in tokens):
        return None, flags + ["unit_designator_only"]
    return " ".join(tokens), flags


def clean_postcode(zip_code, state=None):
    """Return (addr:postcode, flags)."""
    value = clean(zip_code)
    if value is None:
        return None, []
    digits = re.sub(r"[\s-]", "", value)
    if re.fullmatch(r"\d{5}(\d{4})?", digits) and "00501" <= digits[:5] <= "99950":
        return digits[:5], []
    if re.fullmatch(r"\d{4}", digits) and state in LEADING_ZERO_ZIP_STATES:
        return "0" + digits, ["postcode_zero_restored"]
    if not digits.strip("0"):
        return None, []  # 0 and 00000 are just "no value"
    return None, ["bad_postcode"]


def lifecycle_drop_reason(lifecycle):
    value = clean(lifecycle)
    if value and value.upper() in INACTIVE_LIFECYCLES:
        return "inactive_lifecycle"
    return None
