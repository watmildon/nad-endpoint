"""addr:street from the eight NAD street name components.

NAD already delivers directionals and types spelled out in their own fields. The work is in
St_Name, which often arrives in caps with abbreviations, directionals or the street type
embedded in it.
"""

import re

from . import clean
from .casing import smart_title, smart_title_token
from .saints import SAINT_WORDS

DIRECTIONS = {
    "N": "North", "S": "South", "E": "East", "W": "West",
    "NE": "Northeast", "NW": "Northwest", "SE": "Southeast", "SW": "Southwest",
}
ALL_DIRECTIONS = DIRECTIONS.keys() | {d.upper() for d in DIRECTIONS.values()}
# Abbreviated street types expanded when they end St_Name: the USPS suffix abbreviations
# (as in TIGER-ROAR's StreetNameUtils), minus those that are also common name words
# (Br, Is, Un, Pr, Via, Ft, Mt, Ch, Est, Sta ...).
TRAILING_TYPES = {
    "BND": "Bend", "BLF": "Bluff", "BYP": "Bypass", "CYN": "Canyon", "CSWY": "Causeway",
    "CTR": "Center", "CRK": "Creek", "CRES": "Crescent", "GDNS": "Gardens", "GLN": "Glen",
    "GRV": "Grove", "HBR": "Harbor", "HLS": "Hills", "JCT": "Junction", "KNL": "Knoll",
    "LK": "Lake", "MDW": "Meadow", "MDWS": "Meadows", "MNR": "Manor", "MTN": "Mountain",
    "ORCH": "Orchard", "PLZ": "Plaza", "PT": "Point", "RNCH": "Ranch", "RIV": "River",
    "SHR": "Shore", "SHRS": "Shores", "SPG": "Spring", "SPGS": "Springs", "SMT": "Summit",
    "TRCE": "Trace", "VLY": "Valley", "VW": "View", "VLG": "Village", "VIS": "Vista",
    "FLS": "Falls", "FRST": "Forest", "GTWY": "Gateway", "HVN": "Haven",
    "ST": "Street", "RD": "Road", "AVE": "Avenue", "AV": "Avenue", "DR": "Drive",
    "LN": "Lane", "CT": "Court", "CIR": "Circle", "PL": "Place", "BLVD": "Boulevard",
    "TRL": "Trail", "PKWY": "Parkway", "PKY": "Parkway", "HWY": "Highway", "TER": "Terrace",
    "CV": "Cove", "EXT": "Extension", "SQ": "Square", "XING": "Crossing", "HTS": "Heights",
    "EXPY": "Expressway", "FWY": "Freeway", "ALY": "Alley", "TPKE": "Turnpike",
    "RDG": "Ridge", "LNDG": "Landing", "HOLW": "Hollow", "HL": "Hill",
}
TYPE_WORDS = {t.upper() for t in TRAILING_TYPES.values()} | {"ROUTE", "WAY", "LOOP"}
ROUTE_WORDS = {"RTE", "RT", "ROUTE", "HWY", "HIGHWAY", "RD", "ROAD"}
# ST or STE before these words is State.
STATE_ROUTE_WORDS = ROUTE_WORDS | {"LOOP", "SPUR"}
EXTENSION_WORDS = {"EXT", "EXTN", "EXTENSION"}
# Words after an interior DR that make it Drive: PVT DR 3, LINDA DR #2, PRAIRIE POINT DR DR.
DR_DRIVE_NEXT = (EXTENSION_WORDS | TYPE_WORDS | TRAILING_TYPES.keys()
                 | {"STE", "APT", "UNIT", "LOT", "NO", "TRLR", "BLDG", "CUTOFF", "CUT"})
