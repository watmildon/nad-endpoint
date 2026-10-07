import csv
from pathlib import Path

import pytest

from nad_pipeline.rules.casing import smart_title
from nad_pipeline.rules.street import build_street


def street(name, post_type=None, pre_dir=None, post_dir=None, pre_type=None, pre_sep=None,
           pre_mod=None, post_mod=None, state=None, county=None):
    return build_street(pre_mod, pre_dir, pre_type, pre_sep, name, post_type, post_dir, post_mod,
                        state, county)


@pytest.mark.parametrize("text, expected", [
    ("MCDOWELL", "McDowell"),
    ("Mcdowell", "McDowell"),
    ("McAdams", "McAdams"),
    ("O'BRIEN", "O'Brien"),
    ("MARY'S", "Mary's"),
    ("WINSTON-SALEM", "Winston-Salem"),
    ("1ST", "1st"),
    ("09TH", "9th"),
    ("22ND", "22nd"),
    ("MLK", "MLK"),
    ("MARTIN LUTHER KING JR", "Martin Luther King Jr"),
    ("HENRY VIII", "Henry VIII"),
    ("AVENUE OF THE AMERICAS", "Avenue of the Americas"),
    ("Casa Del Mar", "Casa del Mar"),
    ("LA JOLLA", "La Jolla"),
    ("DR A J BROWN", "Dr A J Brown"),
    ("lower case", "Lower Case"),
    ("DeKalb", "DeKalb"),
    ("C & H", "C & H"),
])
def test_smart_title(text, expected):
    assert smart_title(text) == expected


@pytest.mark.parametrize("args, expected", [
    # Plain assembly; NAD delivers directionals and types already spelled out.
    (dict(name="SOUTH", post_type="Road"), "South Road"),
    (dict(name="Jonathan Bourne", post_type="Drive"), "Jonathan Bourne Drive"),
    (dict(name="MAIN", post_type="Street", pre_dir="North"), "North Main Street"),
    (dict(name="HIGHLAND", post_type="Avenue", post_dir="West"), "Highland Avenue West"),
    (dict(name="Mcdowell", post_type="Road", pre_dir="East"), "East McDowell Road"),
    (dict(name="5", pre_type="County Road"), "County Road 5"),
    (dict(name="Sol", pre_type="Calle", pre_sep="del"), "Calle del Sol"),
    # Bugs seen in the Esri layer.
    (dict(name="St Clair", post_type="Street", pre_dir="East"), "East Saint Clair Street"),
    (dict(name="ST MARYS", post_type="Way", pre_dir="East"), "East Saint Marys Way"),
    (dict(name="DR A J BROWN", post_type="Avenue"), "Doctor A J Brown Avenue"),
    (dict(name="09th", post_type="Street", pre_dir="East"), "East 9th Street"),
    (dict(name="07TH", post_type="Street"), "7th Street"),
    # Saint, Mount, Fort and State inside the name.
    (dict(name="OLD ST CHARLES", post_type="Road"), "Old Saint Charles Road"),
    (dict(name="RUE ST FRANCOIS"), "Rue Saint Francois"),
    (dict(name="ST RTE 37"), "State Route 37"),
    (dict(name="ST HWY 16"), "State Highway 16"),
    (dict(name="MT VERNON", post_type="Road"), "Mount Vernon Road"),
    (dict(name="FT CAMPBELL", post_type="Boulevard"), "Fort Campbell Boulevard"),
    # Type and directionals stuck in the name.
    (dict(name="MAIN ST"), "Main Street"),
    (dict(name="E ST CATHERINE ST"), "East Saint Catherine Street"),
    (dict(name="J ST SW"), "J Street Southwest"),
    (dict(name="2ND ST SW"), "2nd Street Southwest"),
    (dict(name="DR W J HODGE ST"), "Doctor W J Hodge Street"),
    (dict(name="S MAIN", post_type="Street"), "South Main Street"),
    (dict(name="MAIN ST", post_type="Street"), "Main Street"),
    (dict(name="MAIN STREET", post_type="Street"), "Main Street"),
    (dict(name="7TH AVE", post_type="Court"), "7th Avenue Court"),
    (dict(name="SILVER LK", post_type="Road"), "Silver Lake Road"),
    # The name repeats the type and directional that the fields already carry.
    (dict(name="CARIBBEAN DR W", post_type="Drive", post_dir="West"), "Caribbean Drive West"),
    (dict(name="US 64 HWY E", post_type="Highway", post_dir="East"), "US 64 Highway East"),
    (dict(name="RUSSWOOD LN W", post_type="Lane", post_dir="West"), "Russwood Lane West"),
    # Lettered streets are not directionals.
    (dict(name="E", post_type="Street"), "E Street"),
    (dict(name="E ST"), "E Street"),
    (dict(name="AVENUE N"), "Avenue N"),
    (dict(name="N", pre_type="Avenue"), "Avenue N"),
    # Routes.
    (dict(name="CR 123"), "County Road 123"),
    (dict(name="CO RD 12"), "County Road 12"),
    (dict(name="HWY 79", post_dir="North"), "Highway 79 North"),
    (dict(name="FS RD 21"), "Forest Service Road 21"),
    (dict(name="FM 1960"), "FM 1960"),
    (dict(name="US 50"), "US 50"),
    (dict(name="US HIGHWAY 50"), "US Highway 50"),
    (dict(name="OLD US 40", post_type="Highway", pre_dir="East"), "East Old US 40 Highway"),
    (dict(name="AR 5"), "AR 5"),
    # Abbreviations inside the name.
    (dict(name="Ave W"), "Avenue W"),
    (dict(name="Woodruff Pl Middle", post_type="Drive"), "Woodruff Place Middle Drive"),
    (dict(name="13Th", post_type="Street"), "13th Street"),
    (dict(name="CHEROKEE HGTS", post_type="Drive"), "Cherokee Heights Drive"),
    (dict(name="COORS BLVD BYPASS", post_dir="Northwest"), "Coors Boulevard Bypass Northwest"),
    (dict(name="WOODLANE ST EXTENSION"), "Woodlane Street Extension"),
    # Modifiers.
    (dict(name="MILL", post_type="Road", pre_mod="OLD"), "Old Mill Road"),
    (dict(name="MAIN", post_type="Street", pre_mod="APT"), "Main Street"),
    (dict(name="10TH", post_type="Street", pre_dir="East", post_mod="EXT"),
     "East 10th Street Extension"),
])
def test_build_street(args, expected):
    assert street(**args)[0] == expected


