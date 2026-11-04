// Firmware & hardware: the bench wiring, the ESP32 sketch, its line protocol and the safety limits.
import { h, card, banner, table, icon, download } from "../ui/dom.js";
import { MSG_READY, MSG_NOT_FOUND, MSG_READ_FAILED, MSG_OVER_VOLTAGE, MSG_OVER_CURRENT, INA219_MAX_BUS_VOLTAGE_V, SHUNT_OHMS, SHUNT_SATURATED_MV } from "../engines/esp32sim.js";
import { firmwareMessageSeverity } from "../engines/bms.js";

export async function render(root, app) {
  const ino = await app.fetchText("data/firmware/revive_tery_esp32.ino");
  const pins = Object.fromEntries(app.circuit.components.flatMap((c) => c.pins.map((p) => [p.id, `${c.title} ${p.label}`])));
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Firmware & hardware"),
    h("p", {}, "The physical bench: a low-voltage cell or small pack discharging through a test load, measured by an INA219 (bus voltage and shunt current over I²C) and a DS18B20 (temperature over 1-Wire), read by an ESP32 that prints one JSON line per second over USB."))));
  root.append(banner("bad", "Low voltage only.", `The INA219 is rated to ${INA219_MAX_BUS_VOLTAGE_V} V. Never connect an EV pack or anything above that to this bench. Above the limit the firmware withholds readings and prints a critical warning.`));
  root.append(h("div", { class: "grid g2" },
    card("Wiring", table([{ label: "From", render: (w) => pins[w.from] }, { label: "To", render: (w) => pins[w.to] }, { key: "type", label: "Type" }, { key: "description", label: "Why" }], app.circuit.wires)),
    card("Line protocol (ESP32 → laptop, 115200 baud)", [
      h("p", {}, "Telemetry, once per second:"),
      h("pre", {}, h("code", {}, '{"voltage":3.712,"current":0.5021,"temperature":28.44}\n{"voltage":3.712,"current":0.5021,"temperature":null}   <- DS18B20 missing')),
      h("p", {}, "Status and fault lines start with ", h("code", {}, "#"), ". The app classifies them:"),
      table([{ key: "m", label: "Message" }, { key: "s", label: "Severity" }], [MSG_READY, MSG_NOT_FOUND, MSG_READ_FAILED, MSG_OVER_VOLTAGE, MSG_OVER_CURRENT].map((m) => ({ m, s: firmwareMessageSeverity(m) }))),
      h("p", { class: "muted mt", style: { fontSize: "12.5px" } }, `Shunt ${SHUNT_OHMS} Ω, saturating at ${SHUNT_SATURATED_MV} mV (≈3.2 A). A DS18B20 reading of −127 °C means disconnected and is dropped. Unknown messages count as warnings — a monitor shouldn't ignore what it doesn't recognise.`),
      h("p", { class: "muted", style: { fontSize: "12.5px" } }, "Monitor-only: the app opens the port for reading, keeps DTR/RTS low so the board doesn't reset, and has no code path that writes to it.")])));
  root.append(card("revive_tery_esp32.ino", [h("div", { class: "row mb" }, h("button", { class: "btn", onclick: () => download("revive_tery_esp32.ino", ino, "text/plain") }, icon("download", 15), "Download sketch"),
    h("small", { class: "muted" }, "Libraries: Adafruit INA219, OneWire, DallasTemperature.")), h("pre", { style: { maxHeight: "520px" } }, h("code", {}, ino))], null, "mt"));
}
