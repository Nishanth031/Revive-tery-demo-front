// Port of revive_ml.insight (engines/ml/src/revive_ml/insight/*.py): explain, confidence, what-if, break-even,
// robustness, next actions, rule gap, impact, fleet assignment (greedy + 2-opt) and the battery passport.
// Every reason cites a report field. Tunables: configs.intelligence (configs/intelligence.yaml). Golden-tested.
import { route, withRegion } from "./econ.js";
import { tag } from "../lib/provenance.js";

export const val = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x.value ?? null : x ?? null);
const r_ = (stage, tone, title, text, metric, provenance, impact) => ({ stage, tone, title, text, metric, provenance, impact });
const fmt0 = (x) => Math.round(x).toLocaleString("en-US");
const f1 = (x) => Number(x).toFixed(1);

export function bestApplication(report) {
  const rec = report.recommendation || {};
  if (rec.application) return rec.application;
  const opts = (report.economics || {}).second_life_options || {};
  const keys = Object.keys(opts);
  if (keys.length) return keys.reduce((a, k) => (val(opts[k].net_value) > val(opts[a].net_value) ? k : a), keys[0]);
  return Object.keys(report.projections || {})[0] || null;
}

// ---------------------------------------------------------------- explain
export function explain(report, configs) {
  const out = [];
  const dq = report.data_quality || {};
  const rd = dq.readiness || {};
  const prov = report.data_provenance;
  if (rd.verdict) {
    const tone = { NOT_READY: "bad", READY_WITH_WARNINGS: "info", READY: "good" }[rd.verdict] || "info";
    out.push(r_("data_quality", tone, `Data quality: ${rd.verdict}`, `${rd.n_pass} of ${rd.n_checks} checks pass, ${rd.n_fail} fail`,
      "data_quality.readiness", prov, rd.verdict === "NOT_READY" ? 100 : 10));
  }
  for (const c of dq.checks || []) {
    if (c.status === "fail") out.push(r_("data_quality", "bad", `Check failed: ${c.id}`, c.message, `data_quality.checks[${c.id}]`, prov, 95));
    else if (c.status === "warn" || c.status === "inconclusive") out.push(r_("data_quality", "warn", `Check ${c.status}: ${c.id}`, c.message, `data_quality.checks[${c.id}]`, prov, 20));
  }
  const g = report.gate;
  if (g) {
    const v = g.verdict;
    if (v === "Reject") out.push(r_("gate", "bad", "Safety gate: Reject", (g.reasons || []).join("; "), "gate.verdict", "modelled", 92));
    else if (v === "Quarantine") out.push(r_("gate", "warn", "Safety gate: Quarantine", (g.reasons || []).join("; "), "gate.verdict", "modelled", 85));
    else if (v === "Pass") out.push(r_("gate", "good", "Safety gate: Pass", "no limit breached, no open high-severity event, telemetry inside the healthy-window distribution", "gate.verdict", "modelled", 35));
    const ood = g.ood || {};
    if ("flagged_fraction" in ood) {
      const q = ood.status === "quarantine";
      out.push(r_("gate", q ? "warn" : "info", "Out-of-distribution filter",
        `${ood.n_flagged_windows} of ${ood.n_windows} telemetry windows flagged (${(100 * val(ood.flagged_fraction)).toFixed(0)} %)`,
        "gate.ood.flagged_fraction", "modelled", q ? 55 : 15));
    }
  }
  const st = report.state || {};
  if (st.soh && st.soh.value !== null && st.soh.value !== undefined) {
    const s = st.soh.value;
    out.push(r_("state", s >= 80 ? "good" : s >= 60 ? "warn" : "bad", `State of health ${f1(s)} %`, st.soh.note || "", "state.soh", st.soh.provenance, 60));
  }
  const feats = st.features || {};
  if (val(feats.fade_slope_per_kcycle) !== null) out.push(r_("state", "info", "Fade slope", `${val(feats.fade_slope_per_kcycle).toFixed(4)} SOH per 1,000 cycles (from the capacity-test history)`, "state.features.fade_slope_per_kcycle", "modelled", 30));
  const ir = val(feats.ir_ratio);
  if (ir !== null) out.push(r_("state", ir > 1.5 ? "warn" : "info", "Resistance growth", `latest / earliest resistance = ${ir.toFixed(2)}`, "state.features.ir_ratio", "modelled", ir > 1.5 ? 40 : 15));
  const tmax = val(feats.t_max_c);
  if (tmax !== null) out.push(r_("state", tmax > 45 ? "warn" : "info", "Maximum temperature", `${f1(tmax)} degC in the telemetry`, "state.features.t_max_c", prov, 20));
  const rul = st.rul_cycles_reference;
  if (rul && rul.value !== null && rul.value !== undefined) {
    out.push(r_("state", "info", "Remaining useful life (reference conditions)",
      `${rul.value.toFixed(0)} cycles, interval ${(rul.lower ?? 0).toFixed(0)}-${(rul.upper ?? 0).toFixed(0)} (nominal ${rul.nominal_level}, measured coverage ${rul.measured_coverage_on_held_out_cells})`,
      "state.rul_cycles_reference", rul.provenance, 45));
  }
  const modelChem = configs?.intelligence?.insight?.state_model_chemistry || "LFP";
  if (report.state && report.chemistry && report.chemistry !== modelChem) {
    out.push(r_("state", "warn", `State model trained on ${modelChem}, pack is ${report.chemistry}`,
      "the RUL interval's coverage was measured on held-out LFP cells and does not apply to this chemistry; treat the remaining-life numbers as indicative", "chemistry", "assumed", 65));
  } else if (st.distribution_shift_note) {
    out.push(r_("state", "info", "Distribution shift", st.distribution_shift_note, "state.distribution_shift_note", "assumed", 12));
  }
  const app = bestApplication(report);
  const pj = app ? (report.projections || {})[app] : null;
  const yrs = (x) => (x !== null && x !== undefined ? f1(x) : "not reached within the projection horizon");
  if (pj) out.push(r_("projection", "info", `Years to the ${pj.workload.label} limit`,
    `conservative ${yrs(val(pj.conservative_years))} years (central ${yrs(val(pj.years_to_application_limit.central))})`, `projections.${app}.conservative_years`, "modelled", 50));
  const econ = report.economics;
  if (econ) {
    const opts = econ.second_life_options || {};
    const recNet = val(econ.recycle.net_value);
    if (app in opts) {
      const o = opts[app];
      const second = String(report.decision || "").startsWith("Second-Life");
      out.push(r_("economics", second ? "good" : "bad", "Best second life vs recycling now",
        `${o.label}: net ${fmt0(val(o.net_value))} USD vs recycling now ${fmt0(recNet)} USD`, `economics.second_life_options.${app}.net_value`, "modelled", 90));
      if (o.capped_by_buy_new) out.push(r_("economics", "warn", "Capped by the buy-new benchmark",
        `the energy value is capped at ${fmt0(val(o.buy_new_cap))} USD, the cost of new storage for the same service`, `economics.second_life_options.${app}.buy_new_cap`, "modelled", 50));
    }
    if ((econ.placeholder_inputs || []).length) out.push(r_("economics", "info", "Placeholder inputs",
      `${econ.placeholder_inputs.length} cost/tariff inputs are PLACEHOLDER: ${econ.placeholder_inputs.slice(0, 3).join(", ")} ...`, "economics.placeholder_inputs", "assumed", 40));
  }
  const ranked = out.map((r, i) => [r, i]).sort((a, b) => b[0].impact - a[0].impact || a[1] - b[1]).map(([r]) => r);
  return { top: ranked.slice(0, 5), all: ranked };
}

