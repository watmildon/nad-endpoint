import urllib.error

import pytest

from nad_pipeline.spotcheck import (
    PUBLIC_OVERPASS, compare_addresses, compare_streets, differs_only_by_directional, overpass,
    overpass_endpoints,
)


def point(housenumber, street, lat=40.0, lon=-86.0, city="Columbus", postcode="47201"):
    return {"lat": lat, "lon": lon, "housenumber": housenumber, "street": street,
            "city": city, "postcode": postcode}


def test_streets_classified_against_osm_names():
    points = [
        point("1", "North Main Street"),
        point("2", "North Main Street"),
        point("3", "Mcadams Avenue"),
        point("4", "Old Route 7"),
        point("5", "Hwy191"),
        point("6", None),
    ]
    result = compare_streets(
        points, names={"North Main Street", "McAdams Avenue", "Highway 191"},
        alt_names={"Old Route 7"},
    )
    assert (result["exact"], result["alternate"], result["case_only"], result["unmatched"]) == (
        2, 1, 1, 1
    )
    assert result["no_street"] == 1
    assert (1, "Mcadams Avenue", "McAdams Avenue") in result["mismatches"]
    assert [m[1] for m in result["mismatches"]] == ["Hwy191", "Mcadams Avenue"]


def test_addresses_match_same_number_and_street_nearby():
    osm = [
        point("12", "Oak Street", city="Columbus", postcode="47201-1234"),
        point("14", "Oak St"),
        point("16", "Oak Street", lat=40.01),  # about 1.1 km away
        point("99", "Elm Street"),
    ]
    source = [
        point("12", "Oak Street", lat=40.0002, city="COLUMBUS"),
        point("12", "Oak Street", lat=40.0003),  # second unit, same address
        point("14", "Oak Street"),
        point("16", "Oak Street"),
        point("102 C", "Pine Street"),
    ]
    result = compare_addresses(source, osm)
    assert result["source_distinct"] == 4
    assert result["matched"] == 1
    assert result["street_conflict"] == 1
    assert result["not_in_osm"] == 2
    assert result["osm_only"] == 3
    assert result["street_conflicts"] == [(("Oak Street", "Oak St"), 1)]
    assert result["city_diffs"] == [(("COLUMBUS", "Columbus"), 1)]
    assert result["postcode_diffs"] == []


def test_housenumber_spacing_is_ignored():
    result = compare_addresses([point("102 C", "Pine Street")], [point("102C", "Pine Street")])
    assert result["matched"] == 1


@pytest.mark.parametrize("a, b, expected", [
    ("North Pennsylvania Street", "Pennsylvania Street", True),
    ("Pennsylvania Street", "North Pennsylvania Street", True),
    ("Adventureland Drive Northwest", "Adventureland Drive", True),
    ("East Broadway", "Broadway", True),
    ("North Main Street", "South Main Street", False),
    ("Lake Drive Southeast", "Lake Drive Southwest", False),
    ("North Street", "South Street", False),
    ("North Main Street", "North Main Street", False),
    ("North Main Street", "Main Avenue", False),
    ("North Main Street", None, False),
])
def test_differs_only_by_directional(a, b, expected):
    assert differs_only_by_directional(a, b) is expected


def test_directional_difference_is_not_a_street_mismatch():
    points = [point("1", "North Pearl Street"), point("2", "South Pearl Street")]
    result = compare_streets(points, names={"Pearl Street", "South Pearl Street"}, alt_names=set())
    assert (result["exact"], result["directional_only"], result["unmatched"]) == (1, 1, 0)
    assert result["directional_differences"] == [(1, "North Pearl Street", "Pearl Street")]
    assert result["mismatches"] == []


def test_directional_difference_still_matches_address():
    result = compare_addresses(
        [point("5", "North Pearl Street"), point("7", "North Pearl Street")],
        [point("5", "Pearl Street"), point("7", "South Pearl Street")],
    )
    assert result["matched"] == 1
    assert result["matched_directional_differs"] == 1
    assert result["street_conflict"] == 1
    assert result["osm_only"] == 1


def test_punctuation_difference_is_its_own_category():
    points = [point("1", "Bennetts Way"), point("2", "C and H Circle"),
              point("3", "Brannon Harris Way")]
    result = compare_streets(
        points, names={"Bennett's Way", "C & H Circle", "Brannon-Harris Way"}, alt_names=set())
    assert (result["punctuation_only"], result["unmatched"]) == (3, 0)


PRIVATE = "https://private.example/api/interpreter"


def test_overpass_endpoints_prefer_env_then_repo_file(tmp_path):
    (tmp_path / ".overpass-url").write_text("https://repo.example/api\n")
    assert overpass_endpoints({}, tmp_path) == ["https://repo.example/api", *PUBLIC_OVERPASS]
    assert overpass_endpoints({"OVERPASS_PRIMARY_URL": PRIVATE}, tmp_path)[0] == PRIVATE
    assert overpass_endpoints(
        {"OVERPASS_URL": PRIVATE, "OVERPASS_PRIMARY_URL": "x"}, tmp_path)[0] == PRIVATE


def test_overpass_endpoints_fall_back_to_public_mirrors(tmp_path):
    assert overpass_endpoints({}, tmp_path) == PUBLIC_OVERPASS


def test_overpass_fails_over_without_naming_servers():
    calls = []

    def get_json(url, data):
        calls.append(url)
        if url == PRIVATE:
            raise urllib.error.HTTPError(url, 504, "Gateway Timeout", {}, None)
        if url == PUBLIC_OVERPASS[0]:
            return {"remark": "runtime error: Query timed out", "elements": []}
        return {"elements": [{"type": "node"}]}

    endpoints = [PRIVATE, *PUBLIC_OVERPASS]
    assert overpass("q", endpoints, get_json) == {"elements": [{"type": "node"}]}
    assert calls == endpoints[:3]

    def failing(url, data):
        raise ValueError("not JSON")

    with pytest.raises(IOError) as exc:
        overpass("q", [PRIVATE, PUBLIC_OVERPASS[0]], failing)
    assert str(exc.value).endswith("server 1: ValueError; server 2: ValueError")
    assert "example" not in str(exc.value) and "overpass" not in str(exc.value).split(":", 1)[1]


def test_overpass_accepts_an_empty_result():
    assert overpass("q", [PRIVATE], lambda url, data: {"elements": []}) == {"elements": []}