# A whole-name DR under a pre-type with one of these words is route letters (County Highway DR).
ROUTE_PRETYPE_WORDS = {"HIGHWAY", "ROUTE", "ROAD", "TRUNK"}
# Route designators whose expansion varies by state (State Route / State Road, Farm to
# Market, Interstate): kept as written and flagged.
ROUTE_ABBREVIATIONS = frozenset({"US", "SR", "FM", "IH", "RM", "RR", "CH", "CSAH", "USFS"})
# Route designators with a known expansion in one state, applied before a number.
STATE_ROUTE_DESIGNATORS = {"OH": {"SR": "State Route", "TR": "Township Road"}}
# Agency initialisms kept in capitals even when no number follows (USFS RD 7175).
KEEP_UPPER = frozenset({"USFS", "BLM"})
# Unambiguous abbreviations expanded wherever they occur in a name.
NAME_ABBREVIATIONS = {
    "HGTS": "Heights", "HTS": "Heights", "BLFS": "Bluffs", "XRDS": "Crossroads",
    "BLVD": "Boulevard", "MNTN": "Mountain", "MTN": "Mountain", "SCHL": "School",
    "CRST": "Crest", "CRSG": "Crossing", "PKWY": "Parkway", "HWY": "Highway",
    "PVT": "Private", "AVE": "Avenue", "PL": "Place", "LN": "Lane", "TWP": "Township",
}
PLACEHOLDER_NAMES = {"UNNAMED", "UNKNOWN", "UNK", "NO NAME", "NONAME", "TBD"}
# Sub-address designators that some sources put in the street pre-modifier field.
MISPLACED_PREMODS = {"APT", "STE", "RM", "TRLR", "LOT", "UNIT", "BLDG", "MM", "#"}
POST_MODIFIERS = {"EXT": "Extension", "EXTN": "Extension", "ACCESS RD": "Access Road"}
# States whose sources repeat St_PreDir in St_PosDir ("West 6 Street West"): in r24 no such
# name there also occurs with a different St_PosDir. Elsewhere the repeat usually tells two
# streets apart (Mason County WA "East Mason Lake Drive East" and "... West").
REPEATED_DIRECTIONAL_STATES = frozenset({"NE", "KY", "IA", "ND"})
NYC_COUNTIES = frozenset({"bronx", "kings", "new york", "queens", "richmond"})
ORDINAL_TYPES = frozenset({"STREET", "AVENUE", "PLACE"})
# Counties whose numbered streets of 100 and more carry the suffix in OSM.
ORDINAL_COUNTIES = frozenset({("OH", "lake"), ("KS", "crawford")})
_NUMBERED_NAME = re.compile(r"(?:(beach|bay) )?0*(\d+)", re.IGNORECASE)


def _bare(token: str) -> str:
    return token.upper().rstrip(".")


def _word(token: str) -> str:
    """A token compared as a word: upper case, periods and apostrophes removed."""
    return token.upper().replace(".", "").replace("'", "")


def _st(i: int, words: list[str], stripped_after: bool):
    """Saint, Street or State for an ST token (data/research/saint-vs-street.md)."""
    nxt = words[i + 1] if i + 1 < len(words) else None
    if nxt is None:
        # Last token: a type, EXT or directional was stripped after it, or ST is the whole name.
        return ("Street", None) if stripped_after or i else (None, "ambiguous_st")
    if nxt in EXTENSION_WORDS:
        return "Street", None
    if nxt in STATE_ROUTE_WORDS:
        return "State", "expanded_st"
    if i == 0:
        if nxt[0].isdigit():
            return None, "ambiguous_st"
        return "Saint", "expanded_st" if nxt.lower() in SAINT_WORDS else "st_saint_unlisted"
    if nxt.lower() in SAINT_WORDS:
        return "Saint", "expanded_st"
    return "Street", "st_street_interior"  # MAIN ST MYSTIC, 12TH ST CUTOFF, 7TH ST LOT 2


def _ste(i: int, words: list[str]):
    nxt = words[i + 1] if i + 1 < len(words) else None
    if nxt in STATE_ROUTE_WORDS:
        return "State", "expanded_st"
    if nxt and nxt.isalpha() and len(nxt) > 1:
        return "Sainte", "expanded_st"
    return None, "suite_in_street_name"  # STE 2, STE C, or a trailing STE


def _dr(i: int, words: list[str], pre_type, has_post_type: bool, type_stripped: bool):
    """Doctor or Drive for a DR token (data/research/doctor-vs-drive.md)."""
    nxt = words[i + 1] if i + 1 < len(words) else None
    prev = words[i - 1] if i else None
    if len(words) == 1:
        if pre_type and ROUTE_PRETYPE_WORDS & set(pre_type.upper().split()):
            return "DR", "route_abbreviation"
        if not has_post_type and not type_stripped:
            return "Drive", "expanded_dr_drive"
        return None, "ambiguous_dr"
    if nxt is None:
        return "Drive", "expanded_dr_drive"  # a stripped EXT or type followed it
    if prev in ("REV", "REVEREND"):
        return "Doctor", "expanded_dr_doctor"
    if all(w in ALL_DIRECTIONS for w in words[i + 1:]):
        return "Drive", "expanded_dr_drive"
    if i == 0 or (i == 1 and prev in ALL_DIRECTIONS):
        if nxt[0].isdigit():
            return "Drive", "expanded_dr_drive"
        if nxt == "PEPPER":
            return None, None  # the brand
        return "Doctor", "expanded_dr_doctor"
    if nxt[0].isdigit() or nxt[0] in "#(" or nxt in DR_DRIVE_NEXT:
        return "Drive", "expanded_dr_drive"
    return None, "ambiguous_dr"


def _merge_mc(tokens: list[str]) -> list[str]:
    """Join MC to the word after it (MC GRATH -> McGrath); MC 85 is a Maricopa County route."""
    out = []
    for token in tokens:
        if out and _bare(out[-1]) == "MC" and token.isalpha():
            out[-1] += token
        else:
            out.append(token)
    return out


