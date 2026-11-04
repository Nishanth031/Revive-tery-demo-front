// Backend: the built-in backend runs in this browser on the project database (data/db/revive_tery.duckdb,
// opened with DuckDB-WASM), with the demo battery DEMO-EV-PACK-001 connected. It answers the same routes as the
// Python FastAPI backend (bulid X/backend/revive_api) and runs scans with the same engines as the rest of the site.
// The optional connector to a locally running FastAPI backend is kept below it.
import { h, clear, card, banner, field, table, pill, icon, collapsible, kpi, toneOfDecision } from "../ui/dom.js";
import { evidence, renderFullReport } from "../ui/report.js";
import { storage, DEMO_TABLES } from "../app.js";
import { listBatteryIds, loadBatteryProfile } from "../engines/bms.js";
import { convertDemo } from "../engines/contract.js";
import { assess, ENGINE } from "../engines/pipeline.js";
import { query, listTables, DUCKDB_WASM_VERSION } from "../lib/duckdb.js";

export const DEMO_BATTERY = "DEMO-EV-PACK-001";

const ENDPOINTS = [
  ["GET", "/api/health", "Engine, database and hardware status"], ["GET", "/api/batteries", "Batteries in the database"], ["GET", "/api/batteries/{id}", "One battery's profile"],
  ["GET", "/api/ports", "Serial ports"], ["GET", "/api/faults", "Simulator faults"], ["POST", "/api/runs", "Start a bench run"], ["POST", "/api/runs/stop", "Stop the run"],
  ["POST", "/api/runs/fault", "Inject a simulator fault"], ["GET", "/api/runs/current", "Current run"], ["GET", "/api/runs/stream", "Run as server-sent events"],
  ["POST", "/api/uploads", "Upload files"], ["GET", "/api/uploads", "Ingest log"], ["POST", "/api/assessments", "Assess a battery"],
  ["POST", "/api/assessments/bundle", "Assess a contract bundle zip"], ["GET", "/api/assessments", "Assessment history"], ["GET", "/api/assessments/{id}", "One assessment"],
];

const sqlStr = (s) => `'${String(s).replace(/'/g, "''")}'`;

/** the built-in backend: route handlers over the DuckDB database and the browser engines */
function builtInBackend(app) {
  const conn = app.db?.conn || null;
  const rows = async (sql) => (await query(conn, sql)).rows;
  const fromTables = (t, id) => (app.demo[t] || []).filter((r) => r.asset_id === id);
  return {
    async health() {
      const tables = conn ? await listTables(conn) : DEMO_TABLES.map((t) => ({ table_name: t }));
      const counts = {};
      for (const t of tables) counts[t.table_name] = conn ? (await rows(`SELECT count(*) AS n FROM "${t.table_name}"`))[0].n : (app.demo[t.table_name] || []).length;
      return {
        status: "ok", backend: "built-in (browser)",
        database: { source: app.dbSource.kind, file: app.dbSource.file,
          engine: app.dbSource.kind === "duckdb" ? `${app.dbSource.version} (DuckDB-WASM ${DUCKDB_WASM_VERSION})` : null,
          read_only: true, tables: counts, fallback_reason: app.dbSource.reason },
        ml_engine: ENGINE, connected_battery: DEMO_BATTERY, hardware: "not attached (monitor-only; Web Serial on the Circuit Studio page)",
      };
    },
    async batteries() {
      return listBatteryIds(app.demo).map((id) => ({ ...loadBatteryProfile(app.demo, id), connected: id === DEMO_BATTERY }));
    },
    async battery(id) {
      if (!listBatteryIds(app.demo).includes(id)) throw new Error(`battery ${id} is not in the database`);
      const q = (t, order) => (conn ? rows(`SELECT * FROM "${t}" WHERE asset_id = ${sqlStr(id)} ORDER BY ${order}`) : fromTables(t, id));
      return {
        profile: loadBatteryProfile(app.demo, id),
        health_history: await q("health_history", "assessment_date"),
        safety_events: await q("safety_events", "timestamp_utc"),
        charge_sessions: await q("charge_sessions", "start_utc"),
        modules: await q("modules", "module_id"),
        telemetry: await q("telemetry", "timestamp_utc"),
      };
    },
    /** scan: the database battery through the full ML engine (data quality → gate → state → projection → economics) */
    async assess(id) {
      if (id !== DEMO_BATTERY) throw new Error(`only ${DEMO_BATTERY} has the tables the full engine needs`);
      const bundle = convertDemo(app.demo);
      const report = assess(bundle, app.assets);
      const st = report.state || {};
      const summary = {
        battery_id: bundle.meta.asset_id, engine: "full", decision: report.decision, rationale: report.rationale || [],
        readiness: report.data_quality.readiness.verdict, gate: report.gate?.verdict ?? null,
        soh_pct: st.soh?.value ?? null, rul_cycles: st.rul_cycles_reference?.value ?? null,
        failed_checks: report.data_quality.checks.filter((c) => c.status === "fail").map((c) => c.id),
        existing_rule: report.comparison_with_existing_rule?.existing_rule ?? null, warnings: report.warnings,
      };
      app.addHistory({ at: new Date().toISOString(), battery_id: summary.battery_id, engine: "full", decision: summary.decision, source: "database (backend)" });
      return { summary, report, bundle };
    },
    async assessments() { return app.history; },
    async sql(text) {
      if (!conn) throw new Error("the DuckDB database is not open, so SQL is unavailable");
      if (!/^\s*(select|with|describe|show|summarize)\b/i.test(text)) throw new Error("read-only: only SELECT, WITH, DESCRIBE, SHOW and SUMMARIZE queries");
      return rows(text);
    },
  };
}