export function ruleGap(report, reasons) {
  const st = report.state || {};
  const cmp = report.comparison_with_existing_rule || {};
  const rule = cmp.existing_rule || st.existing_rule || null;
  const decision = report.decision || "";
  const agrees = Boolean(rule) && rule.split(":")[0] === decision.split(":")[0];
  let why = agrees ? [] : reasons.top.filter((r) => r.tone === "bad" || r.tone === "warn").map((r) => `${r.title}: ${r.text}`).slice(0, 3);
  if (!agrees && !why.length) why = reasons.top.slice(0, 2).map((r) => `${r.title}: ${r.text}`);
  return { agrees, existing_rule: rule, engine_decision: decision, why_different: why,
    note: "existing rule: SOH > 80 % stationary storage, 60-80 % low-speed EV, < 60 % recycle" };
}

// ---------------------------------------------------------------- confidence (heuristic)
const lin = (x, full, zero) => (x <= full ? 1 : x >= zero ? 0 : (zero - x) / (zero - full));

export function rulRange(report) {
  const r = (report.state || {}).rul_cycles_reference;
  if (!r || r.value === null || r.value === undefined) return null;
  return { lower: r.lower ?? null, median: r.value, upper: r.upper ?? null, unit: "cycles", provenance: "modelled",
    nominal_level: r.nominal_level ?? null, measured_coverage: r.measured_coverage_on_held_out_cells ?? null };
}
export function yearsRange(report) {
  const app = bestApplication(report);
  const pj = app ? (report.projections || {})[app] : null;
  if (!pj) return null;
  const y = pj.years_to_application_limit;
  return { application: app, mc_p05: val(y.mc_p05), central: val(y.central), mc_p95: val(y.mc_p95), unit: "years", provenance: "modelled",
    note: "Monte Carlo band is assumption-conditional (physics-parameter priors), not a measured interval" };
}

