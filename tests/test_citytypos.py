import csv

from nad_pipeline.citytypos import COLUMNS, typo_candidates_dir
from nad_pipeline.rules.city import Override, PlaceNames

from test_backfill_dedup import geojson, row, square, write_points

UNKNOWN = ["city_not_in_reference"]
NAMES = PlaceNames([
    ("TX", "Weatherford", "census_place"), ("TX", "Aledo", "census_place"),
    ("KY", "Hallie", "gnis"), ("KY", "Hindman", "census_place"),
])


def test_typo_candidates_scores_and_cross_checks(tmp_path):
    texas = dict(state="TX", county="Parker", postcode="76087")
    osm = write_points(tmp_path / "osm", [
        # A typo; its street neighbours, Census place, ZIP and GNIS all say Weatherford.
        row(1, lon=-97.80, lat=32.76, city="Weatherord", street="Oak Street", flags=UNKNOWN,
            **texas),
        row(2, lon=-97.80, lat=32.76, city="Weatherord", street="Oak Street", flags=UNKNOWN,
            **texas),
        row(3, lon=-97.80, lat=32.76, city="Weatherford", street="Oak Street", **texas),
        row(4, lon=-97.80, lat=32.76, city="Weatherford", street="Elm Street", **texas),
        # A one-letter match to a GNIS place 20 km away and nothing else: listed, no support.
        row(5, lon=-83.00, lat=37.30, city="Mallie", state="KY", county="Knott",
            postcode="41836", flags=UNKNOWN),
        # Nothing close enough: not listed.
        row(6, lon=-97.80, lat=32.76, city="Zzyzx Ranch", flags=UNKNOWN, **texas),
        # Dropped rows are ignored.
        row(7, lon=-97.80, lat=32.76, city="Aleod", flags=UNKNOWN, drop="duplicate", **texas),
    ])
    places = geojson(tmp_path / "places.geojson", [
        square(-97.9, 32.7, -97.7, 32.8, STUSPS="TX", NAME="Weatherford"),
    ])
    gnis = {"TX": [("Weatherford", 32.759, -97.797)], "KY": [("Hallie", 37.48, -83.00)]}
    out = typo_candidates_dir(osm, tmp_path / "report" / "typo_candidates.csv", NAMES, places,
                              gnis)

    with open(out, encoding="utf-8", newline="") as f:
        rows = {(r["state"], r["city"]): r for r in csv.DictReader(f)}
    assert list(next(iter(rows.values()))) == COLUMNS
    assert set(rows) == {("TX", "Weatherord"), ("KY", "Mallie")}

    typo = rows[("TX", "Weatherord")]
    assert (typo["county"], typo["n"], typo["candidate"], typo["via"], typo["edits"]) == (
        "Parker", "2", "Weatherford", "street", "1")
    assert typo["support"] == "street+place+zip+gnis"
    assert (typo["top_zip"], typo["zip_city"], typo["zip_city_share"]) == ("76087", "Weatherford",
                                                                           "1.0")

    far = rows[("KY", "Mallie")]
    assert (far["candidate"], far["via"], far["support"]) == ("Hallie", "gnis", "")
    assert float(far["km"]) > 19


def test_typo_candidates_skips_held_values(tmp_path):
    osm = write_points(tmp_path / "osm", [
        row(1, lon=-83.00, lat=37.30, city="Mallie", state="KY", county="Knott",
            postcode="41836", flags=UNKNOWN),
    ])
    places = geojson(tmp_path / "places.geojson", [
        square(-97.9, 32.7, -97.7, 32.8, STUSPS="TX", NAME="Weatherford"),
    ])
    names = PlaceNames([("KY", "Hallie", "gnis")], overrides=[
        Override("KY", "Mallie", "hold", "Knott", note="a real post office, not Hallie"),
    ])
    out = typo_candidates_dir(osm, tmp_path / "typo_candidates.csv", names, places,
                              {"KY": [("Hallie", 37.48, -83.00)]})
    with open(out, encoding="utf-8", newline="") as f:
        assert list(csv.DictReader(f)) == []
