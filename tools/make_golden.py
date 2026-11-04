"""Write golden outputs from the Python engines, for the JavaScript parity tests (tests/*.test.mjs).

Run with the ML engine's Python:   ..\\revive-tery-ml\\.venv\\Scripts\\python.exe tools\\make_golden.py

Each case stores the exact input the browser will receive and the Python engine's output for it.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import types
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
ML, APP = ROOT / "revive-tery-ml", ROOT / "bulid X"
RELIFE = ROOT / "Hackathon project ev (3)" / "Hackathon project ev"
GOLD = WEB / "tests" / "golden"
sys.path[:0] = [str(ML / "src"), str(APP / "src")]

from revive_ml.contract import Bundle, SafetyEvent, load_bundle  # noqa: E402
from revive_ml.convert import convert_demo  # noqa: E402
from revive_ml.dq.inject import FAULTS, _copy  # noqa: E402
from revive_ml.econ.sensitivity import sweep  # noqa: E402
from revive_ml.physics.sanity import run as physics_sanity  # noqa: E402
from revive_ml.pipeline import assess  # noqa: E402
from revive_ml.synth import NMC_SPEC, make_clean_bundle  # noqa: E402


def clean(o):
    """JSON-safe: NaN -> None, numpy -> python, dates -> ISO."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.isoformat()
    return o


def bundle_json(b: Bundle) -> dict:
    tel = b.telemetry.copy()
    tel["timestamp_utc"] = tel["timestamp_utc"].map(lambda t: t.isoformat())
    rows = clean(tel.astype(object).where(tel.notna(), None).to_dict("records"))
    return {"metadata": json.loads(b.meta.model_dump_json()), "telemetry": rows,
            "ignored_columns": list(b.ignored_columns)}


def write(name: str, obj) -> None:
    path = GOLD / name
    path.write_text(json.dumps(clean(obj), separators=(",", ":")), encoding="utf-8")
    print(f"  wrote tests/golden/{name} ({path.stat().st_size / 1024:.0f} KB)")


def pipeline_cases() -> None:
    cases = {}
    with tempfile.TemporaryDirectory() as tmp:
        cases["demo_pack"] = load_bundle(convert_demo(WEB / "data" / "demo", Path(tmp) / "b"))
    cases["clean_lfp"] = load_bundle(ML / "examples" / "clean_synthetic_bundle")
    cases["clean_nmc"] = make_clean_bundle(NMC_SPEC, seed=3)
    base = make_clean_bundle(seed=3)
    # gate outcomes
    under = _copy(base)
    under.telemetry.loc[100, "voltage_v"] = 1.9 * under.meta.series_cells
    cases["gate_undervoltage"] = under
    rdouble = _copy(base)
    rt = rdouble.meta.resistance_tests
    rt[-1] = rt[-1].model_copy(update={"resistance_mohm": rt[0].resistance_mohm * 2.1})
    cases["gate_resistance_double"] = rdouble
    event = _copy(base)
    event.meta.safety_events = [SafetyEvent(timestamp_utc="2026-10-01T00:00:00Z", event_type="THERMAL",
                                            severity="HIGH", status="OPEN", provenance="synthetic")]
    cases["gate_open_event"] = event
    spiky = _copy(base)
    rng = np.random.default_rng(0)
    for k in rng.choice(len(spiky.telemetry), 4, replace=False):
        spiky.telemetry.loc[k, "voltage_v"] += 0.3 * spiky.meta.series_cells
    cases["gate_spiky"] = spiky
    # every injected data-quality fault
    for name, (inject, _det, _st) in FAULTS.items():
        cases[f"fault_{name}"] = inject(base, np.random.default_rng(3))
    out = {}
    for name, b in cases.items():
        report = assess(b)
        out[name] = {"bundle": bundle_json(b), "report": report}
        print(f"    {name:34s} -> {report['decision']}")
    write("pipeline_cases.json", out)


def lite_cases() -> None:
    from ml_analyzer_suggester import BatteryFileExtractor, BatterySpec, DuckDBSeeder, SecondLifeSuggester
    import ml_engine_bridge as bridge

    spec = BatterySpec(chemistry="LFP", series_cells=16, rated_capacity_ah=100)
    bspec = types.SimpleNamespace(chemistry="LFP", series_cells=16, parallel_cells=1, rated_capacity_ah=100.0,
                                  nominal_voltage_v=None)
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        seeder = DuckDBSeeder(Path(tmp) / "g.duckdb")
        ex = BatteryFileExtractor()
        for f in sorted((WEB / "data" / "samples").glob("[1-6]_*")):
            files = ex.extract(f)
            seeder.seed(files, "synthetic")
            mapping = {x.source: {"mapped": x.mapping, "unmapped": x.unmapped, "warnings": x.warnings,
                                  "rows": len(x.data)} for x in files}
            for bid in sorted({b for x in files for b in x.data["battery_id"].unique()}):
                rep = SecondLifeSuggester(seeder).generate_second_life_suggestion(bid, spec)
                rep.pop("generated_utc", None)
                entry = {"file": f.name, "mapping": mapping, "report": rep}
                try:
                    bundle = bridge.bundle_from_rows(seeder.load_battery(bid), bid, bspec, "golden")
                    entry["bundle"] = bundle_json(bundle)
                    entry["full_report"] = assess(bundle)
                except bridge.AdapterError as exc:
                    entry["adapter_error"] = str(exc)
                out[bid] = entry
                print(f"    {bid:22s} lite -> {rep['suggestion']['decision']}  | full: "
                      f"{entry.get('full_report', {}).get('decision', entry.get('adapter_error', '')[:60])}")
    write("lite_cases.json", out)


