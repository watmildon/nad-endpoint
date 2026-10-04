"""Stage 4: turn raw NAD rows into OSM-tagged address points.

The field rules are Python functions. They run once per distinct input combination (a few
million values) rather than once per row (about 100 million), and the results are joined
back onto the rows in DuckDB. No row is deleted: rows that should not be published carry a
drop_reason, and every rule decision worth auditing is recorded in flags.
"""

import csv
import tempfile
from pathlib import Path

import duckdb

from . import config
from .ingest import raw_glob
from .refdata import load_place_names
from .rules.city import PlaceNames, choose_city
from .rules.fields import (
    INACTIVE_LIFECYCLES, build_housenumber, clean_postcode, clean_unit,
)
from .rules.street import build_street

# Each rule's inputs. Results come back as a list: [value, drop_reason, *flags].
RULES = {
    "street": ["St_PreMod", "St_PreDir", "St_PreTyp", "St_PreSep", "St_Name",
               "St_PosTyp", "St_PosDir", "St_PosMod"],
    "housenumber": ["AddNum_Pre", "Add_Number", "AddNum_Suf"],
    "unit": ["Unit", "Building"],
    "city": ["Post_City", "Inc_Muni", "Uninc_Comm", "State", "County"],
    "postcode": ["Zip_Code", "State"],
}


def _rule_functions(names: PlaceNames) -> dict:
    def street(pre_mod, pre_dir, pre_type, pre_sep, name, post_type, post_dir, post_mod):
        value, flags = build_street(
            pre_mod, pre_dir, pre_type, pre_sep, name, post_type, post_dir, post_mod)
        return [value, flags[0], *flags] if value is None else [value, None, *flags]

    def housenumber(prefix, number, suffix):
        value, flags, drop = build_housenumber(prefix, number, suffix)
        return [value, drop, *flags]

    def unit(unit, building):
        value, flags = clean_unit(unit, building)
        return [value, None, *flags]

    def city(post_city, inc_muni, uninc_comm, state, county):
        value, flags = choose_city(post_city, inc_muni, uninc_comm, state, names, county)
        return [value, None, *flags]

    def postcode(zip_code, state):
        value, flags = clean_postcode(zip_code, state)
        return [value, None, *flags]

    return {"street": street, "housenumber": housenumber, "unit": unit, "city": city,
            "postcode": postcode}


def _build_lookup(con, rule: str, cols: list[str], fn, scratch: Path):
    """Create table lu_<rule>: each distinct input combination with its rule result r."""
    con.execute(
        f"""
        CREATE TABLE in_{rule} AS
        SELECT row_number() OVER () AS id, * FROM (SELECT DISTINCT {', '.join(cols)} FROM nad)
        """
    )
    rows = con.execute(f"SELECT * FROM in_{rule}").fetchall()
    with open(scratch, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "value", "drop_reason", "flags"])
        for row_id, *args in rows:
            value, drop_reason, *flags = fn(*args)
            writer.writerow([row_id, value, drop_reason, "|".join(flags)])
    con.execute(
        f"""
        CREATE TABLE lu_{rule} AS
        SELECT i.* EXCLUDE (id),
               [o.value, o.drop_reason] || coalesce(string_split(o.flags, '|'), []) AS r
        FROM in_{rule} i JOIN read_csv('{scratch.as_posix()}', header = true,
            delim = ',', quote = '"', escape = '"',
            columns = {{'id': 'BIGINT', 'value': 'VARCHAR', 'drop_reason': 'VARCHAR',
                        'flags': 'VARCHAR'}}) o USING (id)
        """
    )


def transform(release: str) -> Path:
    rel = config.release_dir(release)
    return transform_dir(rel / "raw", rel / "osm", load_place_names())


def transform_dir(raw_dir: Path, out_dir: Path, names: PlaceNames) -> Path:
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    con.execute(
        f"""
        CREATE VIEW nad AS
        SELECT * FROM read_parquet('{raw_glob(raw_dir)}', hive_partitioning = false)
        """
    )
    joins = []
    with tempfile.TemporaryDirectory() as tmp:
        for rule, fn in _rule_functions(names).items():
            cols = RULES[rule]
            _build_lookup(con, rule, cols, fn, Path(tmp) / f"{rule}.csv")
            on = " AND ".join(f"nad.{c} IS NOT DISTINCT FROM lu_{rule}.{c}" for c in cols)
            joins.append(f"JOIN lu_{rule} ON {on}")

    inactive = ", ".join(f"'{v}'" for v in sorted(INACTIVE_LIFECYCLES))
    rules = list(RULES)
    flags = " || ".join(f"lu_{r}.r[3:]" for r in rules)
    con.execute(
        f"""
        COPY (
            SELECT
                nad.UUID AS nad_uuid,
                nad.OID_ AS nad_oid,
                try_cast(nad.Longitude AS DOUBLE) AS lon,
                try_cast(nad.Latitude AS DOUBLE) AS lat,
                lu_housenumber.r[1] AS addr_housenumber,
                lu_street.r[1] AS addr_street,
                lu_unit.r[1] AS addr_unit,
                lu_city.r[1] AS addr_city,
                nad.State AS addr_state,
                lu_postcode.r[1] AS addr_postcode,
                nad.NAD_Source AS nad_source,
                nad.County AS county,
                nad.Placement AS placement,
                nad.DateUpdate AS date_update,
                list_sort(list_distinct({flags})) AS flags,
                coalesce(
                    lu_housenumber.r[2],
                    lu_street.r[2],
                    CASE WHEN upper(trim(nad.Lifecycle)) IN ({inactive})
                         THEN 'inactive_lifecycle' END
                ) AS drop_reason
            FROM nad {' '.join(joins)}
        ) TO '{out_dir.as_posix()}' (
            FORMAT parquet, COMPRESSION zstd, PARTITION_BY (addr_state),
            WRITE_PARTITION_COLUMNS true, OVERWRITE_OR_IGNORE
        )
        """
    )
    return out_dir


def osm_glob(out_dir: Path) -> str:
    return f"{out_dir.as_posix()}/**/*.parquet"


def report(release: str) -> list[Path]:
    """Write per-source counts of drop reasons and flags for review."""
    rel = config.release_dir(release)
    return report_dir(rel / "osm", rel / "transform_report")


def report_dir(osm_dir: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        f"""
        CREATE VIEW osm AS
        SELECT * FROM read_parquet('{osm_glob(osm_dir)}', hive_partitioning = false)
        """
    )
    queries = {
        "drops": """
            SELECT addr_state, nad_source, coalesce(drop_reason, 'kept') AS outcome,
                   count(*) AS n
            FROM osm GROUP BY ALL ORDER BY ALL
        """,
        "flags": """
            SELECT addr_state, nad_source, flag, count(*) AS n
            FROM (SELECT addr_state, nad_source, unnest(flags) AS flag FROM osm
                  WHERE drop_reason IS NULL)
            GROUP BY ALL ORDER BY ALL
        """,
        "cities_not_in_reference": """
            SELECT addr_state, addr_city, count(*) AS n
            FROM osm WHERE list_contains(flags, 'city_not_in_reference')
            GROUP BY ALL ORDER BY n DESC
        """,
    }
    paths = []
    for name, sql in queries.items():
        path = out_dir / f"{name}.csv"
        con.execute(f"COPY ({sql}) TO '{path.as_posix()}' (HEADER, DELIMITER ',')")
        paths.append(path)
    return paths