@pytest.mark.parametrize("args, flag", [
    (dict(name="St Clair", post_type="Street"), "expanded_st"),
    (dict(name="MAIN ST"), "name_had_type"),
    (dict(name="S MAIN", post_type="Street"), "name_had_directional"),
    (dict(name="FM 1960"), "route_abbreviation"),
    (dict(name="MAIN", post_type="Street", pre_mod="APT"), "dropped_pre_modifier"),
    (dict(name="MAIN ST", post_type="Street"), "duplicate_type"),
])
def test_build_street_flags(args, flag):
    assert flag in street(**args)[1]


def test_plain_street_has_no_flags():
    assert street("MAIN", "Street", "North") == ("North Main Street", [])


@pytest.mark.parametrize("name, flag", [
    (None, "no_street_name"),
    ("<Null>", "no_street_name"),
    ("UNNAMED", "placeholder_street_name"),
    ("Unknown Road", "placeholder_street_name"),
])
def test_unusable_street(name, flag):
    assert street(name) == (None, [flag])


def check(args, expected, flag):
    value, flags = street(**args)
    assert value == expected
    if flag:
        assert flag in flags


# S1: ST is Saint, Street or State by position and the next word (saint-vs-street.md).
@pytest.mark.parametrize("args, expected, flag", [
    # Trailing ST, including after a stripped EXT or type.
    (dict(name="WASHINGTON ST EXT"), "Washington Street Extension", "name_had_type"),
    (dict(name="WASHINGTON ST EXT", pre_dir="East", post_type="Street", post_mod="EXTENSION"),
     "East Washington Street Extension", "duplicate_type"),
    (dict(name="24TH ST ST"), "24th Street", "duplicate_type"),
    (dict(name="24TH ST ST", post_type="Street"), "24th Street", "duplicate_type"),
    (dict(name="Blazing Star St ST"), "Blazing Star Street", "duplicate_type"),
    (dict(name="7TH ST EXTENSION"), "7th Street Extension", None),
    # Lone ST.
    (dict(name="ST"), "St", "ambiguous_st"),
    # State before route words, including LOOP and SPUR.
    (dict(name="ST LOOP 7"), "State Loop 7", "expanded_st"),
    (dict(name="OLD ST RT 122"), "Old State Route 122", "expanded_st"),
    (dict(name="ST HIGHWAY 146", post_dir="North"), "State Highway 146 North", "expanded_st"),
    (dict(name="ST SPUR 5"), "State Spur 5", "expanded_st"),
    # Leading ST before a number stays St.
    (dict(name="St 18", pre_dir="East", post_type="Road"), "East St 18 Road", "ambiguous_st"),
    # Leading ST before a word is Saint, listed or not.
    (dict(name="ST COSMAS", post_type="Lane"), "Saint Cosmas Lane", "st_saint_unlisted"),
    (dict(name="ST KATERI", post_type="Drive"), "Saint Kateri Drive", "expanded_st"),
    (dict(name="ST MARY'S", post_type="Road"), "Saint Mary's Road", "expanded_st"),
    (dict(name="ST JOHNS", post_type="Road"), "Saint Johns Road", "expanded_st"),
    (dict(name="ST JOHN", post_type="Road"), "Saint John Road", "expanded_st"),
    (dict(name="N ST LOUIS", post_type="Avenue"), "North Saint Louis Avenue", "expanded_st"),
    (dict(name="ST XAVIER ST"), "Saint Xavier Street", "expanded_st"),
    # Interior ST: Saint only before a listed word.
    (dict(name="ROYAL ST GEORGE", post_type="Drive"), "Royal Saint George Drive", "expanded_st"),
    (dict(name="JAYSVILLE ST JOHNS", post_type="Road"), "Jaysville Saint Johns Road",
     "expanded_st"),
    (dict(name="Main St Wtn"), "Main Street Wtn", "st_street_interior"),
    (dict(name="Church St Mystic"), "Church Street Mystic", "st_street_interior"),
    (dict(name="MAIN ST DERBY", post_type="Center"), "Main Street Derby Center",
     "st_street_interior"),
    (dict(name="12th St Cutoff", post_dir="Southeast"), "12th Street Cutoff Southeast",
     "st_street_interior"),
    (dict(name="DAVIS ST FERRY", post_type="Road"), "Davis Street Ferry Road",
     "st_street_interior"),
    (dict(name="7TH ST LOT 2"), "7th Street Lot 2", "st_street_interior"),
    (dict(name="W 26TH ST #2"), "West 26th Street #2", "st_street_interior"),
    (dict(name="I ST CENTER"), "I Street Center", "st_street_interior"),
    # The known miss: HEN abbreviates Henry (OSM "Burkettsville-Saint Henry Road").
    (dict(name="BURKETTSVILLE ST HEN", post_type="Road"), "Burkettsville Street Hen Road",
     "st_street_interior"),
    # STE: State before a route word, Sainte before a name, otherwise a suite.
    (dict(name="PVT RD 3952 STE RTE 378"), "Private Road 3952 State Route 378", "expanded_st"),
    (dict(name="STE RTE 21 E", post_type="Highway"), "State Route 21 Highway East",
     "expanded_st"),
    (dict(name="Sault Ste Marie", post_type="Drive"), "Sault Sainte Marie Drive", "expanded_st"),
    (dict(name="Ste Aurelie", post_type="Road"), "Sainte Aurelie Road", "expanded_st"),
    (dict(name="RAMSHORN STE 2"), "Ramshorn Ste 2", "suite_in_street_name"),
    (dict(name="1 STE C"), "1 Ste C", "suite_in_street_name"),
    (dict(name="STATE ROAD A STE"), "State Road A Ste", "suite_in_street_name"),
])
def test_saint_street_state(args, expected, flag):
    check(args, expected, flag)


