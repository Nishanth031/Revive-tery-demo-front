// Physics projection below the ML training range (port of revive_ml/physics/fade.py).
//   SOH_cyc(m) = SOH0 * [ (1 + eps) * exp(-beta * m) - eps * exp(delta * m) ]   double exponential
//   m(n)       = n * S_T * S_DoD * S_C                                           stress scaling
//   SOH(t)     = SOH_cyc(m(t)) - k_cal * S_Tcal * sqrt(t_years)                  calendar term
// beta is solved so the curve reaches the ML anchor (80 % at the predicted RUL) at reference conditions.

import * as np from "../lib/np.js";
import { tag, PROJECTED_LABEL } from "../lib/provenance.js";

export const EOL_REF = 0.80;
const R = 8.314;

export function nominalParams(physics) {
  return Object.fromEntries(Object.entries(physics.parameters).map(([k, v]) => [k, Number(v.nominal)]));
}
export function kneeParams(physics, p) {
  return { ...p, knee_epsilon: physics.knee_scenario.knee_epsilon, knee_kappa: physics.knee_scenario.knee_kappa };
}
export function drawParams(mcDraws) {
  return mcDraws.rows.map((row) => Object.fromEntries(mcDraws.keys.map((k, j) => [k, row[j]])));
}

export function stressFactor(physics, p, w) {
  const ref = physics.reference;
  const tRef = ref.temperature_c + 273.15 + p.cell_temperature_rise_c_per_c_rate * ref.c_rate;
  const tCell = w.ambient_c + 273.15 + p.cell_temperature_rise_c_per_c_rate * w.c_rate;
  const sT = Math.exp(p.activation_energy_j_mol / R * (1 / tRef - 1 / tCell));
  const sDod = (w.daily_dod / ref.daily_dod) ** p.k_dod;
  const sC = Math.exp(p.c_rate_coefficient_j_mol * (w.c_rate - ref.c_rate) / (R * tCell));
  return sT * sDod * sC;
}

export function solveBeta(soh0, mStar, eps, delta, targetSoh = EOL_REF) {
  const target = targetSoh / soh0;
  const fn = (b) => (1 + eps) * Math.exp(-b * mStar) - eps * Math.exp(delta * mStar) - target;
  if (fn(0.0) <= 0) return 0.0;
  return np.brentq(fn, 0.0, 50.0 / mStar);
}

/** SOH (fraction) over `years` under a workload; rulRef = reference cycles at which the cycle term reaches targetSoh */
export function trajectory(physics, soh0, rulRef, w, p, years, targetSoh = EOL_REF, calendar = true) {
  rulRef = Math.max(rulRef, 1.0);
  const delta = p.knee_kappa / rulRef;
  const beta = solveBeta(soh0, rulRef, p.knee_epsilon, delta, targetSoh);
  const sf = stressFactor(physics, p, w);
  const sCal = Math.exp(p.calendar_activation_energy_j_mol / R * (1 / 298.15 - 1 / (w.ambient_c + 273.15)));
  const out = new Float64Array(years.length);
  for (let i = 0; i < years.length; i++) {
    const m = years[i] * 365.0 * w.cycles_per_day * sf;
    let s = soh0 * ((1 + p.knee_epsilon) * Math.exp(-beta * m) - p.knee_epsilon * Math.exp(delta * m));
    if (calendar) s -= p.calendar_loss_per_sqrt_year * sCal * Math.sqrt(years[i]);
    out[i] = np.clip(s, 0.0, 1.2);
  }
  return out;
}

export function yearsTo(traj, years, threshold) {
  let i = -1;
  for (let k = 0; k < traj.length; k++) if (traj[k] < threshold) { i = k; break; }
  if (i < 0) return null;
  if (i === 0) return 0.0;
  const y0 = years[i - 1], y1 = years[i], s0 = traj[i - 1], s1 = traj[i];
  return y0 + (s0 - threshold) * (y1 - y0) / (s0 - s1);
}

