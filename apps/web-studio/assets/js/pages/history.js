// History: assessments, ML suggestions and test-run summaries. Live API when it answers, else the snapshot
// (data/history.json, written by `just web-db`).
import { h, card, banner, table, pill } from "../ui/dom.js";
import { getBase } from "../lib/mlApi.js";

async function live(path) {
  const r = await fetch(`${getBase().replace(/\/+$/, "")}${path}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function render(root, app) {
  root.append(h("div", { class: "page-head" }, h("h1", {}, "History"),
    h("p", { class: "muted" }, "What has been assessed and suggested, and the bench runs that were logged.")));
  let src = "snapshot", data = { assessments: [], ml_suggestions: [], test_runs: [] };
  if (app.apiLive) {
    try {
      data = { assessments: await live("/api/history/assessments"), ml_suggestions: await live("/api/history/suggestions"),
        test_runs: await live("/api/history/runs").catch(() => []) };
      src = "live API";
    } catch { src = "snapshot"; }
  }
  if (src === "snapshot") {
    try { data = await app.fetchJSON("data/history.json"); } catch {
      root.append(banner("info", "No history snapshot.", "Run `just web-db` to write data/history.json, or start the API with `just api`."));
      return;
    }
  }
  root.append(h("div", { class: "row mb" }, pill(`source: ${src}`, src === "live API" ? "good" : "neutral"), data.generated_utc ? h("small", { class: "muted" }, `snapshot written ${data.generated_utc}`) : null));
  const empty = (what) => h("div", { class: "empty" }, `No ${what} yet.`);
  root.append(card(`Assessments (${data.assessments.length})`, data.assessments.length ? table(["created_utc", "battery_id", "engine", "decision", "readiness", "gate", "soh_pct"].map((k) => ({ key: k, label: k, digits: k === "soh_pct" ? 1 : undefined })), data.assessments, { maxHeight: "360px" }) : empty("assessments")));
  root.append(card(`ML suggestions (${data.ml_suggestions.length})`, data.ml_suggestions.length ? table(["created_utc", "battery_id", "engine", "status", "top_application"].map((k) => ({ key: k, label: k })), data.ml_suggestions, { maxHeight: "320px" }) : empty("suggestions"), null, "mt"));
  root.append(card(`Bench test runs (${data.test_runs.length})`, data.test_runs.length ? table(["started", "source", "asset_id", "data_class", "rows", "duration_s", "min_voltage_v", "max_voltage_v"].map((k) => ({ key: k, label: k, digits: k.endsWith("voltage_v") ? 3 : undefined })), data.test_runs, { maxHeight: "320px" }) : empty("test runs"), null, "mt"));
  root.append(h("p", { class: "muted mt" }, "Runs made in this browser are kept in its own test_run_log (see Database)."));
}
