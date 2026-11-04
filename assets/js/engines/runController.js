// Test runs (port of bulid X/src/run_controller.py): one controller feeds readings from a source through the
// BMS engine and logs them. Sources: virtual replay of recorded telemetry, the simulated ESP32, or a real ESP32
// over Web Serial. MONITOR-ONLY: the serial wrapper below can only read; nothing is ever written to the board.

import { BMSEngine, SerialStats, handleSerialLine, getDecisionForUi, faultFlags, loadBatteryProfile, listBatteryIds,
  replaySamples, BUNDLE_DISCHARGE_POSITIVE } from "./bms.js";
import { SimulatedESP32, FAULTS } from "./esp32sim.js";

export const HISTORY_LIMIT = 2000;
export const HARDWARE_BATTERY_ID = "HARDWARE-BENCH";
export const SIMULATED_BATTERY_ID = "SIMULATED-CELL";
export const SPEED_LIMITS = [1.0, 600.0];
export const SIMULATED_RATED_AH = 2.0;
export const SIMULATED_CUTOFF_V = 3.0;
export const SIM_MAX_LOAD_A = 3.0;

const runId = () => new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z-") + Math.random().toString(16).slice(2, 8);

/** the only access this app has to a serial port: it can read lines and close, and has no way to write */
class ReadOnlyPort {
  constructor(port) { this.port = port; this.reader = null; this.buffer = ""; this.closed = false; }
  static async open(port, baudRate) {
    await port.open({ baudRate });
    // ESP32 boards reset when DTR/RTS are raised; keeping them low means monitoring doesn't restart the board.
    try { await port.setSignals({ dataTerminalReady: false, requestToSend: false }); } catch { /* not supported */ }
    return new ReadOnlyPort(port);
  }
  /** yields complete text lines until closed */
  async *lines() {
    const decoder = new TextDecoder();
    while (!this.closed && this.port.readable) {
      this.reader = this.port.readable.getReader();
      try {
        for (;;) {
          const { value, done } = await this.reader.read();
          if (done) break;
          this.buffer += decoder.decode(value, { stream: true });
          let k;
          while ((k = this.buffer.search(/\r?\n/)) >= 0) {
            const line = this.buffer.slice(0, k);
            this.buffer = this.buffer.slice(this.buffer[k] === "\r" ? k + 2 : k + 1);
            yield line;
          }
        }
      } finally { this.reader.releaseLock(); this.reader = null; }
    }
  }
  async close() {
    this.closed = true;
    try { if (this.reader) await this.reader.cancel(); } catch { /* already closed */ }
    try { await this.port.close(); } catch { /* already closed */ }
  }
}

/** readings outside the pack's stated voltage window: capacity tiers don't cover this, so it is said first */
export function voltageFlags(profile, rows) {
  const v = rows.map((r) => r.voltage_v).filter(Number.isFinite);
  if (!profile || !v.length) return [];
  const flags = [];
  const lo = Math.min(...v), hi = Math.max(...v);
  if (profile.min_voltage_v !== null && profile.min_voltage_v !== undefined && lo < profile.min_voltage_v) {
    flags.push(`Over-discharge: the voltage fell to ${lo.toFixed(1)} V, below the pack's minimum of ${profile.min_voltage_v} V. ` +
      "Inspect the pack before any reuse; this capacity-based tier doesn't account for it.");
  }
  if (profile.max_voltage_v !== null && profile.max_voltage_v !== undefined && hi > profile.max_voltage_v) {
    flags.push(`Over-voltage: the voltage reached ${hi.toFixed(1)} V, above the pack's maximum of ${profile.max_voltage_v} V. Inspect the pack before any reuse.`);
  }
  return flags;
}

export class RunController {
  /** tables: demo database rows; parseTime: ISO -> epoch seconds; onUpdate(): redraw; onLog(rows): store run rows */
  /** packs: optional { asset_id: { profile, samples, note } } replayable alongside the database (engines/samplePacks.js) */
  constructor({ tables, parseTime, onUpdate = () => {}, onLog = () => {}, packs = {} }) {
    this.tables = tables; this.parseTime = parseTime; this.onUpdate = onUpdate; this.onLog = onLog; this.packs = packs;
    this.status = "idle"; this.source = "virtual"; this.notice = ""; this.error = ""; this.logNote = "";
    this.readings = []; this.decision = null; this.stats = new SerialStats(); this.simulated = false; this.sim = null;
    this.engine = null; this.runStartedAt = 0; this.timer = null; this.port = null; this.stopRequested = false;
    this.dbBatteryIds = listBatteryIds(tables);
    this.batteryIds = [...this.dbBatteryIds, ...Object.keys(packs).sort().filter((id) => !this.dbBatteryIds.includes(id))];
    this.profile = this.batteryIds.length ? this.loadProfile(this.batteryIds[0]) : null;
    if (!this.batteryIds.length) this.error = "The database has no batteries yet.";
  }
  get running() { return this.status === "running"; }
  isSamplePack(assetId) { return !this.dbBatteryIds.includes(assetId) && assetId in this.packs; }
  loadProfile(assetId) { return this.isSamplePack(assetId) ? { ...this.packs[assetId].profile } : loadBatteryProfile(this.tables, assetId); }
  whereFrom(assetId) { return this.isSamplePack(assetId) ? `the sample pack ${this.packs[assetId].profile.file}` : "the database"; }

