"""Physics projection below the ML training range.

Model, in "equivalent reference cycles" m (cycles at the ML training conditions):

    SOH_cyc(m) = SOH0 * [ (1 + eps) * exp(-beta * m) - eps * exp(delta * m) ]      (double exponential)
    m(n)       = n * S_T * S_DoD * S_C                                               (stress scaling)
    S_T        = exp( (Ea / R) * (1/T_ref - 1/T_cell) ),  T_cell = T_amb + rise * C
    S_DoD      = (DoD / DoD_ref) ** k_dod
    S_C        = exp( c_coef * (C - C_ref) / (R * T_cell) )
    SOH(t)     = SOH_cyc(m(t)) - k_cal * S_Tcal * sqrt(t_years)                      (calendar term)

Continuity with the ML layer (the hand-over):
  * the curve starts at SOH0 (latest measured capacity / rated) and
  * at reference conditions it reaches 80 % SOH exactly at the ML-predicted RUL m*. beta is
    solved for that; delta = kappa / m*. So inside the training range the physics reproduces the
    ML prediction; everything else (other workloads, below 80 %) is projection.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from scipy.optimize import brentq

from revive_ml.config import load
from revive_ml.provenance import PROJECTED_LABEL, tag

EOL_REF = 0.80


@dataclass(frozen=True)
class Params:
    activation_energy_j_mol: float
    c_rate_coefficient_j_mol: float
    k_dod: float
    cell_temperature_rise_c_per_c_rate: float
    calendar_loss_per_sqrt_year: float
    calendar_activation_energy_j_mol: float
    knee_epsilon: float
    knee_kappa: float

    @classmethod
    def nominal(cls) -> Params:
        p = load("physics.yaml")["parameters"]
        return cls(**{k: float(v["nominal"]) for k, v in p.items()})

    def knee(self) -> Params:
        k = load("physics.yaml")["knee_scenario"]
        return replace(self, knee_epsilon=float(k["knee_epsilon"]), knee_kappa=float(k["knee_kappa"]))


def _ref() -> dict[str, float]:
    return load("physics.yaml")["reference"]


R = 8.314


def stress_factor(p: Params, workload: dict[str, Any]) -> float:
    """Equivalent reference cycles per real cycle under the workload."""
    ref = _ref()
    t_ref = ref["temperature_c"] + 273.15 + p.cell_temperature_rise_c_per_c_rate * ref["c_rate"]
    t_cell = workload["ambient_c"] + 273.15 + p.cell_temperature_rise_c_per_c_rate * workload["c_rate"]
    s_t = np.exp(p.activation_energy_j_mol / R * (1 / t_ref - 1 / t_cell))
    s_dod = (workload["daily_dod"] / ref["daily_dod"]) ** p.k_dod
    s_c = np.exp(p.c_rate_coefficient_j_mol * (workload["c_rate"] - ref["c_rate"]) / (R * t_cell))
    return float(s_t * s_dod * s_c)


def solve_beta(soh0: float, m_star: float, eps: float, delta: float, target_soh: float = EOL_REF) -> float:
    """beta such that SOH_cyc(m*) = target_soh (0.80 by default) at reference conditions."""
    target = target_soh / soh0

    def f(b: float) -> float:
        return (1 + eps) * np.exp(-b * m_star) - eps * np.exp(delta * m_star) - target
    if f(0.0) <= 0:  # the knee term alone already crosses 80 %: no ageing needed from beta
        return 0.0
    return float(brentq(f, 0.0, 50.0 / m_star))


def soh_cycle(m: np.ndarray, soh0: float, beta: float, eps: float, delta: float) -> np.ndarray:
    return soh0 * ((1 + eps) * np.exp(-beta * m) - eps * np.exp(delta * m))


def trajectory(soh0: float, rul_ref: float, workload: dict[str, Any], p: Params,
               years: np.ndarray, target_soh: float = EOL_REF, calendar: bool = True) -> np.ndarray:
    """SOH (fraction) at the given times under a workload.

    rul_ref: reference cycles at which the cycle term reaches target_soh (the ML anchor).
    """
    rul_ref = max(rul_ref, 1.0)
    delta = p.knee_kappa / rul_ref
    beta = solve_beta(soh0, rul_ref, p.knee_epsilon, delta, target_soh)
    n = years * 365.0 * workload["cycles_per_day"]
    m = n * stress_factor(p, workload)
    soh = soh_cycle(m, soh0, beta, p.knee_epsilon, delta)
    if not calendar:
        return np.clip(soh, 0.0, 1.2)
    t_cell = workload["ambient_c"] + 273.15
    s_cal = np.exp(p.calendar_activation_energy_j_mol / R * (1 / 298.15 - 1 / t_cell))
    soh = soh - p.calendar_loss_per_sqrt_year * s_cal * np.sqrt(years)
    return np.clip(soh, 0.0, 1.2)


def years_to(soh_traj: np.ndarray, years: np.ndarray, threshold: float) -> float | None:
    below = np.flatnonzero(soh_traj < threshold)
    if below.size == 0:
        return None  # not reached within the horizon
    i = below[0]
    if i == 0:
        return 0.0
    y0, y1, s0, s1 = years[i - 1], years[i], soh_traj[i - 1], soh_traj[i]
    return float(y0 + (s0 - threshold) * (y1 - y0) / (s0 - s1))


def sample_params(n: int, seed: int) -> list[Params]:
    cfg = load("physics.yaml")["parameters"]
    rng = np.random.default_rng(seed)
    cols: dict[str, np.ndarray] = {}
    for k, v in cfg.items():
        pr = v["prior"]
        if pr["dist"] == "normal":
            cols[k] = np.clip(rng.normal(pr["mean"], pr["sd"], n), pr["low"], pr["high"])
        elif pr["dist"] == "uniform":
            cols[k] = rng.uniform(pr["low"], pr["high"], n)
        elif pr["dist"] == "loguniform":
            cols[k] = np.exp(rng.uniform(np.log(pr["low"]), np.log(pr["high"]), n))
        else:
            raise ValueError(f"unknown prior {pr['dist']}")
    return [Params(**{k: float(cols[k][i]) for k in cols}) for i in range(n)]


def project(soh0_pct: float, rul_ref: dict[str, float], workload: dict[str, Any],
            ml_coverage: float | None = None, target_soh: float = EOL_REF) -> dict[str, Any]:
    """Projection for one workload: central path, ML band, Monte Carlo band and knee scenario.

    rul_ref: {"point", "lower", "upper"} remaining reference cycles from the ML layer.
    """
    cfg = load("physics.yaml")
    hy, spy = cfg["projection"]["horizon_years"], cfg["projection"]["steps_per_year"]
    years = np.linspace(0, hy, hy * spy + 1)
    soh0 = soh0_pct / 100.0
    p0 = Params.nominal()
    def traj(rul: float, q: Params) -> np.ndarray:
        return trajectory(soh0, rul, workload, q, years, target_soh)

    central = traj(rul_ref["point"], p0)
    ml_lo = traj(rul_ref["lower"], p0)  # shorter life
    ml_hi = traj(rul_ref["upper"], p0)
    knee = traj(rul_ref["point"], p0.knee())
    mc = cfg["monte_carlo"]
    draws = np.array([traj(rul_ref["point"], q) for q in sample_params(mc["n_draws"], mc["seed"])])
    q_lo, q_hi = np.quantile(draws, mc["band"], axis=0)
    thr = workload["min_soh_pct"] / 100.0
    yearly = np.arange(0, len(years), spy)
    points = [{
        "year": int(round(years[i])),
        "soh": tag(100 * central[i], "modelled", "%", note=PROJECTED_LABEL),
        "ml_band": {"provenance": "modelled", "label": PROJECTED_LABEL,
                    "values": [round(100 * ml_lo[i], 3), round(100 * ml_hi[i], 3)]},
        "mc_band": {"provenance": "assumed", "label": PROJECTED_LABEL,
                    "values": [round(100 * q_lo[i], 3), round(100 * q_hi[i], 3)]},
        "knee_scenario": tag(100 * knee[i], "modelled", "%", note=PROJECTED_LABEL),
    } for i in yearly]
    life = {
        "central": years_to(central, years, thr),
        "ml_conservative": years_to(ml_lo, years, thr),
        "ml_optimistic": years_to(ml_hi, years, thr),
        "mc_p05": years_to(q_lo, years, thr),
        "mc_p95": years_to(q_hi, years, thr),
        "knee_scenario": years_to(knee, years, thr),
    }
    finite = [v for k, v in life.items() if k in ("ml_conservative", "mc_p05") and v is not None]
    conservative = min(finite) if finite else float(hy)  # both beyond the horizon -> horizon
    return {
        "label": PROJECTED_LABEL,
        "stress_factor_nominal": tag(stress_factor(p0, workload), "modelled",
                                     note="equivalent reference cycles per real cycle"),
        "years_to_application_limit": {
            k: tag(v, "modelled", "years", note=PROJECTED_LABEL + ("; beyond horizon" if v is None else ""))
            for k, v in life.items()},
        "conservative_years": tag(conservative, "modelled", "years",
                                  note="min of ML-lower-bound path and Monte Carlo 5th percentile"),
        "bands": {
            "ml_interval": f"from the CV+ RUL interval (measured coverage "
                           f"{ml_coverage if ml_coverage is not None else 'n/a'} on held-out LFP cells); "
                           "nominal physics parameters",
            "monte_carlo": "assumption-conditional: 5th-95th percentile over the physics-parameter priors "
                           "in configs/physics.yaml with the ML point estimate; NOT a measured interval",
        },
        "points": points,
    }
