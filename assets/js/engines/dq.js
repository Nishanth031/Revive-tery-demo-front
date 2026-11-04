// Data-quality detectors and readiness rules (port of revive_ml/dq/detectors.py and readiness.py).
// Integration always uses the row-to-row step of the time-sorted, de-duplicated rows. Current is never
// flipped: direction-dependent checks work in a "charge-positive" frame from the declared or inferred convention.

import * as np from "../lib/np.js";
import { tag, dataProvenanceTag, f, pct0, pyRepr } from "../lib/provenance.js";
import { latestBy } from "./contract.js";

const SEV = { pass: "info", warn: "medium", fail: "high", inconclusive: "medium" };
const check = (id, name, status, severity, message, evidence = {}) => ({ id, name, status, severity, message, evidence });
const assumed = (v, unit = null) => tag(v, "assumed", unit);
const has = (d, c) => d.columns.includes(c) && d[c] !== undefined;
const notnaCount = (a) => { let n = 0; for (const v of a) if (!Number.isNaN(v)) n++; return n; };

/** str(pandas.Timestamp) for a UTC time: "2026-10-20 08:00:00+00:00" */
export function pyTimestamp(sec) {
  const ms = Math.round(sec * 1e6) / 1e3;
  const iso = new Date(Math.floor(ms)).toISOString();
  const micro = Math.round((sec - Math.floor(sec)) * 1e6);
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)}${micro ? `.${String(micro).padStart(6, "0")}` : ""}+00:00`;
}

// ---------------------------------------------------------------- context
function reorder(tel, idx) {
  const d = { n: idx.length, columns: tel.columns };
  for (const c of tel.columns.concat(["t"])) {
    const src = c === "timestamp_utc" ? null : tel[c];
    if (!src) continue;
    d[c] = Array.isArray(src) ? idx.map((i) => src[i]) : Float64Array.from(idx, (i) => src[i]);
  }
  return d;
}

export function buildContext(bundle, rules) {
  const tel = bundle.tel;
  const order = Array.from({ length: tel.n }, (_, i) => i).sort((a, b) => tel.t[a] - tel.t[b] || a - b);
  const keep = [];
  const seen = new Set();
  for (const i of order) { if (!seen.has(tel.t[i])) { seen.add(tel.t[i]); keep.push(i); } }
  const df = reorder(tel, keep);
  const dt = np.diff(df.t);
  const meta = bundle.meta;
  let cap, src;
  if (meta.capacity_tests.length) {
    const latest = latestBy(meta.capacity_tests);
    cap = latest.measured_capacity_ah; src = `latest capacity test (${latest.date})`;
  } else { cap = meta.rated_capacity_ah; src = "rated capacity (no capacity test)"; }
  const ctx = { bundle, meta, rules, df, dt, prov: dataProvenanceTag(meta.data_provenance), convention: null,
    convention_source: "none", capacity_ref_ah: cap, capacity_ref_source: src };
  const inferred = inferConvention(ctx).inferred;
  if (meta.current_sign_convention !== "unknown") {
    ctx.convention = meta.current_sign_convention; ctx.convention_source = "declared in metadata";
  } else if (inferred === "discharge_negative" || inferred === "discharge_positive") {
    ctx.convention = inferred; ctx.convention_source = "inferred from data (not declared)";
  }
  return ctx;
}

function chargePositive(ctx) {
  const i = ctx.df.current_a;
  if (ctx.convention === "discharge_negative") return Float64Array.from(i);
  if (ctx.convention === "discharge_positive") return Float64Array.from(i, (v) => -v);
  return null;
}

// ---------------------------------------------------------------- 1. sign convention
export function inferConvention(ctx) {
  const r = ctx.rules.sign_convention, df = ctx.df;
  const i = df.current_a, n = i.length;
  const iMid = new Float64Array(Math.max(0, n - 1));
  for (let k = 1; k < n; k++) iMid[k - 1] = 0.5 * (i[k] + i[k - 1]);
  const thr = r.min_current_a_fraction_of_c * ctx.meta.rated_capacity_ah;
  const votes = {};
  if (has(df, "soc_pct") && notnaCount(df.soc_pct) > 2) {
    const dsoc = np.diff(df.soc_pct);
    let agree = 0, cnt = 0;
    for (let k = 0; k < iMid.length; k++) {
      if (Math.abs(iMid[k]) > thr && Number.isFinite(dsoc[k]) && Math.abs(dsoc[k]) > 0) {
        cnt++; if (np.sign(iMid[k]) === np.sign(dsoc[k])) agree++;
      }
    }
    if (cnt >= 2) { votes.soc = agree / cnt; votes.soc_n = cnt; }
  }
  const dv = np.diff(df.voltage_v), di = np.diff(i);
  const idx = [];
  for (let k = 0; k < dv.length; k++) if (Number.isFinite(dv[k]) && Number.isFinite(iMid[k]) && Number.isFinite(di[k])) idx.push(k);
  if (idx.length >= 4) {
    let x0 = idx.map((k) => iMid[k] * ctx.dt[k]), x1 = idx.map((k) => di[k]);
    const y = idx.map((k) => dv[k]);
    const s0 = Math.max(Math.max(...x0.map(Math.abs)), 1e-12), s1 = Math.max(Math.max(...x1.map(Math.abs)), 1e-12);
    x0 = x0.map((v) => v / s0); x1 = x1.map((v) => v / s1);
    const coef = np.lstsq2(x0, x1, y);
    let rss = 0, a = 0, b = 0, d = 0;
    for (let k = 0; k < y.length; k++) {
      const e = y[k] - (x0[k] * coef[0] + x1[k] * coef[1]);
      rss += e * e; a += x0[k] * x0[k]; b += x0[k] * x1[k]; d += x1[k] * x1[k];
    }
    const dof = Math.max(1, idx.length - 2);
    const p = np.pinvSym2(a, b, d);
    const t = [coef[0] / Math.sqrt(Math.max(p[0] * rss / dof, 1e-30)), coef[1] / Math.sqrt(Math.max(p[2] * rss / dof, 1e-30))];
    const kk = Math.abs(t[1]) > Math.abs(t[0]) ? 1 : 0;
    votes.voltage_t_drift = t[0]; votes.voltage_t_ohmic = t[1]; votes.voltage_n = idx.length;
    if (Math.abs(t[kk]) >= 3) votes.voltage = t[kk] > 0 ? 1.0 : 0.0;
  }
  const calls = [];
  for (const k of ["soc", "voltage"]) {
    if (k in votes) {
      const fr = votes[k];
      calls.push(fr >= r.agree_fraction ? "discharge_negative" : fr <= 1 - r.agree_fraction ? "discharge_positive" : "ambiguous");
    }
  }
  const inferred = !calls.length ? "undetermined" : calls.every((c) => c === calls[0]) ? calls[0] : "ambiguous";
  return { inferred, votes, calls };
}

function checkSignConvention(ctx) {
  const r = ctx.rules.sign_convention;
  const inf = inferConvention(ctx);
  const declared = ctx.meta.current_sign_convention;
  const ev = { declared, inferred: inf.inferred, convention_used_downstream: ctx.convention || "none", data_flipped: false };
  if ("soc" in inf.votes) {
    ev.soc_agreement_fraction = tag(inf.votes.soc, ctx.prov, null, "share of active intervals where sign(I) == sign(dSOC)", { n: inf.votes.soc_n });
  }
  if ("voltage_t_drift" in inf.votes) {
    ev.voltage_response_t_stats = tag(null, ctx.prov, null, "t-statistics of dV on (I*dt, dI); positive means charge-positive current",
      { drift: np.pyRound(inf.votes.voltage_t_drift, 2), ohmic: np.pyRound(inf.votes.voltage_t_ohmic, 2), n: inf.votes.voltage_n });
  }
  const issues = [];
  let status = "pass";
  const df = ctx.df;
  if (has(df, "power_kw") && notnaCount(df.power_kw) > 0) {
    let nm = 0, same = 0, opp = 0;
    for (let k = 0; k < df.n; k++) {
      const vi = df.voltage_v[k] * df.current_a[k] / 1000, p = df.power_kw[k];
      if (Number.isFinite(vi) && Number.isFinite(p) && Math.abs(vi) > 1e-3) {
        nm++;
        if (Math.abs(p - vi) <= r.power_rel_tol * Math.abs(vi)) same++;
        if (Math.abs(p + vi) <= r.power_rel_tol * Math.abs(vi)) opp++;
      }
    }
    if (nm) {
      const fs = same / nm, fo = opp / nm;
      ev.power_equals_v_times_i_fraction = tag(fs, ctx.prov);
      ev.power_equals_minus_v_times_i_fraction = tag(fo, ctx.prov);
      if (fo > 0.8) {
        ev.power_column_convention = "discharge_positive";
        if (ctx.convention === "discharge_negative") {
          issues.push("power_kw is +V*|I| on discharge (discharge-positive) while current is discharge-negative: two sign conventions in one record");
          status = "warn";
        }
      } else if (fs > 0.8) {
        ev.power_column_convention = "same as current";
      } else {
        issues.push("power_kw matches neither +V*I nor -V*I");
        status = "warn";
      }
    }
  }
  if (inf.inferred === "ambiguous") { issues.push("SOC and voltage behaviour disagree about the current sign"); status = "fail"; }
  else if (inf.inferred === "undetermined") {
    issues.push("not enough active intervals to infer the current sign");
    status = status === "pass" ? "inconclusive" : status;
  }
  const decided = inf.inferred === "discharge_negative" || inf.inferred === "discharge_positive";
  if (declared !== "unknown" && decided && declared !== inf.inferred) {
    issues.push(`metadata declares ${declared} but the data behave as ${inf.inferred}`); status = "fail";
  }
  if (declared === "unknown" && decided) {
    issues.push(`convention not declared; inferred ${inf.inferred} from the data (used for direction-dependent checks; data not flipped)`);
    status = status === "pass" ? "warn" : status;
  }
  const msg = issues.length ? issues.join("; ") : `declared ${declared} matches the data`;
  return check("sign_convention", "Current sign convention", status, SEV[status] || "info", msg, ev);
}

// ---------------------------------------------------------------- 2. charge balance
export function impliedCapacity(ctx) {
  const i = chargePositive(ctx);
  if (i === null || !has(ctx.df, "soc_pct")) return null;
  const soc = ctx.df.soc_pct;
  const ah = np.cumAh(i.map((v) => (Number.isNaN(v) ? 0 : v)), ctx.dt);
  const idx = [];
  for (let k = 0; k < soc.length; k++) if (Number.isFinite(soc[k])) idx.push(k);
  if (idx.length < 3) return null;
  const s = idx.map((k) => soc[k]), a = idx.map((k) => ah[k]);
  const span = Math.max(...s) - Math.min(...s);
  const ahSpan = Math.max(...a) - Math.min(...a);
  if (ahSpan <= 0) return { soc_span_pts: span, ah_span: ahSpan, capacity_ah: null };
  const slope = np.polyfit1(a, s)[0];
  return { soc_span_pts: span, ah_span: ahSpan, slope, capacity_ah: slope > 0 ? 100.0 / slope : null,
    net_ah: a[a.length - 1] - a[0], net_soc_pts: s[s.length - 1] - s[0] };
}

function checkChargeBalance(ctx) {
  const r = ctx.rules.charge_balance;
  const name = "Charge balance (coulomb count vs recorded SOC)";
  if (!has(ctx.df, "soc_pct") || notnaCount(ctx.df.soc_pct) < 3) return check("charge_balance", name, "not_applicable", "info", "no SOC channel");
  if (ctx.convention === null) return check("charge_balance", name, "inconclusive", "medium", "current sign convention unknown; cannot compare directions");
  const ic = impliedCapacity(ctx);
  if (ic.soc_span_pts < r.min_soc_span_pts) {
    return check("charge_balance", name, "not_applicable", "info", `SOC moved only ${f(ic.soc_span_pts, 1)} points; too little to test`);
  }
  const ref = ctx.capacity_ref_ah;
  const expected = ic.ah_span / ref * 100;
  const ev = {
    coulomb_counted_throughput_ah: tag(ic.ah_span, ctx.prov, "Ah", "trapezoid rule on row-to-row time step"),
    recorded_soc_span: tag(ic.soc_span_pts, ctx.prov, "SOC points"),
    soc_points_explained_by_current: tag(expected, ctx.prov, "SOC points", `throughput / ${ctx.capacity_ref_source}`),
    reference_capacity: tag(ref, ctx.prov, "Ah", ctx.capacity_ref_source),
    convention_used: ctx.convention,
  };
  if (ic.capacity_ah === null) {
    ev.slope_soc_per_ah = tag(ic.slope ?? 0.0, ctx.prov);
    return check("charge_balance", name, "fail", "high", "SOC moves against the direction of the integrated current", ev);
  }
  const rel = ic.capacity_ah / ref;
  ev.implied_capacity = tag(ic.capacity_ah, ctx.prov, "Ah", "least-squares slope of SOC vs cumulative Ah");
  ev.implied_over_reference = tag(rel, ctx.prov);
  const mismatch = Math.abs(ic.soc_span_pts - expected);
  ev.mismatch = tag(mismatch, ctx.prov, "SOC points");
  ev.thresholds = { warn_rel: assumed(r.warn_rel), fail_rel: assumed(r.fail_rel) };
  const dev = Math.abs(1 / rel - 1);
  const msg = `SOC moved ${f(ic.soc_span_pts, 1)} points; current explains ${f(expected, 1)} on ${f(ref, 1)} Ah (implied capacity ${f(ic.capacity_ah, 1)} Ah)`;
  if (dev > r.fail_rel && mismatch > r.min_abs_pts) return check("charge_balance", name, "fail", "high", msg, ev);
  if (dev > r.warn_rel && mismatch > r.min_abs_pts) return check("charge_balance", name, "warn", "medium", msg, ev);
  return check("charge_balance", name, "pass", "info", msg, ev);
}

// ---------------------------------------------------------------- 3. regen sign
function checkRegenSign(ctx) {
  const r = ctx.rules.regen_sign;
  const name = "Regeneration / charging current direction";
  const df = ctx.df;
  if (!has(df, "operating_state") || df.operating_state.every((s) => s === null)) {
    return check("regen_sign", name, "not_applicable", "info", "no operating_state channel");
  }
  const st = df.operating_state.map((s) => String(s === null ? "None" : s).toUpperCase());
  const i = df.current_a;
  const regen = st.map((s, k) => r.regen_states.includes(s) && Number.isFinite(i[k]) && i[k] !== 0);
  const drive = st.map((s, k) => r.drive_states.includes(s) && Number.isFinite(i[k]) && i[k] !== 0);
  if (!regen.some(Boolean)) return check("regen_sign", name, "not_applicable", "info", "no regen/charging rows");
  let driveSign, basis;
  if (drive.some(Boolean)) {
    driveSign = np.sign(np.median(i.filter((_, k) => drive[k])));
    basis = "median sign of driving rows";
  } else if (ctx.convention) {
    driveSign = ctx.convention === "discharge_negative" ? -1.0 : 1.0;
    basis = `convention (${ctx.convention_source})`;
  } else return check("regen_sign", name, "inconclusive", "medium", "no driving rows and unknown convention");
  const wrong = regen.map((g, k) => g && np.sign(i[k]) === driveSign);
  const nWrong = wrong.filter(Boolean).length, nRegen = regen.filter(Boolean).length;
  const frac = nWrong / nRegen;
  const wrongIdx = wrong.map((w, k) => (w ? k : -1)).filter((k) => k >= 0);
  const ev = { regen_rows: nRegen, wrong_sign_rows: nWrong, first_rows: wrongIdx.slice(0, 10), discharge_sign_basis: basis,
    wrong_sign_fraction: tag(frac, ctx.prov) };
  if (nWrong) {
    ev.examples = wrongIdx.slice(0, 3).map((k) => ({ timestamp_utc: pyTimestamp(df.t[k]), operating_state: df.operating_state[k],
      current_a: tag(i[k], ctx.prov, "A") }));
    const status = frac >= r.fail_fraction ? "fail" : "warn";
    return check("regen_sign", name, status, status === "fail" ? "high" : "medium",
      `${nWrong} of ${nRegen} regen/charging rows have the same current sign as driving`, ev);
  }
  return check("regen_sign", name, "pass", "info", "regen/charging rows oppose driving", ev);
}

// ---------------------------------------------------------------- 4. resistance
function checkResistance(ctx) {
  const r = ctx.rules.resistance;
  const name = "Internal resistance plausibility";
  const meta = ctx.meta;
  if (!meta.resistance_tests.length) return check("resistance", name, "not_applicable", "info", "no resistance tests");
  const t = latestBy(meta.resistance_tests);
  const prov = dataProvenanceTag(t.provenance);
  let rCell;
  if (t.level === "cell") rCell = t.resistance_mohm;
  else if (meta.series_cells && meta.parallel_cells) rCell = t.resistance_mohm * meta.parallel_cells / meta.series_cells;
  else return check("resistance", name, "inconclusive", "medium", "pack resistance given without series/parallel counts");
  const cellCap = meta.rated_capacity_ah / (meta.parallel_cells || 1);
  const specific = rCell * cellCap;
  const rNew = r.typical_new_specific_mohm_ah / cellCap;
  const sohR = 100 - 20 * (rCell / rNew - 1) / (r.eol_resistance_factor - 1);
  const ev = {
    latest_test_resistance: tag(t.resistance_mohm, prov, "mOhm", `${t.level} level, ${t.date}`),
    per_cell_resistance: tag(rCell, prov, "mOhm"),
    specific_resistance: tag(specific, prov, "mOhm*Ah", "R_cell x C_cell"),
    plausible_range: { value: [r.specific_min_mohm_ah, r.specific_max_mohm_ah], provenance: "assumed", unit: "mOhm*Ah" },
    resistance_based_soh_unclipped: tag(sohR, "modelled", "%", "vs an assumed typical new cell; EOL at 2x"),
    resistance_based_soh_clipped: tag(Math.min(100.0, Math.max(0.0, sohR)), "modelled", "%"),
  };
  if (specific < r.specific_min_mohm_ah) {
    return check("resistance", name, "inconclusive", "high", `${f(rCell, 2)} mOhm per cell (${f(specific, 1)} mOhm*Ah) is implausibly low for ` +
      "this cell size; resistance-based SOH hits its 100 % ceiling and is not used", ev);
  }
  if (specific > r.specific_max_mohm_ah) {
    return check("resistance", name, "warn", "medium", `${f(specific, 0)} mOhm*Ah is above the plausible range: degraded cell or bad measurement`, ev);
  }
  return check("resistance", name, "pass", "info", "resistance within plausible range", ev);
}

// ---------------------------------------------------------------- 5. timestamps
function checkTimestamps(ctx) {
  const r = ctx.rules.timestamps;
  const name = "Timestamps (order, duplicates, gaps, regularity)";
  const raw = ctx.bundle.tel.t;
  let nBack = 0;
  for (let k = 1; k < raw.length; k++) if (raw[k] - raw[k - 1] < 0) nBack++;
  const nDup = raw.length - new Set(raw).size;
  const dt = ctx.dt, prov = ctx.prov;
  const ev = { n_rows: raw.length, duplicates: nDup, non_monotonic_steps: nBack };
  if (dt.length === 0) return check("timestamps", name, "fail", "high", "fewer than two distinct timestamps", ev);
  const med = np.median(dt);
  let nIrr = 0, nGaps = 0, gapTime = 0;
  for (const s of dt) {
    if (Math.abs(s - med) > r.irregular_rel_tol * med) nIrr++;
    if (s > r.gap_factor * med) { nGaps++; gapTime += s; }
  }
  const irr = nIrr / dt.length;
  const span = np.max(raw) - np.min(raw);
  Object.assign(ev, {
    median_step: tag(med, prov, "s"), min_step: tag(np.min(dt), prov, "s"), max_step: tag(np.max(dt), prov, "s"),
    irregular_step_fraction: tag(irr, prov), gaps: nGaps, gap_time_fraction: tag(span ? gapTime / span : 0.0, prov),
    integration_note: "all integrals use the row-to-row step, never a fixed step",
  });
  const issues = [];
  let status = "pass";
  if (nBack) { issues.push(`${nBack} backwards time step(s)`); status = "fail"; }
  if (nDup) { issues.push(`${nDup} duplicate timestamp(s) (dropped for integration)`); status = "fail"; }
  if (span && gapTime / span > r.gap_fail_fraction) { issues.push(`gaps cover ${f(100 * gapTime / span, 0)} % of the record`); status = "fail"; }
  else if (nGaps) { issues.push(`${nGaps} gap(s) longer than ${f(r.gap_factor, 0)}x the median step`); status = status === "pass" ? "warn" : status; }
  if (irr > r.irregular_warn_fraction) {
    issues.push(`${f(100 * irr, 0)} % of steps deviate >${f(100 * r.irregular_rel_tol, 0)} % from the median step`);
    status = status === "pass" ? "warn" : status;
  }
  const msg = issues.length ? issues.join("; ") : `regular ${f(med, 0)} s steps, no duplicates or reversals`;
  return check("timestamps", name, status, { pass: "info", warn: "medium", fail: "high" }[status], msg, ev);
}

// ---------------------------------------------------------------- 6. sensors
const CHANNELS = ["voltage_v", "current_a", "temperature_c", "soc_pct"];

function checkSensorNulls(ctx) {
  const r = ctx.rules.sensor;
  const tel = ctx.bundle.tel;
  const fr = {};
  for (const c of CHANNELS) if (has(tel, c)) fr[c] = (tel.n - notnaCount(tel[c])) / tel.n;
  const ev = Object.fromEntries(Object.entries(fr).map(([c, v]) => [`${c}_null_fraction`, tag(v, ctx.prov)]));
  const vals = Object.values(fr);
  const worst = vals.length ? Math.max(...vals) : 0.0;
  const bad = Object.keys(fr).filter((c) => fr[c] > r.null_warn_fraction);
  if (worst > r.null_fail_fraction) return check("sensor_nulls", "Sensor nulls", "fail", "high", `null fraction above ${pct0(r.null_fail_fraction)} in ${pyRepr(bad)}`, ev);
  if (bad.length) return check("sensor_nulls", "Sensor nulls", "warn", "medium", `nulls in ${pyRepr(bad)}`, ev);
  return check("sensor_nulls", "Sensor nulls", "pass", "info", "no significant nulls", ev);
}

function checkSensorDropouts(ctx) {
  const r = ctx.rules.sensor;
  const v = ctx.df.voltage_v;
  const floor = 0.5 * ctx.meta.min_voltage_v;
  const rows = [];
  for (let k = 0; k < v.length; k++) if (!Number.isFinite(v[k]) || v[k] < floor) rows.push(k);
  const frac = rows.length / v.length;
  const ev = { voltage_dropout_rows: rows.length, first_rows: rows.slice(0, 10), dropout_fraction: tag(frac, ctx.prov),
    dropout_floor: tag(floor, "assumed", "V", "half the minimum pack voltage") };
  if (frac > r.dropout_fail_fraction) return check("sensor_dropouts", "Sensor dropouts", "fail", "high", `${rows.length} voltage dropout rows`, ev);
  if (rows.length) return check("sensor_dropouts", "Sensor dropouts", "warn", "medium", `${rows.length} voltage dropout rows`, ev);
  return check("sensor_dropouts", "Sensor dropouts", "pass", "info", "no dropouts", ev);
}

// charge throughput (fraction of rated capacity) during a frozen run that makes the frozen reading implausible
export const STUCK_THROUGHPUT = { voltage_v: 0.005, soc_pct: 0.02, temperature_c: 0.10 };

function checkSensorStuck(ctx) {
  const r = ctx.rules.sensor;
  const df = ctx.df;
  const i = df.current_a.map((v) => (Number.isNaN(v) ? 0 : v));
  const rated = ctx.meta.rated_capacity_ah;
  const flowing = Array.from(i, (v) => Math.abs(v) > 0.01 * rated);
  const thru = np.cumAh(i.map(Math.abs), ctx.dt);
  const nFlow = flowing.filter(Boolean).length;
  const found = {};
  for (const [c, frac] of Object.entries(STUCK_THROUGHPUT)) {
    if (!has(df, c)) continue;
    const x = df[c];
    const same = Array.from(x, (v, k) => k > 0 && x[k] - x[k - 1] === 0 && flowing[k]);
    const pRepeat = same.filter(Boolean).length / Math.max(1, nFlow);
    for (const [start, length] of np.runs(same)) {
      const moved = thru[start + length - 1] - thru[start - 1];
      const rows = length + 1;
      const logP = length * Math.log(Math.max(pRepeat, 1e-12));
      const improbable = c === "voltage_v" && pRepeat < 1 && logP < Math.log(1e-6);
      const enough = moved >= frac * rated;
      if (rows >= r.stuck_min_run && (enough || improbable)) found[c] = Math.max(found[c] || 0, rows);
    }
  }
  const ev = Object.fromEntries(Object.entries(found).map(([c, n]) => [`${c}_longest_stuck_run`, n]));
  ev.min_run_rows = r.stuck_min_run;
  ev.throughput_needed_fraction_of_capacity = { value: STUCK_THROUGHPUT, provenance: "assumed" };
  if (Object.keys(found).length) return check("sensor_stuck", "Stuck sensor values", "fail", "high", `values frozen while current flows: ${pyRepr(found)}`, ev);
  return check("sensor_stuck", "Stuck sensor values", "pass", "info", "no stuck channels", ev);
}

export function hampel(x, w, k, minAbs) {
  const med = np.rollingMedianCentered(x, 2 * w + 1, 3);
  const dev = Float64Array.from(x, (v, i) => Math.abs(v - med[i]));
  const mad = np.rollingMedianCentered(dev, 2 * w + 1, 3);
  return Array.from(dev, (d, i) => d > k * 1.4826 * mad[i] && d > minAbs);
}

function checkSensorSpikes(ctx) {
  const r = ctx.rules.sensor;
  const df = ctx.df;
  const series = ctx.meta.series_cells || 1;
  const thr = { voltage_v: r.spike_min_abs.voltage_v_per_cell * series, temperature_c: r.spike_min_abs.temperature_c, soc_pct: r.spike_min_abs.soc_pct };
  const found = {};
  for (const [c, m] of Object.entries(thr)) {
    if (has(df, c) && notnaCount(df[c]) > 5) {
      const sp = hampel(df[c], r.spike_window, r.spike_k_mad, m);
      const rows = sp.map((s, k) => (s ? k : -1)).filter((k) => k >= 0);
      if (rows.length) found[c] = rows.slice(0, 10);
    }
  }
  const ev = Object.fromEntries(Object.entries(found).map(([c, rows]) => [`${c}_spike_rows`, rows]));
  ev.min_spike_size = { value: thr, provenance: "assumed" };
  if (Object.keys(found).length) {
    const n = Object.values(found).reduce((s, v) => s + v.length, 0);
    return check("sensor_spikes", "Sensor spikes", n <= 2 ? "warn" : "fail", n <= 2 ? "medium" : "high", `isolated spikes in ${pyRepr(Object.keys(found))}`, ev);
  }
  return check("sensor_spikes", "Sensor spikes", "pass", "info", "no spikes", ev);
}

function checkSensorRange(ctx) {
  const rr = ctx.rules.sensor.range;
  const df = ctx.df, meta = ctx.meta, series = meta.series_cells;
  const count = (a, bad) => { let n = 0; for (const v of a) if (bad(v)) n++; return n; };
  const out = {};
  out.voltage_v = series ? count(df.voltage_v, (v) => v / series < rr.cell_voltage_min || v / series > rr.cell_voltage_max)
    : count(df.voltage_v, (v) => v < 0 || v > 1.5 * meta.max_voltage_v);
  out.temperature_c = count(df.temperature_c, (v) => v < rr.temperature_min || v > rr.temperature_max);
  if (has(df, "soc_pct")) out.soc_pct = count(df.soc_pct, (v) => v < rr.soc_min || v > rr.soc_max);
  out.current_a = count(df.current_a, (v) => Math.abs(v) > rr.max_abs_c_rate * meta.rated_capacity_ah);
  const ev = Object.fromEntries(Object.entries(out).map(([c, n]) => [`${c}_out_of_range_rows`, n]));
  ev.sensor_ranges = { value: rr, provenance: "assumed", note: "physical sensor plausibility, not operating limits (see gate)" };
  const bad = Object.fromEntries(Object.entries(out).filter(([, n]) => n));
  if (Object.keys(bad).length) return check("sensor_range", "Readings beyond sensor range", "fail", "high", `physically implausible readings: ${pyRepr(bad)}`, ev);
  return check("sensor_range", "Readings beyond sensor range", "pass", "info", "all readings physically plausible", ev);
}

function checkTemperatureMissing(ctx) {
  const tel = ctx.bundle.tel;
  let both = 0, live = 0;
  for (let k = 0; k < tel.n; k++) {
    const isLive = !Number.isNaN(tel.voltage_v[k]) && !Number.isNaN(tel.current_a[k]);
    if (isLive) { live++; if (Number.isNaN(tel.temperature_c[k])) both++; }
  }
  const frac = both / Math.max(1, live);
  const ev = { temperature_missing_while_live_fraction: tag(frac, ctx.prov) };
  const name = "Temperature missing while other channels live";
  if (frac >= 0.5) return check("temperature_missing", name, "fail", "high", "temperature absent for most live rows", ev);
  if (frac > 0) return check("temperature_missing", name, "warn", "medium", `temperature absent on ${pct0(frac)} of live rows`, ev);
  return check("temperature_missing", name, "pass", "info", "temperature present", ev);
}

// ---------------------------------------------------------------- 7. disagreement
function checkEstimateDisagreement(ctx, chargeBalance = null) {
  const r = ctx.rules.estimate_disagreement;
  const name = "Live SOH vs capacity-test SOH";
  const meta = ctx.meta;
  const ic = ctx.convention ? impliedCapacity(ctx) : null;
  let live = null;
  if (ic && ic.capacity_ah && ic.soc_span_pts >= ctx.rules.charge_balance.min_soc_span_pts) live = 100 * ic.capacity_ah / meta.rated_capacity_ah;
  let test = null, latest = null, testProv = null;
  if (meta.capacity_tests.length) {
    latest = latestBy(meta.capacity_tests);
    test = 100 * latest.measured_capacity_ah / meta.rated_capacity_ah;
    testProv = dataProvenanceTag(latest.provenance);
  }
  const ev = {};
  if (live !== null) ev.live_soh_from_telemetry = tag(live, ctx.prov, "%", "implied capacity from SOC vs coulomb count / rated");
  if (test !== null) ev.soh_from_capacity_test = tag(test, testProv, "%", `latest test ${latest.date}`);
  if (has(ctx.df, "bms_soh_pct") && notnaCount(ctx.df.bms_soh_pct) > 0) {
    const vals = Array.from(ctx.df.bms_soh_pct).filter((v) => !Number.isNaN(v));
    ev.bms_reported_soh = tag(vals[vals.length - 1], ctx.prov, "%", "BMS-reported value; not independently measured");
  }
  if (test === null) {
    ev.decision_trusts = "none: no measured capacity";
    return check("estimate_disagreement", name, "inconclusive", "high", "no capacity test; SOH cannot be anchored to a measurement", ev);
  }
  ev.decision_trusts = "capacity test";
  ev.why = "a full-cycle capacity test is a direct, controlled measurement; the live estimate depends on BMS SOC over a partial window" +
    (chargeBalance !== null && chargeBalance.status === "fail" ? "; and the charge-balance check failed for this window" : "");
  if (live === null) return check("estimate_disagreement", name, "not_applicable", "info", "live SOH not computable from this telemetry window", ev);
  const diff = Math.abs(live - test);
  ev.difference = tag(diff, ctx.prov, "SOH points");
  const msg = `live SOH ${f(live, 1)} % vs capacity-test SOH ${f(test, 1)} %`;
  if (diff > r.fail_pts) return check("estimate_disagreement", name, "fail", "high", msg, ev);
  if (diff > r.warn_pts) return check("estimate_disagreement", name, "warn", "medium", msg, ev);
  return check("estimate_disagreement", name, "pass", "info", msg, ev);
}

// ---------------------------------------------------------------- 8. provenance and sample size
function checkProvenance(ctx) {
  const meta = ctx.meta;
  const recs = [...meta.capacity_tests, ...meta.resistance_tests, ...meta.safety_events];
  const recProv = [...new Set(recs.map((r) => r.provenance))].sort();
  const text = [meta.asset_id, meta.notes || "", meta.source || ""].filter(Boolean).join(" ").toUpperCase();
  const ev = { bundle_provenance: meta.data_provenance, record_provenances: recProv, report_tag_for_data_values: ctx.prov };
  if (meta.data_provenance === "measured") {
    if (recProv.some((p) => p !== "measured")) return check("provenance", "Data provenance", "fail", "high", "bundle labelled measured but contains synthetic/simulated records", ev);
    if (["SYNTHETIC", "SIMULATED", "DEMO", "ILLUSTRATIVE"].some((w) => text.includes(w))) {
      return check("provenance", "Data provenance", "fail", "high", "bundle labelled measured but its description says synthetic/demo", ev);
    }
    return check("provenance", "Data provenance", "pass", "info", "measured data", ev);
  }
  return check("provenance", "Data provenance", "warn", "medium",
    `${meta.data_provenance} data: every derived number is tagged 'synthetic'; results show the pipeline works, not anything about a real battery`, ev);
}

function checkSampleSize(ctx) {
  const r = ctx.rules.sample_size;
  const n = ctx.df.n;
  const dur = ctx.dt.length ? np.sum(ctx.dt) : 0.0;
  const ev = { n_rows: n, duration: tag(dur, ctx.prov, "s"), min_rows: r.min_rows, min_duration: assumed(r.min_duration_s, "s") };
  if (n < r.min_rows || dur < r.min_duration_s) return check("sample_size", "Enough telemetry", "fail", "high", `${n} rows over ${f(dur, 0)} s is too little to assess`, ev);
  return check("sample_size", "Enough telemetry", "pass", "info", `${n} rows over ${f(dur, 0)} s`, ev);
}

export function runAll(bundle, rules) {
  const ctx = buildContext(bundle, rules);
  const cb = checkChargeBalance(ctx);
  return [
    checkSampleSize(ctx), checkProvenance(ctx), checkTimestamps(ctx), checkSignConvention(ctx), cb, checkRegenSign(ctx),
    checkResistance(ctx), checkSensorNulls(ctx), checkSensorDropouts(ctx), checkSensorStuck(ctx), checkSensorSpikes(ctx),
    checkSensorRange(ctx), checkTemperatureMissing(ctx), checkEstimateDisagreement(ctx, cb),
  ];
}

// ---------------------------------------------------------------- readiness (explicit rules, no weighted score)
export const READINESS_RULES = [
  "R1: any check with status 'fail' -> NOT_READY",
  "R2: else any 'warn' or 'inconclusive' -> READY_WITH_WARNINGS",
  "R3: else -> READY",
];
export function readiness(checks) {
  const counts = Object.fromEntries(["pass", "warn", "fail", "inconclusive", "not_applicable"].map((s) => [s, checks.filter((c) => c.status === s).length]));
  const fails = checks.filter((c) => c.status === "fail").map((c) => c.id);
  const soft = checks.filter((c) => c.status === "warn" || c.status === "inconclusive").map((c) => c.id);
  let verdict, rule, why;
  if (fails.length) [verdict, rule, why] = ["NOT_READY", READINESS_RULES[0], fails];
  else if (soft.length) [verdict, rule, why] = ["READY_WITH_WARNINGS", READINESS_RULES[1], soft];
  else [verdict, rule, why] = ["READY", READINESS_RULES[2], []];
  return {
    verdict, rule_applied: rule, triggering_checks: why, rules: READINESS_RULES, n_checks: checks.length,
    ...Object.fromEntries(Object.entries(counts).map(([k, v]) => [`n_${k}`, v])),
    excluded_from_decision: checks.filter((c) => c.status === "inconclusive").map((c) => c.id),
  };
}
