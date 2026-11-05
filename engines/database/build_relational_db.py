"""Build the REVIVE-TERY DuckDB database from the CSV bundle.

Safe to run repeatedly: each table is dropped and rebuilt, which also removes its indexes.
Run it while the web backend is stopped, because DuckDB locks the file during a rebuild.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb

# Paths come from this file's location, so the script works from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # platform root (engines/database -> platform)
CSV_DIR = PROJECT_ROOT / "engines" / "database" / "csv_bundle"
DB_PATH = Path(os.environ.get("REVIVE_DB") or PROJECT_ROOT / "data" / "db" / "revive_tery.duckdb")

# Each table is named after its CSV file.
EXPECTED_TABLES = (
    "battery_asset",
    "battery_registry",     # one row per pack (the user's fleet layout); battery_asset is generated from it
    "modules",
    "charge_sessions",
    "telemetry",
    "health_history",
    "safety_events",
    "materials_recycling",
    "data_sources",
)

# The bundle's join key, and the time column in telemetry. Its README names asset_id as the
# key. battery_asset (field, value rows) and data_sources don't have this column.
KEY_COLUMN = "asset_id"
TIME_COLUMN = "timestamp_utc"


def sql_string(value: str) -> str:
    """Quote text as a SQL literal. Paths can contain apostrophes, which must be doubled."""
    return "'" + value.replace("'", "''") + "'"


def table_columns(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    """Return {lowercase column name: DuckDB type} for one table."""
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?",
        [table],
    ).fetchall()
    return {name.lower(): data_type for name, data_type in rows}


def load_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Rebuild every table in one transaction, so a bad CSV leaves the old tables intact."""
    con.execute("BEGIN TRANSACTION")
    try:
        for table in EXPECTED_TABLES:
            csv_path = sql_string((CSV_DIR / f"{table}.csv").as_posix())
            con.execute(f'DROP TABLE IF EXISTS "{table}"')
            # sample_size=-1 reads the whole file to detect column types. It is slower, but
            # it stops an unusual value deep in a large file from failing the load.
            con.execute(
                f'CREATE TABLE "{table}" AS '
                f"SELECT * FROM read_csv_auto({csv_path}, sample_size=-1)"
            )
            row_count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            print(f"Loaded {table}: {row_count:,} rows")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def create_indexes(con: duckdb.DuckDBPyConnection) -> None:
    """Index the key column wherever it exists, plus (key, time) on telemetry."""
    for table in EXPECTED_TABLES:
        columns = table_columns(con, table)
        if KEY_COLUMN not in columns:
            print(f"Skipped index on {table}: no {KEY_COLUMN} column")
            continue
        con.execute(f'CREATE INDEX "idx_{table}_{KEY_COLUMN}" ON "{table}" ("{KEY_COLUMN}")')
        print(f"Indexed {table}({KEY_COLUMN})")

    telemetry_columns = table_columns(con, "telemetry")
    if not {KEY_COLUMN, TIME_COLUMN} <= telemetry_columns.keys():
        raise RuntimeError(
            f"telemetry needs {KEY_COLUMN} and {TIME_COLUMN} columns for the composite index. "
            f"Found: {sorted(telemetry_columns)}"
        )
    con.execute(
        f'CREATE INDEX "idx_telemetry_{KEY_COLUMN}_{TIME_COLUMN}" '
        f'ON "telemetry" ("{KEY_COLUMN}", "{TIME_COLUMN}")'
    )
    print(f"Indexed telemetry({KEY_COLUMN}, {TIME_COLUMN})")

    # Mixed date formats load as text, which sorts and filters incorrectly as time.
    if "TIMESTAMP" not in telemetry_columns[TIME_COLUMN].upper():
        print(
            f"WARNING: telemetry.{TIME_COLUMN} loaded as {telemetry_columns[TIME_COLUMN]}, "
            "not a timestamp type. Check its format in the CSV."
        )


def main() -> int:
    # Check every file first, so a missing one is reported before anything changes.
    missing = [f"{table}.csv" for table in EXPECTED_TABLES if not (CSV_DIR / f"{table}.csv").is_file()]
    if missing:
        print(f"ERROR: missing from {CSV_DIR}: {', '.join(missing)}", file=sys.stderr)
        return 1

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(DB_PATH)) as con:
        load_tables(con)
        # Indexes are built after the commit. If this step fails, rerun the whole script.
        create_indexes(con)
    print(f"Database ready: {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
