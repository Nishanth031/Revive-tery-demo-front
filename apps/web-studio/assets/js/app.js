// App shell: loads the engines' assets once, owns shared state, and routes between pages (hash routing,
// so it works on GitHub Pages with no server rules).
import { h, clear, icon, toast } from "./ui/dom.js";
import { loadAssets } from "./engines/pipeline.js";
import { openDatabase, readTable, DB_FILE } from "./lib/duckdb.js";
import { parseCSV } from "./lib/csv.js";
import { LiteStore } from "./engines/lite.js";
import { health as apiHealth } from "./lib/mlApi.js";

// needsDemo: false = the page renders without the database tables (they keep loading in the background)
const PAGES = [
  { group: "Command" },
  { id: "command", title: "Command Center", icon: "grid", needsDemo: false, load: () => import("./pages/command.js") },
  { id: "live", title: "Live assessment", icon: "play", needsDemo: false, load: () => import("./pages/live.js") },
  { id: "history", title: "History", icon: "history", needsDemo: false, load: () => import("./pages/history.js") },
  { id: "pack", title: "Pack detail", icon: "cell", hidden: true, load: () => import("./pages/pack.js") },
  { group: "Lab" },
  { id: "bench", title: "Circuit Studio", icon: "bolt", load: () => import("./pages/bench.js") },
  { id: "analyze", title: "Analyze batteries", icon: "upload", load: () => import("./pages/analyze.js") },
  { id: "dqlab", title: "Data Quality Lab", icon: "flask", load: () => import("./pages/dqlab.js") },
  { id: "database", title: "Database", icon: "db", load: () => import("./pages/database.js") },
  { id: "evidence", title: "Model evidence", icon: "doc", load: () => import("./pages/evidence.js") },
  { id: "overview", title: "Engine status", icon: "home", load: () => import("./pages/overview.js") },
  { group: "Other software" },
  { id: "relife", title: "ReLife BMS Studio", icon: "cell", load: () => import("./pages/relife.js") },
  { id: "hardware", title: "Firmware & hardware", icon: "chip", load: () => import("./pages/hardware.js") },
  { id: "backend", title: "Backend connector", icon: "plug", load: () => import("./pages/backend.js") },
];

// ---------------------------------------------------------------- persistence (per-browser conveniences only)
export const storage = {
  get(key, fallback = null) { try { const v = localStorage.getItem(`rt-${key}`); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(`rt-${key}`, JSON.stringify(value)); return true; } catch { return false; } },
  remove(key) { try { localStorage.removeItem(`rt-${key}`); } catch { /* ignore */ } },
};

const fetchJSON = async (p) => { const r = await fetch(p); if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`); return r.json(); };
const fetchText = async (p) => { const r = await fetch(p); if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`); return r.text(); };
export const DEMO_TABLES = ["battery_asset", "battery_registry", "telemetry", "telemetry_dense", "health_history", "safety_events", "charge_sessions", "modules", "materials_recycling", "data_sources"];

