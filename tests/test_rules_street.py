import pytest

from nad_pipeline.rules.casing import smart_title
from nad_pipeline.rules.street import build_street


def street(name, post_type=None, pre_dir=None, post_dir=None, pre_type=None, pre_sep=None,
           pre_mod=None, post_mod=None):
    return build_street(pre_mod, pre_dir, pre_type, pre_sep, name, post_type, post_dir, post_mod)


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
