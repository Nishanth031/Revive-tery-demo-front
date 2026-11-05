// Data Quality Lab: one page, four tabs.
//   1. Data quality  - the full engine on reference bundles and every injected fault; editable metadata
//   2. Physics       - the ML hand-over projected under a workload (double-exponential fade, Monte Carlo band)
//   3. Economics     - Second-Life vs Recycle what-if and the price-sensitivity sweep
//   4. Field test    - a simulated bench discharge through the BMS engine, with five live charts
// Each tab is built once and kept, so slider settings and a running field test survive tab switches.
import { h, clear, card, kpi, banner, field, select, numberInput, icon, pill, download, spinnerBox, num, usd, prov, table, tabs,
  collapsible, decisionCard } from "../ui/dom.js";
import { renderFullReport, projectionChart } from "../ui/report.js";
import { lineChart, bars } from "../ui/charts.js";
import { loadBundle, telemetryRows, parseIso } from "../engines/contract.js";
import { assess } from "../engines/pipeline.js";
import { project, stressFactor, nominalParams } from "../engines/physics.js";
import { recycleValue, secondLifeValue, sweep, referenceProjection, metalPricesUsdPerKg } from "../engines/econ.js";
import { RunController, SIM_MAX_LOAD_A } from "../engines/runController.js";
import { INA219_MAX_BUS_VOLTAGE_V } from "../engines/esp32sim.js";
import { loadBatteryProfile, listBatteryIds } from "../engines/bms.js";
import { toCSV } from "../lib/csv.js";

const TABS = [["quality", "Data quality"], ["physics", "Physics projection"], ["economics", "Economics"], ["field", "Field test"]];
let fieldController = null;

export function render(root, app) {
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Data Quality Lab"),
    h("p", {}, "The full engine's stages, one at a time: which data-quality check catches a fault, how the physics model projects life, what the economics decide, and a simulated field test through the BMS engine."))));
  const builders = { quality: dataQualityTab, physics: physicsTab, economics: economicsTab, field: fieldTestTab };
  const built = {};
  const initial = (/[?&]tab=(\w+)/.exec(location.hash) || [])[1];
  root.append(tabs(TABS.map(([id, label]) => ({ id, label, render: () => (built[id] ||= safeBuild(label, () => builders[id](app))) })),
    null, TABS.some(([id]) => id === initial) ? initial : "quality"));
}

export function unmount() {
  if (fieldController) { fieldController.stop(); fieldController = null; }
}

function safeBuild(label, fn) {
  try { return fn(); } catch (e) { console.error(e); return banner("bad", `${label} failed to load.`, String(e.message || e)); }
}
const slider = (label, get, set, min, max, step, onchange, fmt = (v) => v) => {
  const o = h("output", {}, fmt(get()));
  return field(label, h("div", { class: "range-row" }, h("input", { type: "range", min, max, step, value: get(),
    oninput: (e) => { set(Number(e.target.value)); o.textContent = fmt(get()); onchange(); } }), o));
};

// ======================================================================== 1. Data quality
function dataQualityTab(app) {
  const root = h("div", { class: "stack" });
  const wait = spinnerBox("Loading reference bundles…");
  root.append(h("p", { class: "muted", style: { margin: 0 } }, "Pick a clean synthetic pack, a safety-gate case or one of the injected faults, and see which of the 14 checks catches it. Edit the metadata (sign convention, chemistry, capacity tests…) and re-run."), wait);
  app.getBundles().then((bundles) => { wait.remove(); buildQuality(root, app, bundles); })
    .catch((e) => wait.replaceWith(banner("bad", "Could not load the reference bundles.", `${e.message}. Check that data/bundles.json is served.`)));
  return root;
}

