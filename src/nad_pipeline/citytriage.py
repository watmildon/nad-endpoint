"""Diagnostic report: where the city values the rules do not recognise are.

For each state and addr:city the transform flagged city_not_in_reference, counts the points
inside Census places and county subdivisions and sorts the value into a bucket:

- correction_place / correction_cousub: most points fall in a place (or county subdivision)
  whose name is a misspelling or abbreviation of the value ("Dalworthington Gardn" inside
  Dalworthington Gardens). Candidates for city_typos.json.
- differs_from_place: most points fall in a place with a different name ("Hot Springs
  National Park" inside Hot Springs). Often a real postal name.
- split_across_places: most points are in some place, but no one place holds a majority.
- outside_places: most points are outside every place. Unincorporated communities, codes and
  placeholders end up here.

Each value also gets its most common ZIP (from the ZCTA the point falls in when the source gave
none), a sample address for checking by hand, and in `review` the note of any hold in
rules/city_overrides.json, so values already looked at stand out. Written to
data/<release>/transform_report/city_triage.csv; nothing in the pipeline reads it.
"""

import csv
from pathlib import Path

import duckdb

from . import config, refdata
from .backfill import _load_polygons, place_city_name
from .rules.city import PlaceNames, _misspelling_of, city_key
from .transform import osm_glob

COLUMNS = ["state", "city", "n", "bucket", "suggested", "place_share", "top_place",
           "cousub_share", "top_cousub", "top_zip", "zip_from", "sample_address", "review"]
MAJORITY = 0.5


def city_triage(release: str) -> Path:
    rel = config.release_dir(release)
    ref = refdata.reference_dir()
    return city_triage_dir(
        rel / "osm", rel / "transform_report" / "city_triage.csv",
        places=refdata.boundary_file(ref, "place"),
        cousubs=refdata.boundary_file(ref, "cousub"),
        zctas=refdata.boundary_file(ref, "zcta"),
        names=refdata.load_place_names(ref),
    )


