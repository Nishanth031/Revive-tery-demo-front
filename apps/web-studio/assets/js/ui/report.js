// Renders full-engine and lite-analyzer reports. Every number keeps its provenance tag.
import { h, num, usd, tagged, prov, pill, statusPill, table, kv, card, kpi, banner, decisionCard, download, tabs, toneOfDecision, icon } from "./dom.js";
import { lineChart } from "./charts.js";
import { summarizeFull, summarizeLite } from "../engines/contract.js";

const isTag = (o) => o && typeof o === "object" && "provenance" in o && ("value" in o || "values" in o);

/** generic evidence renderer: tags become value + provenance badge, nested objects become nested lists */
export function evidence(obj, depth = 0) {
  if (obj === null || obj === undefined) return h("span", { class: "muted" }, "—");
  if (isTag(obj)) {
    if ("values" in obj && !("value" in obj)) return h("span", {}, h("code", {}, JSON.stringify(obj.values)), " ", prov(obj.provenance), obj.note ? h("small", {}, ` ${obj.note}`) : null);
    const extra = Object.entries(obj).filter(([k]) => !["value", "provenance", "unit", "note"].includes(k));
    const v = obj.value;
    const shown = v === null ? "—" : typeof v === "number" ? `${num(v, Math.abs(v) >= 100 ? 1 : 4)}${obj.unit ? ` ${obj.unit}` : ""}` : Array.isArray(v) ? JSON.stringify(v) + (obj.unit ? ` ${obj.unit}` : "") : typeof v === "object" ? JSON.stringify(v) : String(v);
    return h("span", {}, shown, " ", prov(obj.provenance), obj.note ? h("small", { class: "muted" }, ` — ${obj.note}`) : null,
      extra.length ? h("small", { class: "muted" }, ` (${extra.map(([k, x]) => `${k}: ${typeof x === "object" ? JSON.stringify(x) : x}`).join(", ")})`) : null);
  }
  if (Array.isArray(obj)) {
    if (obj.every((x) => typeof x !== "object" || x === null)) return h("code", {}, JSON.stringify(obj));
    return h("div", { class: "stack", style: { gap: "4px" } }, obj.map((x) => evidence(x, depth + 1)));
  }
  if (typeof obj === "object") return kv(Object.entries(obj).map(([k, v]) => [k.replace(/_/g, " "), evidence(v, depth + 1)]));
  return h("span", {}, typeof obj === "number" ? num(obj, Number.isInteger(obj) ? 0 : 4) : String(obj));
}

export function checksList(checks) {
  return h("div", { class: "checks" }, checks.map((c) => h("details", { class: "check" },
    h("summary", {}, statusPill(c.status), h("div", {}, h("div", { class: "name" }, c.name), h("div", { class: "msg" }, c.message)), h("small", { class: "muted mono" }, c.id)),
    h("div", { class: "body" }, h("div", { class: "muted", style: { fontSize: "12px", marginBottom: "6px" } }, `severity: ${c.severity}`), evidence(c.evidence)))));
}

function stepper(r) {
  const ready = r.data_quality.readiness.verdict;
  const dq = { t: "Data quality", s: ready.replace(/_/g, " "), c: ready === "NOT_READY" ? "stop" : ready === "READY" ? "ok" : "hold" };
  const gv = r.gate ? r.gate.verdict : null;
  const gate = { t: "Safety gate", s: gv || "not run", c: !gv ? "skip" : gv === "Reject" ? "stop" : gv === "Pass" ? "ok" : "hold" };
  const st = r.state ? (r.state.status === "ok" ? `SOH ${num(r.state.soh.value, 1)} %` : "insufficient") : "not run";
  const state = { t: "State (ML)", s: st, c: !r.state ? "skip" : r.state.status === "ok" ? "ok" : "stop" };
  const proj = { t: "Projection", s: r.projections ? `${Object.keys(r.projections).length} workloads` : "not run", c: r.projections ? "ok" : "skip" };
  const eco = { t: "Economics", s: r.economics ? r.economics.decision : "not run", c: r.economics ? "ok" : "skip" };
  return h("div", { class: "stepper" }, [dq, gate, state, proj, eco].map((s, i) =>
    h("div", { class: `step ${s.c}` }, h("div", { class: "n" }, `Stage ${i + 1}`), h("div", { class: "t" }, s.t), h("div", { class: "s" }, s.s))));
}

