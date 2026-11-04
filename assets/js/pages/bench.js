// Circuit Studio: the bench circuit, three reading sources, the BMS engine live, and the decision with its evidence.
import { h, svg, clear, card, kpi, banner, field, select, numberInput, seg, num, decisionCard, icon, pill, table } from "../ui/dom.js";
import { lineChart, gauge } from "../ui/charts.js";
import { RunController, SIMULATED_RATED_AH, SIMULATED_CUTOFF_V, SIM_MAX_LOAD_A, SPEED_LIMITS } from "../engines/runController.js";
import { FAULTS, DEFAULT_SIM } from "../engines/esp32sim.js";
import { parseIso } from "../engines/contract.js";

const WIRE_STYLE = {
  power: ["#e34948", null], ground: ["var(--text-2)", null], logic: ["#6250d6", "6 4"],
  i2c: ["#2a78d6", "2 4"], onewire: ["#008300", "8 4"], usb: ["#eb6834", null],
};
const WIRE_LABEL = { power: "Power", ground: "Ground", logic: "Sensor power", i2c: "I²C", onewire: "1-Wire", usb: "USB (read-only)" };

export function circuitSvg(circuit, running, onBattery = null) {
  const pins = {};
  const root = svg("svg", { viewBox: "0 0 1100 470", role: "img", "aria-label": "Bench wiring diagram" });
  const comps = svg("g");
  for (const c of circuit.components) {
    const xs = c.pins.map((p) => p.x), ys = c.pins.map((p) => p.y);
    const sides = new Set(c.pins.map((p) => p.side));
    let x0 = Math.min(...xs), x1 = Math.max(...xs);
    if (sides.size === 1 && sides.has("right")) x0 = x1 - (c.kind === "passive" ? 70 : 130);
    if (sides.size === 1 && sides.has("left")) x1 = x0 + 130;
    const y0 = Math.min(...ys) - 34, y1 = Math.max(...ys) + 22;
    const g = svg("g", { class: `comp ${c.kind === "battery" ? "battery" : ""}` });
    g.append(svg("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, rx: 8 }));
    g.append(svg("text", { x: (x0 + x1) / 2, y: y0 + 18, "text-anchor": "middle" }, c.title));
    if (c.kind === "battery" && onBattery) {
      g.append(svg("text", { x: (x0 + x1) / 2, y: y1 - 6, "text-anchor": "middle", style: "font-size:10px;font-weight:400;fill:var(--text-3)" }, "tap to switch battery"));
      g.addEventListener("click", onBattery);
      g.setAttribute("tabindex", "0");
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") onBattery(); });
    }
    for (const p of c.pins) {
      pins[p.id] = p;
      const right = p.side === "right";
      g.append(svg("g", { class: "pin" }, svg("circle", { cx: p.x, cy: p.y, r: 4 }),
        svg("text", { x: right ? p.x - 8 : p.x + 8, y: p.y + 4, "text-anchor": right ? "end" : "start" }, p.label)));
    }
    comps.append(g);
  }
  const wires = svg("g");
  for (const w of circuit.wires) {
    const a = pins[w.from], b = pins[w.to];
    if (!a || !b) continue;
    const [color, dash] = WIRE_STYLE[w.type] || ["var(--text-3)", null];
    const mid = a.x === b.x ? a.x + (a.side === "right" ? 36 : -36) : (a.x + b.x) / 2;
    const d = `M${a.x},${a.y} H${mid} V${b.y} H${b.x}`;
    const flowing = running && (w.type === "power" || w.type === "usb");
    wires.append(svg("path", { d, class: `wire ${flowing ? "flow" : ""}`, stroke: color, "stroke-dasharray": flowing ? null : dash }, svg("title", {}, `${WIRE_LABEL[w.type]}: ${w.description}`)));
  }
  root.append(wires, comps);
  return h("div", {}, h("div", { class: "circuit" }, root),
    h("div", { class: "legend" }, Object.entries(WIRE_LABEL).map(([k, l]) => h("span", {}, h("i", { style: { background: WIRE_STYLE[k][0] } }), l))));
}

export async function render(root, app) {
  const { packs, errors: packErrors } = await app.getSamplePacks();
  const ui = { source: "virtual", delay: 0.4, battery: null, sim: { ...DEFAULT_SIM, seed: null }, rated: SIMULATED_RATED_AH, cutoff: SIMULATED_CUTOFF_V,
    fault: "none", hw: { baudrate: 115200, rated_capacity_ah: 2.0, start_soc_pct: 100, cutoff_voltage_v: 3.0, discharge_positive: true } };
  let frame = 0;
  const ctl = new RunController({ tables: app.demo, packs, parseTime: parseIso, onLog: (rows) => app.addRunRows(rows),
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
      f.append(h("p", { class: "muted", style: { margin: 0 } }, "Replays a battery's recorded telemetry: the battery in the database, or one of the synthetic sample packs. Nothing is invented: a short recording gives a short test."));
      const options = ctl.batteryIds.map((id) => [id, ctl.isSamplePack(id) ? `${id} · sample pack` : `${id} · database`]);
      f.append(field("Battery", select(options, ui.battery, (v) => { ui.battery = v; ctl.selectBattery(v); drawControls(); })));
      if (packErrors.length) f.append(banner("warn", "Some sample packs couldn't be loaded.", packErrors.join(" ")));
      if (ctl.profile) {
        const p = ctl.profile;
        const sample = ctl.isSamplePack(p.asset_id);
        f.append(table([{ key: "k", label: sample ? "From the sample pack" : "From the database" }, { key: "v", label: "" }], [
          { k: "Chemistry", v: sample ? `${p.chemistry}, 16 cells in series` : p.chemistry }, { k: "Rated capacity", v: `${num(p.rated_capacity_ah, 1)} Ah` },
          { k: sample ? "Logged capacity" : "Latest capacity test", v: `${num(p.measured_capacity_ah, 1)} Ah (${p.capacity_test_date})` },
          sample ? { k: "Voltage window", v: `${p.min_voltage_v}–${p.max_voltage_v} V (${p.voltage_limits_basis})` } : null,
          { k: "Telemetry rows", v: p.telemetry_rows }, { k: "Data class", v: p.is_synthetic ? "SYNTHETIC" : "RECORDED" }].filter(Boolean)));
        if (sample) f.append(h("small", { class: "muted" }, packs[p.asset_id].note));
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

  let lastStatus = null;
  function paint() {
    if (lastStatus !== ctl.status) { lastStatus = ctl.status; drawControls(); }
    clear(circuitBox).append(circuitSvg(app.circuit, ctl.running, () => { ctl.switchBattery(); ui.battery = ctl.profile?.asset_id; ui.source = "virtual"; drawControls(); }));
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
    if (ctl.logNote) live.append(h("small", { class: "muted" }, ctl.logNote, " See ", h("a", { href: "#/database" }, "Database"), "."));
  }
  paint();
}

let current = null;
export function unmount() { if (current) { current.stop(); current = null; } }
