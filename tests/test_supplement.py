import csv

from nad_pipeline import supplement
from nad_pipeline.rules.city import PlaceNames
from nad_pipeline.supplement import download_source, supplement_dir

from test_backfill_dedup import read_points, row, write_points

NAMES = PlaceNames([
    ("KY", "Somerset", "census_place"), ("KY", "La Grange", "census_place"),
    ("KY", "Glasgow", "census_place"), ("IN", "Columbus", "census_place"),
])


def source_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["number", "community", "lon", "lat"])
        writer.writerows(rows)
    return path


def test_supplement_fills_missing_city_from_matching_source_point(tmp_path):
    src = write_points(tmp_path / "osm", [
        row(1, number="2271", state="KY", city=None, flags=["no_city"]),
        row(2, number="2271", state="KY", city="Burnside"),                   # has a city
        row(3, number="628", state="KY", city=None, flags=["no_city"]),      # number differs
        row(4, number="6910", lat=40.01, state="KY", city=None, flags=["no_city"]),
        row(5, number="3516 A", lat=40.02, state="KY", city=None, flags=["no_city"]),
        row(6, number="2271", state="KY", city=None, drop="inactive_lifecycle",
            flags=["no_city"]),
        row(7, number="2271", lat=40.0005, state="KY", city=None, flags=["no_city"]),  # 55 m
        row(8, number="2271", state="IN", city=None, flags=["no_city"]),      # other state
    ])
    ky = source_csv(tmp_path / "ky.csv", [
        (2271, "SOMERSET", -86.00001, 40.00001),
        (2271, "GLASGOW", -86.0001, 40.0001),        # same number, further away
        (6910, "SHELBY", -86.0, 40.01),              # not a known place in Kentucky
        (3516, "LAGRANGE", -86.0, 40.02),
    ])
    report = tmp_path / "report.csv"
    out = supplement_dir(src, tmp_path / "supplemented", {"KY": ky}, NAMES, report)
    assert read_points(out, "addr_city, flags") == [
        ("Somerset", ["city_from_source_msag"]),
        ("Burnside", []),
        (None, ["no_city"]),
        (None, ["no_city"]),
        ("La Grange", ["city_from_source_msag"]),
        (None, ["no_city"]),
        (None, ["no_city"]),
        (None, ["no_city"]),
    ]
    with open(report, newline="", encoding="utf-8") as f:
        rows = {(r["community"], r["filled_as"], int(r["n_rows"])) for r in csv.DictReader(f)}
    assert rows == {("SOMERSET", "Somerset", 1), ("SHELBY", "", 1), ("LAGRANGE", "La Grange", 1)}


def test_supplement_without_sources_passes_rows_through(tmp_path):
    src = write_points(tmp_path / "osm", [row(1, city=None, flags=["no_city"]), row(2)])
    out = supplement_dir(src, tmp_path / "supplemented", {}, NAMES)
    assert read_points(out, "addr_city, flags") == [(None, ["no_city"]), ("Columbus", [])]


def test_download_source_pages_by_object_id(tmp_path, monkeypatch):
    monkeypatch.setattr(supplement, "PAGE_SIZE", 2)
    features = {
        1: {"attributes": {"Add_Number": 10, "MSAGComm": "SOMERSET"},
            "geometry": {"x": -84.6, "y": 37.0}},
        2: {"attributes": {"Add_Number": 11, "MSAGComm": " "},
            "geometry": {"x": -84.6, "y": 37.0}},
        3: {"attributes": {"Add_Number": 12, "MSAGComm": "GLASGOW"}},          # no geometry
        4: {"attributes": {"Add_Number": 13, "MSAGComm": "GLASGOW"},
            "geometry": {"x": -85.9, "y": 37.0}},
        5: {"attributes": {"Add_Number": None, "MSAGComm": "GLASGOW"},
            "geometry": {"x": -85.9, "y": 37.0}},
    }
    queries = []

    def fake_get(url, params):
        if "outStatistics" in params:
            return {"features": [{"attributes": {"LO": 1, "HI": 5}}]}
        queries.append(params["where"])
        start = int(params["where"].split(">= ")[1].split(" ")[0])
        return {"features": [features[i] for i in (start, start + 1) if i in features]}

    dest = download_source("KY", tmp_path / "ky" / "communities.csv", get_json=fake_get)
    with open(dest, newline="", encoding="utf-8") as f:
        assert list(csv.reader(f)) == [
            ["number", "community", "lon", "lat"],
            ["10", "SOMERSET", "-84.6", "37.0"],
            ["13", "GLASGOW", "-85.9", "37.0"],
        ]
    assert sorted(queries) == [
        "OBJECTID >= 1 AND OBJECTID < 3", "OBJECTID >= 3 AND OBJECTID < 5",
        "OBJECTID >= 5 AND OBJECTID < 7",
    ]
    # A finished download is reused, not fetched again.
    queries.clear()
    download_source("KY", dest, get_json=fake_get)
    assert queries == []
