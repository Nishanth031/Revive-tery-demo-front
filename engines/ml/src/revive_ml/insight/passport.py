"""A one-page battery passport (JSON, contracts/battery_passport.schema.json). Informational, not a regulatory document."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from revive_ml import __version__
from revive_ml.insight.confidence import confidence
from revive_ml.insight.explain import explain, val

NOTE = "informational, not a regulatory document"


def telemetry_sha256(telemetry) -> str:
    """SHA-256 of the input telemetry as CSV (columns sorted, rows in time order)."""
    df = telemetry[sorted(telemetry.columns)].copy()
    if "timestamp_utc" in df:
        df["timestamp_utc"] = df["timestamp_utc"].astype(str)
    return hashlib.sha256(df.to_csv(index=False, lineterminator="\n").encode("utf-8")).hexdigest()


def passport(report: dict[str, Any], bundle_meta: Any, telemetry=None, disposition: dict[str, str] | None = None,
             insight: dict[str, Any] | None = None) -> dict[str, Any]:
    st = report.get("state") or {}
    soh = st.get("soh") or {}
    rul = st.get("rul_cycles_reference") or {}
    conf = (insight or {}).get("confidence") or confidence(report, len(telemetry) if telemetry is not None else None)
    reasons = ((insight or {}).get("reasons") or explain(report))["top"]
    m = bundle_meta
    get = (lambda k: m.get(k)) if isinstance(m, dict) else (lambda k: getattr(m, k, None))
    return {
        "passport_version": "1.0",
        "note": NOTE,
        "asset_id": report.get("asset_id") or get("asset_id"),
        "chemistry": report.get("chemistry") or get("chemistry"),
        "rated_capacity_ah": get("rated_capacity_ah"),
        "nominal_voltage_v": get("nominal_voltage_v"),
        "cycle_count": get("cycle_count"),
        "soh": {"value": soh.get("value"), "provenance": soh.get("provenance"),
                "interval": [rul.get("lower"), rul.get("upper")] if rul else None, "note": soh.get("note")},
        "rul_cycles": {"median": rul.get("value"), "lower": rul.get("lower"), "upper": rul.get("upper"),
                       "provenance": rul.get("provenance")} if rul else None,
        "gate": (report.get("gate") or {}).get("verdict"),
        "decision": report.get("decision"),
        "disposition": disposition,
        "top_reasons": [{"title": r["title"], "text": r["text"], "tone": r["tone"]} for r in reasons],
        "confidence": {"level": conf["level"], "score_0_100": conf["score_0_100"], "label": conf["label"]},
        "provenance_summary": {"data": report.get("data_provenance"),
                               "placeholder_inputs": len((report.get("economics") or {}).get("placeholder_inputs", []))},
        "engine": {"name": "revive-tery-ml", "version": __version__, "report_schema": report.get("schema_version")},
        "input_telemetry_sha256": telemetry_sha256(telemetry) if telemetry is not None else None,
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "net_value_usd": val(((report.get("economics") or {}).get("second_life_options") or {})
                             .get((report.get("recommendation") or {}).get("application") or "", {}).get("net_value")),
    }