def test_trailing_st_is_not_flagged_ambiguous():
    assert "ambiguous_st" not in street("WASHINGTON ST EXT")[1]


# S2: DR is Doctor or Drive by position and the next word (doctor-vs-drive.md).
@pytest.mark.parametrize("args, expected, flag", [
    (dict(name="DR MARTIN LUTHER KING JR", post_type="Boulevard"),
     "Doctor Martin Luther King Jr Boulevard", "expanded_dr_doctor"),
    (dict(name="DR MARTIN LUTHER KING JR", post_type="Drive"),
     "Doctor Martin Luther King Jr Drive", "expanded_dr_doctor"),
    (dict(name="Dr Mlk Jr", pre_dir="East", post_type="Boulevard"),
     "East Doctor MLK Jr Boulevard", "expanded_dr_doctor"),
    (dict(name="DR SPRINGS", post_type="Road"), "Doctor Springs Road", "expanded_dr_doctor"),
    (dict(name="DR STREET", post_type="Road"), "Doctor Street Road", "expanded_dr_doctor"),
    (dict(name="DR WILLIAM G WEATHERS DR"), "Doctor William G Weathers Drive",
     "expanded_dr_doctor"),
    (dict(name="N DR MLK JR", pre_dir="North", post_type="Street"),
     "North N Doctor MLK Jr Street", "expanded_dr_doctor"),
    (dict(name="REV DR RANSOM HOWARD", post_type="Street"),
     "Reverend Doctor Ransom Howard Street", "expanded_dr_doctor"),
    (dict(name="DR 810"), "Drive 810", "expanded_dr_drive"),
    (dict(name="Dr", pre_dir="South"), "South Drive", "expanded_dr_drive"),
    (dict(name="FOOTHILLS DR SOUTH"), "Foothills Drive South", "expanded_dr_drive"),
    (dict(name="PVT DR 3 TWP RD 1128"), "Private Drive 3 Township Road 1128",
     "expanded_dr_drive"),
    (dict(name="MALLARD BEACH DR 22"), "Mallard Beach Drive 22", "expanded_dr_drive"),
    (dict(name="LINDA DR #2"), "Linda Drive #2", "expanded_dr_drive"),
    (dict(name="PRAIRIE POINT DR DR"), "Prairie Point Drive", "duplicate_type"),
    (dict(name="CARIBBEAN DR EXT"), "Caribbean Drive Extension", "expanded_dr_drive"),
    (dict(name="MUIRFIELD DR SW"), "Muirfield Drive Southwest", "name_had_type"),
    (dict(name="DR", pre_type="County Highway"), "County Highway DR", "route_abbreviation"),
    (dict(name="DR PEPPER", post_type="Road"), "Dr Pepper Road", None),
    # Left as written and flagged.
    (dict(name="Dr", post_type="Drive"), "Dr Drive", "ambiguous_dr"),
    (dict(name="DR RD"), "Dr Road", "ambiguous_dr"),
    (dict(name="PARK DR TURKEY", post_type="Lake"), "Park Dr Turkey Lake", "ambiguous_dr"),
])
def test_doctor_drive(args, expected, flag):
    check(args, expected, flag)


