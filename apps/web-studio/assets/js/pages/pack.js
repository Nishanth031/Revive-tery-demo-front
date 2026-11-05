// Pack detail: one battery through the full engine (dense SYNTHETIC telemetry), why the decision, how certain,
// what would change it (live what-if), what to do next, and the evidence tables. Screening only.
import { h, clear, card, banner, pill, icon, kpi, table, collapsible, attempt, usd, num, download, toast } from "../ui/dom.js";
import { lineChart, gauge, bars } from "../ui/charts.js";
import { convertDemo, telemetryRows } from "../engines/contract.js";
import { assess } from "../engines/pipeline.js";
import { insightFor, reroute, breakEven, passport, val } from "../engines/insight.js";
import { loadDecisionMap, disposition } from "../lib/disposition.js";
import { toCSV } from "../lib/csv.js";
import { chip, confChip } from "./command.js";
import { APPLICATIONS } from "../lib/fleet.js";

const TONE_ICON = { good: "check", bad: "x", warn: "alert", info: "doc" };
const param = (k) => new URLSearchParams(location.hash.split("?")[1] || "").get(k);
const downsample = (n, max = 300) => { const step = Math.max(1, Math.ceil(n / max)); const idx = []; for (let i = 0; i < n; i += step) idx.push(i); return idx; };
const reasonView = (r) => h("div", { class: `reason ${r.tone}` }, icon(TONE_ICON[r.tone] || "doc", 18),
  h("div", {}, h("b", {}, r.title), h("small", {}, r.text), h("small", { class: "mono", style: { color: "var(--text-3)" } }, `${r.metric} · ${r.provenance || ""}`)));

