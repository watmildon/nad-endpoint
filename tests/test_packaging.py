import fnmatch
import tomllib

from nad_pipeline import config


def test_package_data_covers_every_data_file():
    """Non-Python files in the package must be listed, or a regular install leaves them out."""
    with open(config.REPO_ROOT / "pyproject.toml", "rb") as f:
        patterns = tomllib.load(f)["tool"]["setuptools"]["package-data"]["nad_pipeline"]
    package = config.REPO_ROOT / "src" / "nad_pipeline"
    data_files = [p.relative_to(package).as_posix() for p in package.rglob("*")
                  if p.is_file() and p.suffix not in (".py", ".pyc")]
    assert data_files
    missing = [f for f in data_files if not any(fnmatch.fnmatch(f, p) for p in patterns)]
    assert missing == []