function gateCard(g) {
  const lim = g.limits;
  const body = [h("p", { class: "muted" }, g.wording)];
  body.push(h("div", { class: "row mb" }, pill(g.verdict, toneOfDecision(g.verdict === "Pass" ? "Pass" : g.verdict === "Reject" ? "Reject" : "Quarantine")), ...g.reasons.map((x) => h("span", { class: "muted" }, x))));
  if (lim.breaches.length) {
    body.push(table([{ key: "limit", label: "Limit" }, { key: "rows", label: "Rows", num: true }, { label: "Observed", render: (b) => tagged(b.observed, 3) },
      { label: "Threshold", render: (b) => tagged(b.threshold, 3) }], lim.breaches));
  }
  if (lim.open_safety_events.length) body.push(h("p", {}, `Open high-severity safety events: ${lim.open_safety_events.map((e) => `${e.event_type} (${e.severity}, ${e.status})`).join("; ")}`));
  body.push(h("ul", { class: "muted", style: { fontSize: "12.5px" } }, lim.notes.map((n) => h("li", {}, n))));
  const o = g.ood || {};
  if (o.window_scores) {
    body.push(h("h3", { class: "mt" }, "Out-of-distribution filter (IsolationForest)"));
    body.push(h("p", { class: "muted" }, `${o.description}. Model family: ${o.model_family} — trained on ${o.trained_on} (${o.training_provenance}).`));
    body.push(h("div", { class: "grid g4 mb" }, kpi("Windows", o.n_windows), kpi("Flagged", o.n_flagged_windows), kpi("Outside envelope", o.n_outside_envelope_windows), kpi("Flagged share", `${num(100 * o.flagged_fraction.value, 1)} %`)));
    body.push(lineChart({ series: [{ name: "window score", x: o.window_scores.map((_, i) => i + 1), y: o.window_scores, points: o.window_scores.length < 60 }],
      hlines: [{ y: o.threshold_score, label: "flag threshold (1st pct of healthy training windows)", color: "--bad" }], xLabel: "window", yLabel: "score", height: 200 }));
    body.push(h("p", { class: "muted", style: { fontSize: "12px" } }, o.rule));
    if (o.most_unusual_window) body.push(h("details", {}, h("summary", {}, "Most unusual window features"), evidence(o.most_unusual_window)));
  } else body.push(h("p", { class: "muted" }, `OOD filter: ${o.status}${o.note ? ` — ${o.note}` : ""}`));
  return card("Safety gate", body);
}

function stateCard(st) {
  if (st.status !== "ok") return card("State", h("p", {}, st.reason));
  const rul = st.rul_cycles_reference;
  const kp = [kpi("SOH (capacity test)", tagged(st.soh, 1), st.soh.note), kpi("Existing rule says", st.existing_rule, "kept for comparison only")];
  if (rul) kp.push(kpi("Remaining cycles to 80 %", h("span", {}, num(rul.value, 0), " ", prov("modelled")), `90 % CV+ interval ${num(rul.lower, 0)} – ${num(rul.upper, 0)} cycles at reference conditions`));
  kp.push(kpi("Fade rate", h("span", {}, st.fade_rate_ref.value.toExponential(2), " ", prov("modelled")), st.fade_rate_ref.unit));
  const body = [h("p", { class: "muted" }, st.method), h("div", { class: "grid g4 mb" }, kp)];
  if (st.warnings.length) body.push(...st.warnings.map((w) => banner("warn", "", w)));
  body.push(h("details", {}, h("summary", { style: { cursor: "pointer", fontWeight: 600 } }, "Field features fed to the model"),
    h("div", { class: "mt" }, table([{ key: "k", label: "Feature" }, { label: "Value", render: (r) => tagged(r.v, 4) }], Object.entries(st.features).map(([k, v]) => ({ k, v }))))));
  if (st.fold_predictions) body.push(h("p", { class: "muted mt", style: { fontSize: "12px" } }, `Fold models (cycles): ${st.fold_predictions.values.join(", ")}. ${st.distribution_shift_note || ""}`));
  if (st.reference_conditions) body.push(h("p", { class: "muted", style: { fontSize: "12px" } }, `Reference conditions: ${st.reference_conditions.values.note || JSON.stringify(st.reference_conditions.values)}`));
  return card("State (ML)", body);
}