def bms_cases() -> None:
    import bms_engine as bms
    from esp32_sim import SimulatedESP32, SimulationSettings
    from test_bench import get_decision_for_ui

    cases = {}
    # 1. demo replay, as the virtual source does (discharge recorded negative)
    tel = pd.read_csv(WEB / "data" / "demo" / "telemetry.csv")
    asset = pd.read_csv(WEB / "data" / "demo" / "battery_asset.csv").set_index("field")["value"]
    hist = pd.read_csv(WEB / "data" / "demo" / "health_history.csv").sort_values("assessment_date")
    samples = [bms.Sample(timestamp=pd.Timestamp(r.timestamp_utc).timestamp(), voltage_v=r.pack_voltage_V,
                          current_a=r.pack_current_A, temperature_c=r.max_cell_temp_C,
                          reported_soc_pct=r.soc_pct, state=r.operating_state) for r in tel.itertuples()]
    eng = bms.BMSEngine(rated_capacity_ah=float(asset["nominal_capacity_Ah"]),
                        baseline_measured_ah=float(hist.iloc[-1]["measured_capacity_Ah"]),
                        baseline_date=str(hist.iloc[-1]["assessment_date"]), discharge_positive=False)
    readings = [eng.process(s) for s in samples]
    cases["demo_replay"] = {"settings": {"rated_capacity_ah": float(asset["nominal_capacity_Ah"]),
                                         "baseline_measured_ah": float(hist.iloc[-1]["measured_capacity_Ah"]),
                                         "baseline_date": str(hist.iloc[-1]["assessment_date"]),
                                         "discharge_positive": False},
                            "samples": [s.__dict__ for s in samples],
                            "readings": [{"soc_pct": r.soc_pct, "soh_live_pct": r.soh_live_pct, "soh_basis": r.soh_basis,
                                          "discharged_ah": r.discharged_ah, "delta_time_s": r.delta_time_s} for r in readings],
                            "decision": get_decision_for_ui(eng)}
    # 2. simulated ESP32 lines (with faults) parsed and processed exactly like hardware
    for name, faults in {"sim_clean": {}, "sim_faults": {300: "ds18b20", 330: "none", 600: "overvoltage",
                                                         620: "none", 900: "ina219", 930: "none"}}.items():
        sim = SimulatedESP32(SimulationSettings(true_capacity_ah=1.8, load_current_a=1.0, speed=60.0, seed=7),
                             start_epoch=0.0, paced=False)
        sim.open()
        lines, t = [], 0
        while not sim.complete and t < 8000:
            if t in faults:
                sim.set_fault(faults[t])
            line = sim.readline()
            if line:
                lines.append({"t": sim.clock(), "line": line.decode().strip()})
            t += 1
        eng = bms.BMSEngine(rated_capacity_ah=2.0, initial_soc_pct=100.0, cutoff_voltage_v=3.0, discharge_positive=True)
        stats = bms.SerialStats()
        out_r = []
        for item in lines:
            raw = item["line"].encode()
            if raw.startswith(b"#"):
                stats.record_message(raw, item["t"])
                out_r.append({"message": item["line"], "severity": bms.firmware_message_severity(item["line"])})
                continue
            s = bms.parse_telemetry_line(raw, item["t"])
            if s is None:
                out_r.append({"skipped": item["line"]})
                continue
            r = eng.process(s)
            out_r.append({"soc_pct": r.soc_pct, "soh_live_pct": r.soh_live_pct, "soh_basis": r.soh_basis,
                          "discharged_ah": r.discharged_ah, "temperature_c": s.temperature_c})
        cases[name] = {"settings": {"rated_capacity_ah": 2.0, "initial_soc_pct": 100.0, "cutoff_voltage_v": 3.0,
                                    "discharge_positive": True},
                       "lines": lines, "results": out_r, "decision": get_decision_for_ui(eng),
                       "fault_counts": stats.fault_counts}
        print(f"    {name}: {len(lines)} lines -> {cases[name]['decision']['use_case']}")
    write("bms_cases.json", cases)


def relife_cases() -> None:
    sys.path.insert(0, str(RELIFE))
    for mod in ("bms_engine", "models"):
        sys.modules.pop(mod, None)
    import bms_engine as relife  # the ReLife prototype's engine (same module name, different folder)
    import battery_details

    profiles = battery_details.seed_profiles()
    out = {"stress": [], "evaluate": [], "compat": []}
    picks = [profiles[0], profiles[3], profiles[-1]]
    for p in picks:
        for adapter in relife.ADAPTERS:
            ok, errors, warnings = relife.check_compatibility(p, adapter)
            out["compat"].append({"profile": p.id, "adapter": adapter.id, "ok": ok, "errors": errors,
                                  "warnings": warnings})
        for scenario in ("Normal", "Overcurrent", "Undervoltage", "Stale sensor"):
            out["evaluate"].append({"profile": p.id, "adapter": "V-HV-PACK", "scenario": scenario,
                                    "result": relife.evaluate(p, relife.ADAPTERS[-1], scenario)})
        for scenario in relife.SCENARIOS:
            for mode in ("Discharge", "Charge"):
                r = relife.stress_test(p, scenario, mode=mode)
                out["stress"].append({"profile": p.id, "scenario": scenario, "mode": mode,
                                      "result": r, "summary": relife.screening_summary(p, r)})
    write("relife_cases.json", out)
    sys.path.remove(str(RELIFE))


if __name__ == "__main__":
    GOLD.mkdir(parents=True, exist_ok=True)
    print("pipeline cases:"); pipeline_cases()
    print("lite analyzer cases:"); lite_cases()
    print("BMS engine cases:"); bms_cases()
    print("ReLife cases:"); relife_cases()
    write("econ_sensitivity.json", sweep(write=False))
    write("physics_sanity.json", physics_sanity(write=False))
    print("done")
