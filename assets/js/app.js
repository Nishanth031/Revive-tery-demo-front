// App shell: loads the engines' assets once, owns shared state, and routes between pages (hash routing,
// so it works on GitHub Pages with no server rules).
import { h, clear, icon, toast } from "./ui/dom.js";
import { loadAssets } from "./engines/pipeline.js";
import { parseCSV } from "./lib/csv.js";
import { LiteStore } from "./engines/lite.js";
import { openDatabase, readTable, DB_FILE } from "./lib/duckdb.js";

const PAGES = [
  { group: "Start" },
  { id: "overview", title: "Overview", icon: "home", load: () => import("./pages/overview.js") },
  { group: "REVIVE-TERY engines" },
  { id: "bench", title: "Circuit Studio", icon: "bolt", load: () => import("./pages/bench.js") },
  { id: "analyze", title: "Analyze batteries", icon: "upload", load: () => import("./pages/analyze.js") },
  { id: "dqlab", title: "Data-quality lab", icon: "flask", load: () => import("./pages/dqlab.js") },
  { id: "physics", title: "Physics projection", icon: "wave", load: () => import("./pages/physics.js") },
  { id: "economics", title: "Economics", icon: "coin", load: () => import("./pages/economics.js") },
  { id: "database", title: "Database", icon: "db", load: () => import("./pages/database.js") },
  { id: "evidence", title: "Model evidence", icon: "doc", load: () => import("./pages/evidence.js") },
  { id: "backend", title: "Backend", icon: "plug", load: () => import("./pages/backend.js") },
  { group: "Other software" },
  { id: "relife", title: "ReLife BMS Studio", icon: "cell", load: () => import("./pages/relife.js") },
  { id: "hardware", title: "Firmware & hardware", icon: "chip", load: () => import("./pages/hardware.js") },
];

// ---------------------------------------------------------------- persistence (per-browser conveniences only)
export const storage = {
  get(key, fallback = null) { try { const v = localStorage.getItem(`rt-${key}`); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(`rt-${key}`, JSON.stringify(value)); return true; } catch { return false; } },
  remove(key) { try { localStorage.removeItem(`rt-${key}`); } catch { /* ignore */ } },
};

const fetchJSON = async (p) => { const r = await fetch(p); if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`); return r.json(); };
const fetchText = async (p) => { const r = await fetch(p); if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`); return r.text(); };
export const DEMO_TABLES = ["battery_asset", "telemetry", "health_history", "safety_events", "charge_sessions", "modules", "materials_recycling", "data_sources"];

/** shared application state */
export const app = {
  assets: null, demo: null, dbSource: null, db: null, relife: null, circuit: null, bundles: null,
  liteStore: null, history: [], runLog: [], fetchJSON, fetchText,
  libs() { return { JSZip: window.JSZip, XLSX: window.XLSX }; },
  saveLite() {
    const ok = storage.set("lite-store", { telemetry: this.liteStore.telemetry, log: this.liteStore.log });
    if (!ok) toast("Uploads are kept for this visit only: the browser would not store them.");
  },
  addHistory(entry) {
    this.history.unshift(entry);
    this.history = this.history.slice(0, 50);
    storage.set("history", this.history);
  },
  addRunRows(rows) {
    this.runLog.push(...rows);
    if (this.runLog.length > 20000) this.runLog = this.runLog.slice(-20000);
    storage.set("run-log", this.runLog.slice(-5000));
  },
  async getBundles() { if (!this.bundles) this.bundles = await fetchJSON("data/bundles.json"); return this.bundles; },
};

async function boot() {
  const [assets, relife, circuit] = await Promise.all([
    loadAssets(fetchJSON), fetchJSON("data/relife.json"), fetchJSON("data/circuit.json"),
  ]);
  app.assets = assets;
  app.relife = relife;
  app.circuit = circuit;
  await loadDemoTables();
  app.liteStore = new LiteStore(storage.get("lite-store"));
  app.history = storage.get("history", []);
  app.runLog = storage.get("run-log", []);
}

/**
 * The demo tables come from the project database (data/db/revive_tery.duckdb, opened with DuckDB-WASM).
 * If the database can't be opened (offline CDN, old browser), the CSV export in data/demo/ is used and the
 * reason is shown on the Overview, Database and Backend pages.
 */
async function loadDemoTables() {
  setBootStatus("Opening the REVIVE-TERY database (DuckDB)…");
  try {
    const db = await openDatabase();
    const rows = await Promise.all(DEMO_TABLES.map((t) => readTable(db.conn, t)));
    app.demo = Object.fromEntries(DEMO_TABLES.map((t, i) => [t, rows[i]]));
    app.db = db;
    app.dbSource = { kind: "duckdb", file: DB_FILE, version: db.version, bytes: db.bytes };
  } catch (e) {
    console.warn("DuckDB unavailable, using the CSV export:", e);
    const tables = await Promise.all(DEMO_TABLES.map((t) => fetchText(`data/demo/${t}.csv`)));
    app.demo = Object.fromEntries(DEMO_TABLES.map((t, i) => [t, parseCSV(tables[i]).rows]));
    app.dbSource = { kind: "csv", file: "data/demo/*.csv", reason: String(e.message || e) };
  }
}
function setBootStatus(text) {
  const el = document.querySelector("#content .loading-screen");
  const line = el && el.firstElementChild; if (line) line.lastChild.textContent = ` ${text}`;
}

// ---------------------------------------------------------------- shell
let current = null;
function nav() {
  const el = document.getElementById("nav");
  clear(el);
  for (const p of PAGES) {
    if (p.group) { el.append(h("div", { class: "nav-group" }, p.group)); continue; }
    el.append(h("a", { href: `#/${p.id}`, "data-id": p.id }, icon(p.icon), p.title));
  }
}
async function route() {
  const id = (location.hash.replace(/^#\/?/, "").split("?")[0]) || "overview";
  const page = PAGES.find((p) => p.id === id) || PAGES[1];
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.id === page.id));
  document.getElementById("page-title").textContent = page.title;
  document.title = page.id === "overview" ? "REVIVE-TERY Studio" : `${page.title} · REVIVE-TERY`;
  document.getElementById("sidebar").classList.remove("open");
  if (current && current.unmount) { try { current.unmount(); } catch (e) { console.error(e); } }
  const root = clear(document.getElementById("content"));
  root.append(h("div", { class: "loading-screen" }, h("div", {}, h("span", { class: "spinner" }), " Loading…")));
  try {
    const mod = await page.load();
    clear(root);
    current = mod;
    await mod.render(root, app);
    window.scrollTo(0, 0);
  } catch (e) {
    console.error(e);
    clear(root).append(h("div", { class: "banner bad" }, h("b", {}, "This page failed to load."), h("span", {}, String(e.message || e))));
  }
}
function theme() {
  const btn = document.getElementById("theme-btn");
  const isDark = () => (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  const paint = () => clear(btn).append(icon(isDark() ? "sun" : "moon"));
  btn.addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("rt-theme", next); } catch { /* ignore */ }
    paint();
    route(); // charts read colours at draw time
  });
  paint();
}

(async () => {
  nav();
  theme();
  const menu = document.getElementById("menu-btn");
  menu.append(icon("menu"));
  menu.addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));
  try {
    await boot();
  } catch (e) {
    console.error(e);
    clear(document.getElementById("content")).append(h("div", { class: "banner bad" }, h("b", {}, "Could not load the engines' data."),
      h("span", {}, `${e.message}. Serve this folder over http (for example: python -m http.server) — browsers block module loading from file://.`)));
    return;
  }
  window.addEventListener("hashchange", route);
  route();
})();
