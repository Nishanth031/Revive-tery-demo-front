// Circuit Studio: the bench circuit, three reading sources, the BMS engine live, and the decision with its evidence.
import { h, svg, clear, card, kpi, banner, field, select, numberInput, seg, num, decisionCard, icon, pill, table } from "../ui/dom.js";
import { lineChart, gauge } from "../ui/charts.js";
import { RunController, SIMULATED_RATED_AH, SIMULATED_CUTOFF_V, SIM_MAX_LOAD_A, SPEED_LIMITS } from "../engines/runController.js";
import { FAULTS, DEFAULT_SIM } from "../engines/esp32sim.js";
import { parseIso } from "../engines/contract.js";
import { circuitSvg } from "../ui/circuitView.js";
import { toCSV } from "../lib/csv.js";
import { analyzeFiles, adviseBattery } from "../lib/mlApi.js";
import { adviceView, needsForm } from "../ui/mlAdvice.js";

// The realistic circuit renderer lives in ui/circuitView.js; re-exported here (hardware.js and the tour import it from bench.js).
export { circuitSvg };

export function render(root, app) {
  const ui = { source: "virtual", delay: 0.4, battery: null, sim: { ...DEFAULT_SIM, seed: null }, rated: SIMULATED_RATED_AH, cutoff: SIMULATED_CUTOFF_V,
    fault: "none", hw: { baudrate: 115200, rated_capacity_ah: 2.0, start_soc_pct: 100, cutoff_voltage_v: 3.0, discharge_positive: true } };
  let frame = 0;
  // ML suggestion for the finished test: the monitored values go to the ML backend, which maps them, assesses the
  // battery and answers with a recommendation (1) or, when it cannot recommend yet, suggestions (2).
  const mlIdle = { runId: null, state: "idle", result: null, analysis: null, error: null, batteryId: null, spec: null };
  const ml = { ...mlIdle };
  const ctl = new RunController({ tables: app.demo, parseTime: parseIso, onLog: (rows) => app.addRunRows(rows),
    onUpdate: () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; paint(); }); } });
  ui.battery = ctl.profile ? ctl.profile.asset_id : null;
  current = ctl;

  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Circuit Studio"),
    h("p", {}, "The bench test: a battery discharges through a load while an INA219 and a DS18B20 report to an ESP32. Readings from any source go through the same BMS engine: SOC by coulomb counting, live SOH with the evidence behind it, and an end-of-life tier."))));
  root.append(banner("info", "Monitor-only.", "This page only ever reads from the ESP32 — no command can be sent to it. The bench is low-voltage only: the INA219 is rated to 26 V."));

  const controls = h("div");
  const live = h("div", { class: "stack" });
  const circuitBox = h("div");
  root.append(card("Bench wiring", circuitBox, null, "mb"), h("div", { class: "grid g-side" }, h("div", { class: "stack" }, card("Source", controls)), live));

  function drawControls() {
    clear(controls);
    controls.append(seg([["virtual", "Replay"], ["simulated", "Simulator"], ["hardware", "Real ESP32"]], ui.source, (v) => { ui.source = v; drawControls(); }));
    const f = h("div", { class: "stack mt", style: { gap: "10px" } });
    if (ui.source === "virtual") {
      f.append(h("p", { class: "muted", style: { margin: 0 } }, "Replays the battery's recorded telemetry from the database. Nothing is invented: a short recording gives a short test."));
      f.append(field("Battery", select(ctl.batteryIds, ui.battery, (v) => { ui.battery = v; ctl.selectBattery(v); })));
      if (ctl.profile) {
        const p = ctl.profile;
        f.append(table([{ key: "k", label: "From the database" }, { key: "v", label: "" }], [
          { k: "Chemistry", v: p.chemistry }, { k: "Rated capacity", v: `${num(p.rated_capacity_ah, 1)} Ah` },
          { k: "Latest capacity test", v: `${num(p.measured_capacity_ah, 1)} Ah (${p.capacity_test_date})` },
          { k: "Telemetry rows", v: p.telemetry_rows }, { k: "Data class", v: p.is_synthetic ? "SYNTHETIC" : "RECORDED" }]));
      }
      f.append(field(`Delay between rows: ${ui.delay.toFixed(2)} s`, h("input", { type: "range", min: 0.05, max: 2, step: 0.05, value: ui.delay, oninput: (e) => { ui.delay = Number(e.target.value); e.target.previousSibling.textContent = `Delay between rows: ${ui.delay.toFixed(2)} s`; } })));
    } else if (ui.source === "simulated") {
      f.append(h("p", { class: "muted", style: { margin: 0 } }, "A software ESP32 and circuit: a 1S Li-ion cell whose true capacity you choose, a constant-current load, and the same JSON lines and fault messages as the firmware. Readings are generated — labelled SIMULATED."));
      const g = h("div", { class: "form-grid" });
      g.append(field("True capacity (Ah)", numberInput(ui.sim.true_capacity_ah, (v) => { ui.sim.true_capacity_ah = v; }, { min: 0.1 })));
      g.append(field("Start SOC (%)", numberInput(ui.sim.start_soc_pct, (v) => { ui.sim.start_soc_pct = v; }, { min: 0, max: 100 })));
      g.append(field(`Load (A, ≤ ${SIM_MAX_LOAD_A})`, numberInput(ui.sim.load_current_a, (v) => { ui.sim.load_current_a = v; }, { min: 0, max: SIM_MAX_LOAD_A })));
      g.append(field("Speed (× real time)", numberInput(ui.sim.speed, (v) => { ui.sim.speed = v; }, { min: SPEED_LIMITS[0], max: SPEED_LIMITS[1] })));
      g.append(field("Rated capacity (Ah)", numberInput(ui.rated, (v) => { ui.rated = v; })));
      g.append(field("Cutoff (V)", numberInput(ui.cutoff, (v) => { ui.cutoff = v; })));
      g.append(field("Seed (optional)", numberInput(ui.sim.seed, (v) => { ui.sim.seed = v; })));
      f.append(g);
      f.append(field("Inject a fault (works mid-run)", select(Object.entries(FAULTS), ui.fault, (v) => { ui.fault = v; ctl.setSimFault(v); })));
    } else {
      const supported = RunController.hardwareSupported();
      f.append(h("p", { class: "muted", style: { margin: 0 } }, "Reads the ESP32 sketch's JSON lines over USB with Web Serial (Chrome or Edge on desktop). The port is opened read-only; DTR/RTS are kept low so the board doesn't reset."));
      if (!supported) f.append(banner("warn", "Web Serial unavailable.", "Use Chrome or Edge on a desktop, served over https (GitHub Pages) or localhost."));
      const g = h("div", { class: "form-grid" });
      g.append(field("Baud rate", numberInput(ui.hw.baudrate, (v) => { ui.hw.baudrate = v; })));
      g.append(field("Rated capacity (Ah)", numberInput(ui.hw.rated_capacity_ah, (v) => { ui.hw.rated_capacity_ah = v; })));
      g.append(field("Start SOC (%)", numberInput(ui.hw.start_soc_pct, (v) => { ui.hw.start_soc_pct = v; })));
      g.append(field("Cutoff (V)", numberInput(ui.hw.cutoff_voltage_v, (v) => { ui.hw.cutoff_voltage_v = v; })));
      f.append(g);
      f.append(h("label", { class: "row" }, h("input", { type: "checkbox", checked: ui.hw.discharge_positive, onchange: (e) => { ui.hw.discharge_positive = e.target.checked; } }), "Discharge reads as positive current (the kit's wiring)"));
    }
    const running = ctl.running;
    f.append(h("div", { class: "row" },
      h("button", { class: "btn primary", disabled: running, onclick: start }, icon("play", 15), "Start test"),
      h("button", { class: "btn danger", disabled: !running, onclick: () => ctl.stop() }, icon("stop", 15), "Stop")));
    controls.append(f);
  }

  function start() {
    if (ui.source === "virtual") ctl.startVirtual(ui.delay);
    else if (ui.source === "simulated") {
      const s = ui.sim;
      if (!(s.true_capacity_ah > 0) || s.load_current_a === null || s.load_current_a < 0 || s.load_current_a > SIM_MAX_LOAD_A) {
        ctl.notice = `Capacity must be positive and the load between 0 and ${SIM_MAX_LOAD_A} A.`; paint(); return;
      }
      try {
        ctl.startSimulated({ rated_capacity_ah: ui.rated, cutoff_voltage_v: ui.cutoff },
          { ...s, speed: Math.min(SPEED_LIMITS[1], Math.max(SPEED_LIMITS[0], s.speed || 60)), seed: s.seed === null ? null : Math.trunc(s.seed) }, ui.fault);
      } catch (e) { ctl.notice = e.message; paint(); }
    } else ctl.startHardware(ui.hw);
    drawControls();
  }

  const PROVENANCE = { SIMULATED: "simulated", MEASURED: "measured" };

  /** the run's monitored values as a table the ML can read: the same columns an engineer would log */
  function monitoredCsv() {
    // the whole run (ctl.readings only keeps the newest 2000 for the charts)
    const rows = ctl.run.rows;
    const full = ctl.status === "finished" && ctl.source !== "virtual";     // reached the cutoff: the discharge IS a capacity test
    const direction = ui.source === "hardware" && !ui.hw.discharge_positive ? -1 : 1;   // same sign rule the BMS engine applies
    const header = ["Battery", "Time (UTC)", "Voltage (V)", "Current (A)", "Temperature (°C)", "SOC (%)", ...(full ? ["Cycle", "Discharged capacity (Ah)"] : [])];
    let discharged = 0, last = null;
    const out = rows.map((r) => {
      const dt = last === null ? 0 : Math.max(0, r.logged_at - last);      // exactly how the engine integrates (never backwards)
      last = r.logged_at;
      discharged += r.current_a * direction * dt / 3600;
      return { Battery: `${ctl.run.asset_id}-${ctl.run.run_id}`, "Time (UTC)": new Date(r.logged_at * 1000).toISOString(), "Voltage (V)": r.voltage_v,
        "Current (A)": r.current_a, "Temperature (°C)": r.temperature_c, "SOC (%)": r.soc_pct, Cycle: 1, "Discharged capacity (Ah)": discharged };
    });
    return { csv: toCSV(header, out), capacityIncluded: full, rows: out.length };
  }

  const benchRated = () => (ui.source === "hardware" ? ui.hw.rated_capacity_ah : ui.rated);

  /** first ask: send the monitored values (a database replay is already stored, so only advice is requested) */
  async function askML() {
    const run = ctl.run;
    Object.assign(ml, { ...mlIdle, runId: run.run_id, state: "loading" });
    paint();
    try {
      if (ctl.source === "virtual" && ctl.profile) {
        ml.batteryId = ctl.profile.asset_id;
        ml.result = { status: "assessed", ...(await adviseBattery({ battery_id: ml.batteryId })) };
      } else {
        const { csv, capacityIncluded } = monitoredCsv();
        const file = new File([csv], `${run.asset_id}-${run.run_id}.csv`, { type: "text/csv" });
        const out = await analyzeFiles([file], { data_provenance: PROVENANCE[run.data_class] || "synthetic", series_cells: 1,
          rated_capacity_ah: benchRated() });
        ml.analysis = out.analysis;
        ml.result = out.results[0];
        ml.batteryId = ml.result.battery_id;
        ml.capacityIncluded = capacityIncluded;
      }
      ml.state = "done";
    } catch (e) { ml.state = "error"; ml.error = e; }
    paint();
  }

  /** later asks reuse the battery already stored in the backend (no second upload); spec = what the user confirmed */
  async function adviseAgain(spec = null) {
    ml.state = "loading";
    if (spec) ml.spec = spec;
    paint();
    try {
      ml.result = { status: "assessed", ...(await adviseBattery({ battery_id: ml.batteryId, spec: ml.spec || null })) };
      ml.state = "done";
    } catch (e) { ml.state = "error"; ml.error = e; }
    paint();
  }
  const askAgain = () => (ml.batteryId ? adviseAgain() : askML());

  function mlBox() {
    if (ctl.running) { if (ml.runId && ml.runId !== ctl.run?.run_id) Object.assign(ml, { ...mlIdle }); return null; }
    if (!ctl.run || ctl.readings.length < 5 || !["finished", "stopped"].includes(ctl.status)) return null;
    if (ml.runId !== ctl.run.run_id && ml.state === "idle") queueMicrotask(askML);     // ask automatically once per finished test
    const body = h("div", { class: "stack" });
    body.append(h("p", { class: "muted", style: { margin: 0 } },
      `The ${ctl.run.rows.length} monitored readings from this test (voltage, current, temperature, SOC${ctl.source === "virtual" ? "" : ", 1S bench cell"}) are passed to the ML, which reads them, `
      + "assesses the battery and ranks second uses for its chemistry."));
    if (ml.state === "loading" || (ml.state === "idle" && ml.runId !== ctl.run.run_id)) body.append(h("div", { class: "empty" }, h("span", { class: "spinner" }), " Asking the ML…"));
    if (ml.state === "error") {
      body.append(banner("bad", ml.error.code === "unreachable" ? "ML backend not reachable." : "The ML could not answer.", ml.error.message));
      body.append(h("div", {}, h("button", { class: "btn", type: "button", onclick: askAgain }, "Try again")));
    }
    if (ml.state === "done" && ml.result) {
      const r = ml.result;
      if (r.status === "assessed") {
        if (ml.analysis && !ml.capacityIncluded && ctl.source !== "virtual") body.append(banner("info", "No capacity test.", "The test was stopped before the cutoff, so no discharge capacity was passed on; the ML judges what the readings alone allow."));
        body.append(adviceView(r));
      } else if (r.status === "needs_input") {
        const b = ml.analysis.batteries.find((x) => x.battery_id === r.battery_id);
        body.append(needsForm(b, (vals) => {
          const chemistry = vals.chemistry || b.spec.chemistry?.value;
          if (!chemistry) return;
          adviseAgain({ chemistry, series_cells: 1, parallel_cells: 1, rated_capacity_ah: benchRated() });   // the bench cell is a single cell
        }));
      } else body.append(banner("warn", "The ML did not assess this test.", r.message));
    }
    return card("ML suggestion", body, ml.state === "done" ? h("button", { class: "btn small", type: "button", onclick: askAgain }, "Ask again") : null);
  }

  // the live snapshot for the circuit view: only values the run actually has
  let lastCount = 0, lastT = performance.now(), lps = null;
  function liveSnapshot() {
    if (!ctl.running && !ctl.readings.length) return false;
    const rs = ctl.readings, last = rs[rs.length - 1];
    const now = performance.now();
    if (now - lastT > 1000) { lps = ((rs.length - lastCount) * 1000) / (now - lastT); lastCount = rs.length; lastT = now; }
    const st = ctl.stats;
    const parts = { ina219: /INA219|OVER|Current above/i, ds18b20: /DS18B20|temperature/i };
    const al = st.last_fault && st.faultIsActive ? Object.entries(parts).filter(([, rx]) => rx.test(st.last_fault)).map(([part]) => ({ part, message: st.last_fault })) : [];
    return { current_a: ctl.running && last ? last.sample.current_a : null, voltage_v: last?.sample.voltage_v ?? null,
      temperature_c: last?.sample.temperature_c ?? null, ambient_c: last?.sample.ambient_temperature_c ?? null,
      lines_per_s: ctl.source === "virtual" ? null : lps, dropped: st.dropped_lines ?? 0, crc_errors: st.crc_errors ?? 0,
      blink: ctl.running && rs.length % 2 === 0, alerts: al };
  }

  let lastStatus = null;
  const alerts = [];
  let lastAlertKey = null;
  function paint() {
    if (lastStatus !== ctl.status) { lastStatus = ctl.status; drawControls(); }
    clear(circuitBox).append(circuitSvg(app.circuit, liveSnapshot(), () => { ctl.switchBattery(); ui.battery = ctl.profile?.asset_id; ui.source = "virtual"; drawControls(); }));
    clear(live);
    const rs = ctl.readings;
    const last = rs[rs.length - 1];
    const s = last ? last.sample : null;
    const statusTone = { running: "info", finished: "good", stopped: "warn", error: "bad", idle: "neutral" }[ctl.status];
    live.append(h("div", { class: "row between" }, h("div", { class: "row" }, pill(ctl.status, statusTone), ctl.simulated ? pill("SIMULATED", "warn") : null,
      ctl.source === "virtual" && ctl.profile ? pill(`replay · ${ctl.profile.asset_id}`, "neutral") : null), h("small", { class: "muted" }, `${rs.length} readings`)));
    if (ctl.notice) live.append(banner("info", "", ctl.notice));
    if (ctl.error) live.append(banner("bad", "Error.", ctl.error));
    live.append(h("div", { class: "grid g4" },
      kpi("Voltage", s ? `${num(s.voltage_v, 3)} V` : "—"), kpi("Current", s ? `${num(s.current_a, 3)} A` : "—", "as the source records it"),
      kpi("Temperature", s && s.temperature_c !== null ? `${num(s.temperature_c, 2)} °C` : "—", s && s.temperature_c === null ? "sensor missing" : ""),
      kpi("Discharged", last ? `${num(last.discharged_ah, 3)} Ah` : "—", "coulomb count over the recorded time")));
    live.append(h("div", { class: "grid g2" },
      card("State of charge", h("div", { class: "row", style: { justifyContent: "space-around" } },
        gauge(last ? last.soc_pct : NaN, 100, "engine SOC", " %"), gauge(s && s.reported_soc_pct !== null ? s.reported_soc_pct : NaN, 100, "reported SOC", " %", "--c2"))),
      card("Live SOH", h("div", {}, gauge(last ? last.soh_live_pct : NaN, 120, "live SOH", " %", "--c4"),
        h("p", { class: "muted", style: { fontSize: "12px", textAlign: "center", margin: 0 } }, last ? last.soh_basis : "Waiting for readings")))));
    if (!rs.length && !ctl.running) live.append(h("div", { class: "empty" }, "No readings yet. Pick a source and press ", h("b", {}, "Start test"), "."));
    if (rs.length) {
      const t0 = rs[0].sample.timestamp;
      const x = rs.map((r) => (r.sample.timestamp - t0) / 60);
      live.append(card("Traces", h("div", { class: "grid g2" },
        lineChart({ series: [{ name: "voltage (V)", x, y: rs.map((r) => r.sample.voltage_v) }], xLabel: "minutes", yLabel: "V", height: 200 }),
        lineChart({ series: [{ name: "engine SOC", x, y: rs.map((r) => r.soc_pct), color: "--c1" }, { name: "reported SOC", x, y: rs.map((r) => r.sample.reported_soc_pct), color: "--c2", dash: "5 4" }], xLabel: "minutes", yLabel: "SOC %", height: 200 }))));
    }
    if (ctl.source === "hardware") {
      const st = ctl.stats;
      live.append(card("Serial link", [h("div", { class: "grid g4" }, kpi("Good lines", st.good_lines), kpi("Bad lines", st.bad_lines, "boot text, half lines"), kpi("Firmware messages", st.message_lines),
        kpi("Last fault", st.last_fault || "none", st.last_fault ? `${st.last_fault_severity}${st.faultIsActive ? " · ACTIVE" : " · cleared"}` : "")),
        Object.keys(st.fault_counts).length ? h("p", { class: "mt" }, Object.entries(st.fault_counts).map(([m, c]) => `${m} × ${c}`).join(" · ")) : null]));
    }
    if (ctl.decision) {
      const d = ctl.decision;
      live.append(decisionCard("End-of-life tier (screening rule)", d.use_case, [
        `SOH used: ${d.soh_pct === null ? "none" : `${num(d.soh_pct, 1)} %`} — ${d.basis}`,
        `Live SOH: ${d.live_soh_pct === null ? "—" : `${num(d.live_soh_pct, 1)} %`} — ${d.live_basis}`, ...d.flags], null, h("p", { class: "muted", style: { fontSize: "12px", margin: "6px 0 0" } }, d.note)));
    }
    const mlEl = mlBox();
    if (mlEl) live.append(mlEl);
    // alert timeline: every firmware fault message the engine classified, in the order it arrived (never invented)
    const lf = ctl.stats.last_fault;
    if (lf && lf !== lastAlertKey) {
      lastAlertKey = lf;
      alerts.unshift({ t: new Date().toLocaleTimeString(), msg: lf, severity: ctl.stats.last_fault_severity || "info" });
      alerts.splice(50);
    }
    if (!ctl.running && ctl.status === "idle") lastAlertKey = null;
    if (alerts.length) live.append(card("Alert timeline", h("div", { class: "stack", style: { gap: "4px", maxHeight: "220px", overflow: "auto" } },
      alerts.map((a) => h("div", { class: "row" }, h("span", { class: "mono muted" }, a.t), pill(a.severity, a.severity === "critical" || a.severity === "error" ? "bad" : a.severity === "warning" ? "warn" : "info"), h("span", {}, a.msg))))));
    if (ctl.logNote) live.append(h("small", { class: "muted" }, ctl.logNote, " See ", h("a", { href: "#/database" }, "Database"), "."));
  }
  paint();
  // #/bench?preset=<fault>: start the simulated ESP32 and inject that fault a few seconds in (Live assessment links here)
  const preset = new URLSearchParams(location.hash.split("?")[1] || "").get("preset");
  if (preset && FAULTS[preset] && preset !== "none") {
    ui.source = "simulated";
    drawControls();
    start();
    setTimeout(() => { if (ctl.running) { ui.fault = preset; ctl.setSimFault(preset); drawControls(); } }, PRESET_DELAY_MS);
  }
}
const PRESET_DELAY_MS = 3000;

let current = null;
export function unmount() { if (current) { current.stop(); current = null; } }