def _initials(tokens: list[str]) -> bool:
    """W C HANDY: a leading N/S/E/W followed by a single letter is an initial."""
    words = [_word(t) for t in tokens]
    return (len(words) > 2 and words[0] in ("N", "S", "E", "W")
            and len(words[1]) == 1 and words[1].isalpha()
            and len(words[2]) > 1 and words[2].isalpha()
            and not all(w in TYPE_WORDS | TRAILING_TYPES.keys() for w in words[2:]))


def expand_name(name: str, has_pre_dir: bool, has_post_dir: bool, pre_type=None,
                has_post_type: bool = False, state=None, post_dir_value=None):
    """Split St_Name into (leading directional, name, trailing type, trailing directional).

    Returns those four values plus the flags describing what was found inside the name.
    """
    tokens = _merge_mc(name.split())
    flags = []
    pre_dir = post_dir = name_type = None
    state_routes = STATE_ROUTE_DESIGNATORS.get(state.upper() if state else None, {})

    if len(tokens) > 1 and not has_post_dir and _bare(tokens[-1]) in DIRECTIONS:
        # "MAIN ST N" carries a directional, but "AVENUE N" is a lettered street.
        rest = tokens[:-1]
        if not (len(rest) == 1 and _bare(rest[0]) in TYPE_WORDS | TRAILING_TYPES.keys()):
            post_dir = DIRECTIONS[_bare(tokens.pop())]
            flags.append("name_had_directional")
    elif (len(tokens) > 1 and has_post_dir and post_dir_value
          and DIRECTIONS.get(_bare(tokens[-1])) == post_dir_value.title()):
        tokens.pop()  # "CARIBBEAN DR W" with St_PosDir West: the field already has it
        flags.append("duplicate_directional")
    if len(tokens) > 2 and _bare(tokens[-1]) == _bare(tokens[-2]) in TRAILING_TYPES:
        tokens.pop()  # 24TH ST ST, PRAIRIE POINT DR DR
        flags.append("duplicate_type")
    if len(tokens) > 1 and _bare(tokens[-1]) in TRAILING_TYPES:
        name_type = TRAILING_TYPES[_bare(tokens.pop())]
        flags.append("name_had_type")
    if len(tokens) > 1 and not has_pre_dir and _bare(tokens[0]) in DIRECTIONS:
        if _initials(tokens):
            flags.append("initials_not_expanded")
        else:
            pre_dir = DIRECTIONS[_bare(tokens.pop(0))]
            flags.append("name_had_directional")

    words = [_word(t) for t in tokens]
    out = []
    for i, token in enumerate(tokens):
        bare = _bare(token)
        nxt = _bare(tokens[i + 1]) if i + 1 < len(tokens) else None
        prev = _bare(tokens[i - 1]) if i else None
        word = flag = None
        if bare == "ST":
            word, flag = _st(i, words, name_type is not None or post_dir is not None)
        elif bare == "STE":
            word, flag = _ste(i, words)
        elif bare == "DR":
            word, flag = _dr(i, words, pre_type, has_post_type, name_type is not None)
        elif prev == "DR" and out[-1] == "Drive" and bare in ALL_DIRECTIONS:
            word = DIRECTIONS.get(bare) or bare.capitalize()  # FOOTHILLS DR SOUTH
            flag = "name_had_directional"
        elif bare in ("REV", "REVEREND") and nxt == "DR":
            word = "Reverend"
        elif bare == "MT" and nxt:
            word = "Mount"
        elif bare == "FT" and nxt:
            word = "Fort"
        elif bare in NAME_ABBREVIATIONS:
            word = NAME_ABBREVIATIONS[bare]
        elif bare == "US":
            word = "US"
        elif bare in ("RTE", "RT") and (prev in ("ST", "STATE", "CO", "COUNTY", "US", "OLD")
                                         or (nxt and nxt[0].isdigit())):
            word = "Route"
        elif bare == "CR" and nxt and nxt[0].isdigit():
            word = "County Road"
        elif bare == "CO" and nxt in ROUTE_WORDS:
            word = "County"
        elif bare == "RD" and (prev in ("CO", "COUNTY", "ST", "STATE", "FS") or (
                prev and prev.isalpha() and nxt and nxt[0].isdigit())):
            word = "Road"  # LEE RD 137, TWP RD 352
        elif bare == "FS" and nxt in ("RD", "ROAD"):
            word = "Forest Service"
        elif bare in state_routes and nxt and nxt[0].isdigit():
            word = state_routes[bare]
        elif bare == "IH" and nxt and nxt[0].isdigit():
            word = "Interstate"
        elif nxt and nxt[0].isdigit() and (
                bare in ROUTE_ABBREVIATIONS or (len(bare) == 2 and bare.isalpha() and i == 0)):
            # Includes state route shorthand such as "AR 5" or "NC 150".
            word, flag = bare, "route_abbreviation"
        elif bare in KEEP_UPPER:
            word = bare
        out.append(word or smart_title_token(token, i == 0))
        if flag:
            flags.append(flag)
    return pre_dir, " ".join(out), name_type, post_dir, flags