export function confidence(report, configs, nRows = null) {
  const cfg = configs.intelligence.confidence;
  const modelChem = configs.intelligence.insight?.state_model_chemistry || "LFP";
  const w = cfg.weights;
  const f = [];
  const rd = (report.data_quality || {}).readiness || {};
  const n = rd.n_checks || 0;
  let frac = n ? (rd.n_pass || 0) / n : 0;
  if (rd.verdict === "NOT_READY") frac = Math.min(frac, 0.5);
  f.push(["data_quality", frac, `${rd.n_pass} of ${n} data-quality checks pass (${rd.verdict})`]);
  const g = report.gate || {};
  const ood = (g.ood || {}).status;
  let ind = ood === "pass" ? 1 : ood === "quarantine" ? 0 : 0.5;
  let detail = `out-of-distribution filter: ${ood || "not run"}`;
  if (report.state && report.chemistry && report.chemistry !== modelChem) { ind *= 0.5; detail += `; state model trained on ${modelChem}, pack is ${report.chemistry}`; }
  f.push(["in_distribution", ind, detail]);
  const rr = rulRange(report);
  if (rr && rr.median && rr.lower !== null && rr.upper !== null && rr.median > 0) {
    const width = (rr.upper - rr.lower) / rr.median;
    f.push(["interval_width", lin(width, cfg.interval_width_full, cfg.interval_width_zero), `RUL interval width ${width.toFixed(2)} x the median`]);
  } else f.push(["interval_width", 0, "no RUL interval (state not estimated)"]);
  const gv = g.verdict;
  f.push(["gate", gv ? cfg.gate_points[gv] ?? 0 : 0, `gate verdict: ${gv || "not run"}`]);
  if (nRows === null || nRows === undefined) f.push(["telemetry_length", 0.5, "telemetry length unknown"]);
  else f.push(["telemetry_length", Math.min(1, nRows / cfg.telemetry_rows_full), `${nRows} telemetry rows`]);
  const prov = report.data_provenance || "synthetic";
  f.push(["provenance", cfg.provenance_points[prov] ?? 0.4, `data provenance: ${prov}`]);
  const factors = f.map(([k, x, d]) => ({ factor: k, points: Math.round(w[k] * x * 100) / 100, max: w[k], detail: d }));
  const score = Math.round(factors.reduce((a, r) => a + r.points, 0) * 10) / 10;
  const lv = cfg.levels;
  const level = score >= lv.High ? "High" : score >= lv.Medium ? "Medium" : "Low";
  return { level, score_0_100: score, factors, label: cfg.label || "heuristic", rul_range: rr, years_range: yearsRange(report) };
}

