"""Review aid: score unknown city values as possible typos of a nearby known place.

For each state, county and addr:city the transform flagged city_not_in_reference, the
candidates are known places in that state from three kinds of evidence:

- street: cities other addresses on the same streets carry (state, county and street match);
- place: the Census place most of the value's points fall in;
- gnis: GNIS populated places within GNIS_KM of the points' centre.

A value is listed when its best candidate is a few edits away, or an abbreviation whose
letters appear in order ("Dalworthington Gardn", "Signal MTN"). Each row also carries the city
most other addresses in the value's top ZIP use, and `support` lists which independent signals
name the candidate: street (the top same-street city), place (the Census place holding most of
the points), zip (the ZIP's leading city) and gnis (a GNIS place of that name within
GNIS_SUPPORT_KM). A GNIS-only match with no support is often a different place ("Mallie" is
not a typo of Hallie). Nothing is applied: reviewed decisions go into rules/city_overrides.json
by hand, as a fix, or as a keep or hold so the value is not proposed again. Written to
data/<release>/transform_report/typo_candidates.csv.
"""

import csv
import math
from collections import defaultdict
from pathlib import Path

import duckdb

from . import config, refdata
from .backfill import _load_polygons, place_city_name
from .rules.city import PlaceNames, _misspelling_of, city_key, edit_distance
from .transform import osm_glob

COLUMNS = ["state", "county", "city", "n", "candidate", "via", "share", "km", "edits",
           "support", "top_street_city", "top_street_share", "top_zip", "zip_city",
           "zip_city_share", "sample_address", "lat", "lon"]
GNIS_KM = 25
# A GNIS place this close to the points counts as support in its own right.
GNIS_SUPPORT_KM = 5
STREET_CITIES = 6  # most common same-street cities considered per value
VIA_ORDER = {"street": 0, "place": 1, "gnis": 2}


def typo_candidates(release: str) -> Path:
    rel = config.release_dir(release)
    ref = refdata.reference_dir()
    return typo_candidates_dir(
        rel / "osm", rel / "transform_report" / "typo_candidates.csv",
        names=refdata.load_place_names(ref),
        places=refdata.boundary_file(ref, "place"),
        gnis=read_gnis_points(ref / "Text" / "DomesticNames_National.txt",
                              refdata.state_fips(ref / "2024_Gaz_place_national.txt")),
    )


def read_gnis_points(path: Path, fips: dict[str, str]) -> dict[str, list]:
    """Populated places by state: (name, lat, lon)."""
    points = defaultdict(list)
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="|", quoting=csv.QUOTE_NONE):
            state = fips.get(row["state_numeric"])
            if (row["feature_class"] == "Populated Place" and state
                    and row["prim_lat_dec"] not in ("", "0")):
                points[state].append((row["feature_name"], float(row["prim_lat_dec"]),
                                      float(row["prim_long_dec"])))
    return points


