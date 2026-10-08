"""Stage 7: mark duplicate address points.

Two kept rows are duplicates when they have the same state, county, house number, street
and unit and lie within NEAR_METERS of each other. The best one stays (most precise
placement, then most recently updated); the others get drop_reason 'duplicate'.

Rows that share the address and also the city but lie further apart are kept and flagged
same_address_elsewhere: one of them is probably wrong, but there is no telling which. The
same house number and street in two different cities of a county is normal and not flagged.
"""

from pathlib import Path

import duckdb

from . import config
from .transform import osm_glob

NEAR_METERS = 100

# Lower is better. Unknown placement ranks below a known parcel or site point.
PLACEMENT_RANK = """
    CASE WHEN placement LIKE 'Structure%' THEN 1
         WHEN placement IN ('Site', 'Property Access') THEN 2
         WHEN placement LIKE 'Parcel%' THEN 3
         WHEN placement = 'Linear Geocode' THEN 5
         ELSE 4 END
"""
# NAD writes "Orleans Parish" and "Anchorage Municipality" where Census (used for the
# extra sources) writes "Orleans" and "Anchorage"; the key ignores the descriptor.
COUNTY_KEY = """regexp_replace(lower(coalesce(county, '')),
    ' (county|parish|borough|census area|municipality|city and borough|city)$', '')"""
ADDRESS_KEY = f"""
    addr_state, {COUNTY_KEY}, lower(addr_housenumber), lower(addr_street),
    lower(coalesce(addr_unit, ''))
"""
ADDRESS_AND_CITY_KEY = ADDRESS_KEY + ", lower(coalesce(addr_city, ''))"


def dedup(release: str) -> Path:
    rel = config.release_dir(release)
    return dedup_dir(rel / "filled", rel / "addresses")


def _verdict_sql(key: str, rows: str) -> str:
    """For each address (by `key`) occurring more than once among `rows`: is a row a nearby
    copy of the address's best row, or does the address also occur further away?"""
    return f"""
        WITH ranked AS (
            SELECT nad_oid, lat, lon, hash({key}) AS address_id,
                   count(*) OVER address AS copies,
                   first_value(lat) OVER best AS best_lat,
                   first_value(lon) OVER best AS best_lon,
                   row_number() OVER best AS position
            FROM {rows}
            WINDOW
                address AS (PARTITION BY {key}),
                best AS (address ORDER BY {PLACEMENT_RANK}, date_update DESC NULLS LAST,
                                          try_cast(nad_oid AS BIGINT) NULLS LAST, nad_oid)
        ), measured AS (
            SELECT nad_oid, address_id, position,
                   111320 * sqrt(pow(lat - best_lat, 2)
                                 + pow((lon - best_lon) * cos(radians(lat)), 2)) AS meters
            FROM ranked WHERE copies > 1
        )
        SELECT nad_oid,
               position > 1 AND meters <= {NEAR_METERS} AS is_duplicate,
               bool_or(meters > {NEAR_METERS}) OVER (PARTITION BY address_id) AS elsewhere
        FROM measured
    """


def dedup_dir(in_dir: Path, out_dir: Path) -> Path:
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    con.execute(
        f"""
        CREATE VIEW src AS
        SELECT * FROM read_parquet('{osm_glob(in_dir)}', hive_partitioning = false)
        """
    )
    # Pass 1 ignores the city, so copies from overlapping sources that disagree on the
    # city still collapse. Pass 2 looks at what is left, address and city together.
    con.execute(
        "CREATE TABLE pass1 AS "
        + _verdict_sql(ADDRESS_KEY, "(SELECT * FROM src WHERE drop_reason IS NULL)")
    )
    con.execute(
        "CREATE TABLE pass2 AS "
        + _verdict_sql(
            ADDRESS_AND_CITY_KEY,
            """(SELECT * FROM src WHERE drop_reason IS NULL AND nad_oid NOT IN
                    (SELECT nad_oid FROM pass1 WHERE is_duplicate))""",
        )
    )
    con.execute(
        f"""
        COPY (
            SELECT src.* REPLACE (
                CASE WHEN p1.is_duplicate OR p2.is_duplicate THEN 'duplicate'
                     ELSE src.drop_reason END AS drop_reason,
                CASE WHEN p2.elsewhere AND NOT p2.is_duplicate
                     THEN list_sort(src.flags || ['same_address_elsewhere'])
                     ELSE src.flags END AS flags
            )
            FROM src
            LEFT JOIN pass1 p1 USING (nad_oid)
            LEFT JOIN pass2 p2 USING (nad_oid)
        ) TO '{out_dir.as_posix()}' (
            FORMAT parquet, COMPRESSION zstd, PARTITION_BY (addr_state),
            WRITE_PARTITION_COLUMNS true, OVERWRITE_OR_IGNORE
        )
        """
    )
    return out_dir