// ---------------------------------------------------------------- what-if, break-even, robustness
const COST_KEYS = ["testing_usd_per_kwh", "refurbishment_usd_per_kwh", "logistics_usd_per_kwh", "installation_usd_per_kwh"];
const METALS = ["nickel", "cobalt", "lithium_carbonate"];
export const LEVERS = ["tariff", "cost_mult", "metal_mult", "new_cost", "discount_rate"];

export function configWith(econCfg, o = {}) {
  let cfg = withRegion(structuredClone(econCfg), o.region || null);
  if (o.tariff !== undefined && o.tariff !== null) cfg.second_life.value_per_kwh_delivered = { ...cfg.second_life.value_per_kwh_delivered, value: Number(o.tariff) };
  if (o.cost_mult !== undefined && o.cost_mult !== null) for (const k of COST_KEYS) cfg.second_life[k] = { ...cfg.second_life[k], value: val(cfg.second_life[k]) * Number(o.cost_mult) };
  if (o.metal_mult !== undefined && o.metal_mult !== null) {
    const p = cfg.recycling.prices_usd_per_tonne;
    for (const m of METALS) p[m] = { ...p[m], value: val(p[m]) * Number(o.metal_mult) };
  }
  if (o.new_cost !== undefined && o.new_cost !== null) cfg.buy_new_benchmark.installed_system_usd_per_kwh = { ...cfg.buy_new_benchmark.installed_system_usd_per_kwh, value: Number(o.new_cost) };
  if (o.discount_rate !== undefined && o.discount_rate !== null) cfg.discount_rate = { ...cfg.discount_rate, value: Number(o.discount_rate) };
  return cfg;
}

export const canReroute = (report) => Boolean(report.economics) && Boolean(report.projections) && (report.state || {}).status === "ok";

export function reroute(report, configs, overrides = {}) {
  if (!canReroute(report)) return null;
  const packKwh = val(report.economics.pack_energy);
  const meta = { nominal_voltage_v: packKwh * 1000, rated_capacity_ah: 1.0, chemistry: report.chemistry };
  let proj = report.projections;
  if (overrides.workloads && overrides.workloads.length) proj = Object.fromEntries(Object.entries(proj).filter(([k]) => overrides.workloads.includes(k)));
  const e = route(meta, report.state, proj, configWith(configs.economics, overrides));
  const opts = e.second_life_options || {};
  const nets = Object.values(opts).map((o) => val(o.net_value));
  return { decision: e.decision, application: (e.recommendation || {}).application ?? null, best_net: nets.length ? Math.max(...nets) : null,
    recycle_net: val(e.recycle.net_value), options: Object.fromEntries(Object.entries(opts).map(([k, o]) => [k, val(o.net_value)])) };
}

const cls = (d) => String(d).split(":")[0];
function baseValue(configs, lever) {
  const c = configs.economics;
  return { tariff: val(c.second_life.value_per_kwh_delivered), cost_mult: 1.0, metal_mult: 1.0,
    new_cost: val(c.buy_new_benchmark.installed_system_usd_per_kwh), discount_rate: val(c.discount_rate) }[lever];
}

export function breakEven(report, configs, lever = "tariff", overrides = {}) {
  const cfg = configs.intelligence.break_even;
  const [lo, hi] = cfg[`${lever}_range`];
  const budget = cfg.max_evaluations;
  const now = reroute(report, configs, overrides);
  if (!now) return null;
  const cur = cls(now.decision);
  const nGrid = 16;
  const xs = Array.from({ length: nGrid }, (_, i) => lo + ((hi - lo) * i) / (nGrid - 1));
  const cs = xs.map((x) => cls(reroute(report, configs, { ...overrides, [lever]: x }).decision));
  let used = 1 + nGrid;
  const b0 = overrides[lever] ?? baseValue(configs, lever);
  let best = -1, bestDist = Infinity;
  for (let i = 0; i < nGrid - 1; i++) {
    if (cs[i] === cs[i + 1]) continue;
    const d = Math.abs((xs[i] + xs[i + 1]) / 2 - b0);
    if (d < bestDist) { bestDist = d; best = i; }
  }
  if (best < 0) return null;
  let a = xs[best], b = xs[best + 1];
  const ca = cs[best];
  while (used < budget) {
    const m = (a + b) / 2;
    const cm = cls(reroute(report, configs, { ...overrides, [lever]: m }).decision);
    used += 1;
    if (cm === ca) a = m; else b = m;
  }
  return { lever, value: (a + b) / 2, below: cs[best], above: cs[best + 1], current: cur, current_value: b0, evaluations: used };
}

