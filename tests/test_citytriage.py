import csv

from nad_pipeline.citytriage import COLUMNS, city_triage_dir
from nad_pipeline.rules.city import Override, PlaceNames

from test_backfill_dedup import geojson, row, square, write_points

UNKNOWN = ["city_not_in_reference"]


def test_city_triage_buckets_unknown_city_values(tmp_path):
    osm = write_points(tmp_path / "osm", [
        # Inside a place it misspells.
        row(1, lon=-97.15, lat=32.70, city="Dalworthington Gardn", state="TX", flags=UNKNOWN),
        row(2, lon=-97.15, lat=32.70, city="Dalworthington Gardn", state="TX", flags=UNKNOWN),
        # Inside a place with another name; one point outside it.
        row(3, lon=-93.05, lat=34.50, city="Hot Springs National Park", state="AR",
            flags=UNKNOWN),
        row(4, lon=-93.05, lat=34.50, city="Hot Springs National Park", state="AR",
            flags=UNKNOWN),
        row(5, lon=-93.50, lat=34.90, city="Hot Springs National Park", state="AR",
            flags=UNKNOWN, number="9", street="Far Road"),
        # Outside every place, inside a county subdivision; no ZIP from the source.
        row(6, lon=-73.85, lat=41.30, city="Cortlandt Manor", state="NY", county="Westchester",
            postcode=None, flags=UNKNOWN, number="12", street="Lexington Avenue"),
        # Not reported: a known city, and a dropped row.
        row(7, lon=-97.15, lat=32.70, city="Arlington", state="TX"),
        row(8, lon=-97.15, lat=32.70, city="Dalworthington Gardn", state="TX", flags=UNKNOWN,
            drop="duplicate"),
    ])
    places = geojson(tmp_path / "places.geojson", [
        square(-97.2, 32.6, -97.1, 32.8, STUSPS="TX", NAME="Dalworthington Gardens"),
        square(-93.1, 34.4, -93.0, 34.6, STUSPS="AR", NAME="Hot Springs"),
    ])
    cousubs = geojson(tmp_path / "cousubs.geojson", [
        square(-74.0, 41.2, -73.7, 41.4, STUSPS="NY", NAME="Cortlandt", NAMELSAD="Cortlandt town"),
    ])
    zctas = geojson(tmp_path / "zctas.geojson", [
        square(-74.0, 41.2, -73.7, 41.4, ZCTA5CE20="10567"),
    ])
    names = PlaceNames([], overrides=[
        Override("NY", "Cortlandt Manor", "hold", "Westchester", note="USPS name? not checked"),
    ])
    out = city_triage_dir(osm, tmp_path / "report" / "city_triage.csv", places, cousubs, zctas,
                          names)

    with open(out, encoding="utf-8", newline="") as f:
        rows = {(r["state"], r["city"]): r for r in csv.DictReader(f)}
    assert list(next(iter(rows.values()))) == COLUMNS
    assert set(rows) == {("TX", "Dalworthington Gardn"), ("AR", "Hot Springs National Park"),
                         ("NY", "Cortlandt Manor")}

    typo = rows[("TX", "Dalworthington Gardn")]
    assert (typo["n"], typo["bucket"], typo["suggested"], typo["place_share"]) == (
        "2", "correction_place", "Dalworthington Gardens", "1.0")
    assert (typo["top_zip"], typo["zip_from"]) == ("47201", "source")

    postal = rows[("AR", "Hot Springs National Park")]
    assert (postal["n"], postal["bucket"], postal["suggested"], postal["place_share"]) == (
        "3", "differs_from_place", "Hot Springs", "0.67")

    outside = rows[("NY", "Cortlandt Manor")]
    assert (outside["bucket"], outside["suggested"], outside["cousub_share"]) == (
        "outside_places", "Cortlandt", "1.0")
    assert (outside["top_zip"], outside["zip_from"], outside["sample_address"]) == (
        "10567", "zcta", "12 Lexington Avenue")
    # A reviewed hold shows in the report; values without one have an empty review.
    assert outside["review"] == "hold: USPS name? not checked"
    assert typo["review"] == ""