export function projectionYears(physics) {
  const { horizon_years: hy, steps_per_year: spy } = physics.projection;
  return np.linspace(0, hy, hy * spy + 1);
}

/** central path, ML band, Monte Carlo band and knee scenario for one workload */
export function project(physics, mcParams, soh0Pct, rulRef, w, mlCoverage = null, targetSoh = EOL_REF) {
  const { horizon_years: hy, steps_per_year: spy } = physics.projection;
  const years = projectionYears(physics);
  const soh0 = soh0Pct / 100.0;
  const p0 = nominalParams(physics);
  const traj = (rul, q) => trajectory(physics, soh0, rul, w, q, years, targetSoh);
  const central = traj(rulRef.point, p0);
  const mlLo = traj(rulRef.lower, p0), mlHi = traj(rulRef.upper, p0);
  const knee = traj(rulRef.point, kneeParams(physics, p0));
  const draws = mcParams.map((q) => traj(rulRef.point, q));
  const [bLo, bHi] = physics.monte_carlo.band;
  const qLo = new Float64Array(years.length), qHi = new Float64Array(years.length);
  const col = new Float64Array(draws.length);
  for (let i = 0; i < years.length; i++) {
    for (let d = 0; d < draws.length; d++) col[d] = draws[d][i];
    qLo[i] = np.quantile(col, bLo); qHi[i] = np.quantile(col, bHi);
  }
  const thr = w.min_soh_pct / 100.0;
  const points = [];
  for (let i = 0; i < years.length; i += spy) {
    points.push({
      year: Math.round(years[i]),
      soh: tag(100 * central[i], "modelled", "%", PROJECTED_LABEL),
      ml_band: { provenance: "modelled", label: PROJECTED_LABEL, values: [np.pyRound(100 * mlLo[i], 3), np.pyRound(100 * mlHi[i], 3)] },
      mc_band: { provenance: "assumed", label: PROJECTED_LABEL, values: [np.pyRound(100 * qLo[i], 3), np.pyRound(100 * qHi[i], 3)] },
      knee_scenario: tag(100 * knee[i], "modelled", "%", PROJECTED_LABEL),
    });
  }
  const life = {
    central: yearsTo(central, years, thr), ml_conservative: yearsTo(mlLo, years, thr), ml_optimistic: yearsTo(mlHi, years, thr),
    mc_p05: yearsTo(qLo, years, thr), mc_p95: yearsTo(qHi, years, thr), knee_scenario: yearsTo(knee, years, thr),
  };
  const finite = ["ml_conservative", "mc_p05"].map((k) => life[k]).filter((v) => v !== null);
  const conservative = finite.length ? Math.min(...finite) : hy;
  return {
    label: PROJECTED_LABEL,
    stress_factor_nominal: tag(stressFactor(physics, p0, w), "modelled", null, "equivalent reference cycles per real cycle"),
    years_to_application_limit: Object.fromEntries(Object.entries(life).map(([k, v]) =>
      [k, tag(v, "modelled", "years", PROJECTED_LABEL + (v === null ? "; beyond horizon" : ""))])),
    conservative_years: tag(conservative, "modelled", "years", "min of ML-lower-bound path and Monte Carlo 5th percentile"),
    bands: {
      ml_interval: `from the CV+ RUL interval (measured coverage ${mlCoverage !== null ? mlCoverage : "n/a"} on held-out LFP cells); nominal physics parameters`,
      monte_carlo: "assumption-conditional: 5th-95th percentile over the physics-parameter priors in configs/physics.yaml with the ML point estimate; NOT a measured interval",
    },
    points,
    series: { years: Array.from(years), central: Array.from(central), ml_lower: Array.from(mlLo), ml_upper: Array.from(mlHi),
      mc_p05: Array.from(qLo), mc_p95: Array.from(qHi), knee: Array.from(knee) },
  };
}
