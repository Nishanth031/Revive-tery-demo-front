// Firmware & hardware: the bench circuit (realistic view), the ESP32 sketch v1.1, its line protocol, the safety
// limits, a test-load calculator and the Wokwi project. Monitor-only throughout.
import { h, clear, card, banner, table, icon, download, collapsible, kpi, numberInput, pill } from "../ui/dom.js";
import { MSG_READY, MSG_NOT_FOUND, MSG_READ_FAILED, MSG_OVER_VOLTAGE, MSG_OVER_CURRENT, MSG_BOOT, MSG_FW, MSG_DS18B20,
  INA219_MAX_BUS_VOLTAGE_V, SHUNT_OHMS, SHUNT_SATURATED_MV } from "../engines/esp32sim.js";
import { firmwareMessageSeverity, crc8 } from "../engines/bms.js";
import { circuitSvg } from "./bench.js";

const INA219_RANGE_A = SHUNT_SATURATED_MV / (SHUNT_OHMS * 1000);

function resistorCalculator() {
  const s = { v: 4.2, i: 1.0 };
  const out = h("div");
  const draw = () => {
    clear(out);
    if (!(s.v > 0) || !(s.i > 0)) { out.append(banner("info", "", "Enter a positive cell voltage and target current.")); return; }
    const r = s.v / s.i, p = s.v * s.i, rating = 2 * p;
    out.append(h("div", { class: "grid g3 mt" }, kpi("Resistance", `${r.toFixed(2)} Ω`, "R = V / I"), kpi("Power dissipated", `${p.toFixed(2)} W`, "P = V × I"),
      kpi("Rate the resistor at least", `${Math.ceil(rating)} W`, "2 × P")));
    if (s.i > INA219_RANGE_A) out.append(banner("bad", "Above the INA219 range.", `${s.i} A exceeds ≈${INA219_RANGE_A.toFixed(1)} A: readings would be withheld. Pick a larger resistance.`));
    if (s.v > INA219_MAX_BUS_VOLTAGE_V) out.append(banner("bad", "Above 26 V.", "The INA219 is rated to 26 V. Never use this bench above that, and never on an EV pack."));
    out.append(h("small", { class: "muted" }, "Choose the nearest standard value and recompute the current; the fuse must be rated above that current and below 3.2 A."));
  };
  draw();
  return card("Test-load calculator", [h("div", { class: "form-grid" },
    h("label", { class: "field" }, "Cell voltage (V)", numberInput(s.v, (v) => { s.v = v; draw(); }, { min: 0, step: 0.1 })),
    h("label", { class: "field" }, "Target current (A)", numberInput(s.i, (v) => { s.i = v; draw(); }, { min: 0, step: 0.05 }))), out]);
}

async function wokwiCard(app) {
  let info = null;
  try { info = await app.fetchJSON("data/wokwi.json"); } catch { /* not exported yet */ }
  const url = info?.project_url || "";
  const run = info?.last_run;
  const status = !run ? h("p", { class: "muted" }, "Wokwi checks: not run yet.")
    : run.ran === false ? h("p", { class: "muted" }, `Wokwi checks: not run (${run.reason}).${run.lint_ok !== undefined ? ` Lint ${run.lint_ok ? "passed" : "failed"}.` : ""}`)
      : h("div", { class: "row" }, pill(`lint ${run.lint_ok ? "ok" : "failed"}`, run.lint_ok ? "good" : "bad"),
        pill(`${(run.scenarios || []).filter((x) => x.passed).length}/${(run.scenarios || []).length} scenarios`, "neutral"),
        pill(`${run.lines} lines`, "neutral"), pill(`bad CRC ${run.bad_crc}`, run.bad_crc ? "warn" : "good"), pill(`dropped ${run.dropped}`, run.dropped ? "warn" : "good"));
  const zip = async () => {
    const JSZip = window.JSZip;
    if (!JSZip || !info) return;
    const z = new JSZip();
    for (const f of info.files) z.file(f, await app.fetchText(`data/wokwi/${f}`));
    download("revive_tery_wokwi.zip", await z.generateAsync({ type: "blob" }), "application/zip");
  };
  return card("Simulate in Wokwi", [
    h("p", {}, "The same firmware and wiring as a Wokwi project: ESP32 DevKit, two DS18B20 on one 1-Wire bus, the 4.7 kΩ pull-up and an INA219 custom chip whose sliders set bus voltage and current."),
    h("div", { class: "row" },
      h("button", { class: "btn primary", type: "button", disabled: !url, title: url ? url : "", onclick: () => { if (url) window.open(url, "_blank", "noopener"); } },
        icon("play", 15), url ? "Open the Wokwi project" : "set wokwi.project_url after importing the project"),
      h("button", { class: "btn", type: "button", disabled: !info, onclick: zip }, icon("download", 15), "Download Wokwi project (zip)")),
    status,
    h("small", { class: "muted" }, "Nothing is loaded from Wokwi until you click. Unverified: the ESP32 board pin names and the custom chip's control fields (see engines/firmware/wokwi/README.md); the custom chip is not built here.")]);
}