  selectBattery(assetId) {
    if (this.running) { this.notice = "Stop the test before switching battery."; this.onUpdate(); return false; }
    if (!this.batteryIds.includes(assetId)) return false;
    this.profile = this.loadProfile(assetId);
    this.reset("virtual");
    this.status = "idle";
    this.notice = `Loaded ${assetId} from ${this.whereFrom(assetId)}.`;
    this.onUpdate();
    return true;
  }
  /** battery tapped in the circuit: move to the next battery and reset */
  switchBattery() {
    if (this.running) { this.notice = "Stop the test before switching battery."; this.onUpdate(); return; }
    const ids = this.batteryIds;
    if (!ids.length) { this.error = "The database has no batteries yet."; this.onUpdate(); return; }
    const pos = this.profile ? ids.indexOf(this.profile.asset_id) : -1;
    const next = ids[(pos + 1) % ids.length];
    this.profile = this.loadProfile(next);
    this.reset("virtual");
    this.status = "idle";
    this.notice = ids.length === 1 ? `Reloaded ${next} from the database. It's the only battery in the database.`
      : `Loaded ${next} from ${this.whereFrom(next)} (${ids.indexOf(next) + 1} of ${ids.length}).`;
    this.onUpdate();
  }
  reset(source) {
    this.readings = []; this.decision = null; this.error = ""; this.notice = ""; this.logNote = "";
    this.source = source; this.simulated = false; this.sim = null; this.stats = new SerialStats(); this.stopRequested = false;
  }
  begin(source, engine, meta) {
    this.reset(source);
    this.status = "running";
    this.engine = engine;
    this.runStartedAt = Date.now() / 1000;
    this.run = { run_id: runId(), ...meta, rows: [] };
    this.onUpdate();
  }
  push(sample) {
    const r = this.engine.process(sample);
    this.readings.push(r);
    if (this.readings.length > HISTORY_LIMIT) this.readings.shift();
    const s = r.sample;
    this.run.rows.push({ run_id: this.run.run_id, logged_at: s.timestamp, source: this.run.source, asset_id: this.run.asset_id,
      data_class: this.run.data_class, voltage_v: s.voltage_v, current_a: s.current_a, temperature_c: s.temperature_c,
      soc_pct: r.soc_pct, soh_live_pct: r.soh_live_pct, soh_basis: r.soh_basis });
    return r;
  }
  finish(finalStatus, error = "") {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    if (this.status !== "running") return;
    this.status = finalStatus;
    this.error = error;
    const n = this.run.rows.length;
    try { this.onLog(this.run.rows); this.logNote = `${n} readings logged to the in-browser table test_run_log (run ${this.run.run_id}).`; }
    catch (e) { this.logNote = `Some readings couldn't be logged: ${e.message}`; }
    this.decision = this.engine.samples_seen ? getDecisionForUi(this.engine) : null;
    if (this.decision && this.source === "virtual") this.decision.flags = [...voltageFlags(this.profile, this.run.rows), ...this.decision.flags];
    if (this.decision) {
      this.decision.flags = [...this.decision.flags, ...faultFlags(this.stats)];
      if (this.simulated) this.decision.flags.unshift("This result comes from a software simulation of a made-up cell, not from a real battery.");
    }
    this.onUpdate();
  }

