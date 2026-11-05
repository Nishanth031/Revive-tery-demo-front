// Client for the local REVIVE-TERY API: the Python ML workflow (map uploads, store, assess, advise a second use).
// The web app works without it (every page keeps its in-browser engines); the ML panels say so when it is down.

const KEY = "revive.api.base";
export const DEFAULT_BASE = "http://127.0.0.1:8000";

export function getBase() {
  try { return localStorage.getItem(KEY) || DEFAULT_BASE; } catch { return DEFAULT_BASE; }
}
export function setBase(url) {
  try { localStorage.setItem(KEY, url); } catch { /* storage may be blocked: the setting then lasts for this page only */ }
}

export class MlApiError extends Error {
  constructor(message, { status = 0, code = "error", body = null } = {}) {
    super(message);
    this.status = status; this.code = code; this.body = body;
  }
}

async function call(path, init = {}, timeoutMs = 180000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  let resp;
  try {
    resp = await fetch(getBase().replace(/\/+$/, "") + path, { ...init, signal: ctl.signal });
  } catch {
    throw new MlApiError(`The ML backend is not reachable at ${getBase()}. Start it with "just api" (or change the address).`,
      { code: "unreachable" });
  } finally { clearTimeout(timer); }
  let body = null;
  try { body = await resp.json(); } catch { /* not JSON */ }
  if (!resp.ok) {
    const detail = body && body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : `HTTP ${resp.status}`;
    throw new MlApiError(detail, { status: resp.status, code: (body && body.code) || "error", body });
  }
  return body;
}

export const health = () => call("/api/health", {}, 4000);

function form(files, fields) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  for (const [k, v] of Object.entries(fields || {})) if (v !== null && v !== undefined && v !== "") fd.append(k, String(v));
  return fd;
}

/** dry run: how would the ML read these files? Nothing is stored. */
export const mapFiles = (files, fields) => call("/api/intelligence/map", { method: "POST", body: form(files, fields) });

/** map, store in the backend database, assess and advise. fields: data_provenance, chemistry, brand, series_cells, ... */
export const analyzeFiles = (files, fields) => call("/api/intelligence/analyze", { method: "POST", body: form(files, fields) });

/** assess a battery that is already stored (database pack or earlier upload) and rank its second uses */
export const adviseBattery = (body) => call("/api/intelligence/advise", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
