"""`just web-db`: rebuild the database and refresh everything the web app reads from it, in order.

    1. rebuild data/db/revive_tery.duckdb (import_fleet.py: user's fleet + dense telemetry + views + runtime tables)
    2. assess the whole fleet (fleet_reports.py, dense telemetry) -> fleet_reports table
    3. storage-v1.0 copy for DuckDB-WASM -> apps/web-studio/data/db/revive_tery.duckdb (tools/convert_db.py);
       fleet_reports.report_json is emptied in the web copy (the browser computes its own reports; keeps the file small)
    4. the CSV fallback -> apps/web-studio/data/demo/*.csv (the CSV bundle + telemetry_dense exported from the DB)
    5. apps/web-studio/data/db_meta.json {generated_utc, source_db_mtime, n_assets, table_counts}
       and apps/web-studio/data/history.json (assessments, ml_suggestions, test-run summaries) for the History page

Single-writer rule: stop the API and the other apps first (DuckDB allows one writer).
Options: --no-build skips 1 and 2 (only re-export the current database).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DB_PATH = Path(os.environ.get("REVIVE_DB") or ROOT / "data" / "db" / "revive_tery.duckdb")
WEB = ROOT / "apps" / "web-studio"
WEB_DATA = WEB / "data"
HISTORY_LIMIT = 500


def run(script: Path, *args: str) -> None:
    print(f"== {script.name} {' '.join(args)}")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / "engines" / x) for x in ("bms", "lite", "database"))}
    subprocess.run([sys.executable, "-W", "ignore", str(script), *args], check=True, env=env)


def rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    try:
        df = con.execute(sql).df()
    except duckdb.Error:
        return []
    for c in df.columns:
        if str(df[c].dtype).startswith("datetime"):
            df[c] = df[c].astype(str)
    return json.loads(df.to_json(orient="records", date_format="iso"))


def main() -> int:
    if "--no-build" not in sys.argv:
        run(HERE / "import_fleet.py")
        run(HERE / "fleet_reports.py", "--source", "dense")

    run(WEB / "tools" / "convert_db.py", str(DB_PATH))
    web_db = WEB_DATA / "db" / "revive_tery.duckdb"
    with duckdb.connect(str(web_db)) as w:
        w.execute("UPDATE fleet_reports SET report_json = NULL")
        w.execute("CHECKPOINT")

    demo = WEB_DATA / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    for f in sorted((HERE / "csv_bundle").glob("*.csv")):
        shutil.copy2(f, demo / f.name)
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        target = (demo / "telemetry_dense.csv").as_posix().replace("'", "''")     # the user folder has an apostrophe
        con.execute(f"COPY (SELECT * FROM telemetry_dense ORDER BY asset_id, timestamp_utc) TO "
                    f"'{target}' (HEADER, DELIMITER ',', TIMESTAMPFORMAT '%Y-%m-%dT%H:%M:%SZ')")
        tables = [t for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' "
                                            "AND table_type = 'BASE TABLE' ORDER BY 1").fetchall()]
        counts = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        n_assets = con.execute("SELECT count(*) FROM battery_registry").fetchone()[0]
        history = {
            "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "assessments": rows(con, f"SELECT id, created_utc, battery_id, engine, decision, readiness, gate, soh_pct "
                                     f"FROM assessments ORDER BY created_utc DESC LIMIT {HISTORY_LIMIT}"),
            "ml_suggestions": rows(con, f"SELECT id, created_utc, battery_id, assessment_id, engine, status, top_application "
                                        f"FROM ml_suggestions ORDER BY created_utc DESC LIMIT {HISTORY_LIMIT}"),
            "test_runs": rows(con, "SELECT run_id, any_value(source) AS source, any_value(asset_id) AS asset_id, "
                                   "any_value(data_class) AS data_class, count(*) AS rows, min(logged_at) AS started, "
                                   "date_diff('second', min(logged_at), max(logged_at)) AS duration_s, "
                                   "min(voltage_v) AS min_voltage_v, max(voltage_v) AS max_voltage_v "
                                   f"FROM test_run_log GROUP BY run_id ORDER BY started DESC LIMIT {HISTORY_LIMIT}"),
        }
    meta = {"generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_db_mtime": datetime.fromtimestamp(DB_PATH.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_assets": n_assets, "table_counts": counts,
            "note": "All packs are SYNTHETIC; telemetry_dense is densified SYNTHETIC telemetry (see engines/database/MODULE.md)."}
    (WEB_DATA / "db_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (WEB_DATA / "history.json").write_text(json.dumps(history, separators=(",", ":"), default=str), encoding="utf-8")
    print(f"web copy ready: {n_assets} packs, {sum(counts.values()):,} rows in {len(counts)} tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
