// Overview: what REVIVE-TERY does, the decision flow, the provenance legend and every engine in this app.
import { h, card, kpi, banner, prov, icon, PROV_HELP, num, pill } from "../ui/dom.js";

const ENGINES = [
  ["bench", "bolt", "Circuit Studio", "BMS engine (SOC by coulomb counting, live SOH with evidence basis), virtual replay of the demo pack, the simulated ESP32 with fault injection, and a real ESP32 over Web Serial (monitor-only).", "bulid X · bms_engine, esp32_sim, test_bench, run_controller"],
  ["analyze", "upload", "Analyze batteries", "Upload CSV, Excel or zip files. The lite analyzer maps headers and suggests a second life; the upload adapter builds a data-contract bundle and the full ML engine assesses it.", "bulid X · ml_analyzer_suggester, ml_engine_bridge, ml_panel"],
  ["dqlab", "flask", "Data-quality lab", "The 14 data-quality detectors and the readiness rules on reference bundles and every injected fault. Edit the metadata and re-run.", "revive-tery-ml · dq, gate, state, physics, econ, pipeline"],
  ["physics", "wave", "Physics projection", "Double-exponential fade with Arrhenius, depth-of-discharge and C-rate stress factors, calendar ageing, the ML hand-over and a 1,000-draw Monte Carlo band.", "revive-tery-ml · physics/fade"],
  ["economics", "coin", "Economics", "Second-Life vs Recycle with the Buy-New cap, sourced metal prices and the price-sensitivity sweep across chemistries.", "revive-tery-ml · econ/router, econ/sensitivity"],
  ["database", "db", "Database", "The eight demo tables, your uploads (ml_telemetry, ml_ingest_log), bench run logs (test_run_log) and assessment history.", "bulid X · database/ (DuckDB tables)"],
  ["evidence", "doc", "Model evidence", "Held-out metrics, CV+ coverage, gate detection rates, data-quality validation, physics sanity checks and the model cards.", "revive-tery-ml · reports, docs"],
  ["relife", "cell", "ReLife BMS Studio", "The PySide6 prototype's engine: 23 catalog profiles, five virtual adapters, scenario evaluation and the 30 s synthetic pulse test.", "Hackathon project ev · bms_engine, models"],
  ["hardware", "chip", "Firmware & hardware", "The bench wiring, the ESP32 sketch and its line protocol, with the low-voltage safety limits.", "bulid X · firmware/revive_tery_esp32"],
  ["backend", "plug", "Backend connector", "Talk to the local FastAPI backend (16 endpoints) when it is running on your machine.", "bulid X · backend/revive_api"],
];

