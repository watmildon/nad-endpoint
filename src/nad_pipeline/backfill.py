"""Stage 5: fill missing city and postcode from Census polygons.

Only rows the transform left without a value are touched, and each fill is flagged
(city_from_census_place, city_from_census_cousub, postcode_from_zcta) because the value is
derived from a boundary, not delivered by the address authority.
"""

import re
from pathlib import Path

import duckdb

from . import config, refdata
from .transform import osm_glob

# States where county subdivisions (towns) are the everyday locality and cover all land.
COUSUB_CITY_STATES = ("CT", "MA", "ME", "NH", "NJ", "NY", "RI", "VT")


def place_city_name(name: str) -> str:
    """City name for a Census place polygon.

    Consolidated governments carry both names ("Nashville-Davidson metropolitan government
    (balance)", "Louisville/Jefferson County metro government (balance)"); the city is the
    first of them.
    """
    if "(balance)" in name or " County" in name or " government" in name:
        name = refdata.strip_census_descriptor(name) or name
        name = re.split(r"[/,-]", name)[0].strip()
    return name


def backfill(release: str) -> Path:
    rel = config.release_dir(release)
    ref = refdata.reference_dir()
    return backfill_dir(
        rel / "osm", rel / "filled",
        places=refdata.boundary_file(ref, "place"),
        cousubs=refdata.boundary_file(ref, "cousub"),
        zctas=refdata.boundary_file(ref, "zcta"),
    )


def backfill_dir(osm_dir: Path, out_dir: Path, places: Path, cousubs: Path, zctas: Path) -> Path:
    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    con.execute("SET preserve_insertion_order = false")
    con.execute(
        f"""
        CREATE VIEW osm AS
        SELECT * FROM read_parquet('{osm_glob(osm_dir)}', hive_partitioning = false)
        """
    )
    _load_polygons(con, "places", places, "STUSPS", "NAME", clean=place_city_name)
    states = ", ".join(f"'{s}'" for s in COUSUB_CITY_STATES)
    _load_polygons(con, "cousubs", cousubs, "STUSPS", "NAME",
                   where=f"STUSPS IN ({states}) AND NAMELSAD NOT LIKE '% CCD'")
    _load_polygons(con, "zctas", zctas, "NULL", "ZCTA5CE20")

    con.execute(
        """
        CREATE TABLE need AS
        SELECT nad_oid, addr_state, ST_Point(lon, lat) AS pt,
               addr_city IS NULL AS need_city, addr_postcode IS NULL AS need_postcode
        FROM osm
        WHERE drop_reason IS NULL AND (addr_city IS NULL OR addr_postcode IS NULL)
        """
    )
    for table, condition, same_state in (
        ("places", "need_city", True), ("cousubs", "need_city", True),
        ("zctas", "need_postcode", False),
    ):
        state_match = "AND p.state = n.addr_state" if same_state else ""
        con.execute(
            f"""
            CREATE TABLE fill_{table} AS
            SELECT n.nad_oid, min(p.name) AS name
            FROM need n JOIN {table} p ON ST_Contains(p.geom, n.pt) {state_match}
            WHERE n.{condition}
            GROUP BY n.nad_oid
            """
        )
    con.execute(
        f"""
        COPY (
            SELECT osm.* REPLACE (
                coalesce(osm.addr_city, fp.name, fc.name) AS addr_city,
                coalesce(osm.addr_postcode, fz.name) AS addr_postcode,
                list_sort(list_filter(osm.flags, f -> NOT (
                        (f = 'no_city' AND coalesce(fp.name, fc.name) IS NOT NULL)))
                    || CASE WHEN osm.addr_city IS NOT NULL THEN []
                            WHEN fp.name IS NOT NULL THEN ['city_from_census_place']
                            WHEN fc.name IS NOT NULL THEN ['city_from_census_cousub']
                            ELSE [] END
                    || CASE WHEN osm.addr_postcode IS NULL AND fz.name IS NOT NULL
                            THEN ['postcode_from_zcta'] ELSE [] END) AS flags
            )
            FROM osm
            LEFT JOIN fill_places fp USING (nad_oid)
            LEFT JOIN fill_cousubs fc USING (nad_oid)
            LEFT JOIN fill_zctas fz USING (nad_oid)
        ) TO '{out_dir.as_posix()}' (
            FORMAT parquet, COMPRESSION zstd, PARTITION_BY (addr_state),
            WRITE_PARTITION_COLUMNS true, OVERWRITE_OR_IGNORE
        )
        """
    )
    return out_dir


def _load_polygons(con, table: str, path: Path, state_col: str, name_col: str,
                   where: str = "true", clean=None):
    con.execute(
        f"""
        CREATE TABLE {table} AS
        SELECT {state_col} AS state, {name_col} AS name, geom
        FROM ST_Read('{path.as_posix()}') WHERE {where}
        """
    )
    if clean:
        names = [r[0] for r in con.execute(f"SELECT DISTINCT name FROM {table}").fetchall()]
        changed = [(clean(n), n) for n in names if clean(n) != n]
        if changed:
            con.executemany(f"UPDATE {table} SET name = ? WHERE name = ?", changed)
