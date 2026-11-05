"""Assess every pack in the platform database and write fleet_reports (one writer, one connection).

    python engines/database/fleet_reports.py [--source dense|original] [--json out.json]

For each pack: the full engine (revive_ml) on the database tables through the lite bridge, plus the insight layer
when revive_ml.insight is available; the disposition comes from config/decision_map.json (the same prefix rules as
services/api/revive_api/disposition.py), and the registry's lifecycle_status (a plain SOH threshold rule in the user's
database) is compared with the engine's disposition. Prints the real outcome counts; nothing is hand-labelled.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DB_PATH = Path(os.environ.get("REVIVE_DB") or ROOT / "data" / "db" / "revive_tery.duckdb")
DECISION_MAP = json.loads((ROOT / "config" / "decision_map.json").read_text(encoding="utf-8"))


def disposition(decision: str, application: str | None) -> str:
    d = (decision or "").strip()
    for rule in DECISION_MAP["rules"]:
        if not d.startswith(rule["match_prefix"]):
            continue
        if rule.get("disposition"):
            return rule["disposition"]
        if application in rule.get("application_keys_to_REUSE", []):
            return "REUSE"
        if application in rule.get("application_keys_to_REPURPOSE", []):
            return "REPURPOSE"
        return rule.get("default_disposition", "REPURPOSE")
    return "NO_DECISION"


def rule_comparison(status: str | None, disp: str, report: dict) -> tuple[bool | None, str]:
    """Does the registry's SOH-threshold status agree with the engine? (None when the registry has no status.)"""
    expect = DECISION_MAP.get("registry_status_expectation", {})
    if not status:
        return None, "no registry status for this pack"
    allowed = expect.get(status)
    if allowed is None:
        return None, f"registry status {status} has no expectation in config/decision_map.json"
    if disp in allowed:
        return True, f"{status} and the engine's {disp} agree"
    why: list[str] = []
    fails = [c["id"] for c in report["data_quality"]["checks"] if c["status"] == "fail"]
    if fails:
        why.append("data-quality checks failed: " + ", ".join(fails))
    gate = report.get("gate") or {}
    why += gate.get("reasons", [])[:2]
    if (gate.get("ood") or {}).get("status") == "quarantine":
        why.append((gate["ood"].get("reason") or "telemetry outside the healthy-window distribution"))
    why += (report.get("rationale") or [])[:1]
    return False, f"registry says {status} (SOH threshold), engine says {disp}: " + "; ".join(why or [report.get("decision", "")])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="dense", choices=["dense", "original"])
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    import ml_engine_bridge as bridge
    from revive_ml.pipeline import assess
    try:
        from revive_ml.insight.workflow import insight_for       # P2 insight layer (optional)
    except ImportError:
        insight_for = None

    rows, out_json = [], []
    with duckdb.connect(str(DB_PATH)) as con:
        reg = con.execute("SELECT asset_id, lifecycle_status, registry_source FROM battery_registry ORDER BY asset_id").fetchall()
        for aid, status, src in reg:
            try:
                bundle = bridge.bundle_from_database(con, aid, args.source)
                report = assess(bundle)
                rec = report.get("recommendation") or {}
                disp = disposition(report["decision"], rec.get("application"))
                agrees, why = rule_comparison(status, disp, report)
                soh = ((report.get("state") or {}).get("soh") or {}).get("value")
                rul = ((report.get("state") or {}).get("rul_cycles_reference") or {}).get("value")
                econ = report.get("economics") or {}
                net = None
                if rec.get("application"):
                    net = ((econ.get("second_life_options") or {}).get(rec["application"], {}).get("net_value") or {}).get("value")
                elif econ.get("recycle"):
                    net = econ["recycle"]["net_value"]["value"]
                ins = insight_for(report, bundle) if insight_for else None
                conf = ins["confidence"]["level"] if ins else None
                if ins:
                    report = {**report, "insight": ins}
                rows.append([aid, datetime.now(UTC), "full", args.source, report["decision"], disp, soh, rul, net, conf,
                             status, agrees, why, json.dumps(report, default=str)])
                out_json.append({"asset_id": aid, "decision": report["decision"], "disposition": disp, "registry": status,
                                 "rule_agrees": agrees, "source": src})
            except Exception as exc:                                  # reported, never hidden
                rows.append([aid, datetime.now(UTC), "error", args.source, f"ERROR: {exc}", "NO_DECISION", None, None, None,
                             None, status, None, str(exc), None])
                out_json.append({"asset_id": aid, "decision": f"ERROR: {exc}", "disposition": "NO_DECISION"})
        con.execute("DELETE FROM fleet_reports WHERE telemetry_source = ?", [args.source])
        con.executemany("INSERT INTO fleet_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    dec = Counter(r[4].split(":")[0] if not r[4].startswith("ERROR") else "ERROR" for r in rows)
    disp = Counter(r[5] for r in rows)
    agree = Counter(str(r[11]) for r in rows)
    print(f"fleet: {len(rows)} packs, telemetry={args.source}")
    print("decisions:", dict(dec))
    print("dispositions:", dict(disp))
    print("registry rule agrees:", dict(agree))
    if args.json:
        Path(args.json).write_text(json.dumps(out_json, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