  // ---------------------------------------------------------------- source 1: virtual replay of recorded telemetry
  startVirtual(delayS = 1.0) {
    if (this.running) return;
    const p = this.profile;
    if (!p) { this.notice = "No battery is loaded."; this.onUpdate(); return; }
    if (!p.telemetry_rows) { this.notice = `${p.asset_id} has no telemetry to replay.`; this.onUpdate(); return; }
    const engine = new BMSEngine({ rated_capacity_ah: p.rated_capacity_ah, baseline_measured_ah: p.measured_capacity_ah,
      baseline_date: p.capacity_test_date, discharge_positive: BUNDLE_DISCHARGE_POSITIVE, ...(p.baseline_source ? { baseline_source: p.baseline_source } : {}) });
    const pack = this.isSamplePack(p.asset_id) ? this.packs[p.asset_id] : null;
    this.begin("virtual", engine, { source: pack ? "sample_pack_replay" : "virtual_replay", asset_id: p.asset_id, data_class: p.is_synthetic ? "SYNTHETIC" : "RECORDED" });
    const samples = pack ? pack.samples : replaySamples(this.tables, p.asset_id, this.parseTime);
    let k = 0;
    const step = () => {
      if (this.stopRequested) return this.finish("stopped");
      if (k >= samples.length) return this.finish("finished");
      this.push(samples[k++]);
      this.onUpdate();
    };
    step();
    this.timer = setInterval(step, Math.max(20, delayS * 1000));
  }

  // ---------------------------------------------------------------- source 2: the simulated ESP32, through the hardware path
  startSimulated(settings, simSettings, fault = "none") {
    if (this.running) return;
    const sim = new SimulatedESP32(simSettings);
    sim.setFault(fault);
    const engine = new BMSEngine({ rated_capacity_ah: settings.rated_capacity_ah, initial_soc_pct: sim.settings.start_soc_pct,
      cutoff_voltage_v: settings.cutoff_voltage_v, discharge_positive: true });
    this.begin("hardware", engine, { source: "esp32_simulated", asset_id: SIMULATED_BATTERY_ID, data_class: "SIMULATED" });
    this.simulated = true;
    this.sim = sim;
    const feed = (lines) => {
      for (const line of lines) {
        const s = handleSerialLine(line, sim.clock(), this.stats);
        if (s) { this.push(s); if (sim.complete) return true; } // a bench run ends when the load has emptied the cell
      }
      return false;
    };
    sim.open().forEach((l) => handleSerialLine(l, sim.clock(), this.stats));
    const t0 = performance.now();
    let ticks = 0;
    const speed = Math.min(SPEED_LIMITS[1], Math.max(SPEED_LIMITS[0], sim.settings.speed));
    this.timer = setInterval(() => {
      if (this.stopRequested) return this.finish("stopped");
      const due = Math.floor((performance.now() - t0) / 1000 * speed);
      let done = false;
      for (let n = 0; ticks < due && n < 2000 && !done; n++) { ticks++; done = feed(sim.tick()); }
      this.onUpdate();
      if (done) this.finish("finished");
    }, 50);
  }
  setSimFault(fault) { if (this.sim && fault in FAULTS) { this.sim.setFault(fault); this.onUpdate(); } }

  // ---------------------------------------------------------------- source 3: a real ESP32 over Web Serial (read-only)
  static hardwareSupported() { return typeof navigator !== "undefined" && "serial" in navigator; }
  async startHardware(settings) {
    if (this.running) return;
    if (!RunController.hardwareSupported()) {
      this.error = "This browser has no Web Serial. Use Chrome or Edge on a desktop, over https or localhost."; this.onUpdate(); return;
    }
    let port;
    try { port = await navigator.serial.requestPort(); }
    catch { this.notice = "No port chosen."; this.onUpdate(); return; }
    const engine = new BMSEngine({ rated_capacity_ah: settings.rated_capacity_ah, initial_soc_pct: settings.start_soc_pct,
      cutoff_voltage_v: settings.cutoff_voltage_v, discharge_positive: settings.discharge_positive });
    this.begin("hardware", engine, { source: "esp32_hardware", asset_id: HARDWARE_BATTERY_ID, data_class: "MEASURED" });
    try {
      this.port = await ReadOnlyPort.open(port, settings.baudrate || 115200);
      for await (const line of this.port.lines()) {
        if (this.stopRequested) break;
        const s = handleSerialLine(line, Date.now() / 1000, this.stats);
        if (s) this.push(s);
        this.onUpdate();
      }
      this.finish(this.stopRequested ? "stopped" : "finished");
    } catch (e) {
      this.finish("error", `Lost the connection to the ESP32: ${e.message}`);
    } finally {
      if (this.port) await this.port.close();
      this.port = null;
    }
  }

  stop() {
    this.stopRequested = true;
    if (this.port) this.port.close();
    if (this.status === "running" && this.source === "virtual" && this.timer) this.finish("stopped");
    if (this.status === "running" && this.simulated) this.finish("stopped");
  }
}
