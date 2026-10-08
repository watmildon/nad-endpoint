"""Reference data: place name spellings from Census, GNIS and Wikidata.

Builds data/reference/place_names.csv (state, name, source), which the city rule uses to
give NAD's often ALL CAPS city values their proper spelling.
"""

import csv
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import config
from .rules.city import PlaceNames

REFERENCE_DIR_NAME = "reference"
GAZETTEER = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/"
DOWNLOADS = {
    "2024_Gaz_place_national.zip": GAZETTEER + "2024_Gaz_place_national.zip",
    "2024_Gaz_cousubs_national.zip": GAZETTEER + "2024_Gaz_cousubs_national.zip",
    "DomesticNames_National_Text.zip": (
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/"
        "DomesticNames_National_Text.zip"
    ),
}
# Census cartographic boundary files used to fill missing city and postcode by location.
BOUNDARIES = {
    "place": "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_place_500k.zip",
    "cousub": "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_cousub_500k.zip",
    "zcta": "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip",
    "county": "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip",
}
WIKIDATA_FILE = "wikidata_fips_places.csv"
# English labels of every item with a FIPS 55-3 place code (state FIPS + place code).
WIKIDATA_QUERY = (
    'SELECT ?fips ?label WHERE { ?item wdt:P774 ?fips. '
    '?item rdfs:label ?label FILTER(LANG(?label)="en") }'
)
USER_AGENT = "nad-pipeline/0.1 (reference data build)"


def reference_dir() -> Path:
    return config.DATA_DIR / REFERENCE_DIR_NAME


def strip_census_descriptor(name: str) -> str | None:
    """'Indianapolis city (balance)' -> 'Indianapolis'. None for statistical areas."""
    name = re.sub(r"\s*\(.*?\)", "", name).strip()
    words = name.split()
    if words[-1] in ("CCD", "UT") or re.search(r"\d", name) or words[0] == "County":
        return None
    while len(words) > 1 and (words[-1].islower() or words[-1] == "CDP"):
        words.pop()
    return " ".join(words)


def read_census(path: Path, source: str):
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            row = {k.strip(): v.strip() for k, v in row.items()}
            if name := strip_census_descriptor(row["NAME"]):
                yield row["USPS"], name, source


def state_fips(place_file: Path) -> dict[str, str]:
    with open(place_file, encoding="utf-8", newline="") as f:
        return {row["GEOID"].strip()[:2]: row["USPS"].strip()
                for row in csv.DictReader(f, delimiter="\t")}


def read_gnis(path: Path, fips: dict[str, str]):
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="|", quoting=csv.QUOTE_NONE):
            state = fips.get(row["state_numeric"])
            if row["feature_class"] == "Populated Place" and state:
                # GNIS marks former places as "Name (historical)".
                if "(historical)" not in row["feature_name"]:
                    yield state, row["feature_name"], "gnis"


def read_wikidata(path: Path, fips: dict[str, str]):
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            code = re.sub(r"\D", "", row["fips"])
            state = fips.get(code[:2])
            if len(code) == 7 and state:
                yield state, row["label"].split(",")[0].strip(), "wikidata"


def download(ref: Path):
    ref.mkdir(parents=True, exist_ok=True)
    for name, url in DOWNLOADS.items():
        if not (ref / name).exists():
            urllib.request.urlretrieve(url, ref / name)
        with zipfile.ZipFile(ref / name) as zf:
            zf.extractall(ref)
    if not (ref / WIKIDATA_FILE).exists():
        url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode(
            {"query": WIKIDATA_QUERY})
        req = urllib.request.Request(
            url, headers={"Accept": "text/csv", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as resp:
            (ref / WIKIDATA_FILE).write_bytes(resp.read())


def boundary_file(ref: Path, kind: str) -> Path:
    stem = BOUNDARIES[kind].rsplit("/", 1)[1].removesuffix(".zip")
    return ref / stem / f"{stem}.shp"


def download_boundaries(ref: Path):
    for kind, url in BOUNDARIES.items():
        shp = boundary_file(ref, kind)
        if not shp.exists():
            archive = ref / url.rsplit("/", 1)[1]
            if not archive.exists():
                urllib.request.urlretrieve(url, archive)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(shp.parent)


def read_all(ref: Path):
    place_file = ref / "2024_Gaz_place_national.txt"
    fips = state_fips(place_file)
    yield from read_census(place_file, "census_place")
    yield from read_census(ref / "2024_Gaz_cousubs_national.txt", "census_cousub")
    yield from read_gnis(ref / "Text" / "DomesticNames_National.txt", fips)
    yield from read_wikidata(ref / WIKIDATA_FILE, fips)


def build(ref: Path | None = None) -> Path:
    """Download the sources if needed and write place_names.csv plus a conflict report."""
    ref = ref or reference_dir()
    download(ref)
    download_boundaries(ref)
    rows = sorted(set(read_all(ref)))
    out = ref / "place_names.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["state", "name", "source"])
        writer.writerows(rows)
    with open(ref / "place_name_conflicts.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["state", "chosen", "spellings"])
        for state, chosen, spellings in sorted(PlaceNames(rows).conflicts):
            writer.writerow([state, chosen, "; ".join(f"{k} ({v})" for k, v in spellings.items())])
    return out


def load_place_names(ref: Path | None = None) -> PlaceNames:
    path = (ref or reference_dir()) / "place_names.csv"
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader)
        return PlaceNames(tuple(row) for row in reader)
