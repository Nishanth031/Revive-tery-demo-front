// Fleet data layer: one compact record per pack (built from the engine's real report), filters, summary, funnel.
// Pure functions: used by tools/make_fleet_reports.mjs (Node), the Command Center and the fleet Web Worker.

export const DISPOSITIONS = ["REUSE", "REPURPOSE", "RECYCLE", "INSPECT", "NO_DECISION"];
export const DISPOSITION_LABEL = { REUSE: "Reuse", REPURPOSE: "Repurpose", RECYCLE: "Recycle", INSPECT: "Inspect", NO_DECISION: "No decision" };
export const APPLICATIONS = { CAR: "Car", BUS: "Bus", "2W": "Two-wheeler", "3W": "Three-wheeler", ESS: "Stationary" };
export const REGISTRY_STATUSES = ["IN_SERVICE", "SECOND_LIFE_CANDIDATE", "END_OF_LIFE_RECYCLE"];
const val = (t) => (t && typeof t === "object" ? t.value ?? null : t ?? null);

/** the compact fleet record for one pack; `insight` (optional) comes from engines/insight.js */
export function summarizeForFleet(id, reg, bundle, report, disp, assets = null, insight = null) {
  const state = report.state || {};
  const econ = report.economics || {};
  const rec = report.recommendation || {};
  const opts = econ.second_life_options || {};
  const best = rec.application || Object.keys(opts).sort((a, b) => val(opts[b].net_value) - val(opts[a].net_value))[0] || null;
  const proj = report.projections || {};
  const dq = report.data_quality || { checks: [], readiness: {} };
  const tests = bundle?.meta?.capacity_tests || [];
  const last = tests[tests.length - 1];
  const rated = bundle?.meta?.rated_capacity_ah ?? null;
  const rul = state.rul_cycles_reference;
  const gate = report.gate || null;
  return {
    asset_id: id,
    chemistry: report.chemistry ?? bundle?.meta?.chemistry ?? null,
    chemistry_label: reg.chemistry ?? null,
    application: reg.application || null,
    registry_status: reg.lifecycle_status || null,
    registry_source: reg.registry_source || null,
    test_case: /TEST CASE/i.test(reg.demo_status || ""),
    demo_status: reg.demo_status || null,
    data_provenance: report.data_provenance,
    decision: report.decision,
    disposition: disp ? disp.code : "NO_DECISION",
    readiness: dq.readiness?.verdict ?? null,
    dq_pass: dq.readiness?.n_pass ?? null, dq_total: dq.readiness?.n_checks ?? null,
    failing: dq.checks.filter((c) => c.status === "fail").map((c) => c.id),
    gate: gate?.verdict ?? null,
    ood: gate?.ood?.status ?? null,
    soh: val(state.soh),
    soh_test: last && rated ? (100 * last.measured_capacity_ah) / rated : null,
    cycles: bundle?.meta?.cycle_count ?? null,
    rul: rul ? { median: rul.value, lower: rul.lower ?? null, upper: rul.upper ?? null } : null,
    best_application: best,
    best_label: best && opts[best] ? opts[best].label : null,
    net_value: best && opts[best] ? val(opts[best].net_value) : null,
    recycle_value: econ.recycle ? val(econ.recycle.net_value) : null,
    capped_by_buy_new: best && opts[best] ? Boolean(opts[best].capped_by_buy_new) : null,
    years: best && proj[best] ? val(proj[best].conservative_years) : null,
    pack_kwh: val(econ.pack_energy) ?? (rated && bundle?.meta?.nominal_voltage_v ? (rated * bundle.meta.nominal_voltage_v) / 1000 : null),
    stages: { data_quality: true, gate: Boolean(gate), state: Boolean(report.state), projection: Object.keys(proj).length > 0, economics: Boolean(report.economics) },
    rule: report.comparison_with_existing_rule ? { existing: report.comparison_with_existing_rule.existing_rule, agree: report.comparison_with_existing_rule.agree } : null,
    options: Object.fromEntries(Object.entries(opts).map(([k, o]) => [k, val(o.net_value)])),
    insight,
  };
}

/** the insight block without the bulky parts (full reason list, the grid) for the fleet file */
export function compactInsight(ins) {
  if (!ins) return null;
  const rob = ins.robustness;
  return { reasons: ins.reasons.top, confidence: ins.confidence, rul_range: ins.rul_range, years_range: ins.years_range,
    robustness: rob ? { share_same_decision: rob.share_same_decision, scenarios: rob.scenarios, break_even_tariff: rob.break_even_tariff, flips: rob.flips.length } : null,
    next_actions: ins.next_actions, rule_gap: ins.rule_gap };
}

/** fleet-plan input for engines/insight.js assign(): eligible = routed to a second life by the engine */
export const planInput = (packs) => packs.map((p) => ({ asset_id: p.asset_id, eligible: p.disposition === "REUSE" || p.disposition === "REPURPOSE",
  kwh: p.pack_kwh && (p.soh ?? p.soh_test) ? (p.pack_kwh * (p.soh ?? p.soh_test)) / 100 : 0, options: p.options || {}, recycle: p.recycle_value ?? 0 }));

