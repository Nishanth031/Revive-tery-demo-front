"""ML-led workflow: understand an upload -> store it -> assess it -> advise a second use.

The learning and judgement live in revive_ml.intelligence; this module only connects it to the backend:
it writes the mapped rows through the existing seeder (ml_telemetry / ml_ingest_log), records the battery's
identity and the advice in two new tables, and reuses the existing assessment code and storage unchanged.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .. import db
from ..schemas import SpecIn
from . import assess, ingest
from .batteries import NotFound, battery_kind
from ml_analyzer_suggester import BatterySpec, ExtractedFile, SecondLifeSuggester
from ml_engine_bridge import AdapterError, summarize_full, summarize_lite
from revive_ml.intelligence import (AdvisorInput, advise, analyze_upload, assess_with_advice, characteristics, profiles)
from revive_ml.intelligence.workflow import UploadError

PROFILE_DDL = """
CREATE TABLE IF NOT EXISTS ml_battery_profile (
    battery_id VARCHAR, recorded_utc TIMESTAMPTZ, ingest_id VARCHAR, chemistry VARCHAR, chemistry_basis VARCHAR,
    brand VARCHAR, series_cells BIGINT, parallel_cells BIGINT, rated_capacity_ah DOUBLE, nominal_voltage_v DOUBLE,
    needs VARCHAR, spec_json VARCHAR)"""
SUGGESTION_DDL = """
CREATE TABLE IF NOT EXISTS ml_suggestions (
    id VARCHAR PRIMARY KEY, created_utc TIMESTAMPTZ, battery_id VARCHAR, assessment_id VARCHAR, engine VARCHAR,
    status VARCHAR, top_application VARCHAR, advice_json VARCHAR)"""


class NeedsInput(ValueError):
    """The battery's spec is incomplete and the ML will not guess it."""

    def __init__(self, battery_id: str, needs: list[str], message: str | None = None):
        self.battery_id, self.needs = battery_id, needs
        super().__init__(message or f"{battery_id}: still needs {', '.join(needs)}")


def ensure_tables() -> None:
    with db.write() as con:
        con.execute(PROFILE_DDL)
        con.execute(SUGGESTION_DDL)


def _num(v: Any, cast=float) -> Any:
    if v in (None, ""):
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        raise ValueError(f"{v!r} is not a number")


def hints_from_form(chemistry=None, brand=None, series_cells=None, parallel_cells=None, rated_capacity_ah=None,
                    nominal_voltage_v=None) -> dict[str, Any]:
    h = {"chemistry": (chemistry or "").strip().upper() or None, "brand": (brand or "").strip() or None,
         "series_cells": _num(series_cells, int), "parallel_cells": _num(parallel_cells, int),
         "rated_capacity_ah": _num(rated_capacity_ah), "nominal_voltage_v": _num(nominal_voltage_v)}
    if h["chemistry"] and h["chemistry"] not in ("LFP", "NMC", "NCA"):
        raise ValueError("chemistry must be LFP, NMC or NCA")
    return {k: v for k, v in h.items() if v is not None}


# ---------------------------------------------------------------------------------------------
# stored identity
# ---------------------------------------------------------------------------------------------

def _save_profile(battery_id: str, ingest_id: str | None, identity: dict[str, Any], spec: dict[str, Any]) -> None:
    val = lambda k: (spec.get(k) or {}).get("value")          # noqa: E731
    with db.write() as con:
        con.execute("INSERT INTO ml_battery_profile VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
            battery_id, datetime.now(UTC), ingest_id, val("chemistry"), (spec.get("chemistry") or {}).get("basis"),
            identity.get("brand"), val("series_cells"), val("parallel_cells"), val("rated_capacity_ah"),
            val("nominal_voltage_v"), json.dumps(spec.get("needs", [])), json.dumps({"identity": identity, "spec": spec},
                                                                                    default=str)])