export function projectionChart(p, minSoh) {
  const s = p.series;
  const pct = (a) => a.map((v) => 100 * v);
  return lineChart({
    series: [{ name: "central", x: s.years, y: pct(s.central), color: "--c1", width: 2.5 },
      { name: "knee scenario", x: s.years, y: pct(s.knee), color: "--c3", dash: "6 4" }],
    bands: [{ name: "ML interval (CV+)", x: s.years, lo: pct(s.ml_lower), hi: pct(s.ml_upper), color: "--c1", opacity: 0.22 },
      { name: "Monte Carlo 5–95 % (assumption-conditional)", x: s.years, lo: pct(s.mc_p05), hi: pct(s.mc_p95), color: "--c2", opacity: 0.14 }],
    hlines: [{ y: minSoh, label: `application limit ${minSoh} %`, color: "--warn" }],
    xLabel: "years", yLabel: "SOH %", height: 260, yMin: 0,
  });
}

function projectionsCard(projections) {
  const items = Object.entries(projections).map(([name, p]) => ({ id: name, label: p.workload.label, render: () => {
    const life = p.years_to_application_limit;
    const w = p.workload.values;
    return h("div", {},
      h("p", { class: "muted" }, `${p.label}. Workload (assumed): ${w.cycles_per_day} cycles/day, ${100 * w.daily_dod} % DoD, ${w.c_rate} C, ${w.ambient_c} °C ambient, limit ${w.min_soh_pct} % SOH. Stress factor ${num(p.stress_factor_nominal.value, 3)} reference cycles per real cycle.`),
      projectionChart(p, w.min_soh_pct),
      h("div", { class: "grid g4 mt" },
        kpi("Conservative life", h("span", {}, `${num(p.conservative_years.value, 1)} y `, prov("modelled")), p.conservative_years.note),
        kpi("Central path", life.central.value === null ? "> horizon" : `${num(life.central.value, 1)} y`),
        kpi("ML interval", `${life.ml_conservative.value === null ? "> 20" : num(life.ml_conservative.value, 1)} – ${life.ml_optimistic.value === null ? "> 20" : num(life.ml_optimistic.value, 1)} y`),
        kpi("Knee scenario", life.knee_scenario.value === null ? "> horizon" : `${num(life.knee_scenario.value, 1)} y`)),
      h("p", { class: "muted mt", style: { fontSize: "12px" } }, `${p.bands.ml_interval}. Monte Carlo: ${p.bands.monte_carlo}.`));
  } }));
  return card("Physics projection per workload", tabs(items));
}

function economicsCard(e) {
  const opts = Object.entries(e.second_life_options).map(([k, o]) => ({ k, ...o }));
  return card("Economics: Second-Life vs Recycle (Buy-New capped)", [
    h("div", { class: "grid g3 mb" }, kpi("Pack energy", tagged(e.pack_energy, 1)), kpi("Recycle now (net)", h("span", {}, usd(e.recycle.net_value.value), " ", prov("modelled"))),
      kpi("Discount rate", `${num(100 * e.discount_rate.value, 0)} %`, e.discount_rate.status)),
    table([{ key: "label", label: "Application" }, { label: "Years used", render: (o) => num(o.conservative_years.value, 1), num: true },
      { label: "Energy value", render: (o) => usd(o.gross_energy_value.value), num: true }, { label: "Buy-New cap", render: (o) => usd(o.buy_new_cap.value), num: true },
      { label: "Capped", render: (o) => (o.capped_by_buy_new ? "yes" : "no") }, { label: "Upfront", render: (o) => usd(o.upfront_costs.value), num: true },
      { label: "Later recycle (PV)", render: (o) => usd(o.end_of_life_recycle_pv.value), num: true }, { label: "Net value", render: (o) => h("b", {}, usd(o.net_value.value)), num: true },
      { label: "LCOS", render: (o) => (Number.isFinite(o.lcos_for_comparison.value) ? `$${num(o.lcos_for_comparison.value, 3)}/kWh` : "—"), num: true }], opts),
    h("div", { class: "grid g2 mt" },
      h("div", {}, h("h3", {}, "Recycle-now breakdown"), kv([["Nickel", usd(e.recycle.nickel_value.value)], ["Cobalt", usd(e.recycle.cobalt_value.value)], ["Lithium", usd(e.recycle.lithium_value.value)], ["Processing cost", `−${usd(e.recycle.processing_cost.value)}`], ["Net", h("b", {}, usd(e.recycle.net_value.value))]])),
      h("div", {}, h("h3", {}, "Placeholder inputs"), h("p", { class: "muted", style: { fontSize: "12.5px" } }, "Replace these with real tariffs and quotes before relying on any value:"), h("code", { style: { whiteSpace: "normal" } }, e.placeholder_inputs.join(", ")))),
    h("p", { class: "muted mt", style: { fontSize: "12px" } }, e.benchmark),
  ]);
}

