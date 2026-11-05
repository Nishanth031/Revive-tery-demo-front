"""Read-only data access for the REVIVE-TERY web backend."""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

# Resolved from this file's location, so it works wherever the web server is started.
DB_PATH = Path(os.environ.get("REVIVE_DB") or Path(__file__).resolve().parents[2] / "data" / "db" / "revive_tery.duckdb")

# Names used by the CSV bundle.
KEY_COLUMN = "asset_id"
TIME_COLUMN = "timestamp_utc"


def _fetch_asset(con: duckdb.DuckDBPyConnection, battery_id: str) -> pd.DataFrame:
    """Return the asset record as one row, with a column per field.

    battery_asset stores one pack as (field, value) rows, so it can't be filtered by ID
    directly: its asset_id row says which pack the whole table describes. Every value is
    text, so convert numbers such as nominal_voltage_V before calculating with them.
    """
    has_key = KEY_COLUMN in {c.lower() for c in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'battery_asset'").df()["column_name"]}
    rows = (con.execute('SELECT "field", "value" FROM "battery_asset" WHERE "asset_id" = ?', [battery_id]).df()
            if has_key else con.execute('SELECT "field", "value" FROM "battery_asset"').df())
    details = dict(zip(rows["field"], rows["value"]))
    if details.get(KEY_COLUMN) != battery_id:
        return pd.DataFrame()
    return pd.DataFrame([details])


def _fetch_time_series(
    con: duckdb.DuckDBPyConnection, table: str, battery_id: str
) -> pd.DataFrame:
    """Return one battery's rows from a table, oldest first."""
    # table is only ever a fixed name from this module. battery_id comes from the user, so
    # it is always passed as a bound parameter, which prevents SQL injection.
    return con.execute(
        f'SELECT * FROM "{table}" WHERE "{KEY_COLUMN}" = ? ORDER BY "{TIME_COLUMN}"',
        [battery_id],
    ).df()


def get_battery_dashboard_data(battery_id: str) -> dict[str, pd.DataFrame]:
    """Fetch the dashboard data for one battery, where battery_id is its asset_id.

    Returns a dictionary with the keys "asset", "telemetry" and "safety_events", each
    holding a DataFrame. An unknown battery_id gives empty DataFrames rather than an error,
    so check result["asset"].empty before using the data.

    Raises FileNotFoundError if the database hasn't been built yet.
    """
    if not DB_PATH.is_file():
        raise FileNotFoundError(
            f"{DB_PATH} not found. Run: python src/build_relational_db.py"
        )

    # read_only=True allows several processes to read at once and blocks accidental writes.
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return {
            "asset": _fetch_asset(con, battery_id),
            "telemetry": _fetch_time_series(con, "telemetry", battery_id),
            "safety_events": _fetch_time_series(con, "safety_events", battery_id),
        }
