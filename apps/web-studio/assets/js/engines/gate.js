// Safety gate (port of revive_ml/gate): deterministic chemistry limits -> Reject; an IsolationForest
// out-of-distribution / sensor-noise filter -> Quarantine; otherwise Pass. "UL 1974-style triage": a
// screening step, not UL certification or a safety approval.

import * as np from "../lib/np.js";
import { tag, dataProvenanceTag, pct0 } from "../lib/provenance.js";
import { buildContext } from "./dq.js";
import { sortByDate } from "./contract.js";

// ---------------------------------------------------------------- a. limits
export function checkLimits(bundle, cfg) {
  const meta = bundle.meta;
  const lim = cfg.chemistries[meta.chemistry];
  const common = cfg.common;
  const prov = dataProvenanceTag(meta.data_provenance);
  const tel = bundle.tel;
  const series = meta.series_cells;
  const breaches = [], notes = [];
  if (series) {
    const vc = Float64Array.from(tel.voltage_v, (v) => v / series);
    for (const key of ["cell_v_min", "cell_v_max"]) {
      const hit = Array.from(vc).filter((v) => Number.isFinite(v) && (key === "cell_v_min" ? v < lim[key].value : v > lim[key].value));
      if (hit.length >= common.min_rows_beyond_limit) {
        const worst = key === "cell_v_min" ? Math.min(...hit) : Math.max(...hit);
        breaches.push({ limit: key, rows: hit.length, observed: tag(worst, prov, "V/cell", "pack voltage / series"),
          threshold: tag(lim[key].value, "assumed", "V/cell", null, { source: lim[key].source }) });
      }
    }
    notes.push("voltage limits applied to the pack-average cell; weak cells can be hidden");
  } else notes.push("series count unknown: cell voltage limits not applied");
  for (const key of ["temp_max_c", "temp_min_c"]) {
    const hit = Array.from(tel.temperature_c).filter((t) => Number.isFinite(t) && (key === "temp_max_c" ? t > lim[key].value : t < lim[key].value));
    if (hit.length >= common.min_rows_beyond_limit) {
      const worst = key === "temp_max_c" ? Math.max(...hit) : Math.min(...hit);
      breaches.push({ limit: key, rows: hit.length, observed: tag(worst, prov, "degC"),
        threshold: tag(lim[key].value, "assumed", "degC", null, { source: lim[key].source }) });
    }
  }
  const rts = sortByDate(meta.resistance_tests);
  if (rts.length >= 2) {
    const ratio = rts[rts.length - 1].resistance_mohm / rts[0].resistance_mohm;
    const thr = common.resistance_ratio_reject.value;
    if (ratio >= thr) {
      breaches.push({ limit: "resistance_ratio", rows: 0,
        observed: tag(ratio, dataProvenanceTag(rts[rts.length - 1].provenance), null, "latest / earliest resistance test"),
        threshold: tag(thr, "assumed", null, null, { source: common.resistance_ratio_reject.source }) });
    }
  }
  const quarantineEvents = meta.safety_events
    .filter((e) => common.open_safety_event_severities_quarantine.includes(e.severity.toUpperCase()) && (e.status || "").toUpperCase() !== "CLOSED")
    .map((e) => ({ event_type: e.event_type, severity: e.severity, status: e.status }));
  return { breaches, open_safety_events: quarantineEvents, notes, chemistry: meta.chemistry };
}

// ---------------------------------------------------------------- b. window features
export const WINDOW = 20, STRIDE = 10, MIN_ROWS = 8;
export const FEATURES = ["v_level", "c_rate_rms", "resid_mad_mv", "resid_max_z", "resid_mean_t", "temp_slope_c_per_min", "temp_resid_z", "v_repeat_frac"];

const madOf = (a) => { if (!a.length) return 0.0; const m = np.median(a); return 1.4826 * np.median(a.map((v) => Math.abs(v - m))); };
const fin = (v) => (Number.isFinite(v) ? v : 0.0); // replace(inf, nan).fillna(0)