export function render(root, app) {
  const api = builtInBackend(app);
  const src = app.dbSource || { kind: "csv" };
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Backend"),
    h("p", {}, "The built-in backend runs in this browser on the project database, with the demo battery already connected. It answers the same routes as the Python backend and runs scans with the same engines as the rest of the site."))));
  root.append(src.kind === "duckdb"
    ? banner("good", "Connected to the project database.", `${src.file} · DuckDB ${src.version} via DuckDB-WASM ${DUCKDB_WASM_VERSION} · read-only · ${(src.bytes / 1024 / 1024).toFixed(1)} MB`)
    : banner("warn", "Database file could not be opened; using its CSV export.", `${src.reason || "unknown reason"}. Scans still run; SQL is unavailable.`));

  const out = h("div", { class: "stack" });
  const show = async (label, fn, renderer = null) => {
    clear(out).append(h("div", { class: "empty" }, h("span", { class: "spinner" }), ` ${label}`));
    await new Promise((r) => setTimeout(r, 20));
    try {
      const body = await fn();
      clear(out).append(h("div", { class: "row" }, pill("200 OK", "good"), h("code", {}, label)), renderer ? renderer(body) : card(null, evidence(body)));
    } catch (e) {
      clear(out).append(h("div", { class: "row" }, pill("error", "bad"), h("code", {}, label)), banner("bad", "", String(e.message || e)));
    }
  };

  const scan = () => show(`POST /api/assessments {battery_id: "${DEMO_BATTERY}"}`, () => api.assess(DEMO_BATTERY), ({ summary, report, bundle }) => h("div", { class: "stack" },
    h("div", { class: "grid g4" },
      kpi("Decision", h("span", { class: `pill ${toneOfDecision(summary.decision)}` }, summary.decision)),
      kpi("Data readiness", summary.readiness ?? "—", summary.failed_checks.length ? `failed: ${summary.failed_checks.join(", ")}` : "no failed checks"),
      kpi("Safety gate", summary.gate ?? "not run"),
      kpi("SOH", summary.soh_pct === null ? "—" : `${Number(summary.soh_pct).toFixed(1)} %`, summary.rul_cycles === null ? "" : `RUL ≈ ${Math.round(summary.rul_cycles).toLocaleString()} reference cycles`)),
    renderFullReport(report, { bundle, notes: ["Scanned from the project database (DuckDB) by the built-in backend."] })));

  const battery = () => show(`GET /api/batteries/${DEMO_BATTERY}`, () => api.battery(DEMO_BATTERY), (b) => h("div", { class: "stack" },
    card("Profile", evidence(b.profile)),
    ...["telemetry", "health_history", "safety_events", "charge_sessions", "modules"].map((t) =>
      card(`${t} (${b[t].length})`, b[t].length ? table(Object.keys(b[t][0]).map((k) => ({ key: k, label: k })), b[t]) : h("p", { class: "muted" }, "No rows.")))));

  const sqlBox = h("textarea", { rows: 4, class: "mono", style: { width: "100%" }, spellcheck: false },
    `SELECT timestamp_utc, soc_pct, soh_pct, pack_voltage_V, pack_current_A, operating_state\nFROM telemetry WHERE asset_id = '${DEMO_BATTERY}' ORDER BY timestamp_utc`);
  const runSql = () => show("SQL", () => api.sql(sqlBox.value), (r) => card(`${r.length} row${r.length === 1 ? "" : "s"}`,
    r.length ? table(Object.keys(r[0]).map((k) => ({ key: k, label: k })), r.slice(0, 500)) : h("p", { class: "muted" }, "No rows.")));

  root.append(h("div", { class: "grid g-side" },
    h("div", { class: "stack" },
      card("Connected battery", [
        h("div", { class: "row between" }, h("b", { class: "mono" }, DEMO_BATTERY), pill("connected", "good")),
        h("p", { class: "muted" }, "The demo EV pack from the database: asset record, telemetry, health history and safety events."),
        h("div", { class: "row mt" },
          h("button", { class: "btn primary", onclick: scan }, icon("play", 15), "Run scan"),
          h("button", { class: "btn", onclick: battery }, "Battery data")),
      ]),
      card("Routes", h("div", { class: "row", style: { flexWrap: "wrap" } },
        h("button", { class: "btn small", onclick: () => show("GET /api/health", api.health) }, "/api/health"),
        h("button", { class: "btn small", onclick: () => show("GET /api/batteries", api.batteries) }, "/api/batteries"),
        h("button", { class: "btn small", onclick: () => show("GET /api/assessments", api.assessments) }, "/api/assessments"))),
      card("SQL (read-only)", [sqlBox, h("div", { class: "row mt" },
        h("button", { class: "btn", disabled: src.kind !== "duckdb", onclick: runSql }, icon("db", 15), "Run query"))]),
      remoteConnector()),
    out));
  scan();
}

