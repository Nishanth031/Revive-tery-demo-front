// A software ESP32 and bench circuit (port of bulid X/src/esp32_sim.py): a 1S Li-ion cell, a constant-current
// load, an INA219 and a DS18B20, running the same decisions as firmware/revive_tery_esp32 (same JSON lines,
// same "#" fault messages, same limits and retry timing). Readings are GENERATED, not measured: label them simulated.
// MONITOR-ONLY like the real monitor: it has no method that accepts data.

import { rng as makeRng, pyRound } from "../lib/np.js";

export const MSG_READY = "# INA219 ready";
export const MSG_NOT_FOUND = "# INA219 not found: check SDA, SCL, VCC and GND";
export const MSG_READ_FAILED = "# INA219 read failed: check the wiring";
export const MSG_OVER_VOLTAGE = "# OVER 26 V: disconnect now, this exceeds the INA219's rating";
export const MSG_OVER_CURRENT = "# Current above the 3.2 A range: reading withheld";
export const SAMPLE_PERIOD_S = 1.0;
export const SENSOR_RETRY_S = 5.0;
export const INA219_MAX_BUS_VOLTAGE_V = 26.0;
export const SHUNT_SATURATED_MV = 319.0;
export const SHUNT_OHMS = 0.1;

export const FAULTS = {
  none: "No fault",
  ina219: "INA219 wire comes loose",
  ds18b20: "DS18B20 temperature sensor disconnected",
  overvoltage: "Over-voltage on the sensor inputs (+22 V)",
  overcurrent: "Load draws 3.5 A (over the 3.2 A range)",
  silent: "ESP32 stops sending (cable or board failure)",
};
export const OVER_VOLTAGE_OFFSET_V = 22.0;
export const OVER_CURRENT_LOAD_A = 3.5;
export const OCV_CURVE = [[0.0, 3.00], [10.0, 3.45], [50.0, 3.75], [90.0, 4.05], [100.0, 4.20]];
export const CELL_RESISTANCE_OHM = 0.10;
export const LOAD_CUTOFF_V = 3.00;
export const THERMAL_MASS_J_PER_K = 40.0;
export const THERMAL_RESISTANCE_K_PER_W = 15.0;
export const BUS_VOLTAGE_LSB_V = 0.004;
export const CURRENT_LSB_A = 0.0001;
export const DS18B20_LSB_C = 0.0625;
export const BUS_VOLTAGE_NOISE_V = 0.002;
export const CURRENT_NOISE_A = 0.0005;
export const TEMPERATURE_NOISE_C = 0.03;

export function openCircuitVoltage(socPct) {
  const soc = Math.max(0.0, Math.min(100.0, socPct));
  for (let k = 0; k < OCV_CURVE.length - 1; k++) {
    const [x0, y0] = OCV_CURVE[k], [x1, y1] = OCV_CURVE[k + 1];
    if (soc <= x1) return y0 + (y1 - y0) * (soc - x0) / (x1 - x0);
  }
  return OCV_CURVE[OCV_CURVE.length - 1][1];
}
const quantise = (v, step) => pyRound(v / step) * step;
const lineWith = (v, i, t) => `{"voltage":${v.toFixed(3)},"current":${i.toFixed(4)},"temperature":${t.toFixed(2)}}`;
const lineWithout = (v, i) => `{"voltage":${v.toFixed(3)},"current":${i.toFixed(4)},"temperature":null}`;

export const DEFAULT_SIM = { true_capacity_ah: 1.8, start_soc_pct: 100.0, load_current_a: 1.0, speed: 60.0, seed: null };

