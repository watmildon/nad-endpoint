"""Stage 9: upload the tileset to Cloudflare R2 and point the "current" aliases at it.

The coverage GeoJSON from `nad coverage` goes up with it when it has been built; the web
viewer reads it, but tile consumers do not need it, so its absence does not stop a publish.
The OSM address counts from `nad osm-counts` follow Layercake's weekly schedule rather than
NAD releases, so they are uploaded on their own by `nad osm-counts --publish`, which also
adds them to the history that `nad osm-history --publish` started.

Credentials come from the environment (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY), or from data/r2.env (KEY=value lines, git-ignored) for any that are
not set. They are passed to rclone through its own environment variables, so they never
appear on a command line or in a config file.
"""

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path

from . import config
from .coverage import coverage_path
from .export import export_dir
from .osmcount import CURRENT as OSM_COUNTS_CURRENT
from .osmcount import HISTORY as OSM_HISTORY
from .osmcount import append_to_history

BUCKET = os.environ.get("NAD_R2_BUCKET", "nad-tiles")
PUBLIC_URL = os.environ.get("NAD_PUBLIC_URL", "https://nad.watmildon.org").rstrip("/")
REQUIRED = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
ENV_FILE = config.DATA_DIR / "r2.env"
# Multipart settings: 64 MiB parts, eight in flight, for a file of a few GB.
UPLOAD_OPTIONS = ["--s3-chunk-size", "64M", "--s3-upload-concurrency", "8"]
OSM_HISTORY_PREVIOUS = "osm-counts-history-previous.json"


def rclone_path() -> str:
    found = shutil.which("rclone")
    if found:
        return found
    # winget installs rclone without touching the current shell's PATH.
    candidates = glob.glob(os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Rclone.Rclone*\*\rclone.exe"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError("rclone is not installed")


def credentials(environ=os.environ, env_file: Path | None = None) -> dict:
    """The R2 variables, from the environment first and then from the env file."""
    env_file = env_file or ENV_FILE
    found = {name: environ[name] for name in REQUIRED if environ.get(name)}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in REQUIRED and value.strip():
                found.setdefault(key, value.strip().strip('"'))
    return found


def rclone_env(environ=os.environ, env_file: Path | None = None) -> dict:
    env_file = env_file or ENV_FILE
    found = credentials(environ, env_file)
    missing = [name for name in REQUIRED if name not in found]
    if missing:
        raise EnvironmentError(
            f"set {', '.join(missing)} in the environment or in {env_file} before publishing")
    environ = {**environ, **found}
    return {
        **environ,
        "RCLONE_CONFIG_R2_TYPE": "s3",
        "RCLONE_CONFIG_R2_PROVIDER": "Cloudflare",
        "RCLONE_CONFIG_R2_ENDPOINT": f"https://{environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        "RCLONE_CONFIG_R2_ACCESS_KEY_ID": environ["R2_ACCESS_KEY_ID"],
        "RCLONE_CONFIG_R2_SECRET_ACCESS_KEY": environ["R2_SECRET_ACCESS_KEY"],
        "RCLONE_CONFIG_R2_NO_CHECK_BUCKET": "true",
    }


def publish_commands(release: str, pmtiles: Path, sidecar: Path,
                     coverage: Path | None = None) -> list[list[str]]:
    rclone = rclone_path()
    dest = f"r2:{BUCKET}"
    commands = [
        [rclone, "copyto", str(pmtiles), f"{dest}/{pmtiles.name}", *UPLOAD_OPTIONS, "--progress"],
        [rclone, "copyto", str(sidecar), f"{dest}/{sidecar.name}"],
        # Server-side copies inside the bucket: the aliases every consumer should point at.
        [rclone, "copyto", f"{dest}/{pmtiles.name}", f"{dest}/nad-current.pmtiles"],
        [rclone, "copyto", f"{dest}/{sidecar.name}", f"{dest}/nad-current.json"],
    ]
    if coverage:
        commands += [
            [rclone, "copyto", str(coverage), f"{dest}/{coverage.name}",
             "--header-upload", "Content-Type: application/geo+json"],
            [rclone, "copyto", f"{dest}/{coverage.name}", f"{dest}/nad-current-coverage.geojson"],
        ]
    return commands


def publish_osm_counts(counts: Path, alias: str | None = OSM_COUNTS_CURRENT,
                       run=subprocess.run, environ=os.environ) -> list[str]:
    """Upload OSM counts from `nad osm-counts` or `nad osm-history`, and point an alias at
    them when given one."""
    rclone = rclone_path()
    dest = f"r2:{BUCKET}"
    env = rclone_env(environ)
    commands = [[rclone, "copyto", str(counts), f"{dest}/{counts.name}",
                 "--header-upload", "Content-Type: application/json"]]
    if alias:
        commands.append([rclone, "copyto", f"{dest}/{counts.name}", f"{dest}/{alias}"])
    for command in commands:
        run(command, check=True, env=env)
    return [f"{PUBLIC_URL}/{name}" for name in (counts.name, alias) if name]


def update_osm_history(counts: Path, run=subprocess.run, environ=os.environ) -> list[str]:
    """Add a week's counts from `nad osm-counts` to the history on R2.

    The history is read from the bucket itself, not the public URL, so a cached copy can
    never be appended to and written back over a newer one. The copy it replaces is kept
    as osm-counts-history-previous.json, one week back.
    """
    rclone = rclone_path()
    dest = f"r2:{BUCKET}"
    env = rclone_env(environ)
    local = counts.parent / OSM_HISTORY
    run([rclone, "copyto", f"{dest}/{OSM_HISTORY}", str(local)], check=True, env=env)
    history = append_to_history(json.loads(local.read_text(encoding="utf-8")),
                                json.loads(counts.read_text(encoding="utf-8")))
    local.write_text(json.dumps(history, separators=(",", ":")), encoding="utf-8")
    for command in (
        [rclone, "copyto", f"{dest}/{OSM_HISTORY}", f"{dest}/{OSM_HISTORY_PREVIOUS}"],
        [rclone, "copyto", str(local), f"{dest}/{OSM_HISTORY}",
         "--header-upload", "Content-Type: application/json"],
    ):
        run(command, check=True, env=env)
    return [f"{PUBLIC_URL}/{OSM_HISTORY}"]


def publish(release: str, run=subprocess.run, environ=os.environ) -> list[str]:
    """Upload the release's tileset and sidecar; returns the public URLs."""
    out = export_dir(release)
    pmtiles, sidecar = out / f"nad-{release}.pmtiles", out / f"nad-{release}.json"
    for path in (pmtiles, sidecar):
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; run `nad export` first")
    coverage = coverage_path(release)
    coverage = coverage if coverage.exists() else None
    env = rclone_env(environ)
    for command in publish_commands(release, pmtiles, sidecar, coverage):
        run(command, check=True, env=env)
    names = [pmtiles.name, sidecar.name, "nad-current.pmtiles", "nad-current.json"]
    if coverage:
        names += [coverage.name, "nad-current-coverage.geojson"]
    return [f"{PUBLIC_URL}/{name}" for name in names]
