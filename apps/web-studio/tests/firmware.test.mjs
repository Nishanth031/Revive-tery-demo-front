// Firmware v1.1 line protocol in the browser port: CRC-8 vectors from Python, old lines still parse, throttling,
// seq gaps and CRC errors counted, ambient mapped.
import { test } from "node:test";
import assert from "node:assert/strict";
import { golden } from "./helpers.mjs";
import { crc8, lineCrcOk, parseTelemetryLine, handleSerialLine, SerialStats, firmwareMessageSeverity } from "../assets/js/engines/bms.js";
import { SimulatedESP32 } from "../assets/js/engines/esp32sim.js";

test("CRC-8 matches the Python vectors", () => {
  const v = golden("crc_vectors.json");
  assert.ok(v.length >= 5);
  for (const { text, crc } of v) assert.equal(crc8(text), crc, JSON.stringify(text));
});

test("v1.0 lines still parse; v1.1 lines with a good CRC parse, a bad CRC is rejected", () => {
  const old = parseTelemetryLine('{"voltage":3.712,"current":0.5210,"temperature":28.44}', 1);
  assert.equal(old.voltage_v, 3.712); assert.equal(old.ambient_temperature_c, null); assert.equal(old.seq, null);
  const body = '{"voltage":3.712,"current":0.5210,"temperature":28.44,"ambient":24.10,"seq":42,"t_ms":42011';
  const line = `${body},"crc":"${crc8(body).toString(16).toUpperCase().padStart(2, "0")}"}`;
  assert.equal(lineCrcOk(line), true);
  const s = parseTelemetryLine(line, 2);
  assert.equal(s.ambient_temperature_c, 24.1); assert.equal(s.seq, 42);
  assert.equal(parseTelemetryLine(line.replace("3.712", "3.713"), 3), null);
  assert.equal(lineCrcOk('{"voltage":1,"current":0}'), null);
});

test("status lines are info; a throttled repeat keeps its base severity", () => {
  for (const m of ["# fw=revive_tery_esp32 v1.1.0 profile=RANGE_32V_2A sensors=ina219,ds18b20", "# hb seq=3", "# boot reason=power_on", "# ds18b20[1]=2800000000000002"]) assert.equal(firmwareMessageSeverity(m), "info");
  assert.equal(firmwareMessageSeverity("# OVER 26 V: disconnect now, this exceeds the INA219's rating (x7)"), "critical");
  assert.equal(firmwareMessageSeverity("# INA219 read failed: check the wiring (x3)"), "warning");
});

test("simulator: a 30 s fault prints the warning at most 3 times; crc and seq faults are counted", () => {
  const sim = new SimulatedESP32({ true_capacity_ah: 1.8, load_current_a: 1.0, speed: 60, seed: 7 }, 0);
  const stats = new SerialStats();
  for (const l of sim.open()) handleSerialLine(l, 0, stats);
  for (let t = 0; t < 10; t++) for (const l of sim.tick()) handleSerialLine(l, t, stats);
  sim.setFault("overvoltage");
  let prints = 0;
  for (let t = 0; t < 30; t++) for (const l of sim.tick()) { if (l.startsWith("# OVER")) prints++; handleSerialLine(l, t, stats); }
  assert.ok(prints >= 1 && prints <= 3, `${prints} prints`);
  const counted = stats.fault_counts["OVER 26 V: disconnect now, this exceeds the INA219's rating"];
  assert.ok(counted >= prints && counted <= 30, `counted ${counted} occurrences from ${prints} prints`);   // "(x10)" adds 10
  sim.setFault("none");
  for (let t = 0; t < 5; t++) for (const l of sim.tick()) handleSerialLine(l, t, stats);
  sim.setFault("crc_corruption");
  for (let t = 0; t < 4; t++) for (const l of sim.tick()) handleSerialLine(l, t, stats);
  assert.equal(stats.crc_errors, 4);
  sim.setFault("seq_gap");
  const before = stats.dropped_lines;
  for (let t = 0; t < 5; t++) for (const l of sim.tick()) handleSerialLine(l, t, stats);
  assert.ok(stats.dropped_lines - before >= 5, `dropped ${stats.dropped_lines - before}`);
});
