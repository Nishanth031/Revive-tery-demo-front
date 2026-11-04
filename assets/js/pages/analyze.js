// Analyze batteries (port of the Circuit Studio ML panel): uploads -> lite analyzer and, when the data allow it,
// the full ML engine through the upload adapter; contract-bundle zips go straight to the full engine.
import { h, clear, card, banner, field, select, numberInput, seg, icon, toast, pill, toneOfDecision } from "../ui/dom.js";
import { renderFullReport, renderLiteReport, mappingTable } from "../ui/report.js";
import * as lite from "../engines/lite.js";
import { bundleFromRows, bundleFromContractFiles, isContractFileSet, convertDemo, AdapterError, ContractError } from "../engines/contract.js";
import { assess } from "../engines/pipeline.js";

const SAMPLES = [
  ["1_healthy_pack.csv", "Healthy pack"], ["2_worn_pack.csv", "Worn pack"], ["3_overdischarged_pack.csv", "Over-discharged pack"],
  ["4_no_capacity_in_zip.zip", "No capacity column (zip)"], ["5_end_of_life_pack.csv", "End-of-life pack"],
  ["6_timestamped_pack.csv", "Timestamped pack (full engine)"], ["7_contract_bundle.zip", "Data-contract bundle (zip)"],
];
const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;

