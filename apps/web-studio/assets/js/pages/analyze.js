// Analyze batteries (port of the Circuit Studio ML panel): uploads -> lite analyzer and, when the data allow it,
// the full ML engine through the upload adapter; contract-bundle zips go straight to the full engine.
import { h, clear, card, banner, field, select, numberInput, seg, icon, toast, pill, toneOfDecision, collapsible } from "../ui/dom.js";
import { renderFullReport, renderLiteReport, mappingTable } from "../ui/report.js";
import * as lite from "../engines/lite.js";
import { listBatteryIds } from "../engines/bms.js";
import { bundleFromRows, bundleFromContractFiles, isContractFileSet, convertDemo, AdapterError, ContractError } from "../engines/contract.js";
import { assess } from "../engines/pipeline.js";
import { parseCSV, toCSV } from "../lib/csv.js";
import { loadDecisionMap, disposition, DISPOSITION_TONE } from "../lib/disposition.js";
import { analyzeFiles, adviseBattery } from "../lib/mlApi.js";
import { connectionBar, mappingView, needsForm, adviceView } from "../ui/mlAdvice.js";

const SAMPLES = [
  ["1_healthy_pack.csv", "Healthy pack"], ["2_worn_pack.csv", "Worn pack"], ["3_overdischarged_pack.csv", "Over-discharged pack"],
  ["4_no_capacity_in_zip.zip", "No capacity column (zip)"], ["5_end_of_life_pack.csv", "End-of-life pack"],
  ["6_timestamped_pack.csv", "Timestamped pack (full engine)"], ["7_contract_bundle.zip", "Data-contract bundle (zip)"],
];
const MAX_UPLOAD_BYTES = 200 * 1024 * 1024;
const PRESETS = [
  ["lfp16", "16S LFP 100 Ah (default demo)", { chemistry: "LFP", series_cells: 16, parallel_cells: 1, rated_capacity_ah: 100 }],
  ["nmc14", "14S NMC 60 Ah (EV module)", { chemistry: "NMC", series_cells: 14, parallel_cells: 1, rated_capacity_ah: 60 }],
  ["nca13", "13S NCA 50 Ah (pack)", { chemistry: "NCA", series_cells: 13, parallel_cells: 1, rated_capacity_ah: 50 }],
  ["lfp4", "4S LFP 20 Ah (stationary)", { chemistry: "LFP", series_cells: 4, parallel_cells: 1, rated_capacity_ah: 20 }],
  ["cell1", "1S cell 2 Ah (bench test)", { chemistry: "NMC", series_cells: 1, parallel_cells: 1, rated_capacity_ah: 2 }],
];
const PASS_THROUGH = [".csv", ".xlsx", ".xls", ".zip"];
const TEXT_TABLES = [".txt", ".md", ".tsv", ".dat", ".log", ".text"];

// ---------------------------------------------------------------- pre-adapter: any file -> something the extractor reads
const ext = (n) => { const k = n.lastIndexOf("."); return k > 0 ? n.slice(k).toLowerCase() : ""; };
const stem = (n) => { const b = n.split("/").pop(); const k = b.lastIndexOf("."); return k > 0 ? b.slice(0, k) : b; };
const flat = (v) => (v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : v);

/** JSON telemetry -> rows: an array of objects, an array of arrays with a header row, an object holding either
 *  (telemetry, data, rows, records, readings, samples, or the first such array), or columns of equal-length arrays */
function jsonRows(data) {
  const asRows = (a) => {
    if (!Array.isArray(a) || !a.length) return null;
    if (a.every((r) => r && typeof r === "object" && !Array.isArray(r))) return a;
    if (Array.isArray(a[0]) && a[0].every((c) => typeof c === "string") && a.slice(1).every(Array.isArray)) {
      return a.slice(1).map((r) => Object.fromEntries(a[0].map((c, k) => [c, r[k]])));
    }
    return null;
  };
  let rows = asRows(data);
  if (rows) return rows;
  if (data && typeof data === "object") {
    for (const k of ["telemetry", "data", "rows", "records", "readings", "samples"]) if ((rows = asRows(data[k]))) return rows;
    for (const v of Object.values(data)) if ((rows = asRows(v))) return rows;
    const cols = Object.entries(data).filter(([, v]) => Array.isArray(v) && v.every((x) => x === null || typeof x !== "object"));
    if (cols.length >= 2 && cols.every(([, v]) => v.length === cols[0][1].length) && cols[0][1].length) {
      return cols[0][1].map((_, i) => Object.fromEntries(cols.map(([c, v]) => [c, v[i]])));
    }
  }
  return null;
}

