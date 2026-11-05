"""Assessments: connect the REVIVE-TERY data to the ML engine.

Two engines sit behind one endpoint:
  full  revive-tery-ml: 14 data-quality checks, safety gate, ML remaining-life with a CV+ interval, physics
        projection and economics. It needs the data contract: timestamps and a capacity test.
  lite  src/ml_analyzer_suggester.py: fast capacity-based triage for uploads that cannot meet the contract.

"auto" tries full and falls back to lite, and says why. Nothing is guessed to make an upload fit the
contract: no timestamps means no full assessment. The conversion into the engine's data contract lives in
src/ml_engine_bridge.py, which the Circuit Studio dashboard uses too, so both convert data the same way.
The ML package itself imports nothing from this backend.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import db, settings
from ..disposition import disposition
from ..schemas import AssessIn, SpecIn
from .batteries import NotFound, battery_kind
from ml_analyzer_suggester import BatterySpec, SecondLifeSuggester
import ml_engine_bridge as bridge
from ml_engine_bridge import AdapterError, summarize_full, summarize_lite
from revive_ml.contract import Bundle
from revive_ml.pipeline import assess as full_assess


# --------------------------------------------------------------------------------------
# Adapters: REVIVE-TERY data -> revive-tery-ml bundle (thin wrappers over the shared bridge)
# --------------------------------------------------------------------------------------

def bundle_from_database(battery_id: str, telemetry_source: str = "dense") -> Bundle:
    """A battery with asset records (the database fleet)."""
    with db.read() as con:
        return bridge.bundle_from_database(con, battery_id, telemetry_source)


def bundle_from_upload(battery_id: str, spec: SpecIn) -> Bundle:
    """Uploaded telemetry (ml_telemetry) -> bundle. Refuses, with reasons, rather than inventing what is missing."""
    return bridge.bundle_from_rows(db.seeder().load_battery(battery_id), battery_id, spec, source="revive_api")


def bundle_from_zip(zip_path: Path) -> Bundle:
    """A contract bundle zipped as-is: metadata.json plus telemetry.csv or telemetry.parquet."""
    return bridge.bundle_from_zip(zip_path, settings.MAX_UPLOAD_BYTES)


# --------------------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------------------

def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def save(battery_id: str, summary: dict[str, Any], report: dict[str, Any]) -> str:
    aid = datetime.now(UTC).strftime("A%Y%m%d%H%M%S-") + uuid.uuid4().hex[:6]
    with db.write() as con:
        con.execute(
            "INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [aid, datetime.now(UTC), battery_id, summary["engine"], summary["decision"], summary["readiness"],
             summary["gate"], summary["soh_pct"], json.dumps(summary, default=str), json.dumps(report, default=str)])
    return aid


def _with_disposition(summary: dict[str, Any]) -> dict[str, Any]:
    """Additive: the reuse/repurpose/recycle reading of the engine's decision (config/decision_map.json)."""
    return {**summary, "disposition": disposition(summary.get("decision") or "", summary.get("application"))}


def _result(aid: str, battery_id: str, summary: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {"id": aid, "battery_id": battery_id, "engine": summary["engine"], "summary": _jsonable(summary),
            "report": _jsonable(report)}


# --------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------

def assess_battery(req: AssessIn) -> dict[str, Any]:
    kind = battery_kind(req.battery_id)
    if kind is None:
        raise NotFound(f"no battery {req.battery_id!r}")
    notes: list[str] = []
    if req.engine in ("auto", "full"):
        try:
            bundle = bundle_from_database(req.battery_id, req.telemetry_source) if kind == "database" \
                else bundle_from_upload(req.battery_id, req.spec)
            report = full_assess(bundle, req.workloads)
            summary = _with_disposition(summarize_full(report, bundle))
            return _result(save(req.battery_id, summary, report), req.battery_id, summary, report)
        except AdapterError as exc:
            if req.engine == "full" or kind == "database":
                raise
            notes.append(f"Full ML engine skipped: {exc}. Used the lite analyzer instead.")
    spec = BatterySpec(chemistry=req.spec.chemistry, series_cells=req.spec.series_cells,
                       rated_capacity_ah=req.spec.rated_capacity_ah, nominal_voltage_v=req.spec.nominal_voltage_v)
    report = SecondLifeSuggester(db.seeder()).generate_second_life_suggestion(req.battery_id, spec)
    summary = _with_disposition(summarize_lite(report, notes))
    return _result(save(req.battery_id, summary, report), req.battery_id, summary, report)


def assess_bundle(zip_path: Path, workloads: dict[str, Any] | None = None) -> dict[str, Any]:
    bundle = bundle_from_zip(zip_path)
    report = full_assess(bundle, workloads)
    summary = _with_disposition(summarize_full(report, bundle))
    return _result(save(bundle.meta.asset_id, summary, report), bundle.meta.asset_id, summary, report)


def list_assessments(battery_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    sql = "SELECT id, created_utc, battery_id, engine, decision, readiness, gate, soh_pct FROM assessments"
    params: list[Any] = []
    if battery_id:
        sql += " WHERE battery_id = ?"
        params.append(battery_id)
    with db.read() as con:
        df = con.execute(sql + " ORDER BY created_utc DESC LIMIT ?", [*params, limit]).df()
    return db.records(df)


def get_assessment(aid: str) -> dict[str, Any]:
    with db.read() as con:
        # epoch_ms: fetching a TIMESTAMPTZ directly would need pytz
        row = con.execute("SELECT battery_id, summary_json, report_json, epoch_ms(created_utc) FROM assessments "
                          "WHERE id = ?", [aid]).fetchone()
    if row is None:
        raise NotFound(f"no assessment {aid!r}")
    created = datetime.fromtimestamp(row[3] / 1000, UTC).isoformat().replace("+00:00", "Z")
    return {"id": aid, "battery_id": row[0], "created_utc": created, "summary": json.loads(row[1]),
            "report": json.loads(row[2]), "engine": json.loads(row[1])["engine"]}
