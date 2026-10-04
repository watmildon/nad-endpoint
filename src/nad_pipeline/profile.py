"""Stage 3: profile the raw data per state and NAD source to drive transform rules."""

from pathlib import Path

import duckdb

from . import config
from .ingest import raw_glob

GROUP = ["State", "NAD_Source"]

# Columns whose most common values are worth seeing per source.
VALUE_COLUMNS = [
    "AddNum_Pre", "AddNum_Suf",
    "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep", "St_PosTyp", "St_PosDir", "St_PosMod",
    "Building", "Floor", "Unit",
    "Inc_Muni", "Post_City", "Census_Plc", "Uninc_Comm", "PlaceNmTyp",
    "AddrRefSys", "Placement", "RelateType", "ParcelSrc", "AddrClass", "Lifecycle",
    "AnomStatus", "Addr_Type", "DeliverTyp",
]
TOP_N = 20

# Street name components that the transform must expand; listed in full, not top-N.
STREET_PART_COLUMNS = [
    "St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep", "St_PosTyp", "St_PosDir", "St_PosMod",
]
MIN_NAME_TOKEN_COUNT = 100


def _filled(col: str) -> str:
    return f"count(nullif(trim({col}), ''))"


def _unpivot(columns: list[str]) -> str:
    cols = ", ".join(columns)
    return f"""
        (UNPIVOT (SELECT {', '.join(GROUP)}, {cols} FROM nad)
         ON {cols} INTO NAME col VALUE val)
    """


def profile(release: str) -> list[Path]:
    rel = config.release_dir(release)
    return profile_dir(rel / "raw", rel / "profile")


def profile_dir(raw_dir: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        f"""
        CREATE VIEW nad AS
        SELECT * FROM read_parquet('{raw_glob(raw_dir)}', hive_partitioning = false)
        """
    )
    group = ", ".join(GROUP)
    queries = {}

    # Percentage of rows with a value, for every column.
    fill = ",\n".join(
        f"round(100.0 * {_filled(c)} / count(*), 1) AS {c}"
        for c in config.NAD_COLUMNS
        if c not in GROUP
    )
    queries["fill_rates"] = f"""
        SELECT {group}, count(*) AS n_rows, count(DISTINCT County) AS counties, {fill}
        FROM nad GROUP BY {group} ORDER BY {group}
    """

    queries["top_values"] = f"""
        SELECT {group}, col, val, count(*) AS n
        FROM {_unpivot(VALUE_COLUMNS)}
        GROUP BY {group}, col, val
        QUALIFY row_number() OVER (PARTITION BY {group}, col ORDER BY n DESC, val) <= {TOP_N}
        ORDER BY {group}, col, n DESC, val
    """

    queries["street_parts"] = f"""
        SELECT col, val, count(*) AS n,
               count(DISTINCT NAD_Source) AS sources, count(DISTINCT State) AS states
        FROM {_unpivot(STREET_PART_COLUMNS)}
        GROUP BY ALL ORDER BY col, n DESC, val
    """

    # First and last words of St_Name: where embedded abbreviations (ST, MT, CR, HWY) live.
    queries["street_name_tokens"] = f"""
        WITH names AS (
            SELECT State, string_split(upper(trim(St_Name)), ' ') AS tokens
            FROM nad WHERE St_Name IS NOT NULL
        ), tokens AS (
            SELECT 'first' AS position, tokens[1] AS token, State FROM names
            UNION ALL
            SELECT 'last', tokens[-1], State FROM names WHERE len(tokens) > 1
        )
        SELECT position, token, count(*) AS n, count(DISTINCT State) AS states
        FROM tokens GROUP BY ALL HAVING n >= {MIN_NAME_TOKEN_COUNT}
        ORDER BY position, n DESC, token
    """

    queries["quality"] = f"""
        SELECT {group}, count(*) AS n_rows,
            count(*) FILTER (St_Name = upper(St_Name) AND regexp_matches(St_Name, '[A-Za-z]'))
                AS street_name_all_caps,
            count(*) FILTER (regexp_matches(St_Name, '[A-Za-z]')) AS street_name_with_letters,
            count(*) FILTER (Add_Number IS NULL) AS no_number,
            count(*) FILTER (try_cast(Add_Number AS BIGINT) = 0) AS zero_number,
            count(*) FILTER (St_Name IS NULL) AS no_street_name,
            count(*) FILTER (try_cast(Longitude AS DOUBLE) IS NULL
                             OR try_cast(Latitude AS DOUBLE) IS NULL) AS no_coords,
            count(*) FILTER (try_cast(Longitude AS DOUBLE) = 0
                             OR try_cast(Latitude AS DOUBLE) = 0) AS zero_coords,
            count(*) FILTER (Zip_Code IS NOT NULL AND NOT regexp_full_match(Zip_Code, '\\d{{5}}'))
                AS bad_zip,
            count(*) - count(DISTINCT (Longitude, Latitude)) AS shared_coords,
            count(*) - count(DISTINCT (AddNo_Full, StNam_Full, SubAddress, Zip_Code,
                                       Longitude, Latitude)) AS exact_duplicates,
            count(*) - count(DISTINCT UUID) AS repeated_uuid,
            min(try_cast(Longitude AS DOUBLE)) AS min_lon,
            max(try_cast(Longitude AS DOUBLE)) AS max_lon,
            min(try_cast(Latitude AS DOUBLE)) AS min_lat,
            max(try_cast(Latitude AS DOUBLE)) AS max_lat,
            min(DateUpdate) AS oldest_update, max(DateUpdate) AS newest_update
        FROM nad GROUP BY {group} ORDER BY {group}
    """

    paths = []
    for name, sql in queries.items():
        path = out_dir / f"{name}.csv"
        con.execute(f"COPY ({sql}) TO '{path.as_posix()}' (HEADER, DELIMITER ',')")
        paths.append(path)
    return paths