export async function render(root, app) {
  const id = param("id");
  const A = app.assets, cfg = A.configs;
  if (!id || !(app.demo.battery_registry || []).some((r) => r.asset_id === id) && !(app.demo.battery_asset || []).some((r) => r.asset_id === id)) {
    root.append(banner("warn", "Unknown pack.", `No pack ${id ? `"${id}"` : ""} in the fleet database. Pick one in the `), h("a", { href: "#/command" }, "Command Center"));
    return;
  }
  const reg = (app.demo.battery_registry || []).find((r) => r.asset_id === id) || {};
  const map = await loadDecisionMap();
  let bundle, report, ins;
  try {
    bundle = convertDemo(app.demo, id, { telemetry: "dense" });
    report = assess(bundle, A);
    ins = insightFor(report, cfg, { nRows: bundle.tel.n });
  } catch (e) {
    root.append(banner("bad", `${id} could not be assessed.`, e.message));
    return;
  }
  const disp = disposition(map, report.decision, report.recommendation?.application ?? null, cfg.workloads) || { code: "NO_DECISION", label: "No decision" };
  document.getElementById("page-title").textContent = id;
  document.title = `${id} · REVIVE-TERY`;

  // ---------------------------------------------------------------- verdict
  root.append(h("div", { class: "page-head row between" },
    h("div", {}, h("a", { href: "#/command", class: "muted no-print" }, "← Command Center"), h("h1", {}, id),
      h("div", { class: "row" }, pill(report.chemistry, "neutral"), APPLICATIONS[reg.application] ? pill(APPLICATIONS[reg.application], "neutral") : null,
        h("span", { class: "pill badge-syn" }, "SYNTHETIC data"), /TEST CASE/i.test(reg.demo_status || "") ? h("span", { class: "pill test-case" }, "test case: " + reg.demo_status.split(":").pop().trim()) : null,
        reg.registry_source ? h("small", { class: "muted" }, reg.registry_source) : null)),
    h("div", { class: "row no-print" },
      h("button", { class: "btn", type: "button", onclick: () => download(`${id}_report.json`, JSON.stringify({ ...report, insight: ins }, null, 1)) }, icon("download", 15), "Report JSON"),
      h("button", { class: "btn", type: "button", onclick: async () => {
        const csv = toCSV(bundle.tel.columns.includes("timestamp_utc") ? bundle.tel.columns : ["timestamp_utc", ...bundle.tel.columns], telemetryRows(bundle.tel));
        download(`${id}_passport.json`, JSON.stringify(await passport(report, bundle.meta, ins, disp, csv), null, 1));
        toast("Passport downloaded (informational, not a regulatory document)");
      } }, icon("shield", 15), "Battery passport"),
      h("button", { class: "btn", type: "button", onclick: () => window.print() }, icon("doc", 15), "Print"))));
  root.append(h("p", { class: "print-note" }, "REVIVE-TERY screening report. SYNTHETIC data; informational, not a regulatory document."));

  const conf = ins.confidence;
  root.append(h("div", { class: "grid g3" },
    card("Verdict", [h("div", { class: "row" }, chip(disp.code)), h("div", { class: "verdict-big mt" }, disp.label),
      h("p", { class: "muted mt" }, `Engine decision: ${report.decision}`),
      reg.lifecycle_status ? h("p", { class: "muted" }, `Registry status (SOH threshold rule): ${reg.lifecycle_status.replaceAll("_", " ").toLowerCase()}`) : null,
      h("div", { class: "row" }, pill(`data: ${report.data_provenance}`, "warn"), report.gate ? pill(`gate: ${report.gate.verdict}`, report.gate.verdict === "Pass" ? "good" : "warn") : pill("gate not run", "neutral"))]),
    card("Confidence (heuristic)", [gauge(conf.score_0_100, 100, `${conf.level} confidence`, "", conf.level === "High" ? "--good" : conf.level === "Medium" ? "--warn" : "--bad", 0),
      h("div", { class: "stack", style: { gap: "4px", fontSize: "12px" } }, conf.factors.map((f) => h("div", { class: "row between" }, h("span", { class: "muted" }, f.detail), h("b", { class: "mono" }, `${num(f.points, 1)}/${f.max}`))))]),
    card("Simple SOH rule vs the engine", (() => { const g = ins.rule_gap; return [
      h("div", { class: "row" }, pill(g.agrees ? "agree" : "disagree", g.agrees ? "good" : "warn")),
      h("p", { class: "mt" }, h("b", {}, "Simple SOH rule says: "), g.existing_rule || "—"), h("p", {}, h("b", {}, "Engine says: "), g.engine_decision),
      g.why_different.length ? h("ul", {}, g.why_different.map((w) => h("li", {}, w))) : null, h("small", { class: "muted" }, g.note)]; })())));

  // ---------------------------------------------------------------- why
  const all = h("div", { class: "reasons", style: { display: "none" } }, ins.reasons.all.map(reasonView));
  root.append(card("Why this decision", [h("div", { class: "reasons" }, ins.reasons.top.map(reasonView)),
    h("button", { class: "btn small mt no-print", type: "button", onclick: (e) => { const s = all.style.display === "none"; all.style.display = s ? "grid" : "none"; e.target.textContent = s ? "Hide the full list" : `Show all ${ins.reasons.all.length} reasons`; } }, `Show all ${ins.reasons.all.length} reasons`), all], null, "mt"));

  // ---------------------------------------------------------------- uncertainty
  const projKeys = Object.keys(report.projections || {});
  if (projKeys.length) {
    let wk = report.recommendation?.application || projKeys[0];
    const chartSlot = h("div");
    const drawProj = () => {
      const pj = report.projections[wk];
      const xs = pj.points.map((p) => p.year);
      clear(chartSlot).append(lineChart({
        series: [{ name: "central projection", x: xs, y: pj.points.map((p) => p.soh.value), color: "--c1", width: 2.5 }],
        bands: [{ name: "ML interval", x: xs, lo: pj.points.map((p) => p.ml_band.values[0]), hi: pj.points.map((p) => p.ml_band.values[1]), color: "--c2" },
          { name: "Monte Carlo 5-95 %", x: xs, lo: pj.points.map((p) => p.mc_band.values[0]), hi: pj.points.map((p) => p.mc_band.values[1]), color: "--c5" }],
        hlines: [{ y: pj.workload.values.min_soh_pct, label: `${pj.workload.label} limit ${pj.workload.values.min_soh_pct} %`, color: "--bad" }],
        xLabel: "years", yLabel: "SOH %", height: 240, legend: true }),
      h("small", { class: "muted" }, `${pj.bands.ml_interval}. ${pj.bands.monte_carlo}.`));
    };
    const sel = h("select", { "aria-label": "Workload", onchange: (e) => { wk = e.target.value; drawProj(); } }, projKeys.map((k) => h("option", { value: k, selected: k === wk }, report.projections[k].workload.label)));
    drawProj();
    const rr = ins.rul_range;
    const rulView = rr ? (() => { const hi = Math.max(rr.upper || rr.median, 1) * 1.1; return h("div", {},
      h("div", { class: "rulbar" }, h("div", { class: "span", style: { left: `${(100 * (rr.lower ?? rr.median)) / hi}%`, width: `${(100 * ((rr.upper ?? rr.median) - (rr.lower ?? rr.median))) / hi}%` } }),
        h("div", { class: "med", style: { left: `${(100 * rr.median) / hi}%` } })),
      h("div", { class: "row between mono", style: { fontSize: "12px" } }, h("span", {}, `lower ${num(rr.lower, 0)}`), h("b", {}, `median ${num(rr.median, 0)} cycles`), h("span", {}, `upper ${num(rr.upper, 0)}`)),
      h("small", { class: "muted" }, `CV+ interval, nominal ${rr.nominal_level}; measured coverage ${rr.measured_coverage} on held-out LFP cells${report.chemistry !== "LFP" ? ` (does NOT apply to ${report.chemistry})` : ""}.`)); })()
      : h("p", { class: "muted" }, "No remaining-life estimate: the engine stopped before the state stage.");
    root.append(h("div", { class: "grid g2 mt" }, card("Projection", [h("div", { class: "row mb" }, sel), chartSlot]), card("Remaining useful life (reference conditions)", rulView)));
  }

  // ---------------------------------------------------------------- economics + what-if
  if (report.economics) {
    const e = report.economics;
    const items = Object.entries(e.second_life_options).map(([k, o]) => ({ label: `${o.label}${o.capped_by_buy_new ? " (capped by buy-new)" : ""}${o.valuation_mode === "avoided_new_pack" ? " (avoided new pack)" : ""}`, value: val(o.net_value) }));
    items.push({ label: "Recycle now", value: val(e.recycle.net_value), color: "--d-recycle" });
    root.append(card("Economics: net value per option (modelled, placeholder inputs)", [bars(items, (v) => usd(v)),
      h("small", { class: "muted" }, `Placeholder inputs: ${e.placeholder_inputs.join(", ")}. Region: ${e.region || "global_default"}.`)], null, "mt"));
    root.append(whatIf(report, cfg, ins));
  } else {
    root.append(banner("info", "No economics for this pack.", "The engine stopped before the economics stage, so there is nothing to re-route. The next actions below say what would let it continue."));
  }

  // ---------------------------------------------------------------- next actions
  root.append(card("Next best actions", ins.next_actions.length ? h("ol", { class: "stack", style: { gap: "6px" } }, ins.next_actions.map((a) => h("li", {}, h("b", {}, a.action), h("div", { class: "muted", style: { fontSize: "12px" } }, `Why: ${a.why}. Effect: ${a.expected_effect}.`))))
    : h("p", { class: "muted" }, "Nothing would change this decision with the data at hand."), null, "mt"));

  // ---------------------------------------------------------------- evidence
  const checks = report.data_quality.checks;
  root.append(collapsible(`Data quality and safety gate (${report.data_quality.readiness.verdict})`, h("div", { class: "stack" },
    table([{ key: "id", label: "Check" }, { key: "status", label: "Status" }, { key: "message", label: "Message" }], checks),
    report.gate ? h("p", {}, h("b", {}, `Gate ${report.gate.verdict}: `), (report.gate.reasons || []).join("; ") || "no reasons") : null), false, "mt"));
  const idx = downsample(bundle.tel.n);
  const t0 = bundle.tel.t[0];
  const x = idx.map((i) => (bundle.tel.t[i] - t0) / 60);
  const ser = (c) => idx.map((i) => (bundle.tel[c] ? bundle.tel[c][i] : NaN));
  root.append(collapsible(`Telemetry (dense SYNTHETIC series, ${bundle.tel.n} rows, ${idx.length} plotted)`, h("div", { class: "grid g3" },
    lineChart({ series: [{ name: "voltage V", x, y: ser("voltage_v") }], xLabel: "minutes", yLabel: "V", height: 180 }),
    lineChart({ series: [{ name: "current A", x, y: ser("current_a"), color: "--c2" }], xLabel: "minutes", yLabel: "A", height: 180 }),
    lineChart({ series: [{ name: "temperature °C", x, y: ser("temperature_c"), color: "--c3" }], xLabel: "minutes", yLabel: "°C", height: 180 })), false, "mt"));
  const orig = (app.demo.telemetry || []).filter((r) => r.asset_id === id);
  root.append(collapsible(`Original sample (${orig.length} recorded rows, never changed)`, orig.length ? table(Object.keys(orig[0]).map((k) => ({ key: k, label: k })), orig) : h("p", { class: "muted" }, "This pack has no original telemetry rows (test cases only have the dense series)."), false, "mt"));
  const by = (t) => (app.demo[t] || []).filter((r) => r.asset_id === id);
  const hist = by("health_history").sort((a, b) => (a.assessment_date < b.assessment_date ? -1 : 1));
  root.append(collapsible(`Health history (${hist.length} capacity tests)`, hist.length ? h("div", { class: "grid g2" },
    lineChart({ series: [{ name: "SOH %", x: hist.map((_, i) => i + 1), y: hist.map((r) => Number(r.soh_pct)), color: "--c1" }], xLabel: "capacity test #", yLabel: "SOH %", height: 200 }),
    table([{ key: "assessment_date", label: "Date" }, { key: "cycle_count", label: "Cycles" }, { key: "measured_capacity_Ah", label: "Ah" }, { key: "soh_pct", label: "SOH %" }, { key: "internal_resistance_mOhm", label: "mOhm" }], hist))
    : h("p", { class: "muted" }, "No capacity tests."), false, "mt"));
  const ev = by("safety_events");
  root.append(collapsible(`Safety events (${ev.length})`, ev.length ? table(["timestamp_utc", "event_type", "severity", "observed_value", "threshold_value", "status"].map((k) => ({ key: k, label: k })), ev) : h("p", { class: "muted" }, "None recorded."), false, "mt"));
  const mods = by("modules"), mats = by("materials_recycling");
  root.append(collapsible(`Modules (${mods.length}) and materials (${mats.length})`, h("div", { class: "grid g2" },
    mods.length ? table(Object.keys(mods[0]).filter((k) => k !== "asset_id").map((k) => ({ key: k, label: k })), mods) : h("p", { class: "muted" }, "No modules recorded."),
    mats.length ? table(["component", "material", "estimated_mass_kg", "recovery_route"].map((k) => ({ key: k, label: k })), mats) : h("p", { class: "muted" }, "No materials recorded.")), false, "mt"));
}