function buildQuality(root, app, bundles) {
  let name = "clean_lfp";
  const groups = {};
  for (const n of Object.keys(bundles)) (groups[bundles[n].group] ||= []).push(n);
  const picker = h("select", { onchange: (e) => { name = e.target.value; load(); } },
    Object.entries(groups).map(([g, ns]) => h("optgroup", { label: g }, ns.map((n) => h("option", { value: n, selected: n === name }, n.replace(/^fault_/, "fault: ").replace(/_/g, " "))))));
  const meta = h("textarea", { rows: 12, spellcheck: "false", "aria-label": "Bundle metadata JSON" });
  const info = h("div"), chart = h("div"), out = h("div");
  root.append(h("div", { class: "grid g2" },
    card("Bundle", [field("Example", picker), info, h("div", { class: "row mt" },
      h("button", { class: "btn primary", onclick: runIt }, icon("play", 15), "Run the full engine"),
      h("button", { class: "btn", onclick: () => { meta.value = JSON.stringify(bundles[name].metadata, null, 2); runIt(); } }, "Reset metadata"),
      h("button", { class: "btn", onclick: exportZip }, icon("download", 15), "Bundle .zip"))]),
    card("metadata.json (editable)", [meta, h("small", { class: "muted" }, "Validated against the data contract before running: unknown fields, bad dates and disordered voltages are refused.")])),
  chart, out);

  function load() {
    const b = bundles[name];
    meta.value = JSON.stringify(b.metadata, null, 2);
    clear(info).append(h("p", { class: "muted mt" }, b.description), h("div", { class: "row" }, pill(`${b.rows.length} rows`, "neutral"), pill(`Python engine: ${b.python_decision}`, "neutral")));
    const ti = b.columns.indexOf("timestamp_utc");
    const t = b.rows.map((r) => Date.parse(r[ti]) / 3.6e6);
    const t0 = Math.min(...t.filter(Number.isFinite));
    const col = (c) => { const k = b.columns.indexOf(c); return k < 0 ? [] : b.rows.map((r) => (r[k] === null ? NaN : r[k])); };
    const x = t.map((v) => v - t0);
    clear(chart).append(card("Telemetry", h("div", { class: "grid g2" },
      lineChart({ series: [{ name: "pack voltage", x, y: col("voltage_v") }], xLabel: "hours", yLabel: "V", height: 190 }),
      lineChart({ series: [{ name: "current (A)", x, y: col("current_a"), color: "--c2" }, { name: "SOC (%)", x, y: col("soc_pct"), color: "--c4" },
        { name: "temperature (°C)", x, y: col("temperature_c"), color: "--c3" }], xLabel: "hours", height: 190 }))));
    runIt();
  }
  function current() {
    const b = bundles[name];
    const bundle = loadBundle(meta.value, b.rows.map((r) => Object.fromEntries(b.columns.map((c, k) => [c, r[k]]))));
    bundle.ignored_columns = b.ignored_columns;
    return bundle;
  }
  function runIt() {
    clear(out);
    let bundle;
    try { bundle = current(); } catch (e) { out.append(banner("bad", "Rejected by the data contract.", e.message)); return; }
    const t = performance.now();
    let r;
    try { r = assess(bundle, app.assets); } catch (e) { console.error(e); out.append(banner("bad", "The full engine failed.", e.message)); return; }
    const ms = performance.now() - t;
    const b = bundles[name];
    const edited = meta.value.trim() !== JSON.stringify(b.metadata, null, 2).trim();
    if (!edited) out.append(banner(r.decision === b.python_decision ? "good" : "bad", r.decision === b.python_decision ? "Same decision as the Python engine." : "Differs from the Python engine.", `Browser: ${r.decision} · Python: ${b.python_decision} · ${ms.toFixed(0)} ms`));
    else out.append(banner("info", "Edited metadata.", `Browser engine: ${r.decision} (${ms.toFixed(0)} ms).`));
    out.append(renderFullReport(r, { bundle }));
  }
  async function exportZip() {
    let bundle;
    try { bundle = current(); } catch (e) { out.prepend(banner("bad", "", e.message)); return; }
    const zip = new (app.libs().JSZip)();
    zip.file("metadata.json", meta.value);
    const rows = telemetryRows(bundle.tel);
    zip.file("telemetry.csv", toCSV(Object.keys(rows[0]), rows));
    download(`${bundle.meta.asset_id}_bundle.zip`, await zip.generateAsync({ type: "blob" }));
  }
  load();
}

