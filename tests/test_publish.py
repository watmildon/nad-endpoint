import pytest

from nad_pipeline import config, publish


@pytest.fixture
def release(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    out = tmp_path / "r99" / "export"
    out.mkdir(parents=True)
    (out / "nad-r99.pmtiles").write_bytes(b"PMTiles")
    (out / "nad-r99.json").write_text("{}")
    monkeypatch.setattr(publish, "rclone_path", lambda: "rclone")
    return "r99"


CREDENTIALS = {"R2_ACCOUNT_ID": "abc123", "R2_ACCESS_KEY_ID": "key", "R2_SECRET_ACCESS_KEY": "secret"}


def test_publish_uploads_then_aliases(release):
    calls = []

    def fake_run(command, check, env):
        calls.append((command, env))

    urls = publish.publish(release, run=fake_run, environ=CREDENTIALS)
    commands = [c for c, _ in calls]
    assert [c[1] for c in commands] == ["copyto"] * 4
    assert commands[0][2].endswith("nad-r99.pmtiles")
    assert commands[0][3] == f"r2:{publish.BUCKET}/nad-r99.pmtiles"
    assert commands[2][2:4] == [f"r2:{publish.BUCKET}/nad-r99.pmtiles",
                                f"r2:{publish.BUCKET}/nad-current.pmtiles"]
    assert commands[3][3] == f"r2:{publish.BUCKET}/nad-current.json"
    assert urls == [f"{publish.PUBLIC_URL}/nad-r99.pmtiles", f"{publish.PUBLIC_URL}/nad-r99.json",
                    f"{publish.PUBLIC_URL}/nad-current.pmtiles",
                    f"{publish.PUBLIC_URL}/nad-current.json"]
    env = calls[0][1]
    assert env["RCLONE_CONFIG_R2_ENDPOINT"] == "https://abc123.r2.cloudflarestorage.com"
    assert env["RCLONE_CONFIG_R2_SECRET_ACCESS_KEY"] == "secret"
    # The secret is never on the command line.
    assert all("secret" not in " ".join(c) for c in commands)


def test_publish_uploads_coverage_when_built(release, tmp_path):
    (tmp_path / "r99" / "export" / "nad-r99-coverage.geojson").write_text("{}")
    calls = []
    urls = publish.publish(release, run=lambda c, check, env: calls.append(c),
                           environ=CREDENTIALS)
    assert len(calls) == 6
    assert calls[4][3] == f"r2:{publish.BUCKET}/nad-r99-coverage.geojson"
    assert "Content-Type: application/geo+json" in calls[4]
    assert calls[5][2:4] == [f"r2:{publish.BUCKET}/nad-r99-coverage.geojson",
                             f"r2:{publish.BUCKET}/nad-current-coverage.geojson"]
    assert urls[-1] == f"{publish.PUBLIC_URL}/nad-current-coverage.geojson"


def test_publish_refuses_without_credentials(release, tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "ENV_FILE", tmp_path / "missing.env")
    with pytest.raises(EnvironmentError, match="R2_SECRET_ACCESS_KEY"):
        publish.publish(release, run=lambda *a, **k: None,
                        environ={"R2_ACCOUNT_ID": "abc123", "R2_ACCESS_KEY_ID": "key"})


def test_credentials_fall_back_to_env_file(tmp_path):
    env_file = tmp_path / "r2.env"
    env_file.write_text(
        "R2_ACCESS_KEY_ID=filekey\nR2_SECRET_ACCESS_KEY=\"filesecret\"\n# note\n")
    found = publish.credentials({"R2_ACCOUNT_ID": "abc123", "R2_ACCESS_KEY_ID": "envkey"}, env_file)
    assert found == {"R2_ACCOUNT_ID": "abc123", "R2_ACCESS_KEY_ID": "envkey",
                     "R2_SECRET_ACCESS_KEY": "filesecret"}


def test_publish_requires_export_first(release, tmp_path):
    (tmp_path / "r99" / "export" / "nad-r99.pmtiles").unlink()
    with pytest.raises(FileNotFoundError, match="nad export"):
        publish.publish(release, run=lambda *a, **k: None, environ=CREDENTIALS)