/** the longest block of delimited lines (a header, then rows with the same field count) in free text or Markdown */
function textTable(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const isMd = (l) => /^\s*\|.*\|\s*$/.test(l);
  const splitters = [
    ["Markdown", (l) => (isMd(l) ? l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()) : null)],
    ["tab-separated", (l) => (l.includes("\t") ? l.split("\t").map((c) => c.trim()) : null)],
    ["comma-separated", (l) => (l.includes(",") ? parseCSV(l, ",").header : null)],
    ["semicolon-separated", (l) => (l.includes(";") ? l.split(";").map((c) => c.trim()) : null)],
    ["pipe-separated", (l) => (l.includes("|") ? l.split("|").map((c) => c.trim()) : null)],
    ["space-aligned", (l) => (/\S\s{2,}\S/.test(l.trim()) ? l.trim().split(/\s{2,}/) : null)],
  ];
  let best = null;
  for (const [kind, split] of splitters) {
    let i = 0;
    while (i < lines.length) {
      const head = split(lines[i]);
      // a header has at least two names and is not itself a row of numbers
      if (!head || head.length < 2 || head.every((c) => c === "" || /^[-+]?\.?\d/.test(c))) { i++; continue; }
      const rows = [];
      let j = i + 1;
      for (; j < lines.length; j++) {
        if (kind === "Markdown" && /^\s*\|?\s*:?-{2,}/.test(lines[j])) continue; // the |---|---| separator
        const f = split(lines[j]);
        if (!f || f.length !== head.length) break;
        rows.push(f);
      }
      if (rows.length && (!best || rows.length > best.rows.length)) best = { kind, head, rows };
      i = Math.max(j, i + 1);
    }
    if (best && kind === "Markdown") break; // a real Markdown table wins over reading its bars as plain pipes
  }
  // semicolon files often use decimal commas (3,7): make those numbers readable
  if (best && best.kind === "semicolon-separated") best.rows = best.rows.map((r) => r.map((c) => (/^[-+]?\d+,\d+$/.test(c) ? c.replace(",", ".") : c)));
  return best;
}