/** a full-engine (revive-tery-ml) report */
export function renderFullReport(r, { bundle = null, notes = [], title = null } = {}) {
  const sum = summarizeFull(r, bundle);
  const out = h("div", { class: "stack" });
  if (title) out.append(h("h2", {}, title));
  out.append(decisionCard(`Full ML engine · ${r.asset_id} · ${r.chemistry} · ${r.data_provenance} data`, r.decision, (r.rationale || []).slice(0, 4)));
  for (const n of notes) out.append(banner("info", "", n));
  out.append(stepper(r));
  out.append(h("div", { class: "grid g4" },
    kpi("Readiness", sum.readiness.replace(/_/g, " "), r.data_quality.readiness.rule_applied),
    kpi("Safety gate", sum.gate || "not run", "UL 1974-style triage, not certification"),
    kpi("SOH", sum.soh_pct !== null ? `${num(sum.soh_pct, 1)} %` : sum.capacity_test_soh_pct !== null ? `${num(sum.capacity_test_soh_pct, 1)} %*` : "—",
      sum.soh_pct !== null ? "latest capacity test / rated" : sum.capacity_test_soh_pct !== null ? "*capacity test, not trusted by the engine" : "no capacity test"),
    kpi("Old fixed rule", sum.legacy_rule, "SOH > 80 / 60–80 / < 60 %")));
  if (r.comparison_with_existing_rule) {
    const c = r.comparison_with_existing_rule;
    out.append(banner(c.agree ? "good" : "info", c.agree ? "Agrees with the old rule." : "Differs from the old rule.", `Old rule: ${c.existing_rule}. ML + economics: ${c.ml_and_economics}. ${c.note}.`));
  }
  if (r.warnings.length) out.append(card("Warnings", h("ul", { style: { margin: 0, paddingLeft: "18px" } }, r.warnings.map((w) => h("li", {}, w)))));
  const ready = r.data_quality.readiness;
  out.append(card("Data quality", [
    h("div", { class: "row mb" }, pill(ready.verdict.replace(/_/g, " "), ready.verdict === "READY" ? "good" : ready.verdict === "NOT_READY" ? "bad" : "warn"),
      h("span", { class: "muted" }, `${ready.n_pass} pass · ${ready.n_warn} warn · ${ready.n_fail} fail · ${ready.n_inconclusive} inconclusive · ${ready.n_not_applicable} n/a`)),
    h("p", { class: "muted", style: { fontSize: "12.5px" } }, `${ready.rule_applied}. Rules: ${ready.rules.join(" · ")}. Inconclusive checks are excluded from the decision, never treated as a pass.`),
    checksList(r.data_quality.checks)]));
  if (r.stages_not_run) out.append(banner("bad", "Stopped at data quality.", `Stages not run: ${r.stages_not_run.join(", ")}. The engine refuses to project or price untrustworthy data.`));
  if (r.gate) out.append(gateCard(r.gate));
  if (r.state) out.append(stateCard(r.state));
  if (r.projections) out.append(projectionsCard(r.projections));
  if (r.economics) out.append(economicsCard(r.economics));
  out.append(h("div", { class: "row" },
    h("button", { class: "btn", onclick: () => download(`revive-report-${r.asset_id}.json`, JSON.stringify(stripSeries(r), null, 2)) }, icon("download", 16), "Download report JSON"),
    h("small", { class: "muted" }, `${r.engine} · schema ${r.schema_version} · generated ${r.generated_utc}`)));
  return out;
}
/** drop the dense chart series before exporting, so the JSON matches the Python report shape */
export function stripSeries(r) {
  const c = JSON.parse(JSON.stringify(r, (k, v) => (v === Infinity ? "Infinity" : v)));
  if (c.projections) for (const p of Object.values(c.projections)) delete p.series;
  if (c.gate && c.gate.ood) { delete c.gate.ood.window_scores; delete c.gate.ood.threshold_score; }
  if (c.state) delete c.state.fold_predictions;
  return c;
}