// ======================================================================== 2. Physics projection
function physicsTab(app) {
  const ph = app.assets.configs.physics;
  const wls = app.assets.configs.workloads.workloads;
  const st = { soh: 92, point: 600, lower: 420, upper: 820, preset: "residential_storage", w: { ...wls.residential_storage } };
  const root = h("div", { class: "stack" });
  root.append(h("p", { class: "muted", style: { margin: 0 } }, "Below the ML training range the engine projects with physics: a double-exponential fade anchored so it reaches 80 % SOH exactly at the ML-predicted remaining cycles under reference conditions (30 °C, 100 % DoD, 4 C), scaled to the workload with Arrhenius, depth-of-discharge and C-rate stress factors, plus √time calendar ageing."),
    banner("warn", "Projected (physics model).", "Parameters are literature-informed assumptions (configs/physics.yaml). The Monte Carlo band is assumption-conditional, not a measured interval."));
  const controls = h("div", { class: "stack", style: { gap: "10px" } });
  const out = h("div", { class: "stack" });
  root.append(h("div", { class: "grid g-side" }, card("Inputs", controls), out));

  function drawControls() {
    clear(controls).append(
      h("h4", {}, "ML hand-over"),
      slider("SOH now (%)", () => st.soh, (v) => { st.soh = v; }, 81, 100, 0.5, draw),
      slider("Remaining reference cycles (point)", () => st.point, (v) => { st.point = v; st.lower = Math.min(st.lower, v); st.upper = Math.max(st.upper, v); }, 50, 3000, 10, draw),
      slider("CV+ lower bound", () => st.lower, (v) => { st.lower = Math.min(v, st.point); }, 10, 3000, 10, draw),
      slider("CV+ upper bound", () => st.upper, (v) => { st.upper = Math.max(v, st.point); }, 50, 4000, 10, draw),
      h("h4", { class: "mt" }, "Workload ", prov("assumed")),
      field("Preset", select(Object.entries(wls).map(([k, w]) => [k, w.label]), st.preset, (v) => { st.preset = v; st.w = { ...wls[v] }; drawControls(); draw(); })),
      slider("Daily depth of discharge", () => st.w.daily_dod, (v) => { st.w.daily_dod = v; }, 0.1, 1, 0.05, draw, (v) => `${Math.round(v * 100)} %`),
      slider("Ambient (°C)", () => st.w.ambient_c, (v) => { st.w.ambient_c = v; }, 0, 50, 1, draw),
      slider("C-rate", () => st.w.c_rate, (v) => { st.w.c_rate = v; }, 0.1, 4, 0.1, draw),
      slider("Cycles per day", () => st.w.cycles_per_day, (v) => { st.w.cycles_per_day = v; }, 0.05, 3, 0.05, draw),
      slider("Application limit (SOH %)", () => st.w.min_soh_pct, (v) => { st.w.min_soh_pct = v; }, 40, 80, 1, draw));
  }
  function draw() {
    clear(out);
    let p;
    try { p = project(ph, app.assets.mcParams, st.soh, { point: st.point, lower: st.lower, upper: st.upper }, st.w, app.assets.stateModel.validation.measured_coverage); } catch (e) {
      console.error(e); out.append(banner("bad", "The physics projection failed.", e.message)); return;
    }
    const life = p.years_to_application_limit;
    const yrs = (t) => (t.value === null ? "> 20 y" : `${num(t.value, 1)} y`);
    out.append(h("div", { class: "grid g4" },
      kpi("Conservative life", yrs(p.conservative_years), "min of ML lower path and MC 5th pct"),
      kpi("Central path", yrs(life.central)), kpi("Knee scenario", yrs(life.knee_scenario), "earlier, sharper knee"),
      kpi("Stress factor", num(p.stress_factor_nominal.value, 3), "reference cycles per real cycle")));
    out.append(card("Projected SOH", projectionChart(p, st.w.min_soh_pct)));
    const p0 = nominalParams(ph);
    const ref = ph.reference;
    const tCell = (amb, c) => amb + 273.15 + p0.cell_temperature_rise_c_per_c_rate * c;
    const parts = [
      ["Temperature (Arrhenius)", Math.exp(p0.activation_energy_j_mol / 8.314 * (1 / tCell(ref.temperature_c, ref.c_rate) - 1 / tCell(st.w.ambient_c, st.w.c_rate)))],
      ["Depth of discharge", (st.w.daily_dod / ref.daily_dod) ** p0.k_dod],
      ["C-rate", Math.exp(p0.c_rate_coefficient_j_mol * (st.w.c_rate - ref.c_rate) / (8.314 * tCell(st.w.ambient_c, st.w.c_rate)))],
    ];
    out.append(collapsible("Stress factors and years per path", h("div", { class: "grid g2" },
      h("div", {}, h("h3", {}, "Stress factors (nominal parameters)"), table([{ key: 0, label: "Factor" }, { label: "Multiplier", render: (r) => num(r[1], 4), num: true }], parts),
        h("p", { class: "muted mt", style: { fontSize: "12px" } }, `Product = ${num(stressFactor(ph, p0, st.w), 4)}.`)),
      h("div", {}, h("h3", {}, "Years to the application limit"), table([{ key: "k", label: "Path" }, { label: "Years", render: (r) => yrs(r.v), num: true }],
        Object.entries(life).map(([k, v]) => ({ k: k.replace(/_/g, " "), v })))))));
    out.append(collapsible("Parameters and sources", table([{ key: "k", label: "Parameter" }, { key: "n", label: "Nominal", num: true }, { key: "prior", label: "Monte Carlo prior" }, { key: "src", label: "Source" }],
      Object.entries(ph.parameters).map(([k, v]) => ({ k, n: v.nominal, prior: `${v.prior.dist} ${JSON.stringify(Object.fromEntries(Object.entries(v.prior).filter(([q]) => q !== "dist")))}`, src: v.source })))));
  }
  drawControls();
  draw();
  return root;
}