def test_dr_pepper_is_not_flagged():
    assert not any("_dr" in f for f in street("DR PEPPER", "Road")[1])


# S3: abbreviations inside the name, some keyed on the state.
@pytest.mark.parametrize("args, expected, flag", [
    (dict(name="LEE RD 137"), "Lee Road 137", None),
    (dict(name="TWP RD 352"), "Township Road 352", None),
    (dict(name="TOWNSHIP RD 12"), "Township Road 12", None),
    (dict(name="TWP 4"), "Township 4", None),
    (dict(name="TR 319", state="OH"), "Township Road 319", None),
    (dict(name="TR N56", state="NM"), "TR N56", None),
    (dict(name="TR 319", state="NM"), "TR 319", "route_abbreviation"),
    (dict(name="SR 241", state="OH"), "State Route 241", None),
    (dict(name="SR 65"), "SR 65", "route_abbreviation"),
    (dict(name="SR 65", state="WV"), "SR 65", "route_abbreviation"),
    (dict(name="IH 35"), "Interstate 35", None),
    (dict(name="USFS RD 7175"), "USFS Road 7175", None),
    (dict(name="USFS 7175"), "USFS 7175", "route_abbreviation"),
    (dict(name="HAWTHORN HL"), "Hawthorn Hill", "name_had_type"),
    (dict(name="Capitol HL", post_type="Street"), "Capitol Hill Street", None),
    (dict(name="MC GRATH", post_type="Avenue"), "McGrath Avenue", None),
    (dict(name="Mc Vicker", post_type="Avenue"), "McVicker Avenue", None),
    # Not changed: RD alone before a number, MC before digits (Maricopa County routes).
    (dict(name="RD 105"), "RD 105", "route_abbreviation"),
    (dict(name="MC 85"), "MC 85", "route_abbreviation"),
    (dict(name="RD 5 AND 6"), "RD 5 and 6", None),
])
def test_interior_abbreviations(args, expected, flag):
    check(args, expected, flag)


