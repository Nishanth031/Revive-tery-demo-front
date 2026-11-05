// State estimate (port of revive_ml/state): measured SOH plus ML remaining-cycles with a CV+ interval.
// The model (HistGradientBoosting on Severson LFP field features, wrapped in MAPIE CV+) is exported from
// scikit-learn as plain trees; the export step checked this exact algorithm against scikit-learn + MAPIE.

import * as np from "../lib/np.js";
import { tag, dataProvenanceTag, g4 } from "../lib/provenance.js";
import { sortByDate } from "./contract.js";

export const EOL_FRACTION = 0.80;

/** the existing REVIVE-TERY routing rule, kept only for comparison */
export function ruleRoute(sohPct) {
  if (sohPct === null || sohPct === undefined) return "Insufficient data";
  if (sohPct > 80) return "Second-Life: stationary storage";
  if (sohPct >= 60) return "Second-Life: low-speed EV";
  return "Recycle";
}

// ---------------------------------------------------------------- field features
function slope(x, y) {
  const xs = [], ys = [];
  for (let i = 0; i < x.length; i++) if (Number.isFinite(x[i]) && Number.isFinite(y[i])) { xs.push(x[i]); ys.push(y[i]); }
  if (xs.length < 3 || Math.max(...xs) - Math.min(...xs) === 0) return 0.0;
  return np.polyfit1(xs, ys)[0];
}

export function windowRow(cycles, soh, ir, irFirst, tMean, tMax, kCycles) {
  if (!cycles.length) throw new Error("capacity tests need cycle counts to build the state features");
  const cmin = Math.min(...cycles), cmax = Math.max(...cycles);
  const half = cmin + (cmax - cmin) / 2;
  const first = cycles.map((c) => c <= half), second = cycles.map((c) => c >= half);
  const pick = (a, m) => a.filter((_, i) => m[i]);
  const sAll = slope(cycles, soh);
  const nf = first.filter(Boolean).length, ns = second.filter(Boolean).length;
  const accel = nf >= 2 && ns >= 2 ? slope(pick(cycles, second), pick(soh, second)) - slope(pick(cycles, first), pick(soh, first)) : 0.0;
  const irNow = ir !== null && ir.some(Number.isFinite) ? np.nanmedian(ir.slice(-5)) : NaN;
  return {
    soh: np.nanmedian(soh.slice(-5)),
    fade_slope_per_kcycle: -1000.0 * sAll,
    fade_accel_per_kcycle: -1000.0 * accel,
    ir_ratio: irFirst && Number.isFinite(irNow) ? irNow / irFirst : NaN,
    t_mean_c: tMean !== null ? np.nanmean(tMean) : NaN,
    t_max_c: tMax !== null ? np.nanmax(tMax) : NaN,
    cycles_so_far: kCycles,
  };
}

export function bundleFieldFeatures(bundle, excluded) {
  const meta = bundle.meta;
  const tests = sortByDate(meta.capacity_tests);
  const cyc = tests.map((t) => (t.cycle_count !== null && t.cycle_count !== undefined ? t.cycle_count : NaN));
  const soh = tests.map((t) => t.measured_capacity_ah / meta.rated_capacity_ah);
  const rts = sortByDate(meta.resistance_tests);
  const ir = rts.length && !excluded.has("resistance") ? rts.map((r) => r.resistance_mohm) : null;
  const irFirst = ir !== null ? ir[0] : null;
  const T = bundle.tel.temperature_c;
  const k = meta.cycle_count || np.nanmax(cyc);
  const m = cyc.map(Number.isFinite);
  const row = windowRow(cyc.filter((_, i) => m[i]), soh.filter((_, i) => m[i]), ir, irFirst, T, T, k);
  row.soh = soh[soh.length - 1]; // capacity and resistance tests are sparse: latest record, not a 5-point median
  if (ir !== null) row.ir_ratio = ir[ir.length - 1] / irFirst;
  return row;
}

// ---------------------------------------------------------------- the exported model
export class StateModel {
  constructor(json) {
    this.features = json.features;
    this.chemistry = json.chemistry;
    this.envelope = json.envelope;
    this.referenceConditions = json.reference_conditions;
    this.validation = json.validation;
    this.confidence = json.confidence;
    this.folds = json.folds.map((t) => ({
      baseline: t.baseline, nTrees: t.n_trees, starts: np.decode(t.starts, "<i4"), feature: np.decode(t.feature, "<i2"),
      threshold: np.decode(t.threshold, "<f8"), left: np.decode(t.left, "<i4"), right: np.decode(t.right, "<i4"),
      isLeaf: np.decode(t.is_leaf, "u1"), missingLeft: np.decode(t.missing_left, "u1"), value: np.decode(t.value, "<f8"),
    }));
    this.scores = np.decode(json.conformity_scores, "<f8");
    this.foldOf = np.decode(json.fold_of, "u1");
    this.foldCounts = this.folds.map((_, k) => this.foldOf.filter((f) => f === k).length);
  }
  /** raw HGB output (log1p space) of one fold model */
  hgb(fold, x) {
    let out = fold.baseline;
    for (let t = 0; t < fold.nTrees; t++) {
      const off = fold.starts[t];
      let i = 0;
      while (!fold.isLeaf[off + i]) {
        const v = x[fold.feature[off + i]];
        const goLeft = Number.isNaN(v) ? fold.missingLeft[off + i] === 1 : v <= fold.threshold[off + i];
        i = goLeft ? fold.left[off + i] : fold.right[off + i];
      }
      out += fold.value[off + i];
    }
    return out;
  }
  /** MAPIE CV+ (method "plus", gamma conformity score, alpha = 1 - confidence) for one input row */
  predictOne(x) {
    const preds = this.folds.map((fold) => Math.expm1(this.hgb(fold, x)));
    const n = this.scores.length;
    let point = 0;
    for (let k = 0; k < preds.length; k++) point += preds[k] * this.foldCounts[k];
    point /= n;
    const level = Number((1 - (1 - this.confidence) / 2).toFixed(12)); // 0.95 for a 90 % interval
    const q = Math.ceil(Number((level * (n + 1)).toFixed(9))) / n;
    const dist = new Float64Array(n), neg = new Float64Array(n);
    for (let i = 0; i < n; i++) { dist[i] = preds[this.foldOf[i]] * (1 + this.scores[i]); neg[i] = -dist[i]; }
    dist.sort(); neg.sort();
    const upper = np.quantileLowerSorted(dist, q);
    const lower = -np.quantileLowerSorted(neg, q);
    return { point: Math.max(point, 0), lower: Math.max(lower, 0), upper, folds: preds };
  }
  predictRow(row) { return this.predictOne(this.features.map((f) => (Number.isFinite(row[f]) ? row[f] : NaN))); }
  outOfRange(row) {
    const out = [];
    for (const f of this.features) {
      const v = row[f];
      const [lo, hi] = this.envelope[f];
      if (!Number.isFinite(v)) out.push(`${f} missing (imputed by the model)`);
      else if (v < lo || v > hi) out.push(`${f}=${g4(v)} outside training range [${g4(lo)}, ${g4(hi)}]`);
    }
    return out;
  }
}

