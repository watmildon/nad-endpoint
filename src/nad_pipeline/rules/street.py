"""addr:street from the eight NAD street name components.

NAD already delivers directionals and types spelled out in their own fields. The work is in
St_Name, which often arrives in caps with abbreviations, directionals or the street type
embedded in it.
"""

from . import clean
from .casing import smart_title, smart_title_token

DIRECTIONS = {
    "N": "North", "S": "South", "E": "East", "W": "West",
    "NE": "Northeast", "NW": "Northwest", "SE": "Southeast", "SW": "Southwest",
}
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
    "RDG": "Ridge", "LNDG": "Landing", "HOLW": "Hollow",
}
TYPE_WORDS = {t.upper() for t in TRAILING_TYPES.values()} | {"ROUTE", "WAY", "LOOP"}
ROUTE_WORDS = {"RTE", "RT", "ROUTE", "HWY", "HIGHWAY", "RD", "ROAD"}
# Route designators whose expansion varies by state (State Route / State Road, Farm to
# Market, Interstate): kept as written and flagged.
ROUTE_ABBREVIATIONS = frozenset({"US", "SR", "FM", "IH", "RM", "RR", "CH", "CSAH", "USFS"})
# Unambiguous abbreviations expanded wherever they occur in a name.
NAME_ABBREVIATIONS = {
    "HGTS": "Heights", "HTS": "Heights", "BLFS": "Bluffs", "XRDS": "Crossroads",
    "BLVD": "Boulevard", "MNTN": "Mountain", "MTN": "Mountain", "SCHL": "School",
    "CRST": "Crest", "CRSG": "Crossing", "PKWY": "Parkway", "HWY": "Highway",
    "PVT": "Private", "AVE": "Avenue", "PL": "Place", "LN": "Lane",
}
PLACEHOLDER_NAMES = {"UNNAMED", "UNKNOWN", "UNK", "NO NAME", "NONAME", "TBD"}
# Sub-address designators that some sources put in the street pre-modifier field.
MISPLACED_PREMODS = {"APT", "STE", "RM", "TRLR", "LOT", "UNIT", "BLDG", "MM", "#"}
POST_MODIFIERS = {"EXT": "Extension", "EXTN": "Extension", "ACCESS RD": "Access Road"}


def _bare(token: str) -> str:
    return token.upper().rstrip(".")


def expand_name(name: str, has_pre_dir: bool, has_post_dir: bool):
    """Split St_Name into (leading directional, name, trailing type, trailing directional).

    Returns those four values plus the flags describing what was found inside the name.
    """
    tokens = name.split()
    flags = []
    pre_dir = post_dir = name_type = None

    if len(tokens) > 1 and not has_post_dir and _bare(tokens[-1]) in DIRECTIONS:
        # "MAIN ST N" carries a directional, but "AVENUE N" is a lettered street.
        rest = tokens[:-1]
        if not (len(rest) == 1 and _bare(rest[0]) in TYPE_WORDS | TRAILING_TYPES.keys()):
            post_dir = DIRECTIONS[_bare(tokens.pop())]
            flags.append("name_had_directional")
    if len(tokens) > 1 and _bare(tokens[-1]) in TRAILING_TYPES:
        name_type = TRAILING_TYPES[_bare(tokens.pop())]
        flags.append("name_had_type")
    if len(tokens) > 1 and not has_pre_dir and _bare(tokens[0]) in DIRECTIONS:
        pre_dir = DIRECTIONS[_bare(tokens.pop(0))]
        flags.append("name_had_directional")

    out = []
    for i, token in enumerate(tokens):
        bare = _bare(token)
        nxt = _bare(tokens[i + 1]) if i + 1 < len(tokens) else None
        prev = _bare(tokens[i - 1]) if i else None
        if bare == "ST" and nxt in ("EXT", "EXTENSION", "EXTN"):
            out.append("Street")
        elif bare == "ST" and nxt:
            out.append("State" if nxt in ROUTE_WORDS else "Saint")
            flags.append("expanded_st")
        elif bare == "ST":
            out.append(smart_title_token(token, i == 0))
            flags.append("ambiguous_st")
        elif bare == "MT" and nxt:
            out.append("Mount")
        elif bare == "FT" and nxt:
            out.append("Fort")
        elif bare == "DR" and nxt and i == 0:
            out.append("Doctor")
        elif bare in NAME_ABBREVIATIONS:
            out.append(NAME_ABBREVIATIONS[bare])
        elif bare == "US":
            out.append("US")
        elif bare in ("RTE", "RT") and (prev in ("ST", "STATE", "CO", "COUNTY", "US", "OLD")
                                         or (nxt and nxt[0].isdigit())):
            out.append("Route")
        elif bare == "CR" and nxt and nxt[0].isdigit():
            out.append("County Road")
        elif bare == "CO" and nxt in ROUTE_WORDS:
            out.append("County")
        elif bare == "RD" and prev in ("CO", "COUNTY", "ST", "STATE", "FS"):
            out.append("Road")
        elif bare == "FS" and nxt in ("RD", "ROAD"):
            out.append("Forest Service")
        elif nxt and nxt[0].isdigit() and (
                bare in ROUTE_ABBREVIATIONS or (len(bare) == 2 and bare.isalpha() and i == 0)):
            # Includes state route shorthand such as "AR 5" or "NC 150".
            out.append(bare)
            flags.append("route_abbreviation")
        else:
            out.append(smart_title_token(token, i == 0))
    return pre_dir, " ".join(out), name_type, post_dir, flags


def build_street(pre_mod, pre_dir, pre_type, pre_sep, name, post_type, post_dir, post_mod):
    """Return (addr:street, flags). The street is None when there is no usable name."""
    pre_mod, pre_dir, pre_type, pre_sep = map(clean, (pre_mod, pre_dir, pre_type, pre_sep))
    name, post_type, post_dir, post_mod = map(clean, (name, post_type, post_dir, post_mod))
    if name is None and pre_type is None:
        return None, ["no_street_name"]
    flags = []
    name_pre_dir = name_type = name_post_dir = None
    if name is not None:
        if name.upper() in PLACEHOLDER_NAMES or name.upper().split()[0] in ("UNNAMED", "UNKNOWN"):
            return None, ["placeholder_street_name"]
        name_pre_dir, name, name_type, name_post_dir, flags = expand_name(
            name, pre_dir is not None, post_dir is not None
        )
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

    parts = [
        pre_mod, pre_dir or name_pre_dir, pre_type, pre_sep, name, name_type,
        post_type, post_dir or name_post_dir, post_mod,
    ]
    return " ".join(p for p in parts if p), sorted(set(flags))