/** c_rate must be charge-positive. Returns one feature row (array) per window. */
export function windowFeatures(cellV, cRate, temp, tS, vMin, vMax, window = WINDOW, stride = STRIDE) {
  const n = cellV.length;
  if (n < MIN_ROWS) return [];
  const w = Math.min(window, n);
  const rows = [];
  for (let s = 0; s <= n - w; s += n > w ? stride : 1) {
    const e = s + w;
    const v = cellV.slice(s, e), c = cRate.slice(s, e), T = temp.slice(s, e), t = tS.slice(s, e);
    const dv = np.diff(v);
    const x0 = [], x1 = [], y = [];
    for (let k = 0; k < w - 1; k++) {
      let dt = t[k + 1] - t[k];
      if (!(dt > 0)) dt = NaN;
      const a = 0.5 * (c[k + 1] + c[k]) * dt / 3600.0, b = c[k + 1] - c[k];
      if (Number.isFinite(dv[k]) && Number.isFinite(a) && Number.isFinite(b)) { x0.push(a); x1.push(b); y.push(dv[k]); }
    }
    let resid;
    if (y.length >= 4) {
      const coef = np.lstsq2(x0, x1, y);
      resid = y.map((yy, k) => yy - (x0[k] * coef[0] + x1[k] * coef[1]));
    } else resid = Array.from(dv).filter(Number.isFinite);
    const mad = resid.length ? madOf(resid) : 0.0;
    const scale = mad + 1e-4;
    const tm = Array.from(t, (x) => (x - t[0]) / 60.0);
    const okT = [];
    for (let k = 0; k < w; k++) if (Number.isFinite(T[k]) && Number.isFinite(tm[k])) okT.push(k);
    let tempSlope = 0.0, tempZ = 0.0;
    if (okT.length >= 3) {
      const xs = okT.map((k) => tm[k]), ys = okT.map((k) => T[k]);
      if (Math.max(...xs) - Math.min(...xs) > 0) {
        const [p1, p0] = np.polyfit1(xs, ys);
        const rT = ys.map((yy, k) => yy - (p1 * xs[k] + p0));
        tempSlope = p1;
        tempZ = Math.max(...rT.map(Math.abs)) / (madOf(rT) + 0.1);
      }
    }
    let rep = 0;
    for (const d of dv) if (d === 0) rep++;
    rows.push([
      fin((np.nanmean(v) - vMin) / (vMax - vMin)),
      fin(Math.sqrt(np.nanmean(Array.from(c, (x) => x * x)))),
      fin(1e3 * mad),
      fin(resid.length ? Math.max(...resid.map(Math.abs)) / scale : 0.0),
      fin(resid.length > 2 ? np.mean(resid) / (np.std(resid) / Math.sqrt(resid.length) + 1e-4) : 0.0),
      fin(tempSlope),
      fin(tempZ),
      fin(dv.length ? rep / dv.length : NaN),
    ]);
  }
  return rows;
}

export function chemistryWindow(limitsCfg, chemistry) {
  const lim = limitsCfg.chemistries[chemistry];
  return [lim.cell_v_min.value, lim.cell_v_max.value];
}

export function bundleFeatures(bundle, rules, limitsCfg, convention = null) {
  const meta = bundle.meta;
  const ctx = buildContext(bundle, rules);
  const conv = convention || ctx.convention;
  const df = ctx.df;
  const sign = conv === "discharge_negative" ? 1.0 : -1.0;
  const series = meta.series_cells || 1;
  const [vmin, vmax] = chemistryWindow(limitsCfg, meta.chemistry);
  return windowFeatures(
    Float64Array.from(df.voltage_v, (v) => v / series),
    Float64Array.from(df.current_a, (i) => sign * i / meta.rated_capacity_ah),
    df.temperature_c, df.t, vmin, vmax,
  );
}

// ---------------------------------------------------------------- IsolationForest (exported from scikit-learn)
const FLAG_FRACTION = 0.10, ENVELOPE_WINDOWS = 2;

