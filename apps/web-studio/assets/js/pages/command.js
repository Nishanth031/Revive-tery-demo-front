// Command Center: the whole fleet at a glance. Every number comes from the engine's real reports
// (data/fleet_reports.json, or the live API); synthetic data, screening only.
import { h, clear, card, banner, pill, icon, kpi, numberInput, usd, num } from "../ui/dom.js";
import { donut, ring, countUp } from "../ui/donut.js";
import { funnel } from "../ui/funnel.js";
import { loadFleet, fleetSummary, filterPacks, page, planInput, DISPOSITIONS, DISPOSITION_LABEL, APPLICATIONS, REGISTRY_STATUSES } from "../lib/fleet.js";
import { assign } from "../engines/insight.js";

const DCOLOR = { REUSE: "--d-reuse", REPURPOSE: "--d-repurpose", RECYCLE: "--d-recycle", INSPECT: "--d-inspect", NO_DECISION: "--d-nodecision" };
const PAGE_SIZE = 25;
const FILTER_KEYS = ["q", "disp", "chem", "app", "status", "source", "conf", "sort", "dir", "page"];

export function query() {
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  return Object.fromEntries(FILTER_KEYS.map((k) => [k, q.get(k) || ""]));
}
function setQuery(f) {
  const q = new URLSearchParams();
  for (const k of FILTER_KEYS) if (f[k]) q.set(k, f[k]);
  history.replaceState(null, "", `#/command${q.toString() ? `?${q}` : ""}`);
}
export const chip = (code) => h("span", { class: `chip ${code}` }, DISPOSITION_LABEL[code] || code);
export const confChip = (c) => (c ? h("span", { class: `chip plain conf-${c.level}`, title: `heuristic score ${c.score_0_100} / 100` }, `${c.level} ${Math.round(c.score_0_100)}`) : h("span", { class: "muted" }, "—"));

async function engineStatus(app) {
  const items = [];
  const ok = (name, good, text) => items.push(h("div", { class: `engine ${good ? "ok" : "bad"}` }, h("span", { class: "dot" }), h("div", {}, h("b", {}, name), text)));
  try { const r = await fetch("data/firmware/revive_tery_esp32.ino", { method: "HEAD" }); ok("Firmware", r.ok, r.ok ? "sketch present, monitor-only" : "sketch missing"); } catch { ok("Firmware", false, "sketch not reachable"); }
  try { const bms = await import("../engines/bms.js"); ok("BMS engine", typeof bms.BMSEngine === "function", "SOC/SOH engine ready"); } catch (e) { ok("BMS engine", false, e.message); }
  try { const lite = await import("../engines/lite.js"); ok("Lite analyzer", typeof lite.LiteStore === "function", "upload triage loaded"); } catch (e) { ok("Lite analyzer", false, e.message); }
  const sm = app.assets?.stateModel;
  const folds = sm?.folds?.length ?? sm?.models?.length ?? null;
  ok("ML engine", Boolean(sm && app.assets.gates), `state model${folds ? ` (${folds} CV folds)` : ""} + 2 gates loaded`);
  const m = app.meta;
  ok("Database", Boolean(m), m ? `${Object.keys(m.table_counts).length} tables, ${m.n_assets} packs, ${new Date(m.generated_utc).toLocaleDateString()}` : "db_meta.json missing");
  return h("div", { class: "engines" }, items);
}

