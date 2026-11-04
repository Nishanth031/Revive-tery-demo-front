// Overview: a minimal dashboard of the four back-end engines (ESP32 hardware, BMS engine, ML engine, database),
// quick actions into each demo, system KPIs, and (folded away) the decision flow and provenance legend.
import { h, kpi, banner, prov, icon, PROV_HELP, num, pill, collapsible } from "../ui/dom.js";
import { listBatteryIds } from "../engines/bms.js";
import { DEMO_TABLES } from "../app.js";

const go = (route) => { location.hash = `#/${route}`; };

/** a card that is itself a link to `route`; inner buttons link elsewhere without triggering it */
function engineCard({ route, ic, title, status, lines, links }) {
  const ok = status.every(([, good]) => good);
  return h("section", {
    class: "card", role: "link", tabindex: 0, style: { cursor: "pointer", display: "flex", flexDirection: "column", gap: "10px" },
    onclick: () => go(route), onkeydown: (e) => { if (e.key === "Enter") go(route); },
  },
  h("div", { class: "row between" },
    h("div", { class: "row" }, h("span", { style: { color: "var(--accent)" } }, icon(ic, 20)), h("h3", { style: { margin: 0 } }, title)),
    pill(ok ? "loaded" : "check", ok ? "good" : "warn")),
  h("div", { class: "stack", style: { gap: "4px" } }, status.map(([text, good]) =>
    h("div", { class: "row", style: { gap: "6px", fontSize: "13px" } }, h("span", { style: { color: good ? "var(--good)" : "var(--warn)" } }, icon(good ? "check" : "alert", 15)), text))),
  h("div", { class: "muted", style: { fontSize: "12.5px" } }, lines.join(" · ")),
  h("div", { class: "row", style: { gap: "6px", marginTop: "auto" } }, links.map(([r, label]) =>
    h("a", { class: "btn small", href: `#/${r}`, onclick: (e) => e.stopPropagation() }, label))));
}