/** grid: full factorial for the share; one lever at a time for ranges and flips */
export function robustness(report, configs, grid = null) {
  const now = reroute(report, configs);
  if (!now) return null;
  grid = grid || configs.intelligence.robustness;
  const cur = cls(now.decision);
  const keys = Object.keys(grid);
  let same = 0, total = 0;
  const rec = (i, o) => {
    if (i === keys.length) { total++; if (cls(reroute(report, configs, o).decision) === cur) same++; return; }
    for (const x of grid[keys[i]]) rec(i + 1, { ...o, [keys[i]]: x });
  };
  rec(0, {});
  const perLever = {}, flips = [];
  for (const k of keys) {
    const keep = [];
    for (const x of grid[k]) {
      const d = reroute(report, configs, { [k]: x }).decision;
      if (cls(d) === cur) keep.push(x); else flips.push({ lever: k, value: x, decision: d });
    }
    perLever[k] = keep.length ? [Math.min(...keep), Math.max(...keep)] : null;
  }
  const be = breakEven(report, configs, "tariff");
  return { current_decision: now.decision, share_same_decision: total ? same / total : null, scenarios: total,
    per_lever_range: perLever, flips, break_even_tariff: be ? be.value : null, grid, label: "assumption sweep, not a probability" };
}

// ---------------------------------------------------------------- next best actions
const NEEDS_TEXT = { chemistry: "the cell chemistry (LFP, NMC or NCA)", series_cells: "the series cell count", rated_capacity_ah: "the rated capacity", timestamps: "timestamps for every reading" };

export function nextActions(report, configs, stillNeeds = []) {
  const acts = [];
  for (const n of stillNeeds || []) acts.push({ action: `Supply ${NEEDS_TEXT[n] || n}`, why: "the ML could not establish it from the upload", expected_effect: "lets the full engine run instead of refusing or using a default" });
  const checks = (report.data_quality || {}).checks || [];
  for (const c of checks) if (c.status === "fail") acts.push({ action: `Fix the data behind '${c.id}'`, why: c.message, expected_effect: "the engine can then judge health from data it trusts" });
  const g = report.gate || {};
  if (g.verdict === "Quarantine") acts.push({ action: "Inspect the pack before any second-life use", why: (g.reasons || []).join("; "), expected_effect: "clears or confirms the quarantine; the economics then run" });
  const st = report.state || {};
  const r = st.rul_cycles_reference;
  if (r && r.value) {
    const width = ((r.upper ?? 0) - (r.lower ?? 0)) / r.value;
    if (width > 0.5) acts.push({ action: "Add a recent full capacity test", why: `the remaining-life interval spans ${(r.lower ?? 0).toFixed(0)}-${(r.upper ?? 0).toFixed(0)} cycles (${Math.round(width * 100)}% of the median)`, expected_effect: "expected to narrow the remaining-life interval and the years-to-limit range" });
  }
  const res = checks.find((c) => c.id === "resistance");
  if (res && res.status !== "pass") acts.push({ action: "Add a pack DC-resistance test", why: res.message, expected_effect: "lets resistance growth count in the safety gate and the state estimate" });
  if (report.chemistry && report.chemistry !== "LFP" && report.state) acts.push({ action: `Validate on ${report.chemistry} cells`, why: "the state model was trained on LFP cells; its interval coverage does not apply here", expected_effect: "would turn the remaining-life numbers from indicative into checked ones" });
  const be = breakEven(report, configs, "tariff");
  if (be) {
    const dir = be.above !== be.current ? "above" : "below";
    const target = dir === "above" ? be.above : be.below;
    acts.push({ action: `Check the real tariff: ${dir} ${be.value.toFixed(3)} USD/kWh the decision becomes ${target}`, why: `today's tariff ${be.current_value.toFixed(3)} USD/kWh is a PLACEHOLDER input`, expected_effect: "confirms or flips the economics decision" });
  }
  return acts;
}

