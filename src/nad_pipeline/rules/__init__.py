"""Field rules: pure functions from raw NAD values to OSM tag values plus audit flags.

Every rule returns (value, flags). Flags record what a rule did or doubted, so output can
be audited per source; a rule never silently guesses.
"""

import re

PLACEHOLDERS = {
    "<null>", "null", "none", "n/a", "na", "not stated", "unknown", "unk", "not applicable",
    "unassigned", "tbd",
}


def clean(value: str | None) -> str | None:
    """Collapse whitespace and turn empty or placeholder values into None."""
    if value is None:
        return None
    value = " ".join(value.replace("\xa0", " ").split())
    if not value or value.casefold() in PLACEHOLDERS or not re.search(r"\w", value):
        return None
    return value