/** turn an upload into what lite.extract() reads: JSON and text tables become CSV in memory; CSV, Excel and zip pass through */
export function adaptFile(name, bytes) {
  const e = ext(name);
  if (PASS_THROUGH.includes(e)) return { name, bytes, note: null };
  const text = new TextDecoder("utf-8").decode(bytes);
  if (e === ".json" || /^\s*[[{]/.test(text)) {
    let data;
    try { data = JSON.parse(text); } catch (err) {
      if (e === ".json") throw new Error(`${name}: not valid JSON (${err.message}).`);
    }
    if (data !== undefined) {
      const rows = jsonRows(data);
      if (!rows) throw new Error(`${name}: no table found in the JSON. Expected an array of row objects, or { "telemetry": [...] } / { "data": [...] }.`);
      const header = [...new Set(rows.flatMap((r) => Object.keys(r)))];
      const csv = toCSV(header, rows.map((r) => Object.fromEntries(header.map((c) => [c, flat(r[c])]))));
      return { name: `${stem(name)}.csv`, bytes: new TextEncoder().encode(csv), note: `${name}: JSON converted to CSV (${rows.length.toLocaleString()} rows, ${header.length} columns).` };
    }
  }
  // text tables; anything else that decodes as text (no control characters) is tried too
  if (TEXT_TABLES.includes(e) || !/[\x00-\x08\x0e-\x1f]/.test(text.slice(0, 4000))) {
    const t = textTable(text);
    if (!t) throw new Error(`${name}: no table found. Expected a header line, then rows separated by commas, tabs, semicolons, pipes or Markdown table bars.`);
    const rows = t.rows.map((r) => Object.fromEntries(t.head.map((c, k) => [c, r[k]])));
    return { name: `${stem(name)}.csv`, bytes: new TextEncoder().encode(toCSV(t.head, rows)),
      note: `${name}: ${t.kind} table converted to CSV (${rows.length.toLocaleString()} rows, ${t.head.length} columns).` };
  }
  throw new Error(`${name}: looks like a binary file. Use JSON, text, Markdown, TSV, CSV, Excel or zip.`);
}

export function render(root, app) {
  const spec = { chemistry: "LFP", series_cells: 16, parallel_cells: 1, rated_capacity_ah: 100, nominal_voltage_v: null };
  const opt = { provenance: "synthetic", engine: "auto" };
  let results = {}, mappings = {}, selected = null;
  const messages = h("div", { class: "stack", style: { gap: "6px" } });
  const demoIds = listBatteryIds(app.demo);
  const packSelect = h("select", { class: "input", "aria-label": "Pack to assess" }, demoIds.map((id) => h("option", { value: id }, id)));
  const out = h("div");

  root.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Analyze batteries"),
    h("p", {}, "Upload cycler logs or telemetry in any common format (JSON, text, Markdown tables, TSV, CSV, Excel or zip). Headers are mapped with an explicit alias table — unknown columns are reported, never guessed. With timestamps, the full ML engine runs; otherwise the lite analyzer does, and says why."))));

  let preset = "lfp16";
  const form = h("div");
  const drawForm = () => clear(form).append(
    field("Battery preset", select([...PRESETS.map(([k, l]) => [k, l]), ["custom", "Custom (edited)"]], preset, (v) => {
      const p = PRESETS.find(([k]) => k === v);
      if (p) { preset = v; Object.assign(spec, p[2]); drawForm(); }
    })),
    h("div", { class: "form-grid mt" },
      field("Chemistry", select(["LFP", "NMC", "NCA"], spec.chemistry, (v) => { spec.chemistry = v; custom(); })),
      field("Series cells", numberInput(spec.series_cells, (v) => { spec.series_cells = v; custom(); }, { min: 1 })),
      field("Parallel cells", numberInput(spec.parallel_cells, (v) => { spec.parallel_cells = v; custom(); }, { min: 1 })),
      field("Rated capacity (Ah)", numberInput(spec.rated_capacity_ah, (v) => { spec.rated_capacity_ah = v; custom(); }), "blank: max of first 5 cycles"),
      field("Nominal voltage (V)", numberInput(spec.nominal_voltage_v, (v) => { spec.nominal_voltage_v = v; }), "blank: chemistry default × series"),
      field("Data provenance", select([["synthetic", "synthetic"], ["simulated", "simulated"], ["measured", "measured"]], opt.provenance, (v) => { opt.provenance = v; }))));
  // editing a field marks the preset as custom without rebuilding the form (which would steal focus)
  const custom = () => { preset = "custom"; const sel = form.querySelector("select"); if (sel) sel.value = "custom"; };
  drawForm();
  const engineSeg = seg([["auto", "Auto"], ["lite", "Lite only"]], opt.engine, (v) => { opt.engine = v; });
  const fileInput = h("input", { type: "file", multiple: true, class: "sr-only", onchange: (e) => run([...e.target.files]) });
  const drop = h("div", { class: "dropzone", tabindex: 0, role: "button", onclick: () => fileInput.click(), onkeydown: (e) => { if (e.key === "Enter") fileInput.click(); } },
    icon("upload", 22), h("div", {}, h("b", {}, "Drop any telemetry file (JSON, TXT, MD, CSV, XLSX, ZIP)"), " or click to choose"),
    h("small", {}, "JSON and text tables are converted to CSV in your browser. Files never leave it."));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("drag"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("drag"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("drag"); run([...e.dataTransfer.files]); });

  // ---------------------------------------------------------------- ML assistant: add a battery through the backend
  // The ML reads the file's own columns and units, stores the data in the backend database, assesses it and
  // advises a second use. Anything it cannot establish it asks for; it never guesses.
  const ml = { hints: { chemistry: "", brand: "", series_cells: null, rated_capacity_ah: null, data_provenance: "synthetic" } };
  const mlOut = h("div", { class: "stack mt" });
  const bar = connectionBar();
  const mlInput = h("input", { type: "file", multiple: true, class: "sr-only", onchange: (e) => mlRun([...e.target.files]) });
  const mlDrop = h("div", { class: "dropzone", tabindex: 0, role: "button", onclick: () => mlInput.click(), onkeydown: (e) => { if (e.key === "Enter") mlInput.click(); } },
    icon("upload", 22), h("div", {}, h("b", {}, "Add a battery: drop its CSV, Excel or zip"), " or click to choose"),
    h("small", {}, "Sent to the local ML backend, which reads the columns and units itself and stores the battery in its database."));
  mlDrop.addEventListener("dragover", (e) => { e.preventDefault(); mlDrop.classList.add("drag"); });
  mlDrop.addEventListener("dragleave", () => mlDrop.classList.remove("drag"));
  mlDrop.addEventListener("drop", (e) => { e.preventDefault(); mlDrop.classList.remove("drag"); mlRun([...e.dataTransfer.files]); });
  const hintGrid = h("div", { class: "form-grid" },
    field("Chemistry", select([["", "let the ML work it out"], "LFP", "NMC", "NCA"], ml.hints.chemistry, (v) => { ml.hints.chemistry = v; }), "optional"),
    field("Maker (optional)", h("input", { type: "text", placeholder: "e.g. BYD, LG, CATL", oninput: (e) => { ml.hints.brand = e.target.value; } })),
    field("Series cells", numberInput(null, (v) => { ml.hints.series_cells = v; }, { min: 1 }), "blank: the ML reads or asks"),
    field("Rated capacity (Ah)", numberInput(null, (v) => { ml.hints.rated_capacity_ah = v; }, { min: 0.01 }), "blank: the ML reads or asks"),
    field("Data is", select([["synthetic", "synthetic"], ["simulated", "simulated"], ["measured", "measured"]], ml.hints.data_provenance, (v) => { ml.hints.data_provenance = v; })));

  async function mlRun(files) {
    if (!files.length) return;
    clear(mlOut).append(h("div", { class: "empty" }, h("span", { class: "spinner" }), " The ML is reading your files…"));
    try {
      const res = await analyzeFiles(files, ml.hints);
      clear(mlOut);
      mlOut.append(banner("good", "Added to the backend database.",
        `${res.stored.rows_inserted} rows for ${res.stored.battery_ids.join(", ")} (ingest ${res.stored.ingest_id}). Data labelled ${res.data_provenance}.`),
      card("How the ML read your file", mappingView(res.analysis)));
      for (const r of res.results) {
        const slot = h("div", { class: "stack" });
        mlOut.append(card(`Battery ${r.battery_id}`, slot));
        if (r.status === "assessed") slot.append(adviceView(r));
        else if (r.status === "needs_input") {
          const b = res.analysis.batteries.find((x) => x.battery_id === r.battery_id);
          slot.append(needsForm(b, async (vals) => {
            const sp = { chemistry: vals.chemistry || b.spec.chemistry.value, series_cells: vals.series_cells || b.spec.series_cells.value,
              parallel_cells: b.spec.parallel_cells.value || 1, rated_capacity_ah: vals.rated_capacity_ah || b.spec.rated_capacity_ah.value };
            if (!sp.chemistry || !sp.series_cells) { toast("Chemistry and series cells are needed."); return; }
            clear(slot).append(h("div", { class: "empty" }, h("span", { class: "spinner" }), " Assessing…"));
            try { clear(slot).append(adviceView(await adviseBattery({ battery_id: r.battery_id, spec: sp, brand: res.analysis.identity.brand }))); }
            catch (e) { clear(slot).append(banner("bad", "Could not assess.", e.message)); }
          }));
        } else slot.append(banner("warn", "Not assessed.", r.message));
      }
    } catch (e) {
      clear(mlOut).append(banner("bad", e.code === "unreachable" ? "ML backend not reachable." : "The ML could not use this upload.", e.message));
      bar.check();
    }
  }
  root.append(card("ML assistant: add a battery", [bar.el, h("div", { class: "grid g2" }, h("div", { class: "stack" }, mlDrop, mlInput), hintGrid), mlOut], null, "mb"));

  root.append(h("div", { class: "grid g3" },
    h("div", { class: "stack" },
      card("What the data can't tell us", [form, h("div", { class: "mt" }, h("div", { class: "muted", style: { fontSize: "12px", marginBottom: "4px" } }, "Engine"), engineSeg, h("small", { class: "muted", style: { display: "block", marginTop: "4px" } }, "Auto runs the full ML engine when the data has timestamps, else the lite analyzer."))]),
    ),
    h("div", { class: "stack" }, card("Upload", [drop, fileInput]),
      card("Or try a sample", h("div", { class: "stack", style: { gap: "6px" } }, SAMPLES.map(([f, l]) =>
        h("button", { class: "btn", style: { justifyContent: "space-between", height: "auto", padding: "6px 10px", flexWrap: "wrap", whiteSpace: "normal", textAlign: "left" }, onclick: () => runSample(f) }, l, h("small", { class: "muted mono" }, f))),
        h("small", { class: "muted" }, "Samples: 16S LFP, 100 Ah (the defaults above). All synthetic.")))),
    h("div", { class: "stack" }, card("Packs in the database", [h("p", { class: "muted" }, `Assess a pack from the project database's own tables (battery_asset, telemetry, health_history, safety_events) with the full engine. ${demoIds.length} synthetic packs.`),
        packSelect,
        h("div", { class: "row mt" }, h("button", { class: "btn primary", onclick: () => runDemo(packSelect.value) }, "Assess the demo pack"),
          h("button", { class: "btn", onclick: runAllDemo }, "Assess all packs"))]))),
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
    const decisionText = r.engine === "full" ? r.report.decision : r.report.suggestion?.decision;
    const application = r.engine === "full" ? r.report.recommendation?.application : r.report.suggestion?.use_case;
    const chipSlot = h("div", { class: "row mb" });
    out.append(chipSlot);
    loadDecisionMap().then((map) => {
      const disp = disposition(map, decisionText, application, app.assets?.configs?.workloads);
      if (disp) chipSlot.append(pill(disp.label, DISPOSITION_TONE[disp.code] || "neutral"));
    });
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
  function assessPack(id) {
    const b = convertDemo(app.demo, id);
    const report = assess(b, app.assets);
    results[b.meta.asset_id] = { engine: "full", report, bundle: b, source: "database",
      notes: ["Assessed from the project database's own tables (battery_asset, telemetry, health_history, safety_events)."] };
    record(b.meta.asset_id, results[b.meta.asset_id]);
    msg("good", `${b.meta.asset_id}: assessed by the full ML engine from the database.`);
  }
  async function runDemo(id = null) {
    clear(messages); results = {};
    clear(out).append(h("div", { class: "empty" }, h("span", { class: "spinner" }), " Running the full ML engine on the demo pack…"));
    await new Promise((r) => setTimeout(r, 20));
    try { assessPack(typeof id === "string" ? id : null); } catch (e) { msg("bad", `Demo pack: ${e.message}`); }
    selected = null; show();
  }
  async function runAllDemo() {
    clear(messages); results = {};
    clear(out).append(h("div", { class: "empty" }, h("span", { class: "spinner" }), " Running the full ML engine on every pack…"));
    await new Promise((r) => setTimeout(r, 20));
    for (const id of demoIds) {
      try { assessPack(id); } catch (e) { msg("bad", `${id}: ${e.message}`); }
    }
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
      const raw = { name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) };
      try {
        const a = adaptFile(raw.name, raw.bytes);
        if (a.note) msg("info", a.note);
        items.push(a);
      } catch (e) { msg("bad", e.message); }
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
          const files = new Set(app.liteStore.loadBattery(id).map((r) => r.source_file));
          if (files.size > 1) {
            msg("warn", `${id} now has rows from ${files.size} files in the database (${[...files].join(", ")}). They are analyzed together, so overlapping timestamps fail the data-quality check. To start fresh, clear ml_telemetry on the Database page.`);
          }
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
        if (Object.keys(mappings).length) messages.append(collapsible("Column mapping", mappingTable(mappings)));
      }
    }
    show();
    messages.scrollIntoView({ behavior: "smooth", block: "start" });
    if (Object.keys(results).length) toast("Telemetry analyzed and saved to database.");
    void toneOfDecision;
  }
  show();
  // "Run demo assessment" on the dashboard links here as #/analyze?demo=1
  if (/[?&]demo=1\b/.test(location.hash)) {
    history.replaceState(null, "", "#/analyze");
    runDemo();
  }
}
