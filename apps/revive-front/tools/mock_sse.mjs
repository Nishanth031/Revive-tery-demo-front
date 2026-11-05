// Tiny local mock of the bench API, so the bench page can be built and tested without starting a real run.
// Usage: node tools/mock_sse.mjs [port=8765], then in the browser console:
//   localStorage.setItem("revive.api.base", "http://127.0.0.1:8765"); location.reload();
// (remove the key afterwards). It answers /api/health, /api/faults, /api/runs*, /api/runs/stream with the field names of
// services/api/revive_api/services/runs.py::snapshot_json. Every other route returns 404, so the rest of the site
// falls back honestly. Nothing here touches the database.
import { createServer } from "node:http";

const PORT = Number(process.argv[2] || 8765);
const FAULTS = [
  ["none", "No fault"], ["ina219", "INA219 wire comes loose"], ["ds18b20", "DS18B20 temperature sensor disconnected"],
  ["overvoltage", "Over-voltage on the sensor inputs (+22 V)"], ["overcurrent", "Load draws 3.5 A (over the 3.2 A range)"],
  ["silent", "ESP32 stops sending (cable or board failure)"], ["crc_corruption", "Lines corrupted on the cable (bad CRC)"], ["seq_gap", "Lines lost on the way (seq gaps)"],
];
const MSG = { overvoltage: ["OVER 26 V: disconnect now, this exceeds the INA219's rating", "critical"], overcurrent: ["Current above the 3.2 A range: reading withheld", "warning"],
  ina219: ["INA219 read failed: check the wiring", "warning"], ds18b20: ["Cell temperature sensor not found", "warning"] };

const run = { status: "idle", running: false, readings: [], fault: "none", soc: 100, t0: 0, last: "", sev: "", counts: {} };
const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Allow-Methods": "GET,POST,OPTIONS" };

function step() {
  if (!run.running) return;
  const now = Date.now() / 1000;
  run.soc = Math.max(0, run.soc - 0.6);
  const f = run.fault;
  const v = f === "overvoltage" ? 25.9 : 3.0 + (run.soc / 100) * 1.15 + (Math.random() - 0.5) * 0.004;
  const i = f === "overcurrent" || f === "ina219" ? null : 1.0 + (Math.random() - 0.5) * 0.01;
  const t = f === "ds18b20" ? null : 25 + (100 - run.soc) * 0.05 + (Math.random() - 0.5) * 0.1;
  if (f !== "silent") run.readings.push({ timestamp: now, voltage_v: v, current_a: i, temperature_c: t, reported_soc_pct: null, state: "discharging",
    soc_pct: run.soc, soh_live_pct: null, soh_basis: null, discharged_ah: (100 - run.soc) / 100 * 1.8, delta_time_s: 1 });
  if (MSG[f]) { run.last = MSG[f][0]; run.sev = MSG[f][1]; }
  if (run.soc <= 0) { run.running = false; run.status = "finished"; }
}
setInterval(step, 500);

function snapshot(since) {
  const rs = since == null ? run.readings.slice(-600) : run.readings.filter((r) => r.timestamp > since);
  return { status: run.status, running: run.running, source: "simulated", mode: "simulated", simulated: true, stale: false, server_time: Date.now() / 1000,
    battery: null, battery_count: 0, notice: run.running ? "SIMULATED run (mock server)" : null, error: null, log_note: null, decision: run.status === "finished" ? "mock run finished" : null,
    run_started_at: run.t0, counts: { good_lines: run.readings.length, bad_lines: 0, message_lines: run.last ? 1 : 0, readings_held: run.readings.length },
    fault: { active: run.fault !== "none", last: run.last, severity: run.sev, counts: {} }, readings: rs };
}

const body = (req) => new Promise((r) => { let b = ""; req.on("data", (c) => { b += c; }); req.on("end", () => { try { r(JSON.parse(b || "{}")); } catch { r({}); } }); });
const json = (res, code, obj) => { res.writeHead(code, { ...cors, "Content-Type": "application/json" }); res.end(JSON.stringify(obj)); };

createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (req.method === "OPTIONS") { res.writeHead(204, cors); res.end(); return; }
  if (url.pathname === "/api/health") return json(res, 200, { status: "ok", api_version: "mock", ml_engine_version: "mock", database: { available: false }, run: { status: run.status } });
  if (url.pathname === "/api/faults") return json(res, 200, FAULTS.map(([id, label]) => ({ id, label })));
  if (url.pathname === "/api/runs" && req.method === "POST") {
    const b = await body(req);
    if (b.source !== "simulated") return json(res, 422, { detail: "mock accepts source 'simulated' only", code: "unsupported" });
    if (run.running) return json(res, 409, { detail: "A test is already running. Stop it first.", code: "run_conflict" });
    Object.assign(run, { status: "running", running: true, readings: [], fault: b.simulation?.fault || "none", soc: 100, t0: Date.now() / 1000, last: "", sev: "" });
    return json(res, 201, snapshot());
  }
  if (url.pathname === "/api/runs/stop" && req.method === "POST") { run.running = false; run.status = "stopped"; return json(res, 200, snapshot()); }
  if (url.pathname === "/api/runs/fault" && req.method === "POST") { const b = await body(req); run.fault = b.fault || "none"; if (run.fault === "none") { run.last = ""; run.sev = ""; } return json(res, 200, snapshot()); }
  if (url.pathname === "/api/runs/stream") {
    res.writeHead(200, { ...cors, "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
    let last = null;
    const iv = setInterval(() => { const s = snapshot(last); if (s.readings.length) last = s.readings[s.readings.length - 1].timestamp; res.write(`event: snapshot\ndata: ${JSON.stringify(s)}\n\n`); }, 400);
    req.on("close", () => clearInterval(iv));
    return;
  }
  json(res, 404, { detail: `mock: ${url.pathname} is not mocked`, code: "not_found" });
}).listen(PORT, "127.0.0.1", () => console.log(`mock bench API on http://127.0.0.1:${PORT}`));