def stored_profile(battery_id: str) -> dict[str, Any] | None:
    with db.read() as con:
        try:
            row = con.execute("SELECT chemistry, chemistry_basis, brand, series_cells, parallel_cells, rated_capacity_ah, "
                              "nominal_voltage_v, needs FROM ml_battery_profile WHERE battery_id = ? "
                              "ORDER BY recorded_utc DESC LIMIT 1", [battery_id]).fetchone()
        except Exception:                                      # table not created yet
            return None
    if not row:
        return None
    return {"chemistry": row[0], "chemistry_basis": row[1], "brand": row[2], "series_cells": row[3],
            "parallel_cells": row[4], "rated_capacity_ah": row[5], "nominal_voltage_v": row[6],
            "needs": json.loads(row[7] or "[]")}


# ---------------------------------------------------------------------------------------------
# assess + advise one battery
# ---------------------------------------------------------------------------------------------

def _save_suggestion(battery_id: str, aid: str, engine: str, advice: dict[str, Any]) -> str:
    sid = datetime.now(UTC).strftime("S%Y%m%d%H%M%S-") + uuid.uuid4().hex[:6]
    top = (advice.get("suggestions") or [{}])[0].get("application")
    with db.write() as con:
        con.execute("INSERT INTO ml_suggestions VALUES (?,?,?,?,?,?,?,?)",
                    [sid, datetime.now(UTC), battery_id, aid, engine, advice.get("status"), top,
                     json.dumps(advice, default=str)])
    return sid


def advise_battery(battery_id: str, spec: SpecIn | None = None, workloads: dict[str, Any] | None = None,
                   brand: str | None = None, basis: str = "user") -> dict[str, Any]:
    """Assess one battery (database fleet or upload) and rank its second-use options."""
    kind = battery_kind(battery_id)
    if kind is None:
        raise NotFound(f"no battery {battery_id!r}")
    ensure_tables()
    prof = stored_profile(battery_id) if kind == "uploaded" else None
    if kind == "uploaded":
        if prof and not prof["needs"] and prof["chemistry"]:
            spec = SpecIn(chemistry=prof["chemistry"], series_cells=prof["series_cells"] or 1,
                          parallel_cells=prof["parallel_cells"] or 1, rated_capacity_ah=prof["rated_capacity_ah"],
                          nominal_voltage_v=prof["nominal_voltage_v"])
            brand, basis = brand or prof["brand"], prof["chemistry_basis"] or basis
        elif spec is None:
            raise NeedsInput(battery_id, (prof or {}).get("needs") or ["chemistry", "series_cells", "rated_capacity_ah"],
                             f"{battery_id}: the ML has no confirmed spec for this upload; supply it or upload with it")
    notes: list[str] = []
    try:
        bundle = assess.bundle_from_database(battery_id) if kind == "database" \
            else assess.bundle_from_upload(battery_id, spec)
        out = assess_with_advice(bundle, workloads, brand, "engine" if kind == "database" else basis)
        advice = out.pop("advice")
        report = out
        summary = assess._with_disposition(summarize_full(report, bundle))
        engine = "full"
    except AdapterError as exc:
        if kind == "database":
            raise
        notes.append(f"Full ML engine skipped: {exc}. Used the lite analyzer instead.")
        lite_spec = BatterySpec(chemistry=spec.chemistry, series_cells=spec.series_cells,
                                rated_capacity_ah=spec.rated_capacity_ah, nominal_voltage_v=spec.nominal_voltage_v)
        report = SecondLifeSuggester(db.seeder()).generate_second_life_suggestion(battery_id, lite_spec)
        summary = assess._with_disposition(summarize_lite(report, notes))
        engine = "lite"
        advice = advise(AdvisorInput(
            chemistry=spec.chemistry, chemistry_basis=basis, brand=brand, soh_pct=summary.get("soh_pct"),
            gate=summary.get("gate"), readiness=None, decision=summary.get("decision"),
            data_provenance=summary.get("data_provenance") or "synthetic"), workloads)
        advice.setdefault("notes", []).append("lite analyzer: no economics or resistance history, so the ranking "
                                              "rests on health and chemistry only")
    aid = assess.save(battery_id, summary, report)
    sid = _save_suggestion(battery_id, aid, engine, advice)
    return {"id": aid, "suggestion_id": sid, "battery_id": battery_id, "engine": engine, "notes": notes,
            "summary": assess._jsonable(summary), "advice": assess._jsonable(advice)}