def test_ohio_routes_not_flagged():
    assert "route_abbreviation" not in street("SR 241", state="OH")[1]


# S4: a leading N/S/E/W followed by a single letter is an initial.
@pytest.mark.parametrize("args, expected, flag", [
    (dict(name="W C HANDY", post_type="Place"), "W C Handy Place", "initials_not_expanded"),
    (dict(name="W B YEATS", post_type="Drive"), "W B Yeats Drive", "initials_not_expanded"),
    (dict(name="W. C. HANDY", post_type="Place"), "W. C. Handy Place", "initials_not_expanded"),
    (dict(name="N J ELMER WEAVER FWY"), "N J Elmer Weaver Freeway", "initials_not_expanded"),
    # Lettered streets keep the directional.
    (dict(name="S G AVE"), "South G Avenue", "name_had_directional"),
    (dict(name="W N AVE"), "West N Avenue", "name_had_directional"),
    (dict(name="N MAIN", post_type="Street"), "North Main Street", "name_had_directional"),
])
def test_initials(args, expected, flag):
    check(args, expected, flag)


# S5: ordinal suffix on numbered streets (regional-expansions.md, ours-vs-esri.md).
@pytest.mark.parametrize("args, expected, flag", [
    (dict(name="47", pre_dir="West", post_type="Street", state="NY", county="New York"),
     "West 47th Street", "ordinal_added"),
    (dict(name="63", post_type="Drive", state="NY", county="Queens"), "63rd Drive",
     "ordinal_added"),
    (dict(name="112", post_type="Street", state="NY", county="Kings"), "112th Street",
     "ordinal_added"),
    (dict(name="1", post_type="Avenue", state="NY", county="Bronx"), "1st Avenue",
     "ordinal_added"),
    (dict(name="116", pre_type="Beach", post_type="Street", state="NY", county="Queens"),
     "Beach 116th Street", "ordinal_added"),
    (dict(name="BAY 13", post_type="Street", state="NY", county="Kings"), "Bay 13th Street",
     "ordinal_added"),
    (dict(name="BEACH 116", post_type="Street", state="NY", county="Queens"),
     "Beach 116th Street", "ordinal_added"),
    (dict(name="6", post_type="Avenue", post_dir="South", state="MN", county="Stearns"),
     "6th Avenue South", "ordinal_added"),
    (dict(name="11", post_type="Street", state="NE", county="Lincoln"), "11th Street",
     "ordinal_added"),
    (dict(name="22", post_type="Place", state="OH", county="Columbiana"), "22nd Place",
     "ordinal_added"),
    (dict(name="337", pre_dir="East", post_type="Street", state="OH", county="Lake"),
     "East 337th Street", "ordinal_added"),
    (dict(name="520", pre_dir="East", post_type="Avenue", state="KS", county="Crawford"),
     "East 520th Avenue", "ordinal_added"),
    # Unchanged.
    (dict(name="930", pre_dir="East", post_type="Avenue", state="IL", county="Fayette"),
     "East 930 Avenue", "numeric_street_name"),
    (dict(name="3600", post_type="Avenue", state="KS", county="Dickinson"), "3600 Avenue",
     "numeric_street_name"),
    (dict(name="400", post_type="Highway", state="KS", county="Crawford"), "400 Highway", None),
    (dict(name="25", post_type="Road", state="CO", county="Mesa"), "25 Road", None),
    (dict(name="410", pre_dir="East", post_type="Road", state="OK", county="Wagoner"),
     "East 410 Road", None),
    (dict(name="12", post_type="Street", state="UT", county="Box Elder"), "12 Street", None),
    (dict(name="12TH", post_type="Street", state="NY", county="Kings"), "12th Street", None),
    (dict(name="J", post_type="Street", state="NY", county="Kings"), "J Street", None),
    (dict(name="47", post_type="Street", state="NY", county="Erie"), "47th Street",
     "ordinal_added"),
    (dict(name="5", pre_type="County Road", state="NY", county="Kings"), "County Road 5", None),
    (dict(name="47", post_type="Street"), "47 Street", None),
])
def test_ordinal_suffix(args, expected, flag):
    check(args, expected, flag)


