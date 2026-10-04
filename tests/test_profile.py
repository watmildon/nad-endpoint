import csv

import pytest

from nad_pipeline import ingest
from nad_pipeline.profile import profile

from conftest import FIXTURE_ROWS


@pytest.fixture
def reports(data_dir, nad_zip):
    ingest.ingest(nad_zip)
    out = {}
    for path in profile("r99"):
        with open(path, newline="", encoding="utf-8") as f:
            out[path.stem] = list(csv.DictReader(f))
    return out


def test_fill_rates_one_row_per_source(reports):
    (row,) = reports["fill_rates"]
    assert row["State"] == "MA"
    assert row["NAD_Source"] == "BOSTON and MASSGIS Massachusetts"
    assert int(row["n_rows"]) == FIXTURE_ROWS
    assert float(row["St_Name"]) == 100.0
    assert float(row["AddNum_Pre"]) == 0.0


def test_top_values_expose_sentinels(reports):
    post_city = [r for r in reports["top_values"] if r["col"] == "Post_City"]
    assert [(r["val"], int(r["n"])) for r in post_city] == [("Not stated", FIXTURE_ROWS)]


def test_street_parts_list_every_value(reports):
    types = {r["val"]: int(r["n"]) for r in reports["street_parts"] if r["col"] == "St_PosTyp"}
    assert types["Road"] > 0
    assert sum(types.values()) <= FIXTURE_ROWS


def test_quality_counts(reports):
    (row,) = reports["quality"]
    assert int(row["n_rows"]) == FIXTURE_ROWS
    assert int(row["street_name_all_caps"]) == int(row["street_name_with_letters"])
    assert int(row["no_coords"]) == 0
    assert int(row["repeated_uuid"]) == 0
    assert -71 < float(row["min_lon"]) <= float(row["max_lon"]) < -70