// ---------------------------------------------------------------- what-if panel
function whatIf(report, cfg, ins) {
  const econ = cfg.economics;
  const base = { tariff: val(econ.second_life.value_per_kwh_delivered), cost_mult: 1, metal_mult: 1, new_cost: val(econ.buy_new_benchmark.installed_system_usd_per_kwh), discount_rate: val(econ.discount_rate), region: "" };
  const s = { ...base };
  const p = param("tariff");
  if (p !== null && Number.isFinite(Number(p))) s.tariff = Number(p);
  const regions = Object.keys(econ.second_life.regions || {});
  const out = h("div");
  const chartSlot = h("div");
  const SL = [["tariff", "Tariff (USD/kWh delivered)", 0, 0.30, 0.005, (v) => v.toFixed(3)], ["cost_mult", "Refurbish/test/install cost x", 0, 3, 0.05, (v) => `${v.toFixed(2)}x`],
    ["metal_mult", "Metal prices x", 0, 5, 0.05, (v) => `${v.toFixed(2)}x`], ["new_cost", "New storage USD/kWh", 50, 500, 5, (v) => v.toFixed(0)], ["discount_rate", "Discount rate", 0, 0.25, 0.005, (v) => `${(100 * v).toFixed(1)} %`]];
  const labels = {};
  const inputs = {};
  let timer = null;
  const schedule = () => { clearTimeout(timer); timer = setTimeout(update, 150); };
  const sliders = SL.map(([k, l, mn, mx, st, fmt]) => {
    labels[k] = h("b", { class: "mono" }, fmt(s[k]));
    inputs[k] = h("input", { type: "range", min: mn, max: mx, step: st, value: s[k], "aria-label": l, oninput: (e) => { s[k] = Number(e.target.value); labels[k].textContent = fmt(s[k]); schedule(); } });
    return h("div", { class: "slider" }, h("span", {}, l), inputs[k], labels[k]);
  });
  const regionSel = h("select", { "aria-label": "Region", onchange: (e) => { s.region = e.target.value; schedule(); } },
    h("option", { value: "" }, "Region: global_default"), regions.filter((r) => r !== "global_default").map((r) => h("option", { value: r }, `${r} (${econ.second_life.regions[r].status})`)));
  const reset = h("button", { class: "btn small", type: "button", onclick: () => { Object.assign(s, base); for (const [k, , , , , fmt] of SL) { inputs[k].value = s[k]; labels[k].textContent = fmt(s[k]); } regionSel.value = ""; update(); } }, "Reset");
  let last = null;
  function update() {
    const o = { cost_mult: s.cost_mult, metal_mult: s.metal_mult, new_cost: s.new_cost, discount_rate: s.discount_rate, region: s.region || null };
    if (!s.region) o.tariff = s.tariff;
    const r = attempt("What-if", () => reroute(report, cfg, o));
    if (!r || r instanceof Node) { clear(out).append(r || banner("info", "", "Nothing to re-route.")); return; }
    const be = breakEven(report, cfg, "tariff", { ...o, tariff: undefined });
    const flipped = last !== null && last !== r.decision;
    last = r.decision;
    clear(out).append(h("div", { class: `grid g3 ${flipped ? "flip" : ""}` },
      kpi("Decision under these inputs", r.decision, r.decision === report.decision ? "same as the engine's" : "CHANGED from the engine's decision"),
      kpi("Best second-life net", usd(r.best_net), r.application ? r.application.replaceAll("_", " ") : "—"),
      kpi("Recycle now", usd(r.recycle_net), "metal value minus processing")),
    h("p", { class: "mt" }, ins.robustness ? `Today's decision holds in ${(100 * ins.robustness.share_same_decision).toFixed(0)} % of ${ins.robustness.scenarios} tested scenarios; ` : "",
      be ? `break-even tariff = ${be.value.toFixed(3)} USD/kWh (below: ${be.below}, above: ${be.above}).` : "no break-even tariff in 0-1 USD/kWh."));
    // tariff chart: best second-life net vs recycling across tariffs, with the break-even marked
    const xs = Array.from({ length: 31 }, (_, i) => i * 0.01);
    const rs = xs.map((t) => reroute(report, cfg, { ...o, region: null, tariff: t }));
    const ys = rs.map((x) => x.best_net), yr = rs.map((x) => x.recycle_net);
    const series = [{ name: "best second-life net", x: xs, y: ys, color: "--c1", width: 2.5 }, { name: "recycle now", x: xs, y: yr, color: "--d-recycle", dash: "5 4" }];
    if (be) { const lo = Math.min(...ys, ...yr), hi = Math.max(...ys, ...yr); series.push({ name: `break-even ${be.value.toFixed(3)}`, x: [be.value, be.value], y: [lo, hi], color: "--bad", dash: "2 3" }); }
    if (!s.region) series.push({ name: "your tariff", x: [s.tariff, s.tariff], y: [Math.min(...ys, ...yr), Math.max(...ys, ...yr)], color: "--c4", dash: "6 3" });
    clear(chartSlot).append(lineChart({ series, xLabel: "tariff USD/kWh", yLabel: "USD", height: 230, legend: true }));
  }
  update();
  return card("What if? (re-runs only the economics stage, live)", [h("div", { class: "grid g2" },
    h("div", { class: "stack" }, sliders, h("div", { class: "row" }, regionSel, reset), h("small", { class: "muted" }, "Region overrides the tariff slider. Sourced regions carry their source in configs/economics.yaml; PLACEHOLDER values are not market data.")),
    h("div", {}, out)), chartSlot], null, "mt");
}
