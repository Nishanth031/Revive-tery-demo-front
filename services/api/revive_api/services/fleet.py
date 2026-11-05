"""Fleet: the whole database through the engine (fleet_reports), summaries, what-if, fleet plan, passport, meta, history.

Reads go through db.read(); the only writer is refresh(), which assesses every pack in one process and writes
fleet_reports in one transaction (DuckDB allows one writer). Records match the web app's compact fleet records
(apps/web-studio/assets/js/lib/fleet.js summarizeForFleet), so the Command Center can use either source.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from .. import db, settings
from .batteries import NotFound

import ml_engine_bridge as bridge
from revive_ml import __version__ as ml_version
from revive_ml.insight import assign, insight_for, passport, reroute
from revive_ml.pipeline import assess

DECISION_MAP = json.loads((settings.APP_ROOT / "config" / "decision_map.json").read_text(encoding="utf-8"))
SECOND = ("REUSE", "REPURPOSE")


def _val(x: Any) -> Any:
    return x.get("value") if isinstance(x, dict) else x


def disposition(decision: str, application: str | None) -> str:
    d = (decision or "").strip()
    for rule in DECISION_MAP["rules"]:
        if d.startswith(rule["match_prefix"]):
            if rule.get("disposition"):
                return rule["disposition"]
            if application in rule.get("application_keys_to_REUSE", []):
                return "REUSE"
            if application in rule.get("application_keys_to_REPURPOSE", []):
                return "REPURPOSE"
            return rule.get("default_disposition", "REPURPOSE")
    return "NO_DECISION"


def compact(asset_id: str, reg: dict[str, Any], report: dict[str, Any], disp: str) -> dict[str, Any]:
    st, econ, rec = report.get("state") or {}, report.get("economics") or {}, report.get("recommendation") or {}
    opts = econ.get("second_life_options") or {}
    best = rec.get("application") or (max(opts, key=lambda k: _val(opts[k]["net_value"])) if opts else None)
    dq = report["data_quality"]
    rul = st.get("rul_cycles_reference")
    ins = report.get("insight")
    rob = (ins or {}).get("robustness")
    pj = (report.get("projections") or {}).get(best) if best else None
    return {
        "asset_id": asset_id, "chemistry": report.get("chemistry"), "chemistry_label": reg.get("chemistry"),
        "application": reg.get("application"), "registry_status": reg.get("lifecycle_status"),
        "registry_source": reg.get("registry_source"), "test_case": "TEST CASE" in (reg.get("demo_status") or "").upper(),
        "demo_status": reg.get("demo_status"), "data_provenance": report.get("data_provenance"),
        "decision": report.get("decision"), "disposition": disp, "readiness": dq["readiness"]["verdict"],
        "dq_pass": dq["readiness"].get("n_pass"), "dq_total": dq["readiness"].get("n_checks"),
        "failing": [c["id"] for c in dq["checks"] if c["status"] == "fail"],
        "gate": (report.get("gate") or {}).get("verdict"), "ood": ((report.get("gate") or {}).get("ood") or {}).get("status"),
        "soh": _val(st.get("soh")), "soh_test": reg.get("soh_pct"), "cycles": reg.get("cycle_count"),
        "rul": {"median": rul["value"], "lower": rul.get("lower"), "upper": rul.get("upper")} if isinstance(rul, dict) else None,
        "best_application": best, "best_label": opts[best]["label"] if best in opts else None,
        "net_value": _val(opts[best]["net_value"]) if best in opts else None,
        "recycle_value": _val(econ["recycle"]["net_value"]) if econ.get("recycle") else None,
        "capped_by_buy_new": bool(opts[best].get("capped_by_buy_new")) if best in opts else None,
        "years": _val(pj["conservative_years"]) if pj else None,
        "pack_kwh": _val(econ.get("pack_energy")),
        "options": {k: _val(o["net_value"]) for k, o in opts.items()},
        "insight": None if not ins else {
            "reasons": ins["reasons"]["top"], "confidence": ins["confidence"], "rul_range": ins.get("rul_range"),
            "years_range": ins.get("years_range"), "next_actions": ins.get("next_actions"), "rule_gap": ins.get("rule_gap"),
            "robustness": None if not rob else {"share_same_decision": rob["share_same_decision"], "scenarios": rob["scenarios"],
                                                "break_even_tariff": rob["break_even_tariff"], "flips": len(rob["flips"])}},
    }


def _registry(con) -> dict[str, dict[str, Any]]:
    df = con.execute("SELECT * FROM battery_registry").df()
    return {r["asset_id"]: {k: (None if v != v else v) for k, v in r.items()} for r in df.astype(object).to_dict("records")}


def packs(source: str = "dense") -> list[dict[str, Any]]:
    with db.read() as con:
        reg = _registry(con)
        rows = con.execute("SELECT asset_id, decision, disposition, report_json FROM fleet_reports WHERE telemetry_source = ? "
                           "ORDER BY asset_id", [source]).fetchall()
    out = []
    for aid, decision, disp, rj in rows:
        if rj:
            out.append(compact(aid, reg.get(aid, {}), json.loads(rj), disp))
        else:
            out.append({"asset_id": aid, "decision": decision, "disposition": disp or "NO_DECISION", "error": decision})
    return out


SORTS = {"net_value": lambda p: p.get("net_value") if p.get("net_value") is not None else float("-inf"),
         "soh": lambda p: p.get("soh") if p.get("soh") is not None else float("-inf"),
         "confidence": lambda p: ((p.get("insight") or {}).get("confidence") or {}).get("score_0_100", float("-inf")),
         "asset_id": lambda p: p["asset_id"]}


def query(q: str | None = None, decision: str | None = None, disposition_: str | None = None, chemistry: str | None = None,
          source: str | None = None, sort: str = "asset_id", desc: bool = False, offset: int = 0, limit: int = 25) -> dict[str, Any]:
    rows = packs()
    if q:
        rows = [p for p in rows if q.lower() in p["asset_id"].lower()]
    if decision:
        rows = [p for p in rows if (p.get("decision") or "").startswith(decision)]
    if disposition_:
        rows = [p for p in rows if p["disposition"] == disposition_]
    if chemistry:
        rows = [p for p in rows if p.get("chemistry") == chemistry]
    if source:
        rows = [p for p in rows if (p.get("test_case") if source == "test" else "user fleet" in (p.get("registry_source") or "")
                                     if source == "user" else not p.get("test_case") and "user fleet" not in (p.get("registry_source") or ""))]
    rows = sorted(rows, key=SORTS.get(sort, SORTS["asset_id"]), reverse=desc)
    return {"total": len(rows), "offset": offset, "limit": limit, "packs": rows[offset:offset + limit]}


def summary() -> dict[str, Any]:
    ps = packs()
    by = {d: 0 for d in ("REUSE", "REPURPOSE", "RECYCLE", "INSPECT", "NO_DECISION")}
    for p in ps:
        by[p["disposition"]] = by.get(p["disposition"], 0) + 1
    second = [p for p in ps if p["disposition"] in SECOND]
    routed = sum(p.get("net_value") or 0 for p in second) + sum(p.get("recycle_value") or 0 for p in ps if p not in second)
    recycle_all = sum(p.get("recycle_value") or 0 for p in ps)
    kwh = sum(p["pack_kwh"] * (p["soh"] or 0) / 100 for p in second if p.get("pack_kwh"))
    return {"n": len(ps), "by_disposition": by, "net_value_routed_usd": routed, "net_value_recycle_all_usd": recycle_all,
            "value_vs_recycle_all_usd": routed - recycle_all, "kwh_redeployed": kwh,
            "funnel": {"total": len(ps), "data_quality_ready": sum(1 for p in ps if p.get("readiness") and p["readiness"] != "NOT_READY"),
                       "gate_pass": sum(1 for p in ps if p.get("gate") == "Pass"),
                       "state_ok": sum(1 for p in ps if p.get("gate") == "Pass" and p.get("soh") is not None),
                       "second_life_chosen": len(second)},
            "provenance": "modelled from SYNTHETIC data; placeholder cost inputs"}


def _stored(asset_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with db.read() as con:
        row = con.execute("SELECT report_json, disposition FROM fleet_reports WHERE asset_id = ? AND telemetry_source = 'dense' "
                          "ORDER BY generated_utc DESC LIMIT 1", [asset_id]).fetchone()
        reg = _registry(con).get(asset_id)
    if not row or not row[0] or reg is None:
        raise NotFound(f"no fleet report for {asset_id!r} (run POST /api/fleet/refresh)")
    return json.loads(row[0]), {**reg, "_disposition": row[1]}


def battery(asset_id: str) -> dict[str, Any]:
    report, reg = _stored(asset_id)
    return {"asset_id": asset_id, "registry": {k: v for k, v in reg.items() if not k.startswith("_")},
            "disposition": reg["_disposition"], "report": report, "insight": report.get("insight")}


def history(asset_id: str) -> list[dict[str, Any]]:
    with db.read() as con:
        df = con.execute("SELECT * FROM pack_history WHERE asset_id = ? ORDER BY assessment_date", [asset_id]).df()
    if df.empty:
        raise NotFound(f"no capacity tests for {asset_id!r}")
    return db.records(df)


def battery_passport(asset_id: str) -> dict[str, Any]:
    with db.read() as con:
        bundle = bridge.bundle_from_database(con, asset_id, "dense")
    report, reg = _stored(asset_id)
    labels = DECISION_MAP["labels"]
    return passport(report, bundle.meta, bundle.telemetry, {"code": reg["_disposition"], "label": labels.get(reg["_disposition"])},
                    report.get("insight"))


def whatif(asset_id: str, overrides: dict[str, Any], region: str | None) -> dict[str, Any]:
    report, _ = _stored(asset_id)
    o = {**overrides, **({"region": region} if region else {})}
    out = reroute(report, o)
    if out is None:
        return {"asset_id": asset_id, "rerouted": False, "decision": report["decision"],
                "reason": "the engine stopped before the economics stage"}
    return {"asset_id": asset_id, "rerouted": True, "engine_decision": report["decision"], **out}


def plan(limits: dict[str, dict[str, float]]) -> dict[str, Any]:
    ps = packs()
    inp = [{"asset_id": p["asset_id"], "eligible": p["disposition"] in SECOND, "options": p.get("options") or {},
            "recycle": p.get("recycle_value") or 0.0,
            "kwh": (p.get("pack_kwh") or 0) * (p.get("soh") or 0) / 100} for p in ps]
    return assign(inp, limits)


def refresh() -> dict[str, Any]:
    """Assess every pack and rewrite fleet_reports (dense) in one connection, one transaction."""
    rows = []
    with db.write() as con:
        reg = _registry(con)
        for aid in sorted(reg):
            try:
                b = bridge.bundle_from_database(con, aid, "dense")
                r = assess(b)
                ins = insight_for(r, b)
                d = disposition(r["decision"], (r.get("recommendation") or {}).get("application"))
                rr = {**r, "insight": ins}
                c = compact(aid, reg[aid], rr, d)
                rows.append([aid, datetime.now(UTC), "full", "dense", r["decision"], d, c["soh"],
                             (c["rul"] or {}).get("median"), c["net_value"], ins["confidence"]["level"],
                             reg[aid].get("lifecycle_status"), None, None, json.dumps(rr, default=str)])
            except Exception as exc:                      # reported per pack, never hidden
                rows.append([aid, datetime.now(UTC), "error", "dense", f"ERROR: {exc}", "NO_DECISION", None, None, None, None,
                             reg[aid].get("lifecycle_status"), None, str(exc), None])
        con.execute("BEGIN TRANSACTION")
        con.execute("DELETE FROM fleet_reports WHERE telemetry_source = 'dense'")
        con.executemany("INSERT INTO fleet_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("COMMIT")
    return {"refreshed": len(rows), "errors": sum(1 for r in rows if r[2] == "error")}


def meta() -> dict[str, Any]:
    with db.read() as con:
        tables = [t for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' "
                                            "AND table_type='BASE TABLE' ORDER BY 1").fetchall()]
        counts = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        n = counts.get("battery_registry")
        # text in SQL: fetching a TIMESTAMPTZ scalar would need pytz, which the platform does not install
        gen = con.execute("SELECT CAST(max(generated_utc) AS VARCHAR) FROM fleet_reports").fetchone()[0] if "fleet_reports" in counts else None
    mtime = datetime.fromtimestamp(os.path.getmtime(settings.DB_PATH), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"db_generated_utc": str(gen) if gen else None, "db_mtime": mtime, "n_assets": n, "table_counts": counts,
            "engine_version": ml_version}


def _hist(sql: str, limit: int) -> list[dict[str, Any]]:
    with db.read() as con:
        try:
            return db.records(con.execute(sql + " LIMIT ?", [limit]).df())
        except Exception:
            return []


def history_assessments(limit: int = 200):
    return _hist("SELECT id, created_utc, battery_id, engine, decision, readiness, gate, soh_pct FROM assessments ORDER BY created_utc DESC", limit)


def history_suggestions(limit: int = 200):
    return _hist("SELECT id, created_utc, battery_id, assessment_id, engine, status, top_application FROM ml_suggestions ORDER BY created_utc DESC", limit)


def history_runs(limit: int = 200):
    return _hist("SELECT run_id, any_value(source) AS source, any_value(asset_id) AS asset_id, any_value(data_class) AS data_class, "
                 "count(*) AS rows, min(logged_at) AS started, date_diff('second', min(logged_at), max(logged_at)) AS duration_s, "
                 "min(voltage_v) AS min_voltage_v, max(voltage_v) AS max_voltage_v FROM test_run_log GROUP BY run_id ORDER BY started DESC", limit)
