"""Stage 8: publish the kept address points as a PMTiles vector tileset.

Consumers (the JOSM MapWithAI plugin, Rapid) read features at the tileset's maximum zoom
and turn properties into OSM tags, so the tiles carry only the addr:* tags, and the maximum
zoom holds every point. Lower zooms are thinned and exist for viewing.

Tiles are built with tippecanoe, which on Windows runs inside WSL. The input is
newline-delimited GeoJSON rather than FlatGeobuf because tippecanoe copies FlatGeobuf
feature ids into the tiles, and those are meaningless row numbers.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import duckdb

from . import config
from .transform import osm_glob

LAYER = "addresses"
MIN_ZOOM = 10
MAX_ZOOM = 14
TAGS = {
    "addr:housenumber": "addr_housenumber",
    "addr:street": "addr_street",
    "addr:unit": "addr_unit",
    "addr:city": "addr_city",
    "addr:state": "addr_state",
    "addr:postcode": "addr_postcode",
}


def export_dir(release: str) -> Path:
    return config.release_dir(release) / "export"


def write_geojson(addresses_dir: Path, out_dir: Path) -> list[Path]:
    """One newline-delimited GeoJSON file per state with the kept rows and their OSM tags."""
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("LOAD spatial")
    states = [r[0] for r in con.execute(
        f"""SELECT DISTINCT addr_state FROM read_parquet('{osm_glob(addresses_dir)}',
            hive_partitioning = false) WHERE drop_reason IS NULL ORDER BY 1"""
    ).fetchall()]
    columns = ", ".join(f'{col} AS "{tag}"' for tag, col in TAGS.items())
    paths = []
    for state in states:
        path = out_dir / f"{state}.geojsonl"
        con.execute(
            f"""
            COPY (
                SELECT ST_Point(lon, lat) AS geom, {columns}
                FROM read_parquet('{osm_glob(addresses_dir)}', hive_partitioning = false)
                WHERE drop_reason IS NULL AND addr_state = '{state}'
            ) TO '{path.as_posix()}' WITH (FORMAT GDAL, DRIVER 'GeoJSONSeq', SRS 'EPSG:4326')
            """
        )
        paths.append(path)
    return paths


def tippecanoe_command(inputs: list[Path], output: Path, release: str) -> list[str]:
    """The tippecanoe invocation; paths are translated for WSL on Windows."""
    args = [
        "tippecanoe", "--force", "-o", _tool_path(output), "-l", LAYER,
        "-n", f"National Address Database {release}",
        "-N", "USDOT National Address Database address points, cleaned for OpenStreetMap",
        "-A", "US Department of Transportation, National Address Database",
        f"-Z{MIN_ZOOM}", f"-z{MAX_ZOOM}",
        # Every point survives at the maximum zoom; lower zooms are thinned for display.
        "--no-feature-limit", "--no-tile-size-limit", "--drop-densest-as-needed",
        # Each point goes in exactly one tile: no edge buffer, no copies at tile seams.
        "--buffer=0", "--no-duplication",
        "-P", "--quiet", *[_tool_path(p) for p in inputs],
    ]
    if _use_wsl():
        return ["wsl.exe", "-e", *args]
    return args


def build_pmtiles(inputs: list[Path], output: Path, release: str, run=subprocess.run) -> Path:
    run(tippecanoe_command(inputs, output, release), check=True)
    return output


def export(release: str, run=subprocess.run) -> Path:
    rel = config.release_dir(release)
    out = export_dir(release)
    inputs = write_geojson(rel / "addresses", out / "geojson")
    pmtiles = build_pmtiles(inputs, out / f"nad-{release}.pmtiles", release, run)
    con = duckdb.connect()
    points = con.execute(
        f"""SELECT count(*) FROM read_parquet('{osm_glob(rel / "addresses")}',
            hive_partitioning = false) WHERE drop_reason IS NULL"""
    ).fetchone()[0]
    (out / f"nad-{release}.json").write_text(json.dumps({
        "release": release, "built": date.today().isoformat(), "points": points,
        "layer": LAYER, "min_zoom": MIN_ZOOM, "max_zoom": MAX_ZOOM, "tags": list(TAGS),
        "file": pmtiles.name, "bytes": pmtiles.stat().st_size,
    }, indent=2))
    return pmtiles


def _use_wsl() -> bool:
    return sys.platform == "win32" and shutil.which("tippecanoe") is None


def _tool_path(path: Path) -> str:
    """A path as tippecanoe sees it: /mnt/<drive>/... when it runs inside WSL."""
    path = Path(path).resolve()
    if not _use_wsl():
        return path.as_posix()
    drive, rest = os.path.splitdrive(path.as_posix())
    return f"/mnt/{drive.rstrip(':').lower()}{rest}"
