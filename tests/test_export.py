import json
import sys

import duckdb
import pytest

from nad_pipeline import config, export
from nad_pipeline.export import build_pmtiles, tippecanoe_command, write_flatgeobuf

from test_backfill_dedup import row, write_points


@pytest.fixture
def addresses(tmp_path):
    return write_points(tmp_path / "addresses", [
        row(1, unit="2", postcode="47201"),
        row(2, number="2", city=None, postcode=None),
        row(3, drop="duplicate"),
        row(4, lon=-71.4, lat=41.5, state="RI", city="Newport", postcode="02840"),
    ])


def test_flatgeobuf_per_state_with_osm_tags(tmp_path, addresses):
    paths = write_flatgeobuf(addresses, tmp_path / "fgb")
    assert [p.name for p in paths] == ["IN.fgb", "RI.fgb"]
    con = duckdb.connect()
    con.execute("LOAD spatial")
    rows = con.execute(
        f"""SELECT "addr:housenumber", "addr:street", "addr:unit", "addr:city", "addr:state",
                   "addr:postcode", ST_X(geom), ST_Y(geom)
            FROM ST_Read('{paths[0].as_posix()}') ORDER BY 1"""
    ).fetchall()
    assert rows == [
        ("1", "Oak Street", "2", "Columbus", "IN", "47201", -86.0, 40.0),
        ("2", "Oak Street", None, None, "IN", None, -86.0, 40.0),
    ]


def test_tippecanoe_command_keeps_every_point_at_max_zoom(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "_use_wsl", lambda: False)
    cmd = tippecanoe_command([tmp_path / "IN.fgb"], tmp_path / "out.pmtiles", "r24")
    assert cmd[0] == "tippecanoe"
    assert "--no-feature-limit" in cmd and "--no-tile-size-limit" in cmd
    assert f"-z{export.MAX_ZOOM}" in cmd
    assert cmd[cmd.index("-l") + 1] == "addresses"
    assert cmd[-1].endswith("/IN.fgb")


def test_tippecanoe_runs_in_wsl_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "_use_wsl", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    cmd = tippecanoe_command([tmp_path / "IN.fgb"], tmp_path / "out.pmtiles", "r24")
    assert cmd[:3] == ["wsl.exe", "-e", "tippecanoe"]
    drive = tmp_path.drive.rstrip(":").lower()
    assert cmd[-1].startswith(f"/mnt/{drive}/") and cmd[-1].endswith("/IN.fgb")


def test_export_writes_tiles_and_metadata(tmp_path, addresses, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "r99").mkdir()
    addresses.rename(tmp_path / "r99" / "addresses")
    calls = []

    def fake_run(cmd, check):
        calls.append(cmd)
        (tmp_path / "r99" / "export" / "nad-r99.pmtiles").write_bytes(b"PMTiles")

    pmtiles = export.export("r99", run=fake_run)
    assert pmtiles.exists() and len(calls) == 1
    meta = json.loads((tmp_path / "r99" / "export" / "nad-r99.json").read_text())
    assert meta["points"] == 3 and meta["max_zoom"] == export.MAX_ZOOM
    assert meta["tags"] == ["addr:housenumber", "addr:street", "addr:unit", "addr:city",
                            "addr:state", "addr:postcode"]
