// Data-quality lab: run the full engine on reference bundles and on every injected fault; edit the metadata and re-run.
import { h, clear, card, banner, field, select, icon, pill, download, spinnerBox } from "../ui/dom.js";
import { renderFullReport } from "../ui/report.js";
import { lineChart } from "../ui/charts.js";
import { loadBundle, telemetryRows } from "../engines/contract.js";
import { assess } from "../engines/pipeline.js";
import { toCSV } from "../lib/csv.js";

export async function render(root, app) {
  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Data-quality lab"),
    h("p", {}, "The full engine refuses data it can't trust. Pick a clean synthetic pack, a safety-gate case or one of the injected faults, and watch which check catches it. Edit the metadata (sign convention, chemistry, capacity tests…) and re-run."))));
  const wait = spinnerBox("Loading reference bundles…");
  root.append(wait);
  let bundles;
  try { bundles = await app.getBundles(); } catch (e) {
    wait.replaceWith(banner("bad", "Could not load the reference bundles.", `${e.message}. Check that data/bundles.json is served.`));
    return;
  }
  wait.remove();
  const names = Object.keys(bundles);
  let name = "clean_lfp";
  const groups = {};
  for (const n of names) (groups[bundles[n].group] ||= []).push(n);
  const picker = h("select", { onchange: (e) => { name = e.target.value; load(); } },
    Object.entries(groups).map(([g, ns]) => h("optgroup", { label: g }, ns.map((n) => h("option", { value: n, selected: n === name }, n.replace(/^fault_/, "fault: ").replace(/_/g, " "))))));
  const meta = h("textarea", { rows: 12, spellcheck: "false", "aria-label": "Bundle metadata JSON" });
  const info = h("div");
  const chart = h("div");
  const out = h("div");
  root.append(h("div", { class: "grid g2" },
      card("Bundle", [field("Example", picker), info, h("div", { class: "row mt" },
        h("button", { class: "btn primary", onclick: runIt }, icon("play", 15), "Run the full engine"),
        h("button", { class: "btn", onclick: () => { const b = bundles[name]; meta.value = JSON.stringify(b.metadata, null, 2); runIt(); } }, "Reset metadata"),
        h("button", { class: "btn", onclick: exportZip }, icon("download", 15), "Bundle .zip"))]),
      card("metadata.json (editable)", [meta, h("small", { class: "muted" }, "Validated against the data contract before running: unknown fields, bad dates and disordered voltages are refused.")])),
    h("div", { class: "stack mt" }, chart, out));

  function load() {
    const b = bundles[name];
    meta.value = JSON.stringify(b.metadata, null, 2);
    clear(info).append(h("p", { class: "muted mt" }, b.description), h("div", { class: "row" }, pill(`${b.rows.length} rows`, "neutral"), pill(`Python engine: ${b.python_decision}`, "neutral")));
    const ti = b.columns.indexOf("timestamp_utc");
    const t = b.rows.map((r) => Date.parse(r[ti]) / 3.6e6);
    const t0 = Math.min(...t.filter(Number.isFinite));
    const col = (c) => { const k = b.columns.indexOf(c); return k < 0 ? [] : b.rows.map((r) => (r[k] === null ? NaN : r[k])); };
    const x = t.map((v) => v - t0);
    clear(chart).append(card("Telemetry", h("div", { class: "grid g2" },
      lineChart({ series: [{ name: "pack voltage", x, y: col("voltage_v") }], xLabel: "hours", yLabel: "V", height: 190 }),
      lineChart({ series: [{ name: "current (A)", x, y: col("current_a"), color: "--c2" }, { name: "SOC (%)", x, y: col("soc_pct"), color: "--c4" }, { name: "temperature (°C)", x, y: col("temperature_c"), color: "--c3" }], xLabel: "hours", height: 190 }))));
    runIt();
  }
  function current() {
    const b = bundles[name];
    const rows = b.rows.map((r) => Object.fromEntries(b.columns.map((c, k) => [c, r[k]])));
    const bundle = loadBundle(meta.value, rows);
    bundle.ignored_columns = b.ignored_columns;
    return bundle;
  }
  function runIt() {
    clear(out);
    let bundle;
    try { bundle = current(); } catch (e) { out.append(banner("bad", "Rejected by the data contract.", e.message)); return; }
    const t = performance.now();
    let r;
    try { r = assess(bundle, app.assets); } catch (e) { console.error(e); out.append(banner("bad", "The full engine failed.", e.message)); return; }
    const ms = performance.now() - t;
    const b = bundles[name];
    const edited = meta.value.trim() !== JSON.stringify(b.metadata, null, 2).trim();
    if (!edited) out.append(banner(r.decision === b.python_decision ? "good" : "bad", r.decision === b.python_decision ? "Same decision as the Python engine." : "Differs from the Python engine.", `Browser: ${r.decision} · Python: ${b.python_decision} · ${ms.toFixed(0)} ms`));
    else out.append(banner("info", "Edited metadata.", `Browser engine: ${r.decision} (${ms.toFixed(0)} ms).`));
    out.append(renderFullReport(r, { bundle }));
  }
  async function exportZip() {
    let bundle;
    try { bundle = current(); } catch (e) { out.prepend(banner("bad", "", e.message)); return; }
    const JSZip = app.libs().JSZip;
    const zip = new JSZip();
    zip.file("metadata.json", meta.value);
    const rows = telemetryRows(bundle.tel);
    zip.file("telemetry.csv", toCSV(Object.keys(rows[0]), rows));
    download(`${bundle.meta.asset_id}_bundle.zip`, await zip.generateAsync({ type: "blob" }));
  }
  load();
}
