"""addr:city: pick the best populated NAD place field and give it its proper spelling."""

import re
import unicodedata
from collections import Counter, defaultdict

from . import clean
from .casing import ENGLISH_LOWER_WORDS, smart_title

CITY_PLACEHOLDERS = {
    "unincorporated", "unincorporated county", "incorporated", "county", "rural", "other", "us",
    "matched", "river features",
}
# Military base abbreviations that stay upper case in a city name ("Hill AFB").
CITY_KEEP_UPPER = frozenset({"AFB", "NAS", "CBC", "MCAS", "MCB", "AFS", "ANGB"})
KEY_WORDS = {"st": "saint", "ste": "sainte", "mt": "mount", "ft": "fort"}
# Only as the first word: a later "s" is a possessive ("Thompson's Station").
LEADING_KEY_WORDS = {"n": "north", "s": "south", "e": "east", "w": "west"}
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
# States whose postal city field holds USPS station and branch names ("Mesa Four Peaks",
# "Andersen Springs", "South Mountain"): any unknown value there gives way to a known
# municipality. r24: 1.02M AZ rows, 39 distinct names, all stations or annexes.
POSTAL_STATION_STATES = {"AZ"}
# Unknown values this short are office codes, not names ("ADK", "DKLB", "WILM").
_CODE = re.compile(r"[A-Za-z]{1,4}")


def city_key(name: str) -> str:
    """Comparison key: case, punctuation, spacing and St/Mt/Ft abbreviations do not matter.

    Spacing is ignored so that "O FALLON" finds O'Fallon and "LAGRANGE" finds La Grange;
    accents so that "ESPANOLA" finds Española. A leading N/S/E/W is read as the direction
    ("E CARONDELET" finds East Carondelet).
    """
    folded = "".join(c for c in unicodedata.normalize("NFKD", name.casefold())
                     if not unicodedata.combining(c))
    words = re.sub(r"[.'’]", " ", folded).replace("-", " ").split()
    if len(words) > 1 and len(words[1]) > 1 and words[0] in LEADING_KEY_WORDS:  # not "S.N.P.J."
        words[0] = LEADING_KEY_WORDS[words[0]]
    return "".join(KEY_WORDS.get(w, w) for w in words)


def edit_distance(a: str, b: str) -> int:
    """Edits (insert, delete, substitute, swap two adjacent letters) that turn a into b."""
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            row[j] = min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], prev2[j - 2] + 1)
        prev2, prev = prev, row
    return prev[-1]


def _misspelling_of(key: str, other: str) -> bool:
    """One edit apart, or two when the name is long: "COBEN"/Cobden, "FRAZYSBURG"/Frazeysburg."""
    limit = 2 if len(key) >= 8 else 1
    return abs(len(key) - len(other)) <= limit and edit_distance(key, other) <= limit


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
        self.keys_by_state = defaultdict(set)
        for state, key in self.by_state:
            self.keys_by_state[state].add(key)

    def lookup(self, state: str | None, name: str, national: bool = True) -> str | None:
        key = city_key(name)
        if known := self.by_state.get((state, key)):
            return known
        return self.national.get(key) if national else None

    def near_miss(self, state: str | None, name: str) -> bool:
        """True if name is one edit from a place in the state ("MISISON" for Mission)."""
        key = city_key(name)
        return len(key) >= 5 and any(
            abs(len(key) - len(k)) <= 1 and edit_distance(key, k) <= 1
            for k in self.keys_by_state.get(state, ()))


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


def _gives_way(value, known, state, names: PlaceNames) -> bool:
    """Whether an earlier field's value, not a known place in the state, should give way to
    the known place a later field names.

    Usually it should not: many real USPS city names are not in the reference ("Lafayette
    Hill", "Cortlandt Manor"). It does when the state's postal field holds station names, or
    the value looks like a misspelling or an office code rather than a name.
    """
    if state in POSTAL_STATION_STATES or _misspelling_of(city_key(value), city_key(known)):
        return True
    if names.lookup(state, value):  # a real place name, if from another state
        return False
    # A one-edit resemblance to some other place in the state is not evidence: real post
    # offices such as Mallie KY (one letter from Hallie) would be replaced. Only office
    # codes give way here.
    return bool(_CODE.fullmatch(value))


def choose_city(post_city, inc_muni, uninc_comm, state, names: PlaceNames, county=None):
    """Return (addr:city, flags).

    Postal city first, then municipality, then community. A field whose value is a known
    place in that state is preferred over an earlier field whose value is not, if the earlier
    value gives way (see _gives_way): some sources put post office branch names ("Mesa Four
    Peaks") or misspellings in the postal city.
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
            if field == candidates[0][0] or _gives_way(candidates[0][1], known, state, names):
                return known, source_flags(field)
            break
    field, value = candidates[0]
    flags = source_flags(field)
    if known := names.lookup(state, value):
        return known, flags
    if not value.isupper() and not value.islower():
        return value, flags + ["city_not_in_reference"]
    return (smart_title(value, keep_upper=CITY_KEEP_UPPER, lower_words=ENGLISH_LOWER_WORDS),
            flags + ["city_not_in_reference", "city_cased_by_rule"])