def city_triage_dir(osm_dir: Path, out: Path, places: Path, cousubs: Path, zctas: Path,
                    names: PlaceNames) -> Path:
    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    _load_polygons(con, "places", places, "STUSPS", "NAME", clean=place_city_name)
    _load_polygons(con, "cousubs", cousubs, "STUSPS", "NAME", where="NAMELSAD NOT LIKE '% CCD'")
    _load_polygons(con, "zctas", zctas, "NULL", "ZCTA5CE20")
    con.execute(
        f"""
        CREATE TABLE pts AS
        SELECT nad_oid, addr_state AS state, county, addr_city AS city, addr_postcode AS zip,
               addr_housenumber AS number, addr_street AS street, ST_Point(lon, lat) AS pt
        FROM read_parquet('{osm_glob(osm_dir)}', hive_partitioning = false)
        WHERE drop_reason IS NULL AND list_contains(flags, 'city_not_in_reference')
        """
    )
    for table in ("places", "cousubs"):
        con.execute(
            f"""
            CREATE TABLE in_{table} AS
            SELECT p.nad_oid, min(g.name) AS name
            FROM pts p JOIN {table} g ON g.state = p.state AND ST_Contains(g.geom, p.pt)
            GROUP BY p.nad_oid
            """
        )
    # Rows the source gave no ZIP get the ZCTA they fall in, as backfill does.
    con.execute(
        """
        CREATE TABLE in_zctas AS
        SELECT p.nad_oid, min(z.name) AS name
        FROM pts p JOIN zctas z ON ST_Contains(z.geom, p.pt)
        WHERE p.zip IS NULL GROUP BY p.nad_oid
        """
    )
    rows = con.execute(
        """
        WITH j AS (
            SELECT p.* REPLACE (coalesce(p.zip, iz.name) AS zip),
                   p.zip IS NULL AS zip_from_zcta, ip.name AS place, ic.name AS cousub
            FROM pts p
            LEFT JOIN in_places ip USING (nad_oid)
            LEFT JOIN in_cousubs ic USING (nad_oid)
            LEFT JOIN in_zctas iz USING (nad_oid)),
        total AS (SELECT state, city, count(*) AS n, count(place) AS n_in_place,
                         list(DISTINCT county) AS counties
                  FROM j GROUP BY ALL),
        top_place AS (
            SELECT state, city, place, count(*) AS c FROM j WHERE place IS NOT NULL
            GROUP BY 1, 2, 3
            QUALIFY row_number() OVER (PARTITION BY state, city ORDER BY c DESC, place) = 1),
        top_cousub AS (
            SELECT state, city, cousub, count(*) AS c FROM j WHERE cousub IS NOT NULL
            GROUP BY 1, 2, 3
            QUALIFY row_number() OVER (PARTITION BY state, city ORDER BY c DESC, cousub) = 1),
        top_zip AS (
            SELECT state, city, zip, bool_and(zip_from_zcta) AS from_zcta, count(*) AS c
            FROM j WHERE zip IS NOT NULL
            GROUP BY 1, 2, 3
            QUALIFY row_number() OVER (PARTITION BY state, city ORDER BY c DESC, zip) = 1),
        -- A row in the top ZIP if there is one, else any row with a number and street.
        sample AS (
            SELECT j.state, j.city,
                   arg_max(j.number || ' ' || j.street,
                           (j.zip IS NOT DISTINCT FROM z.zip)::INT) AS address
            FROM j LEFT JOIN top_zip z ON z.state = j.state AND z.city = j.city
            WHERE j.number IS NOT NULL AND j.street IS NOT NULL
            GROUP BY 1, 2)
        SELECT t.state, t.city, t.n, t.n_in_place, tp.place, tp.c, tc.cousub, tc.c,
               tz.zip, tz.from_zcta, s.address, t.counties
        FROM total t
        LEFT JOIN top_place tp USING (state, city)
        LEFT JOIN top_cousub tc USING (state, city)
        LEFT JOIN top_zip tz USING (state, city)
        LEFT JOIN sample s USING (state, city)
        ORDER BY t.n DESC, t.state, t.city
        """
    ).fetchall()

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for (state, city, n, n_in_place, place, in_place, cousub, in_cousub, zip_code,
             from_zcta, address, counties) in rows:
            place_share, cousub_share = (in_place or 0) / n, (in_cousub or 0) / n
            bucket, suggested = _bucket(city, n_in_place / n, place, place_share,
                                        cousub, cousub_share)
            zip_from = "zcta" if from_zcta else "source" if zip_code else ""
            holds = sorted({note for county in counties
                            if (note := names.held(state, county, city)) is not None})
            review = "; ".join(f"hold: {note}" if note else "hold" for note in holds)
            writer.writerow([state, city, n, bucket, suggested, round(place_share, 2), place,
                             round(cousub_share, 2), cousub, zip_code, zip_from, address, review])
    return out


def _bucket(city, in_any_place, place, place_share, cousub, cousub_share):
    """(bucket, suggested name) for one value; see the module docstring."""
    if _resembles(city, place) and place_share >= MAJORITY:
        return "correction_place", place
    if _resembles(city, cousub) and cousub_share >= MAJORITY:
        return "correction_cousub", cousub
    if place_share >= MAJORITY:
        return "differs_from_place", place
    if in_any_place >= MAJORITY:
        return "split_across_places", place
    return "outside_places", cousub


def _resembles(value: str, name: str | None) -> bool:
    """A misspelling ("Waltill" for Walthill) or an abbreviation whose letters appear in order
    in the name ("Dalworthington Gardn" for Dalworthington Gardens)."""
    if not name:
        return False
    a, b = city_key(value), city_key(name)
    if _misspelling_of(a, b):
        return True
    letters = iter(b)
    return len(a) >= 4 and a[:3] == b[:3] and all(ch in letters for ch in a)
