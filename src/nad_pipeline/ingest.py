"""Stage 2: unpack the NAD text file and convert it verbatim to Parquet partitioned by state."""

import json
import re
import struct
import zipfile
import zlib
from pathlib import Path

import duckdb
import inflate64

from . import config

CHUNK = 1 << 22
ZIP_DEFLATE64 = 9


def find_text_member(zip_path: Path) -> zipfile.ZipInfo:
    with zipfile.ZipFile(zip_path) as zf:
        members = [i for i in zf.infolist() if re.search(r"NAD_r\d+\.txt$", i.filename)]
    if len(members) != 1:
        raise ValueError(f"expected one NAD_r*.txt in {zip_path}, found {len(members)}")
    return members[0]


def release_name(info: zipfile.ZipInfo) -> str:
    return "r" + re.search(r"NAD_r(\d+)\.txt$", info.filename).group(1)


def _decompressor(info: zipfile.ZipInfo):
    # The NAD zip uses Deflate64, which the standard library cannot read.
    if info.compress_type == ZIP_DEFLATE64:
        return inflate64.Inflater().inflate
    if info.compress_type == zipfile.ZIP_DEFLATED:
        return zlib.decompressobj(-15).decompress
    if info.compress_type == zipfile.ZIP_STORED:
        return lambda data: data
    raise ValueError(f"unsupported zip compression method {info.compress_type}")


def iter_member(zip_path: Path, info: zipfile.ZipInfo):
    """Yield the decompressed bytes of a zip member in chunks."""
    inflate = _decompressor(info)
    with open(zip_path, "rb") as f:
        f.seek(info.header_offset)
        header = f.read(30)
        name_len, extra_len = struct.unpack("<HH", header[26:30])
        f.seek(info.header_offset + 30 + name_len + extra_len)
        remaining = info.compress_size
        while remaining:
            data = f.read(min(CHUNK, remaining))
            if not data:
                raise IOError(f"{zip_path} is truncated")
            remaining -= len(data)
            yield inflate(data)


def extract_member(zip_path: Path, info: zipfile.ZipInfo, dest: Path, progress=None) -> Path:
    if dest.exists() and dest.stat().st_size == info.file_size:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    written = 0
    with open(part, "wb") as out:
        for chunk in iter_member(zip_path, info):
            out.write(chunk)
            written += len(chunk)
            if progress:
                progress(written, info.file_size)
    if written != info.file_size:
        raise IOError(f"extracted {written} bytes of {info.filename}, expected {info.file_size}")
    part.replace(dest)
    return dest


def expected_rows(zip_path: Path) -> int | None:
    """Feature count stated in the ISO metadata XML shipped inside the zip, if present."""
    with zipfile.ZipFile(zip_path) as zf:
        members = [i for i in zf.infolist() if i.filename.lower().endswith(".xml")]
    for info in members:
        xml = b"".join(iter_member(zip_path, info)).decode("utf-8", "replace")
        match = re.search(
            r"<gmd:geometricObjectCount>\s*<gco:Integer>(\d+)</gco:Integer>", xml
        )
        if match:
            return int(match.group(1))
    return None


def check_header(txt_path: Path):
    with open(txt_path, encoding="utf-8-sig") as f:
        header = f.readline().rstrip("\r\n").split(",")
    if header != config.NAD_COLUMNS:
        missing = set(config.NAD_COLUMNS) - set(header)
        added = set(header) - set(config.NAD_COLUMNS)
        raise ValueError(
            f"NAD header differs from the expected schema "
            f"(missing: {sorted(missing)}, new: {sorted(added)}, "
            f"reordered: {not missing and not added})"
        )


def csv_to_parquet(txt_path: Path, raw_dir: Path) -> int:
    """Write every column as text, partitioned by State. Returns the row count."""
    check_header(txt_path)
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    columns = {name: "VARCHAR" for name in config.NAD_COLUMNS}
    con.read_csv(
        str(txt_path), header=True, delimiter=",", quotechar='"', escapechar='"',
        columns=columns,
    ).create_view("nad")
    con.execute(
        f"""
        COPY nad TO '{raw_dir.as_posix()}' (
            FORMAT parquet, COMPRESSION zstd, PARTITION_BY (State),
            WRITE_PARTITION_COLUMNS true, OVERWRITE_OR_IGNORE
        )
        """
    )
    return con.execute(
        f"SELECT count(*) FROM read_parquet('{raw_glob(raw_dir)}', hive_partitioning = false)"
    ).fetchone()[0]


def raw_glob(raw_dir: Path) -> str:
    return f"{raw_dir.as_posix()}/**/*.parquet"


def ingest(zip_path: Path, progress=None) -> dict:
    info = find_text_member(zip_path)
    release = release_name(info)
    out_dir = config.release_dir(release)
    txt_path = extract_member(zip_path, info, out_dir / Path(info.filename).name, progress)
    rows = csv_to_parquet(txt_path, out_dir / "raw")
    manifest = {
        "release": release,
        "zip": zip_path.name,
        "rows": rows,
        "expected_rows": expected_rows(zip_path),
        "columns": config.NAD_COLUMNS,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