/** the full insight block (same keys as revive_ml.insight.workflow.insight_for) */
export function insightFor(report, configs, { nRows = null, stillNeeds = [], withRobustness = true } = {}) {
  const reasons = explain(report, configs);
  const c = confidence(report, configs, nRows);
  return { reasons, confidence: { level: c.level, score_0_100: c.score_0_100, factors: c.factors, label: c.label },
    rul_range: c.rul_range, years_range: c.years_range, robustness: withRobustness ? robustness(report, configs) : null,
    next_actions: nextActions(report, configs, stillNeeds), rule_gap: ruleGap(report, reasons) };
}

// ---------------------------------------------------------------- fleet: impact and assignment
export function impact(packs) {
  const counts = {};
  for (const p of packs) counts[p.disposition] = (counts[p.disposition] || 0) + 1;
  const second = packs.filter((p) => p.disposition === "REUSE" || p.disposition === "REPURPOSE");
  const kwh = second.reduce((a, p) => a + (p.pack_kwh && p.soh !== null && p.soh !== undefined ? (p.pack_kwh * p.soh) / 100 : 0), 0);
  const routed = second.reduce((a, p) => a + (p.net_value || 0), 0) + packs.filter((p) => !second.includes(p)).reduce((a, p) => a + (p.recycle_value || 0), 0);
  const all = packs.reduce((a, p) => a + (p.recycle_value || 0), 0);
  return { packs: tag(packs.length, "modelled", "packs"), count_by_disposition: counts,
    kwh_redeployed: tag(kwh, "modelled", "kWh", "pack kWh x SOH for packs routed to a second life"),
    net_value_routed: tag(routed, "modelled", "USD", "engine routing; placeholder cost and tariff inputs"),
    net_value_recycle_all: tag(all, "modelled", "USD", "every pack recycled now"),
    value_vs_recycle_all: tag(routed - all, "modelled", "USD") };
}