/** the original connector to a FastAPI backend running on your own machine */
function remoteConnector() {
  let base = storage.get("backend-url", "http://127.0.0.1:8000");
  const input = h("input", { type: "url", value: base, onchange: (e) => { base = e.target.value.replace(/\/+$/, ""); storage.set("backend-url", base); } });
  const res = h("div", { class: "stack mt" });
  const call = async (path) => {
    clear(res).append(h("div", { class: "empty" }, h("span", { class: "spinner" }), ` GET ${base}${path}`));
    try {
      const r = await fetch(`${base}${path}`, { headers: { Accept: "application/json" } });
      const body = await r.json().catch(() => null);
      clear(res).append(h("div", { class: "row" }, pill(`HTTP ${r.status}`, r.ok ? "good" : "bad"), h("code", {}, `GET ${path}`)), body === null ? h("p", {}, "No JSON body.") : evidence(body));
    } catch (e) {
      clear(res).append(banner("bad", "Could not reach the backend.", `${e.message}. Is it running (uvicorn revive_api.main:app --port 8000) and does its CORS_ORIGINS allow ${location.origin}?`));
    }
  };
  return collapsible("Local Python backend (optional)", h("div", {},
    h("p", { class: "muted" }, "If you run the FastAPI backend on your own machine, read from it here to compare with the browser engines. Only GET requests are sent."),
    field("Backend URL", input),
    h("div", { class: "row mt" },
      h("button", { class: "btn", onclick: () => call("/api/health") }, "Health"),
      h("button", { class: "btn", onclick: () => call("/api/batteries") }, "Batteries"),
      h("button", { class: "btn", onclick: () => call("/api/assessments") }, "Assessments")),
    res, collapsible("Endpoints (16)", table([{ key: 0, label: "Method" }, { key: 1, label: "Path" }, { key: 2, label: "What" }], ENDPOINTS))));
}
