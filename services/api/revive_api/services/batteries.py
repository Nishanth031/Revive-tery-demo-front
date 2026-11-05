"""Batteries: the ones with asset records in the database, and the ones that arrived as uploads."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from .. import db, settings
from bms_engine import DatabaseUnavailable, list_battery_ids, load_battery_profile


class NotFound(LookupError):
    pass


def _uploaded_summary() -> dict[str, dict[str, Any]]:
    with db.read() as con:
        rows = con.execute(
            """SELECT battery_id, count(*) AS n, count(DISTINCT cycle_index) AS cycles,
                      string_agg(DISTINCT data_provenance, ',') AS prov,
                      max(capacity_ah) FILTER (WHERE cycle_index <= (SELECT min(cycle_index) + 4 FROM ml_telemetry m2
                                                                      WHERE m2.battery_id = ml_telemetry.battery_id)) AS early_cap
               FROM ml_telemetry GROUP BY battery_id ORDER BY battery_id"""
        ).fetchall()
    return {r[0]: {"rows": r[1], "cycles": r[2], "data_provenance": r[3], "early_capacity_ah": r[4]} for r in rows}


def list_batteries() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for bid in list_battery_ids():
        p = load_battery_profile(bid)
        out.append({"id": bid, "kind": "database", "chemistry": p.chemistry, "rated_capacity_ah": p.rated_capacity_ah,
                    "measured_capacity_ah": p.measured_capacity_ah, "rows": p.telemetry_rows,
                    "data_provenance": "synthetic" if p.is_synthetic else "recorded"})
    known = {b["id"] for b in out}
    for bid, s in _uploaded_summary().items():
        if bid in known:
            continue
        out.append({"id": bid, "kind": "uploaded", "chemistry": None, "rated_capacity_ah": None,
                    "measured_capacity_ah": None, "rows": s["rows"], "cycles": s["cycles"],
                    "data_provenance": s["data_provenance"]})
    return out


def battery_kind(battery_id: str) -> str | None:
    if battery_id in list_battery_ids():
        return "database"
    return "uploaded" if battery_id in _uploaded_summary() else None


def _query(sql: str, params: list[Any]) -> pd.DataFrame:
    with db.read() as con:
        return con.execute(sql, params).df()


def detail(battery_id: str) -> dict[str, Any]:
    kind = battery_kind(battery_id)
    if kind is None:
        raise NotFound(f"no battery {battery_id!r}")
    if kind == "database":
        profile = load_battery_profile(battery_id)
        health = _query('SELECT * FROM health_history WHERE asset_id = ? ORDER BY assessment_date', [battery_id])
        events = _query('SELECT * FROM safety_events WHERE asset_id = ? ORDER BY timestamp_utc', [battery_id])
        tel = _query('SELECT * FROM telemetry WHERE asset_id = ? ORDER BY timestamp_utc LIMIT ?',
                     [battery_id, settings.TELEMETRY_PREVIEW_ROWS])
        modules = _query('SELECT * FROM modules WHERE asset_id = ?', [battery_id])
        return {"id": battery_id, "kind": kind, "profile": asdict(profile), "health_history": db.records(health),
                "safety_events": db.records(events), "modules": db.records(modules),
                "telemetry": db.records(tel), "telemetry_rows_total": profile.telemetry_rows}
    summary = _uploaded_summary()[battery_id]
    cap = _query("""SELECT cycle_index, max(capacity_ah) AS capacity_ah FROM ml_telemetry
                    WHERE battery_id = ? AND capacity_ah IS NOT NULL AND cycle_index IS NOT NULL
                    GROUP BY cycle_index ORDER BY cycle_index""", [battery_id])
    tel = _query("""SELECT * EXCLUDE (ingest_id, source_file) FROM ml_telemetry WHERE battery_id = ?
                    ORDER BY source_file, row_in_file LIMIT ?""", [battery_id, settings.TELEMETRY_PREVIEW_ROWS])
    sources = _query("SELECT source_file, count(*) AS rows FROM ml_telemetry WHERE battery_id = ? GROUP BY source_file",
                     [battery_id])
    return {"id": battery_id, "kind": kind, "profile": None, "summary": summary,
            "capacity_per_cycle": db.records(cap), "sources": db.records(sources),
            "telemetry": db.records(tel), "telemetry_rows_total": summary["rows"]}


__all__ = ["NotFound", "DatabaseUnavailable", "list_batteries", "battery_kind", "detail"]