export async function render(root, app) {
  let ino = null;
  try { ino = await app.fetchText("data/firmware/revive_tery_esp32.ino"); } catch (e) { console.error(e); }
  const pins = Object.fromEntries(app.circuit.components.flatMap((c) => c.pins.map((p) => [p.id, `${c.title} ${p.label}`])));
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Firmware & hardware"),
    h("p", {}, "The physical bench: a single cell in a holder discharging through a fused, switched test load, measured by an INA219 (bus voltage and shunt current over I²C) and two DS18B20 (cell and ambient, one 1-Wire bus), read by an ESP32 that prints one JSON line per second over USB."))));
  root.append(banner("bad", "Low voltage only.", `The INA219 is rated to ${INA219_MAX_BUS_VOLTAGE_V} V. Never connect an EV pack or anything above that to this bench. Above the limit the firmware withholds readings and prints a critical warning. The circuit gives no protection beyond the fuse.`));
  root.append(card("Bench circuit", [circuitSvg(app.circuit, false),
    h("small", { class: "muted" }, "Hover a pin to see what it connects to; click it to highlight its net. Faded parts are recommended additions (fuse, switch, decoupling, ambient sensor); the I²C pull-ups and the 10 µF are only needed if your boards lack them.")], null, "mb"));
  const sample = '{"voltage":3.712,"current":0.5210,"temperature":28.44,"ambient":24.10,"seq":42,"t_ms":42011';
  const crc = crc8(sample).toString(16).toUpperCase().padStart(2, "0");
  const msgs = [MSG_BOOT, MSG_FW, MSG_READY, ...MSG_DS18B20, "# hb seq=42", MSG_NOT_FOUND, MSG_READ_FAILED, `${MSG_READ_FAILED} (x7)`, MSG_OVER_VOLTAGE, MSG_OVER_CURRENT];
  root.append(h("div", { class: "grid g2" },
    collapsible("Wiring list", table([{ label: "From", render: (w) => pins[w.from] }, { label: "To", render: (w) => pins[w.to] }, { key: "type", label: "Type" }, { key: "description", label: "Why" }], app.circuit.wires)),
    card("Line protocol v1.1 (ESP32 → laptop, 115200 baud)", [
      h("p", {}, "Telemetry, once per second (v1.0 lines with only the first three keys still parse):"),
      h("pre", {}, h("code", {}, `${sample},"crc":"${crc}"}\n{"voltage":3.712,"current":0.5021,"temperature":null}   <- v1.0 line, DS18B20 missing`)),
      table([{ key: "k", label: "Key" }, { key: "d", label: "Meaning" }], [
        { k: "voltage, current", d: "means of 10 INA219 samples in that second (so 1 s coulomb counting equals the sampled integral)" },
        { k: "temperature", d: "cell DS18B20 (index 0), °C or null" },
        { k: "ambient", d: "second DS18B20 (index 1), °C or null → ambient_temperature_c" },
        { k: "seq", d: "line counter; gaps are counted as dropped lines" },
        { k: "t_ms", d: "millis() at sampling on the ESP32" },
        { k: "crc", d: "CRC-8 (poly 0x07) over the bytes before ,\"crc\"; a wrong CRC drops the line and counts a CRC error" }]),
      h("p", { class: "mt" }, "Status and fault lines start with ", h("code", {}, "#"), ". Repeated warnings are printed at most every 10 s with a repeat count:"),
      table([{ key: "m", label: "Message" }, { key: "s", label: "Severity" }], msgs.map((m) => ({ m, s: firmwareMessageSeverity(m) }))),
      h("p", { class: "muted mt", style: { fontSize: "12.5px" } }, `Shunt ${SHUNT_OHMS} Ω, saturating at ${SHUNT_SATURATED_MV} mV (≈3.2 A; RANGE_16V_400MA: 0.4 A and 16 V). A DS18B20 reading of −127 °C means disconnected and is dropped. Unknown messages count as warnings.`),
      h("p", { class: "muted", style: { fontSize: "12.5px" } }, "Monitor-only: the sketch never reads the serial port and drives no output on the battery or load path; the app opens the port for reading only.")])));
  root.append(h("div", { class: "grid g2 mt" }, resistorCalculator(), await wokwiCard(app)));
  if (ino === null) {
    root.append(banner("bad", "Could not load the firmware sketch.", "data/firmware/revive_tery_esp32.ino was not served."));
    return;
  }
  root.append(card("revive_tery_esp32.ino (v1.1.0)", h("div", { class: "row" }, h("button", { class: "btn primary", onclick: () => download("revive_tery_esp32.ino", ino, "text/plain") }, icon("download", 15), "Download sketch"),
    h("small", { class: "muted" }, `${ino.split("\n").length} lines · Libraries: Adafruit INA219, OneWire, DallasTemperature · compiled here with arduino-cli (esp32 core 3.3.12), never flashed.`)), null, "mt"));
  root.append(collapsible("Sketch source", h("pre", { style: { maxHeight: "520px", margin: 0 } }, h("code", {}, ino)), false, "mt"));
}
