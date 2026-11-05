// Model evidence: the ML engine's validation reports and model cards, shown as they were written.
import { h, card, kpi, num, tabs, banner } from "../ui/dom.js";
import { evidence } from "../ui/report.js";
import { markdown } from "../lib/md.js";

const REPORTS = [
  ["state_metrics", "State model metrics"], ["gate_validation", "Gate validation"], ["dq_validation", "Data-quality validation"],
  ["physics_sanity", "Physics sanity"], ["severson_etl_log", "Severson ETL log"], ["download_log", "Dataset downloads"],
];
const DOCS = [["state_rul", "State: RUL model card"], ["state_soh_crosscheck", "State: SOH cross-check"], ["gate_ood", "Gate: OOD filter card"],
  ["physics_projection", "Physics projection card"], ["judge_qa", "Judge Q&A"]];

export async function render(root, app) {
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Model evidence"),
    h("p", {}, "How well the models work, measured on data they never saw — and where they don't apply. These are the reports the Python engine wrote when it was trained."))));
  const [reports, docs] = await Promise.all([
    Promise.all(REPORTS.map(([f]) => app.fetchJSON(`data/reports/${f}.json`).catch(() => null))),
    Promise.all(DOCS.map(([f]) => app.fetchText(`data/docs/${f}.md`).catch(() => ""))),
  ]);
  const v = app.assets.stateModel.validation;
  const gv = app.assets.gates.synthetic_packs.validation || {};
  root.append(h("div", { class: "grid g4 mb" },
    kpi("CV+ coverage (held-out cells)", `${num(100 * v.measured_coverage, 1)} %`, `nominal ${num(100 * v.nominal_level, 0)} %; measured on Severson LFP cells`),
    kpi("Selected RUL model", v.selected.replace(/_/g, " "), "field features only"),
    kpi("Gate: clean packs quarantined", gv.clean_quarantine_rate !== undefined ? `${num(100 * gv.clean_quarantine_rate, 1)} %` : "—", "synthetic pack family"),
    kpi("Gate: spikes detected", gv.detection_rate ? `${num(100 * gv.detection_rate.voltage_spikes, 0)} %` : "—", gv.detection_rate ? `dropouts ${num(100 * gv.detection_rate.voltage_dropout, 0)} %, slow drift ${num(100 * gv.detection_rate.voltage_drift, 0)} %` : "")));
  root.append(banner("info", "Read the limits too.", "The gate catches spikes and dropouts well but misses slow drifts — that's what the data-quality checks and capacity tests are for. Second-life packs are a distribution shift from the training cells, so coverage on real packs is unknown."));
  root.append(card("Reports", tabs(REPORTS.map(([f, l], i) => ({ id: f, label: l, render: () => (reports[i] ? evidence(reports[i]) : h("p", { class: "muted" }, "Not available.")) })))));
  root.append(card("Model cards and Q&A", tabs(DOCS.map(([f, l], i) => ({ id: f, label: l, render: () => h("div", { class: "md", html: markdown(docs[i]) }) }))), null, "mt"));
}
