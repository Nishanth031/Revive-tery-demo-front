"""The single door to DuckDB.

DuckDB allows one writer, and it refuses to open one file with different settings at once in a
single process. bms_engine.open_db already serialises access with a process-wide lock, so the
backend goes through it for everything, including the ML analyzer's own seeder. The backend is
the only process that should write to the database while it is running.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import duckdb
import pandas as pd

from . import settings  # noqa: F401  (points bms_engine at the configured database)
import bms_engine
from ml_analyzer_suggester import DuckDBSeeder

ASSESSMENTS_DDL = """
CREATE TABLE IF NOT EXISTS assessments (
    id VARCHAR PRIMARY KEY,
    created_utc TIMESTAMPTZ,
    battery_id VARCHAR,
    engine VARCHAR,
    decision VARCHAR,
    readiness VARCHAR,
    gate VARCHAR,
    soh_pct DOUBLE,
    summary_json VARCHAR,
    report_json VARCHAR
)
"""


@contextmanager
def read() -> Iterator[duckdb.DuckDBPyConnection]:
    with bms_engine.open_db(read_only=True) as con:
        yield con


@contextmanager
def write() -> Iterator[duckdb.DuckDBPyConnection]:
    with bms_engine.open_db(read_only=False) as con:
        yield con


class _LockedConnection:
    """A connection that keeps the process-wide database lock until it is closed."""

    def __init__(self, cm: Any):
        self._cm = cm
        self._con = cm.__enter__()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._con, name)

    def close(self) -> None:
        self._cm.__exit__(None, None, None)


class LockedSeeder(DuckDBSeeder):
    """The ML analyzer's seeder, but opening the database through the shared lock."""

    def _connect(self, read_only: bool = False) -> _LockedConnection:  # type: ignore[override]
        return _LockedConnection(bms_engine.open_db(read_only=read_only, path=self.db_path))


def seeder() -> LockedSeeder:
    return LockedSeeder(settings.DB_PATH)


def ensure_tables() -> None:
    """Create the tables this backend owns (ml_telemetry, ml_ingest_log, assessments). Additive only."""
    with write() as con:
        DuckDBSeeder.ensure_tables(seeder(), con)
        con.execute(ASSESSMENTS_DDL)


def table_names() -> list[str]:
    with read() as con:
        return sorted(r[0] for r in con.execute("select table_name from information_schema.tables").fetchall())


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> JSON-safe list of dicts (timestamps as UTC ISO strings, NaN as null).

    DuckDB hands TIMESTAMPTZ back in the machine's local zone (+05:30 here), so zone-aware
    columns are converted to UTC first: every time the API emits is UTC and ends in Z.
    """
    if df.empty:
        return []
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            if getattr(out[col].dt, "tz", None) is not None:
                out[col] = out[col].dt.tz_convert("UTC")
            out[col] = out[col].map(lambda v: None if pd.isna(v) else v.isoformat().replace("+00:00", "Z"))
    out = out.astype(object).where(out.notna(), None)
    return out.to_dict("records")
