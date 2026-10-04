import pytest

from nad_pipeline.fetch import download


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(bytes(range(256)) * 100)
    return path


def test_download_complete_file(tmp_path, source):
    dest = download(source.as_uri(), tmp_path / "out" / "a.zip", source.stat().st_size)
    assert dest.read_bytes() == source.read_bytes()
    assert not dest.with_name("a.zip.part").exists()


def test_download_restarts_when_range_is_ignored(tmp_path, source):
    # file:// URLs ignore Range, like a server without resume support.
    dest = tmp_path / "a.zip"
    dest.with_name("a.zip.part").write_bytes(b"stale partial data")
    download(source.as_uri(), dest, source.stat().st_size)
    assert dest.read_bytes() == source.read_bytes()


def test_download_size_mismatch_is_an_error(tmp_path, source):
    with pytest.raises(IOError, match="expected"):
        download(source.as_uri(), tmp_path / "a.zip", source.stat().st_size + 1)
