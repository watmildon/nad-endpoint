import zipfile

import duckdb
import pytest

from nad_pipeline import ingest
from nad_pipeline.ingest import raw_glob

from conftest import FIXTURE, FIXTURE_ROWS


def read_raw(raw_dir, select, where="true"):
    return duckdb.sql(
        f"SELECT {select} FROM read_parquet('{raw_glob(raw_dir)}', hive_partitioning = false) "
        f"WHERE {where}"
    ).fetchall()


def test_release_name_comes_from_text_member(nad_zip):
    info = ingest.find_text_member(nad_zip)
    assert ingest.release_name(info) == "r99"


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_extract_member_matches_original(tmp_path, method):
    path = tmp_path / "x.zip"
    with zipfile.ZipFile(path, "w", method) as zf:
        zf.writestr("readme.xml", "<a/>")
        zf.write(FIXTURE, "TXT/NAD_r99.txt")
    info = ingest.find_text_member(path)
    out = ingest.extract_member(path, info, tmp_path / "out.txt")
    assert out.read_bytes() == FIXTURE.read_bytes()


def test_expected_rows_read_from_metadata(nad_zip):
    assert ingest.expected_rows(nad_zip) == FIXTURE_ROWS


def test_ingest_writes_all_rows_partitioned_by_state(data_dir, nad_zip):
    manifest = ingest.ingest(nad_zip)
    assert manifest["release"] == "r99"
    assert manifest["rows"] == manifest["expected_rows"] == FIXTURE_ROWS
    raw = data_dir / "r99" / "raw"
    assert [p.name for p in raw.iterdir()] == ["State=MA"]
    assert read_raw(raw, "count(*), count(DISTINCT OID_), min(State)") == [
        (FIXTURE_ROWS, FIXTURE_ROWS, "MA")
    ]


def test_ingest_keeps_values_verbatim(data_dir, nad_zip):
    ingest.ingest(nad_zip)
    raw = data_dir / "r99" / "raw"
    # Leading zeros survive, empty fields become NULL, quoted commas stay in one field.
    assert read_raw(raw, "Zip_Code, AddNum_Pre, St_Name, Post_City", "OID_ = '1'") == [
        ("02559", None, "SOUTH", "Not stated")
    ]
    assert read_raw(raw, "Building, Unit", "OID_ = '2491'") == [
        ("ABBINGTON ACADEMY, INC.", "B")
    ]


def test_changed_header_is_rejected(tmp_path):
    txt = tmp_path / "NAD_r99.txt"
    txt.write_text(FIXTURE.read_text(encoding="utf-8").replace("St_Name", "StreetName", 1),
                   encoding="utf-8")
    with pytest.raises(ValueError, match="St_Name"):
        ingest.csv_to_parquet(txt, tmp_path / "raw")
