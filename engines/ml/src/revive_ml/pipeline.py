"""End-to-end assessment: data quality -> gate -> state -> projection -> economics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from revive_ml import __version__
from revive_ml.config import load
from revive_ml.contract import Bundle
from revive_ml.dq.detectors import run_all
from revive_ml.dq.readiness import readiness
from revive_ml.provenance import data_provenance_tag

SCHEMA_VERSION = 1
INSUFFICIENT = "Insufficient or untrustworthy data"
INSPECTION = "Inspection required"


def _workloads(override: dict[str, Any] | None) -> dict[str, Any]:
    return override if override is not None else load("workloads.yaml")["workloads"]


def physics_anchor(st: dict[str, Any]) -> tuple[dict[str, float], float, float | None]:
    """ML -> physics hand-over: reference cycles to an anchor SOH, the anchor, and ML coverage.

    With the ML model: remaining reference cycles to 80 % (point and CV+ bounds).
    Without it (SOH <= 80 % or no model): cycles to lose 10 more SOH points at the trend fade rate.
    """
    if "rul_cycles_reference" in st:
        r = st["rul_cycles_reference"]
        return ({"point": r["value"], "lower": r["lower"], "upper": r["upper"]}, 0.80,
                r.get("measured_coverage_on_held_out_cells"))
    soh0 = st["soh"]["value"] / 100.0
    drop = 0.10
    return ({"point": drop / st["fade_rate_ref"]["value"],
             "lower": drop / st["fade_rate_ref_conservative"]["value"],
             "upper": drop / st["fade_rate_ref_optimistic"]["value"]}, soh0 - drop, None)


def tag_workload(w: dict[str, Any], user: bool) -> dict[str, Any]:
    return {"label": w.get("label", ""), "provenance": "assumed",
            "source": "user-supplied workload" if user else "configs/workloads.yaml (default)",
            "values": {k: v for k, v in w.items() if k != "label"}}


def assess(bundle: Bundle, workloads: dict[str, Any] | None = None, region: str | None = None) -> dict[str, Any]:
    from revive_ml import gate
    from revive_ml.econ.router import route
    from revive_ml.physics.fade import project
    from revive_ml.state.estimate import estimate

    meta = bundle.meta
    warnings: list[str] = []
    if meta.data_provenance != "measured":
        warnings.append(f"Data provenance is '{meta.data_provenance}'. Every value read from it is "
                        "tagged 'synthetic'. This report shows the pipeline works; it says nothing "
                        "about a real battery.")
    if bundle.ignored_columns:
        warnings.append(f"Ignored telemetry columns not in the contract: {bundle.ignored_columns}")

    checks = run_all(bundle)
    ready = readiness(checks)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "engine": f"revive-tery-ml {__version__}",
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "asset_id": meta.asset_id,
        "chemistry": meta.chemistry,
        "data_provenance": meta.data_provenance,
        "value_provenance_for_data": data_provenance_tag(meta.data_provenance),
        "data_quality": {"checks": [c.to_dict() for c in checks], "readiness": ready},
        "gate": None,
        "state": None,
        "projections": None,
        "economics": None,
        "recommendation": None,
        "warnings": warnings,
    }
    for c in checks:
        if c.status in ("warn", "inconclusive"):
            warnings.append(f"[{c.id}] {c.message}")

    if ready["verdict"] == "NOT_READY":
        report["decision"] = INSUFFICIENT
        report["rationale"] = [f"data-quality check '{c.id}' failed: {c.message}"
                               for c in checks if c.status == "fail"]
        report["stages_not_run"] = ["gate", "state", "projections", "economics", "recommendation"]
        return report

    g = gate.evaluate(bundle)
    report["gate"] = g
    if g["verdict"] == "Reject":
        report["decision"] = "Reject (safety triage): route to recycling"
        report["rationale"] = g["reasons"]
        return report

    st = estimate(bundle, excluded=set(ready["excluded_from_decision"]))
    warnings.extend(f"[state] {w}" for w in st.get("warnings", []))
    report["state"] = st
    wl = _workloads(workloads)
    if st.get("status") == "ok" and "fade_rate_ref" in st:
        anchor, target, coverage = physics_anchor(st)
        report["projections"] = {
            name: {"workload": tag_workload(w, workloads is not None),
                   **project(st["soh"]["value"], anchor, w, coverage, target)}
            for name, w in wl.items()
        }
    if g["verdict"] == "Quarantine":
        report["decision"] = INSPECTION
        report["rationale"] = g["reasons"]
        return report
    if st.get("status") != "ok":
        report["decision"] = INSUFFICIENT
        report["rationale"] = [st.get("reason", "state estimate unavailable")]
        return report
    econ = route(meta, st, report["projections"] or {}, region=region)
    report["economics"] = econ
    report["decision"] = econ.get("decision") or "No recommendation (economics unavailable)"
    report["recommendation"] = econ.get("recommendation")
    report["rationale"] = econ.get("rationale", [])
    rule = st.get("existing_rule")
    report["comparison_with_existing_rule"] = {
        "existing_rule": rule,
        "ml_and_economics": report["decision"],
        "agree": bool(rule and rule.split(":")[0] == report["decision"].split(":")[0]),
        "note": "existing rule: SOH > 80 % stationary storage, 60-80 % low-speed EV, < 60 % recycle; "
                "shown for comparison only",
    }
    return report