function planPanel(packs) {
  const limits = { residential_storage: { packs: 10 }, commercial_peak_shaving: { packs: 6 }, telecom_backup: { packs: 4 }, low_speed_ev: { packs: 4 } };
  const out = h("div", { class: "mt" });
  const inputs = h("div", { class: "form-grid" }, Object.keys(limits).map((a) => h("label", { class: "field" }, a.replaceAll("_", " "),
    numberInput(limits[a].packs, (v) => { limits[a].packs = Math.max(0, Math.round(v || 0)); }, { min: 0, step: 1 }), "max packs")));
  const run = () => {
    const res = assign(planInput(packs), limits);
    const rows = res.plan.map((p) => h("tr", { class: "click", onclick: () => { location.hash = `#/pack?id=${encodeURIComponent(p.asset_id)}`; } },
      h("td", {}, p.asset_id), h("td", {}, p.application.replaceAll("_", " "))));
    clear(out).append(
      h("div", { class: "grid g4" },
        kpi("Plan value", usd(res.total_value), "modelled, placeholder inputs"),
        kpi("Per-pack greedy", usd(res.per_pack_greedy_value), "every pack its own best option, no limits"),
        kpi("Value gap vs greedy", usd(res.value_gap_vs_per_pack_greedy), "what the demand limits cost"),
        kpi("Packs placed", String(res.plan.length), `of ${packs.filter((p) => p.disposition === "REUSE" || p.disposition === "REPURPOSE").length} eligible`)),
      h("div", { class: "row mt" }, Object.entries(res.by_application).map(([a, u]) => pill(`${a.replaceAll("_", " ")}: ${u.packs}/${u.limit.packs} packs, ${num(u.kwh, 0)} kWh`, "neutral"))),
      res.plan.length ? h("div", { class: "table-wrap mt", style: { maxHeight: "260px" } }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Pack"), h("th", {}, "Assigned application"))), h("tbody", {}, rows)))
        : banner("info", "", "No pack is eligible for a second life under the current reports."));
  };
  run();
  return card("Fleet plan", [h("p", { class: "muted" }, "Assign second-life packs to applications under demand limits (greedy + 2-opt, the same algorithm as revive_ml.insight.fleet_opt). Packs the engine routes to recycling, inspection or no decision stay out."),
    inputs, h("div", { class: "row mt" }, h("button", { class: "btn primary", type: "button", onclick: run }, icon("route", 15), "Re-plan")), out], null, "mt");
}

export async function render(root, app) {
  const startDemo = /[?&]demo=1\b/.test(location.hash);      // read before the filters rewrite the hash
  const head = h("div", { class: "page-head row between" },
    h("div", {}, h("h1", {}, "Command Center"), h("p", { class: "muted" }, "Every pack in the fleet database through the full engine: data quality, safety gate, state of health, projection and economics. SYNTHETIC data; screening only.")),
    h("div", { class: "row no-print" },
      h("button", { class: "btn primary", type: "button", onclick: () => import("../ui/tour.js").then((t) => t.startTour(app)) }, icon("play", 15), "Start guided demo"),
      h("a", { class: "btn", href: "#/live" }, icon("spark", 15), "Run live assessment"),
      h("a", { class: "btn", href: "#/analyze" }, icon("upload", 15), "Analyze an upload"),
      h("button", { class: "btn", type: "button", onclick: () => planSlot.scrollIntoView({ behavior: "smooth" }) }, icon("route", 15), "Fleet plan")));
  root.append(head);
  const status = h("div");
  const body = h("div", {}, h("div", { class: "empty" }, h("span", { class: "spinner" }), " Loading the fleet…"));
  const planSlot = h("div");
  root.append(status, body, planSlot);
  engineStatus(app).then((el) => status.append(el));

  let fleet;
  try {
    fleet = await loadFleet(app, (d, t) => { clear(body).append(h("div", { class: "empty" }, h("span", { class: "spinner" }), ` Assessing pack ${d} of ${t} in this browser…`)); });
  } catch (e) {
    clear(body).append(banner("bad", "The fleet could not be loaded.", `${e.message}. Run "just web-db" and "just web-regen" to rebuild the snapshot.`));
    return;
  }
  const packs = fleet.packs || [];
  const s = fleetSummary(packs);
  clear(body);
  const hero = h("div", { class: "hero" });
  const big = (val, fmt, suffix = "") => { const el = h("span", { class: "count-up" }); countUp(el, val, fmt); return h("div", { class: "big" }, el, suffix ? h("small", {}, suffix) : null); };
  const card5 = (label, value, sub) => h("div", { class: "kpi" }, h("div", { class: "label" }, h("span", {}, label)), value, h("div", { class: "kpi-sub" }, sub));
  const second = s.by_disposition.REUSE + s.by_disposition.REPURPOSE;
  hero.append(
    card5("Packs assessed", big(s.n, undefined), `${s.test_cases} labelled test cases · source: ${fleet.source}`),
    card5("Second life", big(second, undefined, `/ ${s.n}`), `${s.by_disposition.REUSE} reuse · ${s.by_disposition.REPURPOSE} repurpose · ${s.by_disposition.RECYCLE} recycle`),
    card5("Value vs recycle-all", big(s.net_value_routed - s.net_value_recycle_all, (v) => usd(v)), "engine routing vs recycling every pack now (modelled; placeholder costs)"),
    card5("kWh redeployed", big(s.kwh_redeployed, (v) => Math.round(v).toLocaleString("en-US"), "kWh"), "pack kWh x SOH of second-life packs (modelled)"),
    card5("Flagged for inspection", big(100 * s.inspect_share, (v) => v.toFixed(0), "%"), `${s.by_disposition.INSPECT} packs: quarantine or open safety event`));
  body.append(hero);
  body.append(h("div", { class: "grid g2" },
    card("Disposition split", donut(DISPOSITIONS.map((d) => ({ label: DISPOSITION_LABEL[d], value: s.by_disposition[d] || 0, color: DCOLOR[d] })), { sub: "packs" })),
    card("Where packs leave the pipeline", [funnel(s.funnel), h("small", { class: "muted" }, "Counts from each pack's real stage results. Data ready = no failing data-quality check; safe = gate Pass.")])));
  if (!s.by_disposition.REUSE) body.append(banner("info", "No Reuse in this fleet.", "With today's valuation, reuse in a low-speed EV earns 108/8 = 13.5 USD per usable kWh a year while stationary storage is capped at 236/15 = 15.7 USD and lasts longer, so stationary repurposing wins every time. See the pack page's what-if panel."));

  // ---- fleet table
  const f = query();
  const tools = h("div", { class: "fleet-tools no-print" });
  const tableSlot = h("div");
  const opt = (v, l, cur) => h("option", { value: v, selected: v === cur }, l);
  const sel = (key, label, options) => h("select", { "aria-label": label, onchange: (e) => { f[key] = e.target.value; f.page = ""; draw(); } },
    opt("", label, f[key]), options.map(([v, l]) => opt(v, l, f[key])));
  const search = h("input", { type: "search", placeholder: "Search asset id…", value: f.q, "aria-label": "Search by asset id",
    oninput: (e) => { f.q = e.target.value; f.page = ""; clearTimeout(search._t); search._t = setTimeout(draw, 150); } });
  tools.append(icon("search", 16), search,
    sel("disp", "Disposition", DISPOSITIONS.map((d) => [d, DISPOSITION_LABEL[d]])),
    sel("chem", "Chemistry", ["LFP", "NMC", "NCA"].map((c) => [c, c])),
    sel("app", "Application", Object.entries(APPLICATIONS)),
    sel("status", "Registry status", REGISTRY_STATUSES.map((x) => [x, x.replaceAll("_", " ").toLowerCase()])),
    sel("source", "Source", [["user", "User fleet DB"], ["platform", "Platform packs"], ["test", "Test cases"]]),
    sel("conf", "Confidence", [["High", "High"], ["Medium", "Medium"], ["Low", "Low"]]),
    sel("sort", "Sort", [["net_value", "Net value"], ["soh", "SOH"], ["rul", "RUL"], ["confidence", "Confidence"], ["asset_id", "Asset id"]]),
    sel("dir", "Order", [["desc", "High → low"], ["asc", "Low → high"]]));
  body.append(card("Fleet", [tools, tableSlot]));

  function draw() {
    setQuery(f);
    const rows = filterPacks(packs, { ...f, sort: f.sort || "asset_id", dir: f.dir || (f.sort ? "desc" : "asc") });
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    const n = Math.min(pages, Math.max(1, Number(f.page) || 1));
    const body = page(rows, n, PAGE_SIZE).map((p) => h("tr", { class: "click", tabindex: 0, onclick: () => { location.hash = `#/pack?id=${encodeURIComponent(p.asset_id)}`; },
      onkeydown: (e) => { if (e.key === "Enter") location.hash = `#/pack?id=${encodeURIComponent(p.asset_id)}`; } },
      h("td", {}, h("b", { class: "mono" }, p.asset_id), p.test_case ? h("span", { class: "pill test-case", style: { marginLeft: "6px" } }, "test case") : null),
      h("td", {}, pill(p.chemistry || "?", "neutral")),
      h("td", {}, APPLICATIONS[p.application] || p.application || "—"),
      h("td", { class: "muted", style: { fontSize: "12px" } }, (p.registry_status || "—").replaceAll("_", " ").toLowerCase()),
      h("td", {}, ring(p.soh ?? p.soh_test)),
      h("td", {}, chip(p.disposition)),
      h("td", { style: { fontSize: "12px", maxWidth: "260px" } }, p.decision),
      h("td", {}, confChip(p.insight?.confidence)),
      h("td", { class: "num mono" }, p.net_value === null || p.net_value === undefined ? "—" : usd(p.net_value)),
      h("td", { class: "num mono" }, p.rul ? num(p.rul.median, 0) : "—")));
    clear(tableSlot).append(
      rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "fleet-table" },
        h("thead", {}, h("tr", {}, ["Pack", "Chem.", "Application", "Registry", "SOH", "Disposition", "Engine decision", "Confidence", "Net value", "RUL (cyc)"].map((x) => h("th", {}, x)))),
        h("tbody", {}, body))) : h("div", { class: "empty" }, "No pack matches these filters."),
      h("div", { class: "pager" }, h("span", { class: "muted" }, `${rows.length} packs · page ${n} of ${pages}`),
        h("button", { class: "btn small", type: "button", disabled: n <= 1, onclick: () => { f.page = String(n - 1); draw(); } }, icon("prev", 14)),
        h("button", { class: "btn small", type: "button", disabled: n >= pages, onclick: () => { f.page = String(n + 1); draw(); } }, icon("next", 14))));
  }
  draw();
  try { performance.mark("fleet-rendered"); } catch { /* old browsers */ }
  planSlot.append(planPanel(packs));
  if (startDemo) import("../ui/tour.js").then((t) => t.startTour(app));
}
