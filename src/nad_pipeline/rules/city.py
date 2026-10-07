"""addr:city: pick the best populated NAD place field and give it its proper spelling."""

import re
from collections import Counter, defaultdict

from . import clean
from .casing import ENGLISH_LOWER_WORDS, smart_title

CITY_PLACEHOLDERS = {
    "unincorporated", "unincorporated county", "incorporated", "county", "rural", "other", "us",
}
KEY_WORDS = {"st": "saint", "ste": "sainte", "mt": "mount", "ft": "fort"}
# When reference sources disagree on spelling, the earlier source wins a tie.
# Abbreviations a source uses for a city, by state.
CITY_OVERRIDES = {("GA", "ATL"): "Atlanta"}
_GOVERNMENT_PREFIX = re.compile(r"^(city|town|village|borough|township) of ", re.IGNORECASE)
# Descriptors some sources append to the place name ("Essex Town", "Vail Area").
_DESCRIPTOR_SUFFIX = re.compile(
    r"\s+(city|town|village|borough|boro|township|twp|area|cpu)$", re.IGNORECASE)
_COUNTY_SUFFIX = re.compile(r"\s+(county|co)$", re.IGNORECASE)
_TRAILING_ZIP = re.compile(r"\s+\d{5}(-\d{4})?$")
# Maine's unorganized townships are named like "T1 R9 WELS"; digits elsewhere mean junk.
_DIGITS_ALLOWED = {"ME"}
SOURCE_PRIORITY = ["census_place", "gnis", "census_cousub", "wikidata"]


def city_key(name: str) -> str:
    """Comparison key: case, punctuation, spacing and St/Mt/Ft abbreviations do not matter.

    Spacing is ignored so that "O FALLON" finds O'Fallon and "LAGRANGE" finds La Grange.
    """
    words = re.sub(r"[.'’]", " ", name.casefold()).replace("-", " ").split()
    return "".join(KEY_WORDS.get(w, w) for w in words)


class PlaceNames:
    """Proper spellings of place names, combined from several reference sources."""

    def __init__(self, rows):
        """rows: iterable of (state, name, source)."""
        votes = defaultdict(Counter)
        sources = defaultdict(dict)
        for state, name, source in rows:
            key = (state, city_key(name))
            votes[key][name] += 1
            sources[key].setdefault(name, source)
        self.by_state = {}
        self.conflicts = []
        national = defaultdict(set)
        for key, counter in votes.items():
            best = min(counter, key=lambda n: (
                -counter[n], SOURCE_PRIORITY.index(sources[key][n]), n))
            self.by_state[key] = best
            national[key[1]].add(best)
            if len(counter) > 1:
                self.conflicts.append((key[0], best, dict(counter)))
        self.national = {k: next(iter(v)) for k, v in national.items() if len(v) == 1}

    def lookup(self, state: str | None, name: str, national: bool = True) -> str | None:
        key = city_key(name)
        if known := self.by_state.get((state, key)):
            return known
        return self.national.get(key) if national else None


def _candidate(raw, state, county, names: PlaceNames) -> str | None:
    """Clean one place field; None if it holds a placeholder or the county, not a city."""
    value = clean(raw)
    if value is None or value.casefold() in CITY_PLACEHOLDERS:
        return None
    value = _GOVERNMENT_PREFIX.sub("", value)
    value = _TRAILING_ZIP.sub("", value)  # "Sonora 76950"
    if state:  # "Covington Ky", "West Bend, WI"
        value = re.sub(rf",?\s+{state}$", "", value, flags=re.IGNORECASE) or value
    if names.lookup(state, value, national=False):
        return value
    stripped = _DESCRIPTOR_SUFFIX.sub("", value)
    if stripped != value and names.lookup(state, stripped, national=False):
        return stripped
    if not re.search(r"[A-Za-z]", value) or _COUNTY_SUFFIX.search(value):
        return None  # a ZIP code or a county in the city field
    if county and city_key(value) == city_key(county):
        return None
    if re.search(r"\d", value) and state not in _DIGITS_ALLOWED:
        return None  # "971Xx", "Us 12 W", "Green Twp Area 1"
    return value


def choose_city(post_city, inc_muni, uninc_comm, state, names: PlaceNames, county=None):
    """Return (addr:city, flags).

    Postal city first, then municipality, then community. A field whose value is a known
    place in that state is preferred over an earlier field whose value is not: some sources
    put post office branch names ("Mesa Four Peaks") in the postal city.
    """
    candidates = [
        (field, value)
        for field, raw in (("post_city", post_city), ("inc_muni", inc_muni),
                           ("uninc_comm", uninc_comm))
        if (value := _candidate(raw, state, county, names))
    ]
    if not candidates:
        return None, ["no_city"]

    def source_flags(field):
        flags = [] if field == "post_city" else [f"city_from_{field}"]
        if field != candidates[0][0]:
            flags.append(f"unknown_{candidates[0][0]}_skipped")
        return flags

    for field, value in candidates:
        known = CITY_OVERRIDES.get((state, value.upper())) or names.lookup(
            state, value, national=False)
        if known:
            return known, source_flags(field)
    field, value = candidates[0]
    flags = source_flags(field)
    if known := names.lookup(state, value):
        return known, flags
    if not value.isupper() and not value.islower():
        return value, flags + ["city_not_in_reference"]
    return (smart_title(value, lower_words=ENGLISH_LOWER_WORDS),
            flags + ["city_not_in_reference", "city_cased_by_rule"])