function trendFallback(row) {
  const s = Math.max(row.fade_slope_per_kcycle / 1000.0, 1e-6);
  return {
    method: "linear capacity-test trend (fallback, not ML)",
    fade_rate_ref: tag(s, "modelled", "SOH fraction per cycle", "slope of capacity tests; observed duty, not reference conditions"),
    fade_rate_ref_conservative: tag(1.5 * s, "modelled", "SOH fraction per cycle", "1.5x trend slope (assumed margin)"),
    fade_rate_ref_optimistic: tag(s / 1.5, "modelled", "SOH fraction per cycle"),
    out_of_distribution: true,
  };
}

export function estimate(bundle, model, excluded = new Set()) {
  const meta = bundle.meta;
  const tests = sortByDate(meta.capacity_tests);
  if (!tests.length) return { status: "insufficient", reason: "no measured capacity: SOH cannot be anchored", existing_rule: ruleRoute(null) };
  const last = tests[tests.length - 1];
  const prov = dataProvenanceTag(last.provenance);
  const soh = last.measured_capacity_ah / meta.rated_capacity_ah;
  const out = { status: "ok", soh: tag(100 * soh, prov, "%", `latest capacity test ${last.date} / rated capacity`),
    existing_rule: ruleRoute(100 * soh), warnings: [] };
  const row = bundleFieldFeatures(bundle, excluded);
  out.features = Object.fromEntries(Object.entries(row).map(([k, v]) => [k, tag(Number.isFinite(v) ? v : null, prov)]));
  if (excluded.has("resistance")) out.warnings.push("resistance excluded (data-quality check inconclusive); model imputes it");
  if (soh <= EOL_FRACTION) {
    out.warnings.push("SOH at or below 80 %: below the ML training range; fade rate from the capacity-test trend only");
    return Object.assign(out, trendFallback(row));
  }
  if (!model) {
    out.warnings.push("no trained state model; using capacity-test trend");
    return Object.assign(out, trendFallback(row));
  }
  const pred = model.predictRow(row);
  const { point, lower: lo, upper: hi } = pred;
  const cov = model.validation.measured_coverage;
  out.method = `${model.validation.selected} on field features, trained on Severson LFP cells; CV+ interval`;
  out.rul_cycles_reference = tag(point, "modelled", "cycles", "remaining cycles to 80 % SOH at the training conditions",
    { lower: np.pyRound(lo, 1), upper: np.pyRound(hi, 1), nominal_level: model.validation.nominal_level, measured_coverage_on_held_out_cells: cov });
  const span = soh - EOL_FRACTION;
  out.fade_rate_ref = tag(span / Math.max(point, 1.0), "modelled", "SOH fraction per reference cycle", "(SOH - 0.80) / predicted RUL; the ML-to-physics hand-over");
  out.fade_rate_ref_conservative = tag(span / Math.max(lo, 1.0), "modelled", "SOH fraction per reference cycle", "from the CV+ lower bound of RUL (conservative)");
  out.fade_rate_ref_optimistic = tag(span / Math.max(hi, 1.0), "modelled", "SOH fraction per reference cycle");
  out.reference_conditions = { provenance: "assumed", values: model.referenceConditions };
  const oor = model.outOfRange(row);
  if (meta.chemistry !== model.chemistry) {
    out.warnings.push(`chemistry out of distribution: model trained on ${model.chemistry}, battery is ${meta.chemistry}; the interval's coverage does not apply`);
  }
  if (oor.length) out.warnings.push("inputs outside the training feature distribution: " + oor.join("; "));
  out.out_of_distribution = oor.length > 0 || meta.chemistry !== model.chemistry;
  out.distribution_shift_note = "Second-life packs differ from the Severson training cells (pack level, duty, often chemistry). " +
    "Interval coverage was measured on held-out Severson cells only.";
  out.fold_predictions = { provenance: "modelled", values: pred.folds.map((v) => np.pyRound(v, 1)), note: "the five cross-validation fold models" };
  return out;
}
