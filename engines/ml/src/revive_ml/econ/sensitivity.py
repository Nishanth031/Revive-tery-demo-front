"""Illustrative price-sensitivity sweep: where does the Second-Life vs Recycle decision flip?

Uses a clearly labelled SYNTHETIC reference battery per chemistry (60 kWh pack, SOH 85 %,
residential workload, conservative life from the nominal physics model). This is illustrative
sensitivity, not proof of anything about a real battery.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from revive_ml.config import load
from revive_ml.econ.router import recycle_value, second_life_value
from revive_ml.paths import REPORTS_DIR
from revive_ml.physics.fade import Params, trajectory, years_to

REF_PACK_KWH = 60.0
REF_SOH = 0.85
REF_RUL_REF = 400.0


def _reference_projection() -> tuple[dict[str, Any], list[float], float]:
    w = load("workloads.yaml")["workloads"]["residential_storage"]
    years = np.linspace(0, 20, 241)
    tr = trajectory(REF_SOH, REF_RUL_REF, w, Params.nominal(), years)
    life = years_to(tr, years, w["min_soh_pct"] / 100) or 20.0
    return w, [float(tr[i]) for i in range(0, 241, 12)], life


def sweep(write: bool = True) -> dict[str, Any]:
    cfg = load("economics.yaml")
    mults = cfg["sensitivity"]["price_multipliers"]
    vmults = cfg["sensitivity"]["value_per_kwh_multipliers"]
    w, soh_by_year, life = _reference_projection()
    out: dict[str, Any] = {
        "label": "ILLUSTRATIVE SENSITIVITY on a synthetic reference battery; "
                 "not a result about any real pack",
        "reference_battery": {"pack_kwh": REF_PACK_KWH, "soh_pct": 100 * REF_SOH,
                              "workload": "residential_storage", "projected_years": round(life, 2),
                              "provenance": "synthetic"},
        "chemistries": {},
    }
    for chem in ("LFP", "NMC", "NCA"):
        comp_status = cfg["recycling"]["composition_kg_per_kwh"][chem]["status"]
        res: dict[str, Any] = {"composition_status": comp_status, "grid": []}
        for vm in vmults:
            for m in mults:
                mult = {"nickel": m, "cobalt": m, "lithium": m}
                rec = recycle_value(chem, REF_PACK_KWH, cfg, mult)["net_usd"]
                sl = second_life_value(REF_PACK_KWH, REF_SOH, soh_by_year, life, w, rec, cfg, vm)["net_usd"]
                res["grid"].append({"metal_price_multiplier": m, "energy_value_multiplier": vm,
                                    "recycle_net_usd": round(rec, 0), "second_life_net_usd": round(sl, 0),
                                    "decision": "Second-Life" if sl > rec else "Recycle"})
        res["recycle_wins_at_metal_multipliers"] = {
            str(vm): [g["metal_price_multiplier"] for g in res["grid"]
                      if g["energy_value_multiplier"] == vm and g["decision"] == "Recycle"]
            for vm in vmults
        }
        res["provenance"] = "assumed"
        out["chemistries"][chem] = res
    out["note"] = ("All metal prices are scaled together (x current sourced prices). An empty list means "
                   "Second-Life wins across the whole swept range at that energy value. At very low metal "
                   "prices recycling has negative value, so Recycle can 'win' only because second life also "
                   "loses money (both options are then uneconomic). Cost inputs include PLACEHOLDERS.")
    if write:
        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "econ_sensitivity.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
