// Database: the demo tables (DuckDB in the desktop app), plus this browser's uploads, run logs and assessment history.
import { h, clear, card, banner, table, tabs, icon, download, toast } from "../ui/dom.js";
import { toCSV } from "../lib/csv.js";
import { DEMO_TABLES } from "../app.js";
import { isoUTC } from "../engines/contract.js";

const SHOW = 500;

function tableView(name, rows, note, onClear = null) {
  if (!rows.length) return h("div", {}, h("p", { class: "muted" }, note), h("div", { class: "empty" }, `${name} is empty.`));
  const cols = Object.keys(rows[0]);
  return h("div", {},
    h("div", { class: "row between mb" }, h("span", { class: "muted" }, `${note} ${rows.length.toLocaleString()} rows${rows.length > SHOW ? ` (first ${SHOW} shown)` : ""}.`),
      h("div", { class: "row" },
        h("button", { class: "btn small", onclick: () => download(`${name}.csv`, toCSV(cols, rows), "text/csv") }, icon("download", 14), "CSV"),
        onClear ? h("button", { class: "btn small danger", onclick: onClear }, "Clear") : null)),
    table(cols.map((c) => ({ key: c, label: c, num: typeof rows[0][c] === "number" })), rows.slice(0, SHOW)));
}

export function render(root, app) {
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Database"),
    h("p", {}, "The REVIVE-TERY demo database (the same tables the desktop app loads into DuckDB), plus what you have done in this browser: uploaded telemetry, ingest logs, bench run logs and assessment history."))));
  root.append(app.dbSource?.kind === "duckdb"
    ? banner("good", "Loaded from the project database.", `${app.dbSource.file} (DuckDB ${app.dbSource.version}, read-only). Uploads and logs below are kept in this browser only. Demo tables are SYNTHETIC.`)
    : banner("info", "Stored in this browser only.", `Demo tables come from the CSV export (database not opened: ${app.dbSource?.reason || "unknown"}). Uploads and logs are kept in this browser's local storage; nothing is sent anywhere. Demo tables are SYNTHETIC.`));
  const body = h("div");
  root.append(body);
  const draw = () => {
    const fix = (rows) => rows.map((r) => ({ ...r, timestamp_utc: r.timestamp_utc === undefined ? undefined : Number.isFinite(r.timestamp_utc) ? isoUTC(r.timestamp_utc, true) : null }));
    const items = [
      ...DEMO_TABLES.map((t) => ({ id: t, label: t, render: () => tableView(t, app.demo[t], "Demo table (synthetic).") })),
      { id: "ml_telemetry", label: "ml_telemetry", render: () => tableView("ml_telemetry", fix(app.liteStore.telemetry).map((r) => { const o = { ...r }; if (o.timestamp_utc === undefined) delete o.timestamp_utc; return o; }), "Uploaded rows, standardised by the extractor.",
        () => { if (confirm("Clear every uploaded row and ingest log in this browser?")) { app.liteStore.clear(); app.saveLite(); toast("Uploads cleared"); clear(body); draw(); } }) },
      { id: "ml_ingest_log", label: "ml_ingest_log", render: () => tableView("ml_ingest_log", app.liteStore.log, "One row per uploaded table, with its column mapping.") },
      { id: "test_run_log", label: "test_run_log", render: () => tableView("test_run_log", app.runLog.map((r) => ({ ...r, logged_at: isoUTC(r.logged_at, true) })), "Every reading from Circuit Studio runs, with its source and data class.",
        () => { if (confirm("Clear the bench run log?")) { app.runLog = []; app.addRunRows([]); clear(body); draw(); } }) },
      { id: "history", label: "assessments", render: () => tableView("assessments", app.history, "Decisions made on the Analyze page.",
        () => { app.history = []; app.addHistory({}); app.history = []; try { localStorage.removeItem("rt-history"); } catch { /* ignore */ } clear(body); draw(); }) },
    ];
    body.append(card(null, tabs(items)));
  };
  draw();
}