// ======================================================================== 3. Economics
function economicsTab(app) {
  const cfg = app.assets.configs.economics, ph = app.assets.configs.physics, wl = app.assets.configs.workloads.workloads;
  const st = { chem: "NMC", kwh: 60, soh: 85, rul: 400, valueMult: 1, metalMult: 1 };
  const root = h("div", { class: "stack" });
  root.append(h("p", { class: "muted", style: { margin: 0 } }, "Second-life value is the discounted energy a pack delivers, capped at what new storage giving the same service would cost (the Buy-New benchmark), minus testing, refurbishment, logistics and installation, plus recycling it at the end. Recycling now is recovered metal value minus processing."),
    banner("warn", "Placeholder inputs.", "Several cost and tariff inputs are placeholders: energy value, testing, refurbishment, logistics, installation, processing and payable fractions. Metal prices and the new-storage cost are sourced (see below)."));
  const controls = h("div", { class: "stack", style: { gap: "10px" } });
  const out = h("div", { class: "stack" });
  root.append(h("div", { class: "grid g-side" }, card("What-if (residential storage workload)", controls), out));
  const s = (label, key, min, max, step, fmt) => slider(label, () => st[key], (v) => { st[key] = v; }, min, max, step, draw, fmt);
  controls.append(field("Chemistry", select(["LFP", "NMC", "NCA"], st.chem, (v) => { st.chem = v; draw(); })),
    s("Pack energy (kWh)", "kwh", 5, 120, 1), s("SOH (%)", "soh", 81, 99, 1), s("Remaining reference cycles (ML)", "rul", 50, 2000, 10),
    s("Energy value ×", "valueMult", 0.25, 3, 0.25, (v) => `${v}×`), s("Metal prices ×", "metalMult", 0.25, 12, 0.25, (v) => `${v}×`));

  function draw() {
    clear(out);
    let rec, sl;
    try {
      const ref = referenceProjection(ph, wl, { soh: st.soh / 100, rul: st.rul });
      const m = { nickel: st.metalMult, cobalt: st.metalMult, lithium: st.metalMult };
      rec = recycleValue(st.chem, st.kwh, cfg, m);
      sl = secondLifeValue(st.kwh, st.soh / 100, ref.sohByYear, ref.life, ref.w, rec.net_usd, cfg, st.valueMult);
    } catch (e) { console.error(e); out.append(banner("bad", "The economics engine failed.", e.message)); return; }
    const win = sl.net_usd > rec.net_usd;
    out.append(h("div", { class: "grid g4" },
      kpi("Second-life net", usd(sl.net_usd), `${num(sl.years_used, 1)} years of service`), kpi("Recycle now", usd(rec.net_usd), `${num(rec.pack_kg, 0)} kg pack`),
      kpi("Decision", pill(win ? "Second-Life" : "Recycle", win ? "good" : "bad"), "illustrative"), kpi("Buy-New cap", usd(sl.buy_new_cap_usd), sl.capped ? "value was capped" : "not binding")));
    out.append(h("div", { class: "grid g2" },
      card("Second-life value", bars([{ label: "Energy value (discounted)", value: sl.gross_energy_value_usd, color: "--c1" }, { label: "Buy-New cap", value: sl.buy_new_cap_usd, color: "--c2" },
        { label: "Upfront costs", value: -sl.upfront_cost_usd, color: "--c3" }, { label: "Recycle at end (PV)", value: sl.end_of_life_recycle_pv_usd, color: "--c4" }, { label: "Net", value: sl.net_usd, color: "--c5" }], usd)),
      card("Recycle now", bars([{ label: "Nickel", value: rec.nickel_usd }, { label: "Cobalt", value: rec.cobalt_usd }, { label: "Lithium", value: rec.lithium_usd },
        { label: "Processing", value: -rec.processing_cost_usd, color: "--c3" }, { label: "Net", value: rec.net_usd, color: "--c5" }], usd))));
  }
  draw();
  const prices = metalPricesUsdPerKg(cfg);
  const p = cfg.recycling.prices_usd_per_tonne;
  root.append(collapsible("Sourced prices", table([{ key: "k", label: "Input" }, { key: "v", label: "Value", num: true }, { key: "s", label: "Source" }], [
    { k: "Nickel", v: `$${num(p.nickel.value, 0)}/t (${num(prices.nickel, 2)} $/kg)`, s: p.nickel.source },
    { k: "Cobalt", v: `$${num(p.cobalt.value, 0)}/t`, s: p.cobalt.source },
    { k: "Lithium carbonate", v: `$${num(p.lithium_carbonate.value, 0)}/t`, s: p.lithium_carbonate.source },
    { k: "New storage, installed", v: `$${cfg.buy_new_benchmark.installed_system_usd_per_kwh.value}/kWh`, s: cfg.buy_new_benchmark.installed_system_usd_per_kwh.source },
    { k: "Stationary pack price", v: `$${cfg.buy_new_benchmark.stationary_pack_usd_per_kwh.value}/kWh`, s: cfg.buy_new_benchmark.stationary_pack_usd_per_kwh.source }])));

  let sw;
  try { sw = sweep(cfg, ph, wl); } catch (e) { console.error(e); root.append(banner("bad", "The price-sensitivity sweep failed.", e.message)); return root; }
  root.append(card("Price sensitivity: where does the decision flip?", [
    banner("info", "Illustrative.", `${sw.label}. Reference: ${sw.reference_battery.pack_kwh} kWh, SOH ${sw.reference_battery.soh_pct} %, residential workload, ${sw.reference_battery.projected_years} projected years.`),
    tabs(Object.entries(sw.chemistries).map(([chem, r]) => ({ id: chem, label: chem, render: () => {
      const vms = [...new Set(r.grid.map((g) => g.energy_value_multiplier))];
      const mms = [...new Set(r.grid.map((g) => g.metal_price_multiplier))];
      return h("div", {}, h("p", { class: "muted" }, `Composition: ${r.composition_status}. Rows: energy value multiplier; columns: metal price multiplier. Cells show second-life minus recycle (USD).`),
        h("div", { class: "table-wrap" }, h("table", { class: "heat" }, h("thead", {}, h("tr", {}, h("th", {}, "value × \\ metal ×"), mms.map((m) => h("th", { class: "num" }, `${m}×`)))),
          h("tbody", {}, vms.map((vm) => h("tr", {}, h("th", {}, `${vm}×`), mms.map((mm) => {
            const g = r.grid.find((x) => x.energy_value_multiplier === vm && x.metal_price_multiplier === mm);
            return h("td", { class: g.decision === "Second-Life" ? "sl" : "rc", title: `${g.decision}: second life ${usd(g.second_life_net_usd)} vs recycle ${usd(g.recycle_net_usd)}` }, usd(g.second_life_net_usd - g.recycle_net_usd));
          })))))),
        h("div", { class: "legend" }, h("span", {}, h("i", { class: "band", style: { background: "var(--good)" } }), "Second-Life wins"), h("span", {}, h("i", { class: "band", style: { background: "var(--warn)" } }), "Recycle wins")));
    } }))),
    h("p", { class: "muted mt", style: { fontSize: "12px" } }, sw.note)]));
  return root;
}