def typo_candidates_dir(osm_dir: Path, out: Path, names: PlaceNames, places: Path,
                        gnis: dict[str, list]) -> Path:
    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    con.execute(
        f"""
        CREATE VIEW osm AS
        SELECT * FROM read_parquet('{osm_glob(osm_dir)}', hive_partitioning = false)
        WHERE drop_reason IS NULL AND addr_city IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE TABLE g AS
        SELECT addr_state AS state, county, addr_city AS city, addr_street AS street,
               addr_postcode AS zip, addr_housenumber AS number, lat, lon
        FROM osm WHERE list_contains(flags, 'city_not_in_reference')
        """
    )
    groups = {(s, c, v): (n, lat, lon, z, a) for s, c, v, n, lat, lon, z, a in con.execute(
        """
        SELECT state, county, city, count(*), avg(lat), avg(lon), mode(zip),
               any_value(number || ' ' || street)
        FROM g GROUP BY ALL
        """).fetchall()}

    street = defaultdict(list)
    for s, c, v, nb, n in con.execute(
        """
        WITH streets AS (SELECT DISTINCT state, county, city, street FROM g
                         WHERE street IS NOT NULL)
        SELECT st.state, st.county, st.city, o.addr_city, count(*)
        FROM streets st JOIN osm o
          ON o.addr_state = st.state AND o.county IS NOT DISTINCT FROM st.county
         AND o.addr_street = st.street
        WHERE NOT list_contains(o.flags, 'city_not_in_reference')
        GROUP BY ALL
        """).fetchall():
        street[(s, c, v)].append((nb, n))

    _load_polygons(con, "places", places, "STUSPS", "NAME", clean=place_city_name)
    place = {(s, c, v): (p, n) for s, c, v, p, n in con.execute(
        """
        SELECT g.state, g.county, g.city, p.name, count(*)
        FROM g JOIN places p ON p.state = g.state AND ST_Contains(p.geom, ST_Point(g.lon, g.lat))
        GROUP BY 1, 2, 3, 4
        QUALIFY row_number() OVER (PARTITION BY g.state, g.county, g.city
                                   ORDER BY count(*) DESC, p.name) = 1
        """).fetchall()}

    zips = sorted({z for _, _, _, z, _ in groups.values() if z})
    con.execute("CREATE TABLE z (zip VARCHAR)")
    con.executemany("INSERT INTO z VALUES (?)", [(z,) for z in zips])
    zip_city = defaultdict(list)
    for state, z, city, n in con.execute(
        """
        SELECT o.addr_state, o.addr_postcode, o.addr_city, count(*)
        FROM osm o JOIN z ON o.addr_postcode = z.zip
        WHERE NOT list_contains(o.flags, 'city_not_in_reference')
        GROUP BY ALL
        """).fetchall():
        zip_city[(state, z)].append((city, n))

    rows = []
    for key, (n, lat, lon, top_zip, address) in groups.items():
        state, county, city = key
        if names.held(state, county, city) is not None:
            continue  # reviewed already; see its note in city_overrides.json
        neighbours = sorted(street.get(key, []), key=lambda t: -t[1])
        street_total = sum(k for _, k in neighbours) or 1
        options = [(nb, "street", k / street_total, None)
                   for nb, k in neighbours[:STREET_CITIES]
                   if names.lookup(state, nb, national=False)]
        if key in place and names.lookup(state, place[key][0], national=False):
            options.append((place[key][0], "place", place[key][1] / n, None))
        for name, glat, glon in gnis.get(state, ()):
            km = _km(lat, lon, glat, glon)
            if km <= GNIS_KM and names.lookup(state, name, national=False):
                options.append((name, "gnis", 0.0, km))
        if not options:
            continue
        edits, *_, best = min((_edits(city, o[0]), VIA_ORDER[o[1]], -o[2], o[3] or 0, i)
                              for i, o in enumerate(options))
        candidate, via, share, km = options[best]
        if not _close_enough(city, candidate, edits):
            continue
        by_zip = sorted(zip_city.get((state, top_zip), []), key=lambda t: -t[1])
        zip_total = sum(k for _, k in by_zip) or 1
        target = city_key(candidate)
        support = [signal for signal, agrees in (
            ("street", neighbours and city_key(neighbours[0][0]) == target),
            ("place", key in place and city_key(place[key][0]) == target
             and place[key][1] / n >= 0.5),
            ("zip", by_zip and city_key(by_zip[0][0]) == target),
            ("gnis", any(city_key(o[0]) == target and o[1] == "gnis" and o[3] <= GNIS_SUPPORT_KM
                         for o in options)),
        ) if agrees]
        rows.append([
            state, county, city, n, names.lookup(state, candidate, national=False), via,
            round(share, 2), round(km, 1) if km is not None else "", edits, "+".join(support),
            neighbours[0][0] if neighbours else "",
            round(neighbours[0][1] / street_total, 2) if neighbours else "",
            top_zip or "", by_zip[0][0] if by_zip else "",
            round(by_zip[0][1] / zip_total, 2) if by_zip else "",
            address or "", round(lat, 4), round(lon, 4),
        ])

    rows.sort(key=lambda r: (-r[3], r[0], r[2]))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return out


def _edits(value: str, name: str) -> int:
    """Edits between the comparison keys; an abbreviation (the value's letters in order in
    the name, same first two letters) counts as 1, or 2 when it leaves out a lot."""
    a, b = city_key(value), city_key(name)
    edits = edit_distance(a, b)
    letters = iter(b)
    if len(a) >= 3 and a[:2] == b[:2] and all(ch in letters for ch in a):
        edits = min(edits, 1 if len(b) - len(a) <= 4 else 2)
    return edits


def _close_enough(value: str, candidate: str, edits: int) -> bool:
    """Edits allowed grow with length: 1 below 5 letters, 2 below 9, else 3."""
    a = city_key(value)
    limit = 1 if len(a) < 5 else 2 if len(a) < 9 else 3
    return edits <= limit or _misspelling_of(a, city_key(candidate))


def _km(lat1, lon1, lat2, lon2) -> float:
    return 111.2 * math.hypot(lat1 - lat2, (lon1 - lon2) * math.cos(math.radians(lat1)))
