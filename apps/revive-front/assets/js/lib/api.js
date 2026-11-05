// Data layer: probes the local API (live) and falls back to the snapshot files (snapshot).
// One normalised shape for fleet + summary in both modes. Nothing here invents a value.

const DEFAULT_BASE = "http://127.0.0.1:8000";
export const SECOND = ["REUSE", "REPURPOSE"];
export const DISPOSITIONS = ["REPURPOSE", "REUSE", "RECYCLE", "INSPECT", "NO_DECISION"];

export class ApiError extends Error {
  constructor(message, { status = 0, code = "network", detail = null, body = null } = {}) {
    super(message); this.status = status; this.code = code; this.detail = detail; this.body = body;
  }
}

function base() {
  try { return (localStorage.getItem("revive.api.base") || DEFAULT_BASE).replace(/\/$/, ""); } catch { return DEFAULT_BASE; }
}

const state = { mode: "unknown", health: null, meta: null, listeners: new Set(), timer: null };
const cache = new Map();

export function mode() { return state.mode; }
export function isLive() { return state.mode === "live"; }
export function health() { return state.health; }
export function onMode(fn) { state.listeners.add(fn); return () => state.listeners.delete(fn); }

async function request(url, { method = "GET", body, timeout = 8000, headers } = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeout);
  try {
    const init = { method, signal: ctrl.signal, headers: { ...(headers || {}) } };
    if (body instanceof FormData) init.body = body;
    else if (body !== undefined) { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
    const r = await fetch(url, init);
    const text = await r.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch { json = null; }
    if (!r.ok) {
      const detail = json?.detail;
      const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ") : `HTTP ${r.status}`;
      throw new ApiError(msg, { status: r.status, code: json?.code || `http_${r.status}`, detail, body: json });
    }
    return json;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    const aborted = e?.name === "AbortError";
    throw new ApiError(aborted ? "The request timed out." : "The local API could not be reached.", { code: aborted ? "timeout" : "network" });
  } finally { clearTimeout(t); }
}

export const api = {
  get: (path, opts) => request(base() + path, opts),
  post: (path, body, opts) => request(base() + path, { ...opts, method: "POST", body }),
};

export async function snapshotFile(name) {
  if (cache.has("snap:" + name)) return cache.get("snap:" + name);
  const p = fetch(`data/${name}`).then((r) => { if (!r.ok) throw new ApiError(`data/${name}: HTTP ${r.status}`, { status: r.status, code: "snapshot_missing" }); return r.json(); });
  cache.set("snap:" + name, p);
  p.catch(() => cache.delete("snap:" + name));
  return p;
}
export async function snapshotText(path) {
  const r = await fetch(path);
  if (!r.ok) throw new ApiError(`${path}: HTTP ${r.status}`, { status: r.status });
  return r.text();
}

/** GET /api/health with a 1500 ms timeout; flips the mode and tells listeners. */
export async function probe() {
  let next = "snapshot";
  try { state.health = await request(base() + "/api/health", { timeout: 1500 }); next = "live"; } catch { state.health = null; }
  if (next !== state.mode) {
    const prev = state.mode; state.mode = next;
    if (prev !== "unknown") { for (const k of [...cache.keys()]) if (!k.startsWith("snap:")) cache.delete(k); }
    state.listeners.forEach((fn) => { try { fn(next, prev); } catch (e) { console.error(e); } });
  }
  return next;
}
export function startProbing() {
  clearInterval(state.timer);
  state.timer = setInterval(probe, 10000);
  window.addEventListener("focus", probe);
}

/** the snapshot's summary, computed with the same formulas as services/api/revive_api/services/fleet.py::summary */
export function computeSummary(packs) {
  const by = { REUSE: 0, REPURPOSE: 0, RECYCLE: 0, INSPECT: 0, NO_DECISION: 0 };
  for (const p of packs) by[p.disposition] = (by[p.disposition] || 0) + 1;
  const second = packs.filter((p) => SECOND.includes(p.disposition));
  const routed = second.reduce((s, p) => s + (p.net_value || 0), 0) + packs.filter((p) => !second.includes(p)).reduce((s, p) => s + (p.recycle_value || 0), 0);
  const recycleAll = packs.reduce((s, p) => s + (p.recycle_value || 0), 0);
  const kwh = second.reduce((s, p) => s + (p.pack_kwh ? p.pack_kwh * (p.soh || 0) / 100 : 0), 0);
  return {
    n: packs.length, by_disposition: by, net_value_routed_usd: routed, net_value_recycle_all_usd: recycleAll,
    value_vs_recycle_all_usd: routed - recycleAll, kwh_redeployed: kwh,
    funnel: {
      total: packs.length,
      data_quality_ready: packs.filter((p) => p.readiness && p.readiness !== "NOT_READY").length,
      gate_pass: packs.filter((p) => p.gate === "Pass").length,
      state_ok: packs.filter((p) => p.gate === "Pass" && p.soh != null).length,
      second_life_chosen: second.length,
    },
    provenance: "modelled from SYNTHETIC data; placeholder cost inputs",
  };
}

async function cached(key, fn) {
  if (cache.has(key)) return cache.get(key);
  const p = fn(); cache.set(key, p); p.catch(() => cache.delete(key)); return p;
}

/** { source, generated, packs[] } — all packs, live or snapshot */
export function loadFleet() {
  return cached(`fleet:${state.mode}`, async () => {
    if (isLive()) {
      try {
        const r = await api.get("/api/fleet?limit=1000&compact=true&sort=asset_id");
        return { source: "live", generated: state.meta?.db_generated_utc || null, packs: r.packs || [] };
      } catch (e) { console.warn("live fleet failed, using snapshot:", e.message); }
    }
    const s = await snapshotFile("fleet_reports.json");
    return { source: "snapshot", generated: s.generated_utc || null, packs: s.packs || [] };
  });
}

export function loadSummary() {
  return cached(`summary:${state.mode}`, async () => {
    if (isLive()) { try { return { ...(await api.get("/api/fleet/summary")), source: "live" }; } catch (e) { console.warn("live summary failed:", e.message); } }
    const f = await loadFleet();
    return { ...computeSummary(f.packs), source: "snapshot" };
  });
}

export function loadMeta() {
  return cached(`meta:${state.mode}`, async () => {
    if (isLive()) { try { state.meta = await api.get("/api/meta"); return { ...state.meta, source: "live" }; } catch { /* fall through */ } }
    const m = await snapshotFile("db_meta.json");
    return { db_generated_utc: m.generated_utc, n_assets: m.n_assets, table_counts: m.table_counts, source: "snapshot" };
  });
}

export function loadDecisionMap() { return snapshotFile("decision_map.json"); }

/** live only: the full stored report for one pack */
export function loadBattery(id) {
  if (!isLive()) return Promise.reject(new ApiError("Needs the live API.", { code: "snapshot_mode" }));
  return cached(`battery:${id}`, () => api.get(`/api/battery/${encodeURIComponent(id)}`, { timeout: 12000 }));
}
export function loadBatteryHistory(id) {
  if (!isLive()) return Promise.reject(new ApiError("Needs the live API.", { code: "snapshot_mode" }));
  return cached(`history:${id}`, () => api.get(`/api/battery/${encodeURIComponent(id)}/history`));
}
export function apiBase() { return base(); }
