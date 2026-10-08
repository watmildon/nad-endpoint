"""Command line entry point. Stages in order:
nad fetch | ingest | profile | refdata | transform | supplement | backfill | dedup | export | coverage | publish."""

import argparse
import sys
import time
from pathlib import Path

from . import config


def _progress():
    last = [0.0]

    def report(done: int, total: int):
        now = time.monotonic()
        if now - last[0] >= 30 or done == total:
            last[0] = now
            print(f"  {done / 1e9:.2f} / {total / 1e9:.2f} GB", flush=True)

    return report


def _latest_zip() -> Path:
    zips = sorted(config.DOWNLOAD_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        sys.exit("No downloaded release found; run `nad fetch` first.")
    return zips[-1]


def _latest_release() -> str:
    releases = sorted(
        (p.parent for p in config.DATA_DIR.glob("r*/manifest.json")),
        key=lambda p: int(p.name[1:]),
    )
    if not releases:
        sys.exit("No ingested release found; run `nad ingest` first.")
    return releases[-1].name


def main(argv=None):
    parser = argparse.ArgumentParser(prog="nad")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="download the current NAD text file")
    p = sub.add_parser("ingest", help="convert a downloaded zip to raw Parquet")
    p.add_argument("--zip", type=Path, help="zip to ingest (default: newest download)")
    p = sub.add_parser("profile", help="profile raw Parquet per state and source")
    p.add_argument("--release", help="release to profile, e.g. r24 (default: newest)")
    sub.add_parser("refdata", help="download and build the place name reference")
    p = sub.add_parser("transform", help="apply the field rules and write OSM-tagged points")
    p.add_argument("--release", help="release to transform, e.g. r24 (default: newest)")
    p = sub.add_parser("sources", help="fetch the extra sources in sources/*.toml")
    p.add_argument("--release", help="release to attach them to (default: newest)")
    p.add_argument("--only", nargs="*", help="source ids to build (default: all)")
    for name, text in (("supplement", "fill missing cities from original state datasets"),
                       ("backfill", "fill missing city and postcode from Census polygons"),
                       ("dedup", "mark duplicate address points"),
                       ("export", "build the PMTiles tileset of kept points"),
                       ("coverage", "build the county coverage GeoJSON for the web viewer"),
                       ("publish", "upload the tileset to Cloudflare R2")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--release", help="release, e.g. r24 (default: newest)")
    args = parser.parse_args(argv)

    if args.command == "fetch":
        from .fetch import fetch

        print(fetch(_progress()))
    elif args.command == "ingest":
        from .ingest import ingest

        manifest = ingest(args.zip or _latest_zip(), _progress())
        print(f"{manifest['release']}: {manifest['rows']:,} rows")
        if manifest["rows"] != manifest["expected_rows"]:
            sys.exit(
                f"Row count mismatch: metadata says {manifest['expected_rows']:,}"
            )
    elif args.command == "profile":
        from .profile import profile

        for path in profile(args.release or _latest_release()):
            print(path)
    elif args.command == "refdata":
        from .refdata import build

        print(build())
    elif args.command == "transform":
        from .transform import report, transform

        release = args.release or _latest_release()
        print(transform(release))
        for path in report(release):
            print(path)
    elif args.command == "sources":
        from .sources import build

        for path in build(args.release or _latest_release(), args.only):
            print(path)
    elif args.command == "supplement":
        from .supplement import supplement

        print(supplement(args.release or _latest_release()))
    elif args.command == "backfill":
        from .backfill import backfill

        print(backfill(args.release or _latest_release()))
    elif args.command == "dedup":
        from .dedup import dedup

        print(dedup(args.release or _latest_release()))
    elif args.command == "export":
        from .export import export

        print(export(args.release or _latest_release()))
    elif args.command == "coverage":
        from .coverage import coverage

        print(coverage(args.release or _latest_release()))
    elif args.command == "publish":
        from .publish import publish

        for url in publish(args.release or _latest_release()):
            print(url)


if __name__ == "__main__":
    main()