// ---------------------------------------------------------------- filters, sort, paging
export const SORTS = {
  net_value: (p) => p.net_value ?? -Infinity,
  soh: (p) => p.soh ?? p.soh_test ?? -Infinity,
  rul: (p) => p.rul?.median ?? -Infinity,
  confidence: (p) => p.insight?.confidence?.score_0_100 ?? -Infinity,
  asset_id: (p) => p.asset_id,
};

/** f: { q, disp, chem, app, status, source, conf, sort, dir } (all optional) */
export function filterPacks(packs, f = {}) {
  const q = (f.q || "").trim().toLowerCase();
  let out = packs.filter((p) =>
    (!q || p.asset_id.toLowerCase().includes(q)) &&
    (!f.disp || p.disposition === f.disp) &&
    (!f.chem || p.chemistry === f.chem) &&
    (!f.app || p.application === f.app) &&
    (!f.status || p.registry_status === f.status) &&
    (!f.source || (f.source === "test" ? p.test_case : f.source === "user" ? /user fleet/i.test(p.registry_source || "") : !/user fleet/i.test(p.registry_source || "") && !p.test_case)) &&
    (!f.conf || p.insight?.confidence?.level === f.conf));
  const key = SORTS[f.sort] || null;
  if (key) {
    const dir = f.dir === "asc" ? 1 : -1;
    out = [...out].sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * dir; });
  }
  return out;
}
export const page = (rows, n, size = 25) => rows.slice((n - 1) * size, n * size);

// ---------------------------------------------------------------- summary
export function fleetSummary(packs) {
  const by = Object.fromEntries(DISPOSITIONS.map((d) => [d, 0]));
  for (const p of packs) by[p.disposition] = (by[p.disposition] || 0) + 1;
  const second = packs.filter((p) => p.disposition === "REUSE" || p.disposition === "REPURPOSE");
  const netSecond = second.reduce((a, p) => a + (p.net_value ?? 0), 0);
  const recycleAll = packs.reduce((a, p) => a + (p.recycle_value ?? 0), 0);
  const recycleOthers = packs.filter((p) => !second.includes(p)).reduce((a, p) => a + (p.recycle_value ?? 0), 0);
  const kwh = second.reduce((a, p) => a + (p.pack_kwh && (p.soh ?? p.soh_test) ? (p.pack_kwh * (p.soh ?? p.soh_test)) / 100 : 0), 0);
  return {
    n: packs.length, by_disposition: by,
    funnel: [
      ["All packs", packs.length],
      ["Data ready", packs.filter((p) => p.readiness && p.readiness !== "NOT_READY").length],
      ["Safe (gate pass)", packs.filter((p) => p.gate === "Pass").length],
      ["State estimated", packs.filter((p) => p.gate === "Pass" && p.soh !== null).length],
      ["Second life chosen", second.length],
    ],
    // engine routing vs recycling everything now (modelled, placeholder cost inputs)
    net_value_routed: netSecond + recycleOthers, net_value_recycle_all: recycleAll,
    kwh_redeployed: kwh,
    inspect_share: packs.length ? by.INSPECT / packs.length : 0,
    test_cases: packs.filter((p) => p.test_case).length,
  };
}

// ---------------------------------------------------------------- loading (browser)
const cacheKey = (meta) => `rt-fleet:${meta?.generated_utc || "unknown"}`;

/** The fleet: live API (/api/fleet) when it answers, else data/fleet_reports.json (precomputed by
 *  tools/make_fleet_reports.mjs), else computed in a Web Worker and cached in localStorage per DB version. */
export async function loadFleet(app, onProgress = () => {}) {
  if (app.apiLive) {
    try {
      const { getBase } = await import("./mlApi.js");
      const r = await fetch(`${getBase().replace(/\/+$/, "")}/api/fleet?limit=1000&compact=true`);
      if (r.ok) { const body = await r.json(); if (body.packs?.length) return { ...body, source: "live API" }; }
    } catch { /* fall back to the snapshot */ }
  }
  try {
    const r = await fetch("data/fleet_reports.json");
    if (r.ok) return { ...(await r.json()), source: "snapshot" };
  } catch { /* compute below */ }
  try {
    const hit = localStorage.getItem(cacheKey(app.meta));
    if (hit) return { ...JSON.parse(hit), source: "computed in this browser (cached)" };
  } catch { /* storage blocked */ }
  const out = await new Promise((resolve, reject) => {
    const w = new Worker(new URL("../workers/fleet.worker.js", import.meta.url), { type: "module" });
    w.onmessage = (e) => {
      if (e.data.type === "progress") onProgress(e.data.done, e.data.total);
      else if (e.data.type === "done") { w.terminate(); resolve(e.data.result); }
      else if (e.data.type === "error") { w.terminate(); reject(new Error(e.data.message)); }
    };
    w.onerror = (e) => { w.terminate(); reject(new Error(e.message)); };
  });
  try { localStorage.setItem(cacheKey(app.meta), JSON.stringify(out)); } catch { /* too big or blocked: fine */ }
  return { ...out, source: "computed in this browser" };
}
