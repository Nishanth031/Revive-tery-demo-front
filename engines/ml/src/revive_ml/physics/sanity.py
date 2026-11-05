"""Sanity checks of the physics layer against the published trends it is built from.

Honest scope: the temperature and C-rate dependence follow Wang et al. (2011)'s Arrhenius form
by construction, so these checks confirm the implementation and show the resulting magnitudes;
they are not independent validation. The DoD check confirms the projection never gives less
charge throughput at shallower cycling (charge-throughput equivalence, k_dod = 1, is the lower
bound; Naumann et al. 2020 report additional benefit at lower depth for LFP).
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from revive_ml.paths import REPORTS_DIR
from revive_ml.physics.fade import EOL_REF, Params, sample_params, stress_factor, trajectory, years_to


def _life_cycles(workload: dict[str, Any], p: Params, soh0: float = 1.0, rul_ref: float = 1000.0) -> float:
    """Cycles to 80 % SOH, cycle ageing only (no calendar term)."""
    w = {**workload, "cycles_per_day": 1.0}
    years = np.linspace(0, 60, 60 * 365 + 1)
    tr = trajectory(soh0, rul_ref, w, p, years, calendar=False)
    y = years_to(tr, years, EOL_REF)
    return float("inf") if y is None else y * 365.0


def _table(keys: list[float], values: list[float]) -> dict[str, float]:
    return {str(k): round(v, 0) for k, v in zip(keys, values, strict=True)}


def run(write: bool = True) -> dict[str, Any]:
    p = Params.nominal()
    base = {"daily_dod": 1.0, "ambient_c": 25.0, "c_rate": 1.0}
    checks: dict[str, Any] = {}

    # 1. continuity: at reference conditions the cycle term reaches 80 % at the ML RUL
    ref = {"daily_dod": 1.0, "ambient_c": 30.0, "c_rate": 4.0}
    cont = []
    for soh0, rul in [(0.95, 400.0), (0.90, 150.0), (0.99, 1500.0)]:
        life = _life_cycles(ref, p, soh0, rul)
        cont.append({"soh0": soh0, "ml_rul_ref": rul, "physics_cycles_to_80": round(life, 1),
                     "pass": bool(abs(life - rul) / rul < 0.01)})
    checks["continuity_at_reference"] = {"cases": cont, "pass": all(c["pass"] for c in cont)}
    t0 = trajectory(0.93, 500.0, {**ref, "cycles_per_day": 1.0}, p, np.array([0.0]))
    checks["starts_at_measured_soh"] = {"soh_at_t0": float(t0[0]), "pass": bool(abs(t0[0] - 0.93) < 1e-9)}

    # 2. temperature: life falls with temperature; 25 -> 45 degC ratio follows Ea
    temps = [15.0, 25.0, 35.0, 45.0]
    lives = [_life_cycles({**base, "ambient_c": t}, p) for t in temps]
    ratio = lives[1] / lives[3]
    bounds = []
    for ea in (20000.0, 45000.0):
        q = Params(**{**p.__dict__, "activation_energy_j_mol": ea})
        bounds.append(_life_cycles({**base, "ambient_c": 25}, q) / _life_cycles({**base, "ambient_c": 45}, q))
    checks["temperature"] = {
        "cycles_to_80_by_ambient_c": _table(temps, lives),
        "life_ratio_25_vs_45c": round(ratio, 3),
        "ratio_range_over_Ea_prior": [round(min(bounds), 3), round(max(bounds), 3)],
        "ten_degree_doubling_rule_would_give": 4.0,
        "reference": "wang2011 (Ea = 31.7 kJ/mol)",
        "pass": bool(np.all(np.diff(lives) < 0) and min(bounds) <= ratio <= max(bounds)),
    }

    # 3. depth of discharge: cycle life rises at shallower DoD, throughput never falls
    dods = [0.2, 0.5, 0.8, 1.0]
    lives = [_life_cycles({**base, "daily_dod": d}, p) for d in dods]
    thr = [n * d for n, d in zip(lives, dods, strict=True)]
    r50 = lives[1] / lives[3]
    checks["depth_of_discharge"] = {
        "cycles_to_80_by_dod": _table(dods, lives),
        "full_equivalent_cycles_by_dod": _table(dods, thr),
        "life_ratio_50_vs_100": round(r50, 3),
        "expected_range_from_k_dod_prior": [2.0, round(2 ** 1.5, 3)],
        "reference": "charge-throughput equivalence (k=1) as lower bound; naumann2020 (qualitative)",
        "pass": bool(np.all(np.diff(lives) < 0) and np.all(np.diff(thr) <= 1e-6) and 2.0 <= r50 <= 2 ** 1.5),
    }

    # 4. C-rate: life falls with C-rate
    crs = [0.2, 0.5, 1.0, 2.0, 4.0]
    lives = [_life_cycles({**base, "c_rate": c}, p) for c in crs]
    checks["c_rate"] = {"cycles_to_80_by_c_rate": _table(crs, lives),
                        "reference": "wang2011 (370.3 J/mol per C)",
                        "pass": bool(np.all(np.diff(lives) < 0))}

    # 5. knee scenario no later than base; Monte Carlo band brackets the central path
    w = {**base, "cycles_per_day": 1.0}
    years = np.linspace(0, 20, 241)
    central = trajectory(0.92, 400.0, w, p, years)
    knee = trajectory(0.92, 400.0, w, p.knee(), years)
    draws = np.array([trajectory(0.92, 400.0, w, q, years) for q in sample_params(300, 0)])
    lo, hi = np.quantile(draws, [0.05, 0.95], axis=0)
    inside = float(np.mean((central >= lo - 1e-9) & (central <= hi + 1e-9)))
    knee_ok = (years_to(knee, years, 0.6) or 99.0) <= (years_to(central, years, 0.6) or 99.0)
    checks["knee_and_band"] = {"knee_not_later_than_base": bool(knee_ok),
                               "band_brackets_central_fraction": round(inside, 3),
                               "pass": bool(knee_ok and inside >= 0.95)}
    examples = {
        "residential_25c_0.3c_0.8dod": round(stress_factor(p, {"ambient_c": 25, "c_rate": 0.3,
                                                                "daily_dod": 0.8}), 4),
        "reference_30c_4c_1.0dod": round(stress_factor(p, {"ambient_c": 30, "c_rate": 4.0,
                                                           "daily_dod": 1.0}), 4),
    }
    out = {
        "provenance": "modelled",
        "note": "All projection parameters are assumed (configs/physics.yaml). Temperature and C-rate trends "
                "follow wang2011 by construction; these checks verify the implementation and magnitudes, "
                "they are not independent validation against measured second-life data.",
        "all_pass": all(c["pass"] for c in checks.values()),
        "checks": checks,
        "stress_factor_examples": examples,
    }
    if write:
        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "physics_sanity.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