export function render(root, app) {
  const v = app.assets.stateModel.validation;
  const gp = app.assets.gates.synthetic_packs;
  root.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "REVIVE-TERY Studio"),
      h("p", {}, "Triage for used EV batteries: is the data trustworthy, is the pack safe to handle, how healthy is it, how long will it last in a second life, and is that worth more than recycling? Every engine below runs in your browser — nothing is uploaded anywhere."))),
    banner("warn", "Synthetic data.", "All REVIVE-TERY datasets here are synthetic or simulated. Results show the pipeline works; they say nothing about a real battery. The safety gate is UL 1974-style triage — a screening step, not UL certification or a safety approval."),
    h("div", { class: "grid g4 mb" },
      kpi("State model", "HGB + CV+", `trained on Severson LFP cells; held-out coverage ${num(100 * v.measured_coverage, 1)} % at nominal ${num(100 * v.nominal_level, 0)} %`),
      kpi("Safety gate", "Limits + IForest", `${gp.nTrees} trees; ${gp.trainingSummary.train_windows?.toLocaleString?.() || ""} healthy training windows`),
      kpi("Data-quality checks", "14", "explicit rules; inconclusive is never a pass"),
      kpi("Monte Carlo draws", app.assets.mcParams.length.toLocaleString(), "physics-parameter priors, seed 0")),
  );

  const flow = [
    ["1", "Data quality", "14 detectors: timestamps, sign convention, charge balance, regen sign, resistance, nulls, dropouts, stuck values, spikes, ranges, temperature, estimate disagreement, provenance, sample size.", "NOT_READY stops here"],
    ["2", "Safety gate", "Chemistry limits (cell voltage, temperature, resistance growth, open safety events) then an IsolationForest out-of-distribution filter.", "Reject → recycling · Quarantine → inspection"],
    ["3", "State (ML)", "SOH from the latest capacity test; remaining cycles to 80 % from gradient boosting with a 90 % CV+ interval.", "Fallback: capacity-test trend"],
    ["4", "Projection", "Physics model anchored to the ML prediction, per workload: central path, ML band, Monte Carlo band, knee scenario.", "Labelled: projected (physics model)"],
    ["5", "Economics", "Discounted second-life value, capped at the cost of buying new, against recycling now.", "Second-Life: <application> or Recycle"],
  ];
  root.append(card("How a decision is made (full ML engine)", h("div", { class: "stepper" }, flow.map(([n, t, s, out]) =>
    h("div", { class: "step" }, h("div", { class: "n" }, `Stage ${n}`), h("div", { class: "t" }, t), h("div", { class: "s muted" }, s), h("div", { class: "s", style: { marginTop: "6px", fontWeight: 600 } }, out))))));

  root.append(h("div", { class: "grid g2 mt" },
    card("Every number carries its provenance", h("div", { class: "stack", style: { gap: "8px" } },
      Object.entries(PROV_HELP).map(([p, t]) => h("div", { class: "row" }, prov(p), h("span", { class: "muted" }, t))),
      h("p", { class: "muted", style: { fontSize: "12.5px", margin: 0 } }, "Simulated data is never tagged measured. Placeholder economic inputs are listed in every report."))),
    card("Two engines, compared honestly", h("div", { class: "stack", style: { gap: "6px" } },
      h("p", { style: { margin: 0 } }, h("b", {}, "Full ML engine"), " (revive-tery-ml): data contract, data quality, gate, ML state, physics, economics. Needs real timestamps."),
      h("p", { style: { margin: 0 } }, h("b", {}, "Lite analyzer"), " (ml_analyzer_suggester): header mapping, simple gate, capacity-based SoH and fade, placeholder economics. Works on cycler logs without timestamps."),
      h("p", { style: { margin: 0 } }, h("b", {}, "Old fixed rule"), ": SOH > 80 % stationary storage, 60–80 % low-speed EV, < 60 % recycle. Shown next to every result for comparison only.")))));

  root.append(h("h2", { class: "mt", style: { marginTop: "22px" } }, "Engines and software in this app"));
  root.append(h("div", { class: "grid g2" }, ENGINES.map(([id, ic, t, d, src]) =>
    h("a", { href: `#/${id}`, class: "card", style: { display: "block", color: "inherit", textDecoration: "none" } },
      h("div", { class: "row", style: { marginBottom: "6px" } }, h("span", { style: { color: "var(--accent)" } }, icon(ic, 20)), h("h3", { style: { margin: 0 } }, t)),
      h("p", { class: "muted", style: { margin: "0 0 6px" } }, d), pill(src, "neutral")))));

  root.append(card("Safety, by design", h("ul", { style: { margin: 0, paddingLeft: "18px" } },
    h("li", {}, "Monitor-only hardware: the app reads lines from the ESP32 and has no code path that writes to it."),
    h("li", {}, "Bench is low-voltage only. The INA219 is rated to 26 V; the firmware withholds readings and warns above it."),
    h("li", {}, "The gate never says a battery is safe: it rejects, quarantines for inspection, or passes it to the next screening step."),
    h("li", {}, "No value is invented: missing timestamps, capacity or temperature are reported, and the engine falls back or refuses with a reason.")), null, "mt"));
}