/** a lite-analyzer report */
export function renderLiteReport(r, { mapping = null, notes = [] } = {}) {
  const sum = summarizeLite(r, notes);
  const s = r.suggestion || {};
  const out = h("div", { class: "stack" });
  out.append(decisionCard(`Lite analyzer · ${r.battery_id} · ${r.data_provenance || "?"} data`, s.decision || "—", [s.reason].filter(Boolean)));
  for (const n of [...notes, ...r.warnings]) out.append(banner("info", "", n));
  const st = r.state || {};
  out.append(h("div", { class: "grid g4" },
    kpi("Safety gate", r.safety_gate ? r.safety_gate.verdict : "—", "UL 1974-style triage"),
    kpi("SoH", st.soh ? tagged(st.soh, 1) : "—", st.soh ? st.soh.note : (st.reason || "")),
    kpi("Fade", st.fade_rate && st.fade_rate.value !== null ? `${num(st.fade_rate.value, 4)} pts/cycle` : "—", st.cycles_observed ? `${st.cycles_observed} cycles observed` : ""),
    kpi("Old fixed rule", sum.legacy_rule)));
  if (r.safety_gate) {
    const g = r.safety_gate;
    out.append(card("Safety gate", [h("p", { class: "muted" }, g.wording), g.reasons.length ? h("ul", {}, g.reasons.map((x) => h("li", {}, x))) : h("p", {}, "No limit breached."),
      kv([["Min cell voltage", tagged(g.min_cell_voltage, 3)], ["Max temperature", tagged(g.max_temperature, 1)], ["Limits", evidence(g.limits)]]), h("small", { class: "muted" }, g.note)]));
  }
  if (st.capacity_by_cycle && st.capacity_by_cycle.length) {
    out.append(card("Capacity by cycle", lineChart({ series: [{ name: "max discharge capacity", x: st.capacity_by_cycle.map((e) => e[0]), y: st.capacity_by_cycle.map((e) => e[1]) }],
      hlines: st.rated_capacity ? [{ y: st.rated_capacity.value * 0.8, label: "80 % of rated", color: "--warn" }] : [], xLabel: "cycle", yLabel: "Ah", height: 220 })));
  }
  if (r.state) out.append(card("State estimate", evidence(Object.fromEntries(Object.entries(r.state).filter(([k]) => k !== "capacity_by_cycle")))));
  if (r.economics) {
    const e = r.economics;
    out.append(card("Economics (placeholder inputs)", [
      h("div", { class: "grid g3 mb" }, kpi("Pack energy now", tagged(e.pack_energy_now, 2)), kpi("Recycle now", usd(e.recycle_now.value)), kpi("New storage cost", `$${num(e.new_storage_cost_per_kwh_delivered.value, 3)}/kWh`, "per kWh delivered, benchmark")),
      e.options.length ? table([{ key: "use_case", label: "Use case" }, { key: "category", label: "Category" }, { label: "Years", render: (o) => num(o.service_years.value, 1), num: true },
        { label: "Energy value", render: (o) => usd(o.energy_value.value), num: true }, { label: "Buy-New cap", render: (o) => usd(o.buy_new_cap.value), num: true },
        { label: "Refurb cost", render: (o) => usd(o.refurbishment_cost.value), num: true }, { label: "Net", render: (o) => h("b", {}, usd(o.net_value.value)), num: true },
        { label: "$/kWh delivered", render: (o) => (o.cost_per_kwh_delivered.value === null ? "—" : num(o.cost_per_kwh_delivered.value, 3)), num: true }], e.options) : h("p", { class: "muted" }, "No use case qualifies at this SoH."),
      h("p", { class: "muted mt", style: { fontSize: "12px" } }, `Placeholder inputs: ${s.placeholder_inputs.join(", ")}`)]));
  }
  if (mapping) out.append(card("Column mapping", mappingTable(mapping)));
  out.append(h("div", {}, h("button", { class: "btn", onclick: () => download(`revive-lite-${r.battery_id}.json`, JSON.stringify(r, null, 2)) }, icon("download", 16), "Download report JSON")));
  return out;
}

export function mappingTable(mappings) {
  const rows = Object.entries(mappings).map(([src, m]) => ({ src, mapped: Object.entries(m.mapped).map(([a, b]) => `${a} → ${b}`).join(", "), unmapped: m.unmapped.join(", ") || "—", warnings: m.warnings.join("; ") || "—", rows: m.rows }));
  return table([{ key: "src", label: "Table" }, { key: "rows", label: "Rows", num: true }, { key: "mapped", label: "Mapped (explicit aliases only)" }, { key: "unmapped", label: "Unmapped (reported, never guessed)" }, { key: "warnings", label: "Warnings" }], rows);
}