@pytest.mark.parametrize("number, expected", [
    ("1", "1st"), ("2", "2nd"), ("3", "3rd"), ("4", "4th"), ("11", "11th"), ("12", "12th"),
    ("13", "13th"), ("21", "21st"), ("101", "101st"), ("111", "111th"), ("07", "7th"),
])
def test_ordinal_spelling(number, expected):
    assert street(number, "Street", state="NY", county="Kings")[0] == f"{expected} Street"


def test_no_ordinal_flag_on_roads():
    assert street("25", "Road", state="CO", county="Mesa")[1] == []


# S6: the same directional before and after. The field repeat is dropped only in the states
# whose sources do that systematically; elsewhere it can tell two streets apart (Mason County
# WA has "East Mason Lake Drive East" and "East Mason Lake Drive West").
@pytest.mark.parametrize("args, expected, flag", [
    (dict(name="6", pre_dir="West", post_type="Street", post_dir="West", state="NE",
          county="Lincoln"), "West 6th Street", "duplicate_directional_dropped"),
    (dict(name="MAIN", pre_dir="North", post_type="Street", post_dir="North", state="KY"),
     "North Main Street", "duplicate_directional_dropped"),
    (dict(name="MASON LAKE", pre_dir="East", post_type="Drive", post_dir="East", state="WA"),
     "East Mason Lake Drive East", "repeated_directional"),
    (dict(name="LAKEWOOD", pre_dir="East", post_type="Parkway", post_dir="East", state="AZ"),
     "East Lakewood Parkway East", "repeated_directional"),
    (dict(name="259", pre_dir="North", pre_type="United States Highway", post_dir="North",
          state="TX"), "North United States Highway 259 North", "repeated_directional"),
    (dict(name="MAIN", pre_dir="North", post_type="Street", post_dir="North"),
     "North Main Street North", "repeated_directional"),
    # The name itself ending in the trailing directional is a repeat in any state.
    (dict(name="FAIRVIEW HILL DR WEST", post_dir="West"), "Fairview Hill Drive West",
     "duplicate_directional_dropped"),
    (dict(name="300", pre_dir="South", post_dir="East"), "South 300 East", None),
    (dict(name="300 EAST", pre_dir="South", post_dir="East"), "South 300 East",
     "duplicate_directional_dropped"),
    (dict(name="MAIN", pre_dir="West", post_type="Street", post_dir="East"),
     "West Main Street East", None),
])
def test_repeated_directional(args, expected, flag):
    check(args, expected, flag)


# S7: casing fixes.
@pytest.mark.parametrize("text, expected", [
    ("Saint Alban'S", "Saint Alban's"),
    ("Alban'S", "Alban's"),
    ("Mlk", "MLK"),
    ("mlk", "MLK"),
    ("Dr Mlk Jr", "Dr MLK Jr"),
    ("O'Brien", "O'Brien"),
])
def test_casing_fixes(text, expected):
    assert smart_title(text) == expected


VALIDATION = Path(__file__).parent / "fixtures" / "street_validation.csv"


def test_osm_validated_streets():
    """ST and DR names whose reading OSM confirmed (saint-vs-street.md, doctor-vs-drive.md).

    The one known miss is BURKETTSVILLE ST HEN (Saint Henry), which needs a nearby-road lookup.
    """
    with open(VALIDATION, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    failures = []
    for row in rows:
        args = [row[c] or None for c in (
            "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep", "St_Name", "St_PosTyp",
            "St_PosDir", "St_PosMod", "State", "County")]
        got = build_street(*args)[0]
        if got != row["expected"]:
            failures.append(f"{row['State']} {row['St_Name']!r}: {got!r} != {row['expected']!r}")
    print("\n".join(failures))
    assert len(rows) > 250
    assert len(failures) <= len(rows) // 100, failures