export function render(root, app) {
  const a = app.assets;
  const sm = a.stateModel;
  const gates = Object.values(a.gates);
  const rowCounts = DEMO_TABLES.map((t) => [t, (app.demo[t] || []).length]);
  const totalRows = rowCounts.reduce((s, [, n]) => s + n, 0);
  const tablesLoaded = rowCounts.filter(([, n]) => n > 0).length;
  const batteries = listBatteryIds(app.demo);
  const serial = "serial" in navigator;
  const modelsLoaded = [sm, ...gates, a.mcParams.length ? 1 : null].filter(Boolean).length;
  const runs = new Set(app.runLog.map((r) => r.run_id).filter(Boolean)).size;

  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Engine dashboard"),
    h("p", {}, "Second-life battery triage. Every engine runs in this browser; nothing is uploaded."))));
  root.append(banner("warn", "Synthetic data.", "Results show the pipeline works, not the state of a real battery. The safety gate is UL 1974-style triage, not certification."));

  // ------------------------------------------------ system health
  root.append(h("div", { class: "grid g4 mb" },
    kpi("Models loaded", `${modelsLoaded} / 4`, "state RUL, 2 safety gates, Monte Carlo draws"),
    kpi("Demo tables", `${tablesLoaded} / ${DEMO_TABLES.length}`, `${totalRows.toLocaleString()} rows in total`),
    kpi("Assessments", app.history.length.toLocaleString(), "kept in this browser"),
    kpi("Run log entries", app.runLog.length.toLocaleString(), runs ? `${runs} bench run${runs === 1 ? "" : "s"}` : "no bench runs yet")));

  // ------------------------------------------------ quick actions
  root.append(h("div", { class: "row mb" },
    h("a", { class: "btn primary", href: "#/analyze?demo=1" }, icon("play", 15), "Run demo assessment"),
    h("a", { class: "btn", href: "#/bench" }, icon("bolt", 15), "Start bench test"),
    h("a", { class: "btn", href: "#/dqlab" }, icon("flask", 15), "Open DQ lab"),
    h("a", { class: "btn", href: "#/database" }, icon("db", 15), "View database")));

  // ------------------------------------------------ the four engines
  const fw = [ "Firmware sketch", null ];
  const hwCard = engineCard({ route: "hardware", ic: "chip", title: "ESP32 hardware",
    status: [fw, [serial ? "Web Serial available (read-only)" : "Web Serial unavailable in this browser", serial]],
    lines: ["INA219 + DS18B20", "JSON lines at 115200 baud", "monitor-only, ≤ 26 V"],
    links: [["hardware", "Firmware & wiring"], ["bench", "Live bench"]] });
  const fwLine = hwCard.querySelector(".stack > .row");
  const setFw = (good, text) => {
    fwLine.replaceChildren(h("span", { style: { color: good ? "var(--good)" : "var(--warn)" } }, icon(good ? "check" : "alert", 15)), text);
    const all = [...hwCard.querySelectorAll(".stack > .row > span")].every((s) => s.style.color.includes("good"));
    hwCard.querySelector(".pill").replaceWith(pill(all ? "loaded" : "check", all ? "good" : "warn"));
  };
  fwLine.replaceChildren(h("span", { class: "spinner", style: { width: "13px", height: "13px" } }), "Checking firmware sketch…");
  app.fetchText("data/firmware/revive_tery_esp32.ino")
    .then((t) => setFw(true, `Firmware sketch present (${t.split("\n").length} lines)`))
    .catch(() => setFw(false, "Firmware sketch missing"));

  root.append(h("div", { class: "grid g2" },
    hwCard,
    engineCard({ route: "bench", ic: "bolt", title: "BMS engine",
      status: [["Coulomb-counting SOC and live SOH ready", true], [`${batteries.length} batter${batteries.length === 1 ? "y" : "ies"} available for replay`, batteries.length > 0],
        ["Simulated ESP32 with fault injection", true]],
      lines: [`${app.runLog.length.toLocaleString()} logged readings`, "tiers: > 80 % stationary · 60–80 % low-speed EV · < 60 % recycle"],
      links: [["bench", "Circuit Studio"], ["relife", "ReLife BMS"]] }),
    engineCard({ route: "analyze", ic: "flask", title: "ML engine",
      status: [[`State model: ${sm.folds.length} folds, ${sm.folds.reduce((s, f) => s + f.nTrees, 0).toLocaleString()} trees (HGB + CV+)`, sm.folds.length > 0],
        [`Safety gate: ${gates.map((g) => `${g.nTrees} trees`).join(" + ")} (IsolationForest)`, gates.length === 2],
        [`Physics: ${a.mcParams.length.toLocaleString()} Monte Carlo draws`, a.mcParams.length > 0]],
      lines: [`held-out CV+ coverage ${num(100 * sm.validation.measured_coverage, 1)} %`, "14 data-quality checks"],
      links: [["analyze", "Analyze"], ["dqlab", "DQ lab"], ["physics", "Physics"], ["economics", "Economics"]] }),
    engineCard({ route: "database", ic: "db", title: "Database",
      status: [[`${tablesLoaded} of ${DEMO_TABLES.length} demo tables loaded`, tablesLoaded === DEMO_TABLES.length],
        [`${app.liteStore.telemetry.length.toLocaleString()} uploaded rows, ${app.liteStore.log.length} ingest log entries`, true]],
      lines: rowCounts.map(([t, n]) => `${t} ${n}`),
      links: [["database", "Tables"], ["evidence", "Model evidence"], ["backend", "Backend"]] })));

  // ------------------------------------------------ reference (folded)
  const flow = [
    ["Data quality", "14 detectors", "NOT_READY stops here"],
    ["Safety gate", "Chemistry limits, then an IsolationForest OOD filter", "Reject → recycle · Quarantine → inspect"],
    ["State (ML)", "SOH from capacity tests; RUL with a 90 % CV+ interval", "Fallback: capacity trend"],
    ["Projection", "Physics fade anchored to the ML prediction, per workload", "Central, ML band, MC band, knee"],
    ["Economics", "Discounted second-life value capped at buy-new, vs recycling", "Second-Life or Recycle"],
  ];
  root.append(collapsible("How a decision is made (full ML engine)", h("div", { class: "stepper" }, flow.map(([t, s, out], i) =>
    h("div", { class: "step" }, h("div", { class: "n" }, `Stage ${i + 1}`), h("div", { class: "t" }, t), h("div", { class: "s muted" }, s),
      h("div", { class: "s", style: { marginTop: "6px", fontWeight: 600 } }, out)))), false, "mt"));
  root.append(collapsible("Provenance tags", h("div", { class: "stack", style: { gap: "8px" } },
    Object.entries(PROV_HELP).map(([p, t]) => h("div", { class: "row" }, prov(p), h("span", { class: "muted" }, t)))), false, "mt"));
}