const MAX_PASSES = 20;
export function assign(packsIn, limits) {
  const packs = [...packsIn].sort((a, b) => (a.asset_id < b.asset_id ? -1 : a.asset_id > b.asset_id ? 1 : 0));
  const elig = packs.filter((p) => p.eligible);
  const used = Object.fromEntries(Object.keys(limits).map((a) => [a, { packs: 0, kwh: 0 }]));
  const plan = Object.fromEntries(packs.map((p) => [p.asset_id, null]));
  const fits = (a, kwh) => { const l = limits[a]; if (!l) return false; if ("packs" in l && used[a].packs + 1 > l.packs) return false; if ("kwh" in l && used[a].kwh + kwh > l.kwh + 1e-9) return false; return true; };
  const v = (p, a) => (a ? p.options[a] : p.recycle);
  const total = () => packs.reduce((s, p) => s + v(p, plan[p.asset_id]), 0);
  const cand = [];
  for (const p of elig) for (const a of Object.keys(p.options)) if (a in limits) cand.push([p.options[a] - p.recycle, p.asset_id, a, p]);
  cand.sort((x, y) => y[0] - x[0] || (x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0) || (x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0));
  for (const [gain, aid, a, p] of cand) {
    if (gain <= 0 || plan[aid] !== null || !fits(a, p.kwh)) continue;
    plan[aid] = a; used[a].packs++; used[a].kwh += p.kwh;
  }
  const greedy = total();
  for (let pass = 0; pass < MAX_PASSES; pass++) {
    let improved = false;
    for (const p of elig) {
      let cur = plan[p.asset_id];
      for (const a of [...Object.keys(p.options).sort(), null]) {
        if (a === cur || (a && !(a in limits))) continue;
        if (a && !fits(a, p.kwh)) continue;
        if (v(p, a) > v(p, cur) + 1e-9) {
          if (cur) { used[cur].packs--; used[cur].kwh -= p.kwh; }
          if (a) { used[a].packs++; used[a].kwh += p.kwh; }
          plan[p.asset_id] = cur = a; improved = true;
        }
      }
    }
    for (let i = 0; i < elig.length; i++) {
      for (let j = i + 1; j < elig.length; j++) {
        const p = elig[i], q = elig[j];
        const a = plan[p.asset_id], b = plan[q.asset_id];
        if (a === b || (a && !(a in q.options)) || (b && !(b in p.options))) continue;
        const gain = v(p, b) + v(q, a) - v(p, a) - v(q, b);
        if (gain <= 1e-9) continue;
        const dk = q.kwh - p.kwh;
        const ok = (!a || !("kwh" in limits[a]) || used[a].kwh + dk <= limits[a].kwh + 1e-9) && (!b || !("kwh" in limits[b]) || used[b].kwh - dk <= limits[b].kwh + 1e-9);
        if (ok) { if (a) used[a].kwh += dk; if (b) used[b].kwh -= dk; plan[p.asset_id] = b; plan[q.asset_id] = a; improved = true; }
      }
    }
    if (!improved) break;
  }
  const t = total();
  const perPack = packs.reduce((s, p) => s + (p.eligible ? Math.max(p.recycle, ...Object.values(p.options)) : p.recycle), 0);
  return { plan: Object.entries(plan).filter(([, a]) => a).map(([asset_id, application]) => ({ asset_id, application })),
    by_application: Object.fromEntries(Object.entries(used).map(([a, u]) => [a, { packs: Math.round(u.packs), kwh: Math.round(u.kwh * 1000) / 1000, limit: limits[a] }])),
    total_value: t, greedy_value: greedy, per_pack_greedy_value: perPack, value_gap_vs_per_pack_greedy: perPack - t,
    algorithm: "greedy + 2-opt", provenance: "modelled" };
}

// ---------------------------------------------------------------- passport (informational, not regulatory)
export async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
export async function passport(report, meta, insight, disposition = null, telemetryCsv = null) {
  const st = report.state || {};
  const soh = st.soh || {};
  const rul = st.rul_cycles_reference || null;
  const rec = report.recommendation || {};
  return {
    passport_version: "1.0", note: "informational, not a regulatory document",
    asset_id: report.asset_id, chemistry: report.chemistry, rated_capacity_ah: meta?.rated_capacity_ah ?? null,
    nominal_voltage_v: meta?.nominal_voltage_v ?? null, cycle_count: meta?.cycle_count ?? null,
    soh: { value: soh.value ?? null, provenance: soh.provenance ?? null, interval: rul ? [rul.lower ?? null, rul.upper ?? null] : null, note: soh.note ?? null },
    rul_cycles: rul ? { median: rul.value, lower: rul.lower ?? null, upper: rul.upper ?? null, provenance: rul.provenance } : null,
    gate: (report.gate || {}).verdict ?? null, decision: report.decision, disposition,
    top_reasons: insight.reasons.top.map((r) => ({ title: r.title, text: r.text, tone: r.tone })),
    confidence: { level: insight.confidence.level, score_0_100: insight.confidence.score_0_100, label: insight.confidence.label },
    provenance_summary: { data: report.data_provenance, placeholder_inputs: ((report.economics || {}).placeholder_inputs || []).length },
    engine: { name: "revive-tery-ml (web-studio JS port)", version: report.engine || null, report_schema: report.schema_version ?? null },
    input_telemetry_sha256: telemetryCsv ? await sha256Hex(telemetryCsv) : null,
    generated_utc: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
    net_value_usd: rec.application ? val(((report.economics || {}).second_life_options || {})[rec.application]?.net_value) : null,
  };
}
