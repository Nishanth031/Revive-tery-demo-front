// Backend connector: talk to the local REVIVE-TERY FastAPI backend (bulid X/backend/revive_api) if it is running.
import { h, clear, card, banner, field, table, pill, icon } from "../ui/dom.js";
import { evidence } from "../ui/report.js";
import { storage } from "../app.js";

const ENDPOINTS = [
  ["GET", "/api/health", "Engine, database and hardware status"], ["GET", "/api/batteries", "Batteries in the database"], ["GET", "/api/batteries/{id}", "One battery's profile"],
  ["GET", "/api/ports", "Serial ports"], ["GET", "/api/faults", "Simulator faults"], ["POST", "/api/runs", "Start a bench run"], ["POST", "/api/runs/stop", "Stop the run"],
  ["POST", "/api/runs/fault", "Inject a simulator fault"], ["GET", "/api/runs/current", "Current run"], ["GET", "/api/runs/stream", "Run as server-sent events"],
  ["POST", "/api/uploads", "Upload files"], ["GET", "/api/uploads", "Ingest log"], ["POST", "/api/assessments", "Assess a battery"],
  ["POST", "/api/assessments/bundle", "Assess a contract bundle zip"], ["GET", "/api/assessments", "Assessment history"], ["GET", "/api/assessments/{id}", "One assessment"],
];

export function render(root) {
  let base = storage.get("backend-url", "http://127.0.0.1:8000");
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Backend connector"),
    h("p", {}, "This site runs every engine in the browser and needs no server. If you also run the Python backend on your own machine, this page can read from it — useful for checking the browser port against the original engines and the DuckDB database."))));
  root.append(banner("info", "Your browser must be allowed to call it.", `The backend only accepts browser requests from origins listed in backend/revive_api/settings.py (CORS_ORIGINS, currently localhost:5173 and :4173). Add this page's origin (${location.origin}) there and restart the backend. Pages served over https may also be blocked from calling http://127.0.0.1 by the browser.`));
  const input = h("input", { type: "url", value: base, onchange: (e) => { base = e.target.value.replace(/\/+$/, ""); storage.set("backend-url", base); } });
  const out = h("div", { class: "stack" });
  const call = async (path) => {
    clear(out).append(h("div", { class: "empty" }, h("span", { class: "spinner" }), ` GET ${base}${path}`));
    try {
      const r = await fetch(`${base}${path}`, { headers: { Accept: "application/json" } });
      const body = await r.json().catch(() => null);
      clear(out).append(h("div", { class: "row" }, pill(`HTTP ${r.status}`, r.ok ? "good" : "bad"), h("code", {}, `GET ${path}`)), card(null, body === null ? h("p", {}, "No JSON body.") : evidence(body)));
    } catch (e) {
      clear(out).append(banner("bad", "Could not reach the backend.", `${e.message}. Is it running (uvicorn revive_api.main:app --port 8000) and does it allow this origin?`));
    }
  };
  root.append(h("div", { class: "grid g-side" },
    h("div", { class: "stack" }, card("Connection", [field("Backend URL", input), h("div", { class: "row mt" },
      h("button", { class: "btn primary", onclick: () => call("/api/health") }, icon("plug", 15), "Check health"),
      h("button", { class: "btn", onclick: () => call("/api/batteries") }, "Batteries"),
      h("button", { class: "btn", onclick: () => call("/api/assessments") }, "Assessments"),
      h("button", { class: "btn", onclick: () => call("/api/uploads") }, "Uploads"))]),
      card("Endpoints", table([{ key: 0, label: "Method" }, { key: 1, label: "Path" }, { key: 2, label: "What" }], ENDPOINTS))),
    out));
  out.append(h("div", { class: "empty" }, "Responses appear here. Only read-only GET requests are sent from this page."));
}