export function render(root, app) {
  const spec = { chemistry: "LFP", series_cells: 16, parallel_cells: 1, rated_capacity_ah: 100, nominal_voltage_v: null };
  const opt = { provenance: "synthetic", engine: "auto" };
  let results = {}, mappings = {}, selected = null;
  const messages = h("div", { class: "stack", style: { gap: "6px" } });
  const out = h("div");

  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Analyze batteries"),
    h("p", {}, "Upload cycler logs or telemetry (.csv, .xlsx or .zip). Headers are mapped with an explicit alias table — unknown columns are reported, never guessed. With timestamps, the full ML engine runs; otherwise the lite analyzer does, and says why."))));

  const form = h("div", { class: "form-grid" },
    field("Chemistry", select(["LFP", "NMC", "NCA"], spec.chemistry, (v) => { spec.chemistry = v; })),
    field("Series cells", numberInput(spec.series_cells, (v) => { spec.series_cells = v; }, { min: 1 })),
    field("Parallel cells", numberInput(spec.parallel_cells, (v) => { spec.parallel_cells = v; }, { min: 1 })),
    field("Rated capacity (Ah)", numberInput(spec.rated_capacity_ah, (v) => { spec.rated_capacity_ah = v; }), "blank: max of first 5 cycles"),
    field("Nominal voltage (V)", numberInput(spec.nominal_voltage_v, (v) => { spec.nominal_voltage_v = v; }), "blank: chemistry default × series"),
    field("Data provenance", select([["synthetic", "synthetic"], ["simulated", "simulated"], ["measured", "measured"]], opt.provenance, (v) => { opt.provenance = v; })));
  const engineSeg = seg([["auto", "Auto"], ["lite", "Lite only"]], opt.engine, (v) => { opt.engine = v; });
  const fileInput = h("input", { type: "file", multiple: true, accept: ".csv,.xlsx,.xls,.zip", class: "sr-only", onchange: (e) => run([...e.target.files]) });
  const drop = h("div", { class: "dropzone", tabindex: 0, role: "button", onclick: () => fileInput.click(), onkeydown: (e) => { if (e.key === "Enter") fileInput.click(); } },
    icon("upload", 22), h("div", {}, h("b", {}, "Drop files here"), " or click to choose (.csv, .xlsx, .zip)"), h("small", {}, "Files stay in your browser."));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("drag"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("drag"); run([...e.dataTransfer.files]); });

  root.append(h("div", { class: "grid g3" },
    h("div", { class: "stack" },
      card("What the data can't tell us", [form, h("div", { class: "mt" }, h("div", { class: "muted", style: { fontSize: "12px", marginBottom: "4px" } }, "Engine"), engineSeg, h("small", { class: "muted", style: { display: "block", marginTop: "4px" } }, "Auto runs the full ML engine when the data has timestamps, else the lite analyzer."))]),
    ),
    h("div", { class: "stack" }, card("Upload", [drop, fileInput]),
      card("Or try a sample", h("div", { class: "stack", style: { gap: "6px" } }, SAMPLES.map(([f, l]) =>
        h("button", { class: "btn", style: { justifyContent: "space-between", height: "auto", padding: "6px 10px", flexWrap: "wrap", whiteSpace: "normal", textAlign: "left" }, onclick: () => runSample(f) }, l, h("small", { class: "muted mono" }, f))),
        h("small", { class: "muted" }, "Samples: 16S LFP, 100 Ah (the defaults above). All synthetic.")))),
    h("div", { class: "stack" }, card("Demo pack from the database", [h("p", { class: "muted" }, "Assess DEMO-EV-PACK-001 from the project database's own tables (battery_asset, telemetry, health_history, safety_events) with the full engine."),
        h("button", { class: "btn primary", onclick: runDemo }, "Assess the demo pack")]))),
    h("div", { class: "stack mt" }, messages, out));

  function msg(tone, text) { messages.append(banner(tone, "", text)); }
  function show() {
    clear(out);
    const ids = Object.keys(results);
    if (!ids.length) { out.append(h("div", { class: "empty" }, "Results appear here. Choose a sample or upload a file.")); return; }
    if (!selected || !results[selected]) selected = ids[0];
    out.append(h("div", { class: "row mb" }, ids.map((id) => h("button", { class: `btn small ${id === selected ? "primary" : ""}`, onclick: () => { selected = id; show(); } },
      id, " ", pill(results[id].engine, "neutral")))));
    const r = results[selected];
    if (r.engine === "full") {
      if (r.lite_decision) out.append(banner("info", "Lite analyzer said:", `${r.lite_decision}. The full engine's decision is below.`));
      out.append(renderFullReport(r.report, { bundle: r.bundle, notes: r.notes }));
    } else out.append(renderLiteReport(r.report, { mapping: r.mapping, notes: r.notes }));
  }
  function record(id, r) {
    const decision = r.engine === "full" ? r.report.decision : r.report.suggestion?.decision;
    app.addHistory({ at: new Date().toISOString(), battery_id: id, engine: r.engine, decision, source: r.source || "upload" });
  }

  async function runSample(name) {
    const resp = await fetch(`data/samples/${name}`);
    run([new File([await resp.arrayBuffer()], name)]);
  }
  function runDemo() {
    clear(messages); results = {};
    try {
      const b = convertDemo(app.demo);
      const report = assess(b, app.assets);
      results[b.meta.asset_id] = { engine: "full", report, bundle: b, source: "database",
        notes: ["Assessed from the project database's own tables (battery_asset, telemetry, health_history, safety_events)."] };
      record(b.meta.asset_id, results[b.meta.asset_id]);
      msg("good", `${b.meta.asset_id}: assessed by the full ML engine from the database.`);
    } catch (e) { msg("bad", `Demo pack: ${e.message}`); }
    selected = null; show();
  }

  async function run(files) {
    if (!files.length) return;
    clear(messages); results = {}; mappings = {}; selected = null;
    clear(out).append(h("div", { class: "empty" }, h("span", { class: "spinner" }), " Analyzing…"));
    await new Promise((r) => setTimeout(r, 20));
    const libs = app.libs();
    const items = [];
    for (const f of files) {
      if (f.size > MAX_UPLOAD_BYTES) { msg("bad", `${f.name}: larger than ${MAX_UPLOAD_BYTES / 1024 / 1024} MB.`); continue; }
      items.push({ name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) });
    }
    // contract bundles (metadata.json + telemetry.csv) go to the full engine directly
    const others = [];
    for (const it of items) {
      if (it.name.toLowerCase().endsWith(".zip") && libs.JSZip) {
        let zip = null;
        try { zip = await libs.JSZip.loadAsync(it.bytes); } catch { /* the extractor reports it */ }
        if (zip && isContractFileSet(Object.values(zip.files).filter((m) => !m.dir).map((m) => m.name))) {
          if (opt.engine === "lite") { msg("bad", `${it.name} is a data-contract bundle, which only the full ML engine reads.`); continue; }
          try {
            const files2 = {};
            for (const m of Object.values(zip.files)) {
              const base = m.name.split("/").pop();
              if (!m.dir && ["metadata.json", "telemetry.csv", "telemetry.parquet"].includes(base)) files2[base] = await m.async("string");
            }
            const b = bundleFromContractFiles(files2);
            results[b.meta.asset_id] = { engine: "full", report: assess(b, app.assets), bundle: b, notes: [] };
            record(b.meta.asset_id, results[b.meta.asset_id]);
            msg("good", `${it.name}: data-contract bundle for ${b.meta.asset_id}, assessed by the full ML engine.`);
          } catch (e) { msg("bad", `${it.name}: ${e.message}`); }
          continue;
        }
      }
      others.push(it);
    }
    if (others.length) {
      const extracted = [];
      for (const it of others) {
        try { extracted.push(...await lite.extract(it.name, it.bytes, libs)); } catch (e) { msg("bad", e.message); }
      }
      if (!extracted.length && !Object.keys(results).length) msg("bad", "No usable telemetry found.");
      if (extracted.length) {
        const ing = app.liteStore.seed(extracted, opt.provenance);
        app.saveLite();
        for (const x of extracted) mappings[x.source] = { mapped: x.mapping, unmapped: x.unmapped, warnings: x.warnings, rows: x.data.length };
        msg("good", `Stored ${ing.rows_inserted.toLocaleString()} rows from ${ing.files.length} table(s) (ingest ${ing.ingest_id}). Batteries: ${ing.battery_ids.join(", ")}.`);
        const liteSpec = { chemistry: spec.chemistry, series_cells: spec.series_cells || 1, rated_capacity_ah: spec.rated_capacity_ah || null, nominal_voltage_v: null };
        for (const id of ing.battery_ids) {
          const liteReport = lite.suggest(app.liteStore, id, liteSpec);
          const mine = Object.fromEntries(Object.entries(mappings).filter(([src]) => extracted.some((x) => x.source === src && x.data.some((r) => r.battery_id === id))));
          if (opt.engine === "auto") {
            try {
              const b = bundleFromRows(app.liteStore.loadBattery(id), id, { ...spec, series_cells: spec.series_cells || 1, parallel_cells: spec.parallel_cells || 1 }, "REVIVE-TERY web", app.assets.configs.limits);
              results[id] = { engine: "full", report: assess(b, app.assets), bundle: b, notes: [], lite_decision: liteReport.suggestion?.decision };
              record(id, results[id]);
              continue;
            } catch (e) {
              const why = e instanceof AdapterError || e instanceof ContractError ? e.message : `the full engine failed: ${e.message}`;
              results[id] = { engine: "lite", report: liteReport, mapping: mine, notes: [`Full ML engine skipped: ${why}. This is the lite analyzer's suggestion.`] };
            }
          } else results[id] = { engine: "lite", report: liteReport, mapping: mine, notes: ["Lite analyzer chosen in the Engine menu."] };
          record(id, results[id]);
        }
        if (Object.keys(mappings).length) messages.append(card("Column mapping", mappingTable(mappings)));
      }
    }
    show();
    messages.scrollIntoView({ behavior: "smooth", block: "start" });
    if (Object.keys(results).length) toast(`${Object.keys(results).length} battery result(s) ready`);
    void toneOfDecision;
  }
  show();
}
