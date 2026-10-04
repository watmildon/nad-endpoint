"""Stage 1: download the current NAD text file from the USDOT open data portal."""

import json
import urllib.request
from pathlib import Path

from . import config

CHUNK = 1 << 20


def portal_metadata() -> dict:
    url = f"{config.PORTAL}/api/views/{config.VIEW_ID}.json"
    with urllib.request.urlopen(url) as resp:
        return json.load(resp)


def blob_url(meta: dict) -> str:
    return (
        f"{config.PORTAL}/api/views/{config.VIEW_ID}/files/{meta['blobId']}"
        f"?filename={meta['blobFilename']}"
    )


def download(url: str, dest: Path, expected_size: int, progress=None) -> Path:
    """Download url to dest, resuming a partial download if one exists."""
    if dest.exists() and dest.stat().st_size == expected_size:
        return dest
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = part.stat().st_size if part.exists() else 0
    if have > expected_size:
        part.unlink()
        have = 0
    if have < expected_size:
        req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"})
        with urllib.request.urlopen(req) as resp:
            if have and resp.status != 206:
                # Server ignored the range request; start over.
                have = 0
            with open(part, "ab" if have else "wb") as out:
                while chunk := resp.read(CHUNK):
                    out.write(chunk)
                    have += len(chunk)
                    if progress:
                        progress(have, expected_size)
    if part.stat().st_size != expected_size:
        raise IOError(
            f"{part} is {part.stat().st_size} bytes, expected {expected_size}; "
            "re-run fetch to resume"
        )
    part.replace(dest)
    return dest


def fetch(progress=None) -> Path:
    """Download the current release zip (keyed by the portal's blob id) and return its path."""
    meta = portal_metadata()
    dest = config.DOWNLOAD_DIR / f"{meta['blobId']}.zip"
    download(blob_url(meta), dest, meta["blobFileSize"], progress)
    info = {
        k: meta.get(k)
        for k in ("blobId", "blobFilename", "blobFileSize", "rowsUpdatedAt", "description")
    }
    dest.with_suffix(".json").write_text(json.dumps(info, indent=2))
    return dest
