import zipfile
from pathlib import Path

import pytest

from nad_pipeline import config

FIXTURE = Path(__file__).parent / "fixtures" / "nad_sample.csv"
FIXTURE_ROWS = 300

METADATA_XML = """<gmd:MD_Metadata>
  <gmd:geometricObjectCount>
    <gco:Integer>300</gco:Integer>
  </gmd:geometricObjectCount>
</gmd:MD_Metadata>"""


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DOWNLOAD_DIR", tmp_path / "downloads")
    return tmp_path


@pytest.fixture
def nad_zip(tmp_path):
    """A zip laid out like the USDOT download (but Deflate, which Python can write)."""
    path = tmp_path / "TXT.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("NationalAddressDatabaseMetadata.xml", METADATA_XML)
        zf.write(FIXTURE, "TXT/NAD_r99.txt")
    return path