export class OODFilter {
  constructor(json) {
    this.family = json.family;
    this.features = json.features;
    this.logIdx = json.log_features.map((c) => json.features.indexOf(c));
    this.tIdx = json.features.indexOf("resid_mean_t");
    this.mean = json.scaler_mean; this.scale = json.scaler_scale;
    this.thrFlag = json.thr_flag; this.envLo = json.env_lo; this.envHi = json.env_hi;
    this.denominator = json.denominator; this.nTrees = json.n_trees;
    this.starts = np.decode(json.starts, "<i4"); this.feature = np.decode(json.feature, "<i2");
    this.value = np.decode(json.value, "<f8"); this.left = np.decode(json.left, "<i4"); this.right = np.decode(json.right, "<i4");
    this.trainingSummary = json.training_summary || {};
    this.validation = json.validation;
  }
  logSome(x) {
    const z = Float64Array.from(x);
    for (const j of this.logIdx) z[j] = Math.log1p(Math.abs(z[j]));
    const t = z[this.tIdx];
    z[this.tIdx] = np.sign(t) * Math.log1p(Math.abs(t));
    return z;
  }
  scoreOne(x) {
    const z = this.logSome(x);
    for (let j = 0; j < z.length; j++) z[j] = Math.fround((z[j] - this.mean[j]) / this.scale[j]); // the forest reads float32
    let depth = 0;
    const F = this.feature, L = this.left, R = this.right, V = this.value;
    for (let t = 0; t < this.nTrees; t++) {
      const off = this.starts[t];
      let i = 0;
      while (F[off + i] >= 0) i = z[F[off + i]] <= V[off + i] ? L[off + i] : R[off + i];
      depth += V[off + i];
    }
    return -(2.0 ** (-depth / this.denominator));
  }
  score(X) { return X.map((x) => this.scoreOne(x)); }
  outsideEnvelope(X) {
    return X.map((x) => { const z = this.logSome(x); return z.some((v, j) => this.envLo[j] > v || this.envHi[j] < v); });
  }
  decide(X) {
    if (X.length === 0) return { status: "unavailable", note: `fewer than ${MIN_ROWS} rows; no window to score` };
    const s = this.score(X);
    const flagged = s.map((v) => v < this.thrFlag);
    const outside = this.outsideEnvelope(X);
    const nFlag = flagged.filter(Boolean).length, nOut = outside.filter(Boolean).length;
    const frac = nFlag / X.length;
    const quarantine = frac > FLAG_FRACTION || nOut >= ENVELOPE_WINDOWS;
    const out = {
      status: quarantine ? "quarantine" : "pass", n_windows: X.length, n_flagged_windows: nFlag,
      n_outside_envelope_windows: nOut, flagged_fraction: tag(frac, "modelled"),
      rule: `quarantine if IsolationForest flags > ${pct0(FLAG_FRACTION)} of windows or >= ${ENVELOPE_WINDOWS} windows fall outside the training envelope`,
      description: "IsolationForest trained on healthy windows: an out-of-distribution and sensor-noise filter, not a fault detector",
      window_scores: s,
    };
    if (quarantine) {
      const worst = X[np.argmin(s)];
      out.reason = `telemetry outside the healthy-window distribution (${nFlag} of ${X.length} windows flagged)`;
      out.most_unusual_window = Object.fromEntries(FEATURES.map((k, j) => [k, tag(worst[j], "modelled")]));
    }
    return out;
  }
  assess(bundle, rules, limitsCfg) {
    const X = bundleFeatures(bundle, rules, limitsCfg);
    const out = this.decide(X);
    out.model_family = this.trainingSummary.family || "unknown";
    out.trained_on = this.trainingSummary.trained_on || "unknown";
    out.training_provenance = this.trainingSummary.provenance || "unknown";
    out.threshold_score = this.thrFlag;
    return out;
  }
}

/** packs (more than one cell) use the pack model; single cells use the measured-cell model */
export function familyFor(bundle) {
  const m = bundle.meta;
  return (m.series_cells || 1) > 1 || (m.parallel_cells || 1) > 1 ? "synthetic_packs" : "measured_cells";
}

export function evaluate(bundle, assets) {
  const cfg = assets.configs.limits;
  const lim = checkLimits(bundle, cfg);
  const out = { wording: cfg.wording, limits: lim };
  if (lim.breaches.length) {
    out.verdict = "Reject";
    out.reasons = lim.breaches.map((b) => `${b.limit} breached on ${b.rows} row(s)`);
    out.ood = { status: "not run: limits already rejected" };
    return out;
  }
  const model = assets.gates[familyFor(bundle)];
  const ood = model ? model.assess(bundle, assets.configs.dq_rules, cfg) : { status: "unavailable", note: "no trained OOD model" };
  out.ood = ood;
  const reasons = [];
  if (lim.open_safety_events.length) reasons.push(`${lim.open_safety_events.length} open high-severity safety event(s)`);
  if (ood.status === "quarantine") reasons.push(ood.reason);
  if (ood.status === "unavailable") reasons.push("OOD filter unavailable; cannot clear the battery for second life");
  if (reasons.length) { out.verdict = "Quarantine"; out.reasons = reasons; }
  else { out.verdict = "Pass"; out.reasons = ["no hard-limit breach; telemetry inside the healthy-window distribution"]; }
  return out;
}