export class SimulatedESP32 {
  constructor(settings = {}, startEpoch = null) {
    this.settings = { ...DEFAULT_SIM, ...settings };
    const s = this.settings;
    if (!(s.true_capacity_ah > 0) || s.load_current_a < 0 || !(s.speed > 0)) throw new Error("capacity and speed must be positive and the load can't be negative");
    this.startEpoch = startEpoch === null ? Date.now() / 1000 : startEpoch;
    this.rand = makeRng(s.seed === null || s.seed === undefined ? Math.floor(Math.random() * 2 ** 31) : s.seed);
    this.fault = "none";
    this.t = 0.0;
    this.ready = true;
    this.lastRetry = 0.0;
    this.isOpen = false;
    this.soc_pct = Math.max(0.0, Math.min(100.0, s.start_soc_pct));
    this.delivered_ah = 0.0;
    this.temperature_c = 25.0;
    this.ambient_c = 25.0;
    this.load_on = s.load_current_a > 0;
    this.complete = false;
    this.terminal_v = openCircuitVoltage(this.soc_pct);
    this.current_a = 0.0;
  }
  /** setup() in the sketch announces the sensor, or reports it missing */
  open() {
    this.isOpen = true;
    if (this.fault === "ina219") { this.ready = false; return [MSG_NOT_FOUND]; }
    return [MSG_READY];
  }
  close() { this.isOpen = false; }
  clock() { return this.startEpoch + this.t; }
  setFault(fault) {
    if (!(fault in FAULTS)) throw new Error(`Unknown fault '${fault}'`);
    this.fault = fault;
  }
  loadCurrent() {
    if (!this.load_on) return 0.0;
    return this.fault === "overcurrent" ? OVER_CURRENT_LOAD_A : this.settings.load_current_a;
  }
  stepPhysics() {
    const dt = SAMPLE_PERIOD_S, current = this.loadCurrent();
    this.current_a = current;
    this.delivered_ah += current * dt / 3600.0;
    this.soc_pct = Math.max(0.0, this.soc_pct - current * dt / 3600.0 / this.settings.true_capacity_ah * 100.0);
    this.terminal_v = openCircuitVoltage(this.soc_pct) - current * CELL_RESISTANCE_OHM;
    const heat = current * current * CELL_RESISTANCE_OHM;
    const loss = (this.temperature_c - this.ambient_c) / THERMAL_RESISTANCE_K_PER_W;
    this.temperature_c += (heat - loss) * dt / THERMAL_MASS_J_PER_K;
  }
  /** one pass of the firmware's loop(), a second later; returns the lines it would print */
  tick() {
    const fault = this.fault;
    this.t += SAMPLE_PERIOD_S;
    this.stepPhysics();
    const sampleV = this.terminal_v, sampleI = this.current_a;
    if (this.load_on && sampleV <= LOAD_CUTOFF_V) { this.load_on = false; this.complete = true; }
    if (fault === "silent") return [];
    if (!this.ready) {
      if (this.t - this.lastRetry >= SENSOR_RETRY_S) {
        this.lastRetry = this.t;
        if (fault === "ina219") return [MSG_NOT_FOUND];
        this.ready = true;
        return [MSG_READY];
      }
      return [];
    }
    if (fault === "ina219") { this.ready = false; this.lastRetry = this.t; return [MSG_READ_FAILED]; }
    let shuntMv = sampleI * SHUNT_OHMS * 1000.0;
    let busV = sampleV - shuntMv / 1000.0;
    if (fault === "overvoltage") busV += OVER_VOLTAGE_OFFSET_V;
    busV = quantise(busV + this.rand.gauss(0, BUS_VOLTAGE_NOISE_V), BUS_VOLTAGE_LSB_V);
    const currentA = quantise(sampleI + this.rand.gauss(0, CURRENT_NOISE_A), CURRENT_LSB_A);
    shuntMv = currentA * SHUNT_OHMS * 1000.0;
    const voltage = busV + shuntMv / 1000.0;
    if (voltage > INA219_MAX_BUS_VOLTAGE_V) return [MSG_OVER_VOLTAGE];
    if (Math.abs(currentA * 100.0) > SHUNT_SATURATED_MV) return [MSG_OVER_CURRENT];
    if (fault === "ds18b20") return [lineWithout(voltage, currentA)];
    const temperature = quantise(this.temperature_c + this.rand.gauss(0, TEMPERATURE_NOISE_C), DS18B20_LSB_C);
    return [lineWith(voltage, currentA, temperature)];
  }
}