// ======================================================================== 4. Field test
// The simulator models one Li-ion cell (3.0-4.2 V) on the low-voltage bench, so a demo pack is tested as one of its
// cells: cell capacity = pack capacity / parallel cells, and the cell's true capacity follows the pack's latest
// capacity test. Anything above the INA219's 26 V rating is refused rather than simulated.
const PROFILES = [
  ["standard", "Standard test: 0.5 A constant load", 0.5],
  ["high", "High current test: 1.5 A (thermal / sag stress)", 1.5],
  ["low", "Low rate test: 0.2 A (precision capacity)", 0.2],
  ["max", `Max bench load: ${SIM_MAX_LOAD_A} A (simulator limit; the INA219 saturates near 3.2 A)`, SIM_MAX_LOAD_A],
];
const SPEEDS = [[60, "60× real time"], [300, "300×"], [600, "600× (fastest)"]];
const CUSTOM = "__custom__";

function fieldTestTab(app) {
  const ids = listBatteryIds(app.demo);
  const st = { battery: ids[0] || CUSTOM, profile: "standard", speed: 600, startSoc: 100,
    custom: { nominal_v: 3.7, rated_ah: 2.0, true_ah: 1.8 } };
  const root = h("div", { class: "stack" });
  const controls = h("div", { class: "stack", style: { gap: "10px" } });
  const live = h("div", { class: "stack" });
  root.append(h("p", { class: "muted", style: { margin: 0 } }, "A simulated bench discharge: the software ESP32 sends the firmware's JSON lines, the BMS engine counts charge into SOC and measures SOH from a full discharge to the 3.0 V cutoff, and the decision rule assigns a tier."),
    banner("warn", "Simulated.", "Readings are generated by the ESP32 simulator, not measured. A demo pack is tested as one of its cells, because the bench is low-voltage only (≤ 26 V)."),
    card("Test setup", controls), live);

  /** what this setup tests: one cell's rated and true capacity, and the voltage that has to stay under 26 V */
  function cellUnderTest() {
    if (st.battery === CUSTOM) {
      const c = st.custom;
      return { label: "Custom cell", rated: c.rated_ah, trueAh: c.true_ah, nominal: c.nominal_v, note: "values you entered" };
    }
    const p = loadBatteryProfile(app.demo, st.battery);
    const asset = Object.fromEntries((app.demo.battery_asset || [])
      .filter((r) => r.asset_id === undefined || String(r.asset_id) === String(st.battery)).map((r) => [r.field, r.value]));
    const m = /^(\d+)s(\d+)p$/.exec(String(asset.series_parallel_configuration || "").trim());
    const parallel = m && asset.asset_id === st.battery ? Number(m[2]) : 1;
    const series = m && asset.asset_id === st.battery ? Number(m[1]) : 1;
    const rated = p.rated_capacity_ah ? p.rated_capacity_ah / parallel : null;
    const soh = p.measured_capacity_ah && p.rated_capacity_ah ? p.measured_capacity_ah / p.rated_capacity_ah : null;
    return { label: `One cell of ${p.asset_id}`, rated, trueAh: rated !== null && soh !== null ? rated * soh : rated,
      nominal: p.nominal_voltage_v && series ? Number((p.nominal_voltage_v / series).toFixed(3)) : 3.7, packV: p.nominal_voltage_v,
      note: `${series}s${parallel}p pack: cell = ${num(p.rated_capacity_ah, 0)} Ah / ${parallel}; true capacity from the ${p.capacity_test_date || "?"} capacity test (${soh !== null ? num(100 * soh, 1) : "?"} %)` };
  }

  const est = h("small", { class: "muted" });
  const updateEstimate = () => { est.textContent = estimate(cellUnderTest()); };
  function drawControls() {
    const running = fieldController && fieldController.running;
    const cell = cellUnderTest();
    const custom = st.battery === CUSTOM;
    const g = h("div", { class: "form-grid" },
      field("Nominal cell voltage (V)", numberInput(custom ? st.custom.nominal_v : cell.nominal, (v) => { st.custom.nominal_v = v; updateEstimate(); }, { min: 0, disabled: !custom || running })),
      field("Rated capacity (Ah)", numberInput(custom ? st.custom.rated_ah : cell.rated, (v) => { st.custom.rated_ah = v; updateEstimate(); }, { min: 0.1, disabled: !custom || running })),
      field("True capacity (Ah)", numberInput(custom ? st.custom.true_ah : cell.trueAh, (v) => { st.custom.true_ah = v; updateEstimate(); }, { min: 0.1, disabled: !custom || running }), "what the simulated cell really holds"),
      field("Start SOC (%)", numberInput(st.startSoc, (v) => { st.startSoc = v; updateEstimate(); }, { min: 1, max: 100, disabled: running })));
    clear(controls).append(
      h("div", { class: "grid g3" },
        field("Battery", select([...ids.map((id) => [id, `${id} (demo asset)`]), [CUSTOM, "Custom cell"]], st.battery, (v) => { st.battery = v; drawControls(); }, { disabled: running })),
        field("Test profile", select(PROFILES.map(([k, l]) => [k, l]), st.profile, (v) => { st.profile = v; drawControls(); }, { disabled: running })),
        field("Simulation speed", select(SPEEDS, st.speed, (v) => { st.speed = Number(v); updateEstimate(); }, { disabled: running }))),
      h("small", { class: "muted" }, cell.note), g, est,
      h("div", { class: "row" },
        h("button", { class: "btn primary", disabled: running, onclick: start }, icon("play", 15), "Start Field Test"),
        h("button", { class: "btn danger", disabled: !running, onclick: () => fieldController && fieldController.stop() }, icon("stop", 15), "Stop")));
    updateEstimate();
  }
  function estimate(cell) {
    const load = PROFILES.find(([k]) => k === st.profile)[2];
    if (!(cell.trueAh > 0)) return "";
    const hours = cell.trueAh * (st.startSoc / 100) / load;
    return `About ${num(hours, 1)} h of simulated discharge at ${load} A (${num(hours * 3600 / st.speed / 60, 1)} min at ${st.speed}×).`;
  }

  // downsampled series for the five charts: readings beyond the controller's 2000-reading window are kept here
  let series = null, lastT = -Infinity, t0 = null, frame = 0, lastPaint = 0;
  const reset = () => { series = { t: [], v: [], i: [], temp: [], soc: [], soh: [] }; lastT = -Infinity; t0 = null; };
  function collect() {
    for (const r of fieldController.readings) {
      const s = r.sample;
      if (s.timestamp <= lastT) continue;
      lastT = s.timestamp;
      if (t0 === null) t0 = s.timestamp;
      series.t.push((s.timestamp - t0) / 60); series.v.push(s.voltage_v); series.i.push(s.current_a);
      series.temp.push(s.temperature_c === null ? NaN : s.temperature_c); series.soc.push(r.soc_pct ?? NaN); series.soh.push(r.soh_live_pct ?? NaN);
    }
    if (series.t.length > 3000) for (const k of Object.keys(series)) series[k] = series[k].filter((_, j) => j % 2 === 0);
  }

  function start() {
    const cell = cellUnderTest();
    const load = PROFILES.find(([k]) => k === st.profile)[2];
    const problems = [];
    if (!(cell.nominal > 0)) problems.push("enter the cell's nominal voltage");
    else if (cell.nominal > INA219_MAX_BUS_VOLTAGE_V) problems.push(`${cell.nominal} V is above the INA219's ${INA219_MAX_BUS_VOLTAGE_V} V rating: the bench refuses it`);
    if (!(cell.rated > 0)) problems.push("rated capacity must be positive");
    if (!(cell.trueAh > 0)) problems.push("true capacity must be positive");
    if (!(st.startSoc > 0 && st.startSoc <= 100)) problems.push("start SOC must be between 1 and 100 %");
    if (problems.length) { clear(live).append(banner("bad", "Can't start.", problems.join("; ") + ".")); return; }
    if (fieldController) fieldController.stop();
    reset();
    fieldController = new RunController({ tables: app.demo, parseTime: parseIso, onLog: (rows) => app.addRunRows(rows), onUpdate: schedule });
    fieldController.startSimulated({ rated_capacity_ah: cell.rated, cutoff_voltage_v: 3.0 },
      { true_capacity_ah: cell.trueAh, start_soc_pct: st.startSoc, load_current_a: load, speed: st.speed, seed: null }, "none");
    drawControls();
  }
  function schedule() {
    if (frame) return;
    const wait = Math.max(0, 250 - (performance.now() - lastPaint)); // five charts: repaint at most four times a second
    frame = setTimeout(() => { frame = 0; lastPaint = performance.now(); paint(); }, fieldController && fieldController.running ? wait : 0);
  }

  let lastStatus = null;
  function paint() {
    const ctl = fieldController;
    if (!ctl) return;
    if (ctl.status !== lastStatus) { lastStatus = ctl.status; drawControls(); }
    collect();
    const rs = ctl.readings, last = rs[rs.length - 1];
    clear(live);
    const tone = { running: "info", finished: "good", stopped: "warn", error: "bad", idle: "neutral" }[ctl.status];
    live.append(h("div", { class: "row between" }, h("div", { class: "row" }, pill(ctl.status, tone), pill("SIMULATED", "warn")),
      h("small", { class: "muted" }, `${series.t.length.toLocaleString()} points plotted · ${ctl.stats.good_lines.toLocaleString()} readings`)));
    if (ctl.error) live.append(banner("bad", "Error.", ctl.error));
    live.append(h("div", { class: "grid g4" },
      kpi("Voltage", last ? `${num(last.sample.voltage_v, 3)} V` : "—"), kpi("Current", last ? `${num(last.sample.current_a, 3)} A` : "—"),
      kpi("SOC", last && last.soc_pct !== null ? `${num(last.soc_pct, 1)} %` : "—", "coulomb count"),
      kpi("Live SOH", last && last.soh_live_pct !== null ? `${num(last.soh_live_pct, 1)} %` : "—", last ? last.soh_basis : "")));
    const x = series.t;
    const chart = (title, y, label, color, extra = {}) => card(title, lineChart({ series: [{ name: label, x, y, color }], xLabel: "minutes", yLabel: label, height: 180, ...extra }));
    live.append(h("div", { class: "grid g2" },
      chart("Terminal voltage", series.v, "V", "--c1", { hlines: [{ y: 3.0, label: "cutoff 3.0 V", color: "--bad" }] }),
      chart("Pack current", series.i, "A", "--c2"),
      chart("Cell temperature", series.temp, "°C", "--c3"),
      chart("State of charge", series.soc, "SOC %", "--c4", { yMin: 0, yMax: 100 })));
    live.append(card("Dynamic SOH", [lineChart({ series: [{ name: "live SOH", x, y: series.soh, color: "--c5" }], xLabel: "minutes", yLabel: "SOH %", height: 200,
      hlines: [{ y: 80, label: "80 %: stationary storage above", color: "--good" }, { y: 60, label: "60 %: recycle below", color: "--warn" }] }),
    h("p", { class: "muted", style: { fontSize: "12px", margin: "6px 0 0" } }, `Evidence basis: ${last ? last.soh_basis : "waiting for readings"}. Until the cutoff, the live figure is only a lower bound (Ah delivered so far); it becomes a measurement at the full discharge.`)]));
    if (ctl.decision) {
      const d = ctl.decision;
      live.append(decisionCard("Field test result (screening rule)", d.use_case, [
        `SOH used: ${d.soh_pct === null ? "none" : `${num(d.soh_pct, 1)} %`} — ${d.basis}`, ...d.flags], null,
      h("p", { class: "muted", style: { fontSize: "12px", margin: "6px 0 0" } }, d.note)));
      if (ctl.logNote) live.append(h("small", { class: "muted" }, ctl.logNote, " See ", h("a", { href: "#/database" }, "Database"), "."));
    }
  }

  drawControls();
  live.append(h("div", { class: "empty" }, "Choose a battery and a test profile, then start the field test. Five charts update live."));
  return root;
}