# ---------------------------------------------------------------------------------------------
# upload -> understand -> store -> assess -> advise
# ---------------------------------------------------------------------------------------------

def analyze(files: Iterable[tuple[str, Any]], data_provenance: str, hints: dict[str, Any], store: bool = True,
            assess_after: bool = True) -> dict[str, Any]:
    if data_provenance not in ingest.PROVENANCES:
        raise ValueError(f"data_provenance must be one of {ingest.PROVENANCES}")
    tmp = Path(tempfile.mkdtemp(prefix="revive_ml_upload_"))
    try:
        paths = ingest.save_uploads(files, tmp)
        analysis = analyze_upload(paths, hints)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    result: dict[str, Any] = {"analysis": analysis.to_dict(), "stored": None, "results": [], "data_provenance": data_provenance}
    if not store:
        return result
    extracted = [ExtractedFile(t.source, t.data, {m.column: m.field for m in t.mapping.matches},
                               [u["column"] for u in t.mapping.unmapped], list(t.mapping.warnings))
                 for t in analysis.telemetry]
    result["stored"] = db.seeder().seed(extracted, data_provenance)
    ensure_tables()
    ident = analysis.identity.to_dict()
    for b in analysis.batteries:
        _save_profile(b.battery_id, result["stored"]["ingest_id"], ident, b.spec.to_dict())
    if assess_after:
        for b in analysis.batteries:
            if not b.spec.complete:
                result["results"].append({"battery_id": b.battery_id, "status": "needs_input", "needs": b.spec.needs,
                                          "message": "the ML will not guess these; resubmit with them or call "
                                                     "/api/intelligence/advise once they are known"})
                continue
            spec = b.spec
            try:
                res = advise_battery(b.battery_id, SpecIn(
                    chemistry=spec.chemistry.value, series_cells=spec.series_cells.value,
                    parallel_cells=spec.parallel_cells.value, rated_capacity_ah=spec.rated_capacity_ah.value,
                    nominal_voltage_v=spec.nominal_voltage_v.value), None, ident.get("brand"), spec.chemistry.basis)
                result["results"].append({"battery_id": b.battery_id, "status": "assessed", **res})
            except (AdapterError, NeedsInput) as exc:
                result["results"].append({"battery_id": b.battery_id, "status": "not_assessed", "message": str(exc)})
    return result


def profiles_catalog() -> dict[str, Any]:
    p = profiles()
    return {"chemistries": {k: characteristics(k) for k in p["chemistries"]},
            "brands": [{"name": b["name"], "chemistry": b["chemistry"], "ambiguous": b["ambiguous"], "note": b["note"]}
                       for b in p["brands"]],
            "provenance": "assumed", "note": "qualitative priors from general literature; see configs/battery_profiles.yaml"}


def list_suggestions(battery_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    sql = "SELECT id, created_utc, battery_id, assessment_id, engine, status, top_application FROM ml_suggestions"
    params: list[Any] = []
    if battery_id:
        sql += " WHERE battery_id = ?"
        params.append(battery_id)
    with db.read() as con:
        try:
            df = con.execute(sql + " ORDER BY created_utc DESC LIMIT ?", [*params, limit]).df()
        except Exception:
            return []
    return db.records(df)


__all__ = ["NeedsInput", "UploadError", "advise_battery", "analyze", "ensure_tables", "hints_from_form",
           "list_suggestions", "profiles_catalog", "stored_profile"]