def _ordinal(number: int) -> str:
    if 10 <= number % 100 <= 13:
        return f"{number}th"
    return f"{number}" + {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")


def _county_key(county) -> str | None:
    return county.casefold().strip().removesuffix(" county") if county else None


def add_ordinal(name: str, pre_type, post_type, state, county):
    """Return (name, flags) with an ordinal suffix on a numbered street where OSM uses one.

    NYC sources write "47 Street" and "Beach 116 Street" where OSM has "47th" and "116th".
    Elsewhere small numbers on a Street, Avenue or Place take the suffix; larger ones are
    usually grid distances that OSM keeps bare (data/research/regional-expansions.md).
    """
    if not state or not post_type:
        return name, []
    m = _NUMBERED_NAME.fullmatch(name)
    if not m or int(m.group(2)) == 0:
        return name, []
    prefix, number = m.group(1), int(m.group(2))
    state, county = state.upper(), _county_key(county)
    if state == "NY" and county in NYC_COUNTIES and (
            pre_type is None or pre_type.upper() in ("BEACH", "BAY")):
        return (f"{prefix} " if prefix else "") + _ordinal(number), ["ordinal_added"]
    if prefix or pre_type or post_type.upper() not in ORDINAL_TYPES:
        return name, []
    if number < 100:
        return (name, []) if state == "UT" else (_ordinal(number), ["ordinal_added"])
    if (state, county) in ORDINAL_COUNTIES:
        return _ordinal(number), ["ordinal_added"]
    return name, ["numeric_street_name"]


def build_street(pre_mod, pre_dir, pre_type, pre_sep, name, post_type, post_dir, post_mod,
                 state=None, county=None):
    """Return (addr:street, flags). The street is None when there is no usable name."""
    pre_mod, pre_dir, pre_type, pre_sep = map(clean, (pre_mod, pre_dir, pre_type, pre_sep))
    name, post_type, post_dir, post_mod = map(clean, (name, post_type, post_dir, post_mod))
    state, county = clean(state), clean(county)
    if name is None and pre_type is None:
        return None, ["no_street_name"]
    flags = []
    name_pre_dir = name_type = name_post_dir = None
    if name is not None:
        if name.upper() in PLACEHOLDER_NAMES or name.upper().split()[0] in ("UNNAMED", "UNKNOWN"):
            return None, ["placeholder_street_name"]
        name, ordinal_flags = add_ordinal(name, pre_type, post_type, state, county)
        name_pre_dir, name, name_type, name_post_dir, flags = expand_name(
            name, pre_dir is not None, post_dir is not None, pre_type, post_type is not None,
            state, post_dir,
        )
        flags += ordinal_flags
    if name_type and post_type and name_type.casefold() == post_type.casefold():
        name_type = None
        flags.append("duplicate_type")
    elif name and post_type and name.split()[-1].casefold() == post_type.casefold() \
            and len(name.split()) > 1:
        # "MAIN STREET" in the name and "Street" again in the type field.
        post_type = None
        flags.append("duplicate_type")

    if pre_mod and pre_mod.upper() in MISPLACED_PREMODS:
        pre_mod = None
        flags.append("dropped_pre_modifier")
    elif pre_mod:
        pre_mod = smart_title(pre_mod)
    if post_mod:
        post_mod = POST_MODIFIERS.get(post_mod.upper()) or smart_title(post_mod)
        if name_type and name_type.casefold() == post_mod.casefold():
            # WASHINGTON ST EXT with St_PosMod EXTENSION.
            name_type = None
            flags.append("duplicate_type")
    repeated = bool(post_dir and pre_dir and pre_dir.casefold() == post_dir.casefold())
    name_repeats = bool(post_dir and name and not post_type and len(name.split()) > 1
                        and name.split()[-1].casefold() == post_dir.casefold())
    if name_repeats or (repeated and state and state.upper() in REPEATED_DIRECTIONAL_STATES):
        post_dir = None  # West 6 Street West; FAIRVIEW HILL DR WEST with St_PosDir West
        flags.append("duplicate_directional_dropped")
    elif repeated:
        flags.append("repeated_directional")

    parts = [
        pre_mod, pre_dir or name_pre_dir, pre_type, pre_sep, name, name_type,
        post_type, post_dir or name_post_dir, post_mod,
    ]
    return " ".join(p for p in parts if p), sorted(set(flags))
