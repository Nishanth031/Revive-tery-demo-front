// End-to-end assessment (port of revive_ml/pipeline.py):
// data quality -> safety gate -> state -> physics projection -> economics.

import { runAll, readiness } from "./dq.js";
import * as gate from "./gate.js";
import { StateModel, estimate } from "./state.js";
import { project, drawParams } from "./physics.js";
import { route } from "./econ.js";
import { OODFilter } from "./gate.js";
import { dataProvenanceTag } from "../lib/provenance.js";

export const SCHEMA_VERSION = 1;
export const ENGINE = "revive-tery-ml 0.1.0 (browser port)";
export const INSUFFICIENT = "Insufficient or untrustworthy data";
export const INSPECTION = "Inspection required";

/** Load every model and config the engine needs. `read(path)` returns parsed JSON (fetch in the browser, fs in Node). */
export async function loadAssets(read) {
  const [configs, state, gp, gc, mc] = await Promise.all([
    read("data/configs.json"), read("data/models/state_rul.json"), read("data/models/gate_ood_synthetic_packs.json"),
    read("data/models/gate_ood_measured_cells.json"), read("data/models/mc_draws.json"),
  ]);
  return {
    configs,
    stateModel: new StateModel(state),
    gates: { synthetic_packs: new OODFilter(gp), measured_cells: new OODFilter(gc) },
    mcParams: drawParams(mc),
    raw: { state, gp, gc, mc },
  };
}

/** ML -> physics hand-over: reference cycles to an anchor SOH, the anchor, and ML coverage */
export function physicsAnchor(st) {
  if (st.rul_cycles_reference) {
    const r = st.rul_cycles_reference;
    return [{ point: r.value, lower: r.lower, upper: r.upper }, 0.80, r.measured_coverage_on_held_out_cells ?? null];
  }
  const soh0 = st.soh.value / 100.0, drop = 0.10;
  return [{ point: drop / st.fade_rate_ref.value, lower: drop / st.fade_rate_ref_conservative.value,
    upper: drop / st.fade_rate_ref_optimistic.value }, soh0 - drop, null];
}

export function tagWorkload(w, user) {
  const { label = "", ...values } = w;
  return { label, provenance: "assumed", source: user ? "user-supplied workload" : "configs/workloads.yaml (default)", values };
}

export function assess(bundle, assets, workloads = null, region = null) {
  const meta = bundle.meta;
  const cfg = assets.configs;
  const warnings = [];
  if (meta.data_provenance !== "measured") {
    warnings.push(`Data provenance is '${meta.data_provenance}'. Every value read from it is tagged 'synthetic'. This report shows ` +
      "the pipeline works; it says nothing about a real battery.");
  }
  if (bundle.ignored_columns.length) warnings.push(`Ignored telemetry columns not in the contract: [${bundle.ignored_columns.map((c) => `'${c}'`).join(", ")}]`);
  const checks = runAll(bundle, cfg.dq_rules);
  const ready = readiness(checks);
  const report = {
    schema_version: SCHEMA_VERSION, engine: ENGINE, generated_utc: new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00"),
    asset_id: meta.asset_id, chemistry: meta.chemistry, data_provenance: meta.data_provenance,
    value_provenance_for_data: dataProvenanceTag(meta.data_provenance),
    data_quality: { checks, readiness: ready }, gate: null, state: null, projections: null, economics: null, recommendation: null, warnings,
  };
  for (const c of checks) if (c.status === "warn" || c.status === "inconclusive") warnings.push(`[${c.id}] ${c.message}`);
  if (ready.verdict === "NOT_READY") {
    report.decision = INSUFFICIENT;
    report.rationale = checks.filter((c) => c.status === "fail").map((c) => `data-quality check '${c.id}' failed: ${c.message}`);
    report.stages_not_run = ["gate", "state", "projections", "economics", "recommendation"];
    return report;
  }
  const g = gate.evaluate(bundle, assets);
  report.gate = g;
  if (g.verdict === "Reject") {
    report.decision = "Reject (safety triage): route to recycling";
    report.rationale = g.reasons;
    return report;
  }
  const st = estimate(bundle, assets.stateModel, new Set(ready.excluded_from_decision));
  warnings.push(...(st.warnings || []).map((w) => `[state] ${w}`));
  report.state = st;
  const wl = workloads || cfg.workloads.workloads;
  if (st.status === "ok" && st.fade_rate_ref) {
    const [anchor, target, coverage] = physicsAnchor(st);
    report.projections = Object.fromEntries(Object.entries(wl).map(([name, w]) =>
      [name, { workload: tagWorkload(w, workloads !== null), ...project(cfg.physics, assets.mcParams, st.soh.value, anchor, w, coverage, target) }]));
  }
  if (g.verdict === "Quarantine") {
    report.decision = INSPECTION;
    report.rationale = g.reasons;
    return report;
  }
  if (st.status !== "ok") {
    report.decision = INSUFFICIENT;
    report.rationale = [st.reason || "state estimate unavailable"];
    return report;
  }
  const econ = route(meta, st, report.projections || {}, cfg.economics, region);
  report.economics = econ;
  report.decision = econ.decision || "No recommendation (economics unavailable)";
  report.recommendation = econ.recommendation;
  report.rationale = econ.rationale || [];
  const rule = st.existing_rule;
  report.comparison_with_existing_rule = {
    existing_rule: rule, ml_and_economics: report.decision,
    agree: Boolean(rule && rule.split(":")[0] === report.decision.split(":")[0]),
    note: "existing rule: SOH > 80 % stationary storage, 60-80 % low-speed EV, < 60 % recycle; shown for comparison only",
  };
  return report;
}