/** shared application state */
export const app = {
  assets: null, demo: null, relife: null, circuit: null, bundles: null, dbSource: null,
  liteStore: null, history: [], runLog: [], fetchJSON, fetchText, demoReady: null, meta: null, apiLive: false,
  ensureDemo() { return this.demoReady; },
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

/** demo tables: the project database through DuckDB-WASM, else the CSV export in data/demo/ */
async function loadDemoTables() {
  // DuckDB-WASM loads its engine from a CDN, so it is opt-in (?duckdb=1, remembered); by default the app makes no
  // external request and reads the CSV copy written by `just web-db`.
  let useWasm = /[?&]duckdb=1\b/.test(location.search);
  try { if (useWasm) localStorage.setItem("rt-duckdb", "1"); else useWasm = localStorage.getItem("rt-duckdb") === "1"; } catch { /* ignore */ }
  if (!useWasm) {
    app.dbSource = { kind: "csv", reason: "DuckDB-WASM is opt-in (add ?duckdb=1 to the URL); offline CSV copy in use" };
    const tables = await Promise.all(DEMO_TABLES.map((t) => fetchText(`data/demo/${t}.csv`)));
    return Object.fromEntries(DEMO_TABLES.map((t, i) => [t, parseCSV(tables[i]).rows]));
  }
  try {
    const { conn, version, bytes } = await openDatabase();
    const rows = await Promise.all(DEMO_TABLES.map((t) => readTable(conn, t)));
    app.dbSource = { kind: "duckdb", file: DB_FILE, version, bytes };
    return Object.fromEntries(DEMO_TABLES.map((t, i) => [t, rows[i]]));
  } catch (err) {
    app.dbSource = { kind: "csv", reason: String(err?.message || err) };
    const tables = await Promise.all(DEMO_TABLES.map((t) => fetchText(`data/demo/${t}.csv`)));
    return Object.fromEntries(DEMO_TABLES.map((t, i) => [t, parseCSV(tables[i]).rows]));
  }
}

async function boot() {
  const [assets, relife, circuit] = await Promise.all([
    loadAssets(fetchJSON), fetchJSON("data/relife.json"), fetchJSON("data/circuit.json"),
  ]);
  app.assets = assets;
  app.relife = relife;
  app.circuit = circuit;
  // the database tables (the whole fleet, ~70k dense rows) load in the background; pages that need them wait
  app.demoReady = loadDemoTables().then((d) => { app.demo = d; return d; });
  app.demoReady.catch((e) => console.error(e));
  app.liteStore = new LiteStore(storage.get("lite-store"));
  app.history = storage.get("history", []);
  app.runLog = storage.get("run-log", []);
}

// ---------------------------------------------------------------- shell
let current = null;
function nav() {
  const el = document.getElementById("nav");
  clear(el);
  for (const p of PAGES) {
    if (p.group) { el.append(h("div", { class: "nav-group" }, p.group)); continue; }
    if (p.hidden) continue;
    el.append(h("a", { href: `#/${p.id}`, "data-id": p.id }, icon(p.icon), p.title));
  }
}
async function route() {
  const id = (location.hash.replace(/^#\/?/, "").split("?")[0]) || "command";
  // the Physics and Economics pages are now tabs of the Data Quality Lab
  if (id === "physics" || id === "economics") { location.replace(`#/dqlab?tab=${id}`); return; }
  const page = PAGES.find((p) => p.id === id) || PAGES[1];
  const navId = page.id === "pack" ? "command" : page.id;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.id === navId));
  document.getElementById("page-title").textContent = page.title;
  document.title = page.id === "command" ? "REVIVE-TERY Command Center" : `${page.title} · REVIVE-TERY`;
  document.getElementById("sidebar").classList.remove("open");
  if (current && current.unmount) { try { current.unmount(); } catch (e) { console.error(e); } }
  const root = clear(document.getElementById("content"));
  root.append(h("div", { class: "loading-screen" }, h("div", {}, h("span", { class: "spinner" }), " Loading…")));
  try {
    if (page.needsDemo !== false && !app.demo) {
      clear(root).append(h("div", { class: "loading-screen" }, h("div", {}, h("span", { class: "spinner" }), " Loading the fleet database…")));
      await app.ensureDemo();
    }
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
  const isDark = () => (document.documentElement.dataset.theme || "dark") === "dark";
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
  topbarStatus();
})();

/** "DB updated <time>, <n> packs" from data/db_meta.json, and a Live API / Snapshot chip */
async function topbarStatus() {
  const stamp = document.getElementById("db-stamp"), chip = document.getElementById("api-chip");
  try {
    app.meta = await fetchJSON("data/db_meta.json");
    const t = new Date(app.meta.generated_utc);
    stamp.textContent = `DB updated ${t.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}, ${app.meta.n_assets} packs`;
  } catch { stamp.textContent = "DB snapshot"; }
  const paint = (live) => {
    app.apiLive = live;
    clear(chip).append(live ? h("span", { class: "pill good", title: "the local API answers: pages prefer live data" }, h("i", { class: "live-dot" }), "Live API")
      : h("span", { class: "pill neutral", title: "no local API: pages use the precomputed snapshot" }, "Snapshot"));
  };
  try { await apiHealth(); paint(true); } catch { paint(false); }
}
