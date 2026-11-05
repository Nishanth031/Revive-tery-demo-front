// #/analyze: drop files -> dry run (/api/intelligence/map, stores nothing) -> optional, explicit "Store and assess".
import { h, headline } from "../lib/dom.js";
import { isLive, api, ApiError } from "../lib/api.js";
import { humanKey } from "../lib/format.js";
import { lockedPanel, errorMsg } from "../ui/chip.js";
import { reduced } from "../core/reduced.js";
import { revealLines } from "../core/transitions.js";

// services/api/revive_api/services/ingest.py::PROVENANCES
const PROVENANCES = ["synthetic", "simulated", "measured"];
const HINT_FIELDS = { chemistry: "text", brand: "text", series_cells: "number", parallel_cells: "number", rated_capacity_ah: "number", nominal_voltage_v: "number" };

export async function mount(root, { ctx }) {
  const title = headline("h1", "Bring a pack's *data*.", "");
  root.append(h("section", { class: "wrap page-head", "data-rail": "" }, h("p", { class: "label eyebrow" }, "Analyze"), title,
    h("p", {}, "Drop cycler or telemetry exports (CSV, XLSX or ZIP). First the ML reads them without storing anything, so you can see how it understood each column. Storing and assessing is a separate, deliberate step.")));
  const steps = h("div", { class: "wrap steps", "data-rail": "" });
  root.append(steps);
  ctx.add(() => revealLines(title));
  if (!isLive()) {
    steps.append(lockedPanel("Reading uploaded files with the ML column mapper"),
      h("p", { class: "muted" }, "Snapshot mode cannot read new files: the column mapper and the assessment run in the engine behind the API."));
    return {};
  }

  let files = [];
  const hints = {};
  const fileList = h("p", { class: "muted" }, "No file chosen.");
  const input = h("input", { type: "file", multiple: true, accept: ".csv,.xlsx,.xls,.zip", "aria-label": "Choose files" });
  const drop = h("label", { class: "drop" }, input, h("div", {}, h("h2", {}, "Drop files here"), h("p", { class: "muted" }, "or click to choose · CSV, XLSX, ZIP"), fileList));
  const setFiles = (list) => { files = [...list]; fileList.textContent = files.length ? files.map((f) => `${f.name} (${Math.round(f.size / 1024)} kB)`).join(", ") : "No file chosen."; dryBtn.disabled = !files.length; };
  input.addEventListener("change", () => setFiles(input.files));
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => setFiles(e.dataTransfer.files));

  const dryBtn = h("button", { class: "btn primary", disabled: true, "data-magnetic": "" }, "Step 1 · Dry run: how does the ML read this?");
  const dryOut = h("div", {});
  const hintHost = h("div", {});
  const storeHost = h("div", {});
  steps.append(drop, h("div", { class: "btn-row" }, dryBtn), hintHost, dryOut, storeHost);

  const form = (base) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    Object.entries({ ...hints, ...base }).forEach(([k, v]) => { if (v !== "" && v != null) fd.append(k, String(v)); });
    return fd;
  };

  async function dryRun() {
    dryBtn.disabled = true;
    dryOut.replaceChildren(h("div", { class: "skeleton", style: { height: "160px" } }));
    try {
      const r = await api.post("/api/intelligence/map", form({}), { timeout: 60000 });
      dryOut.replaceChildren(h("h2", { style: { fontSize: "var(--fs-h3)", marginBottom: "16px" } }, "How the ML read your files"), render(r), h("p", { class: "muted small" }, "Dry run: nothing was stored."));
      const needs = collectNeeds(r);
      hintHost.replaceChildren(needs.length ? needsForm(needs, "The ML could not establish these. Fill them in (it will not guess), then run the dry run again.", dryRun) : "");
      storeStep();
      animateRows(dryOut);
    } catch (e) { dryOut.replaceChildren(errorMsg(e, "The dry run failed.")); }
    dryBtn.disabled = !files.length;
  }
  dryBtn.addEventListener("click", dryRun);

  function needsForm(needs, text, onSubmit, extra = {}) {
    const fields = needs.map((n) => {
      const key = typeof n === "string" ? n : n.field || n.name || n.key;
      const why = typeof n === "string" ? "" : n.why || n.reason || n.detail || "";
      const type = HINT_FIELDS[key] || "text";
      const inp = h("input", { class: "input", type, name: key, required: true, value: hints[key] ?? "", step: type === "number" ? "any" : null });
      return { key, el: h("div", { class: "field" }, h("label", { class: "label" }, humanKey(key)), inp, why ? h("small", { class: "muted" }, why) : null), inp };
    }).filter((f) => f.key);
    const f = h("form", { class: "panel", style: { display: "grid", gap: "16px" } }, h("span", { class: "label" }, "Needs your input"), h("p", {}, text),
      h("div", { class: "form-grid" }, fields.map((x) => x.el)), h("div", { class: "btn-row" }, h("button", { class: "btn", type: "submit" }, "Use these values")));
    f.addEventListener("submit", (e) => { e.preventDefault(); fields.forEach((x) => { hints[x.key] = x.inp.value; }); Object.assign(hints, extra); onSubmit(); });
    return f;
  }

  function storeStep() {
    const prov = h("select", { class: "input", required: true, "aria-label": "Data provenance" }, PROVENANCES.map((p) => h("option", { value: p, selected: p === "synthetic" }, p)));
    const ack = h("input", { type: "checkbox", id: "ack-store" });
    const btn = h("button", { class: "btn", disabled: true }, "Step 2 · Store and assess");
    ack.addEventListener("change", () => { btn.disabled = !ack.checked; });
    const out = h("div", {});
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      out.replaceChildren(h("div", { class: "skeleton", style: { height: "160px" } }));
      try {
        const r = await api.post("/api/intelligence/analyze", form({ data_provenance: prov.value, assess_after: "true" }), { timeout: 120000 });
        out.replaceChildren(h("h2", { style: { fontSize: "var(--fs-h3)", margin: "16px 0" } }, "Stored, assessed and advised"), render(r));
        animateRows(out);
      } catch (e) {
        if (e instanceof ApiError && e.code === "needs_input" && e.body) {
          const needs = e.body.needs || e.body.detail?.needs || [];
          const bid = e.body.battery_id || e.body.detail?.battery_id;
          out.replaceChildren(errorMsg(e, "The engine needs more before it can assess."), needsForm(needs, `Battery ${bid || "—"} was stored; give exactly these values and store again.`, () => btn.click()));
        } else out.replaceChildren(errorMsg(e, "Storing failed."));
      }
      btn.disabled = !ack.checked;
    });
    storeHost.replaceChildren(h("div", { class: "panel", style: { display: "grid", gap: "16px" } },
      h("span", { class: "label" }, "Step 2 · optional"),
      h("p", { class: "warn-line" }, "This stores data in the database."),
      h("div", { class: "field" }, h("label", { class: "label", for: "prov" }, "What is this data, honestly?"), prov),
      h("label", { style: { display: "flex", gap: "10px", alignItems: "center", minHeight: "44px" } }, ack, "I understand this writes to the platform database."),
      h("div", { class: "btn-row" }, btn), out));
  }
  return {};
}

function collectNeeds(r) {
  const out = [];
  const walk = (o) => {
    if (!o || typeof o !== "object") return;
    if (Array.isArray(o)) { o.forEach(walk); return; }
    for (const [k, v] of Object.entries(o)) {
      if ((k === "needs_from_user" || k === "needs") && Array.isArray(v)) out.push(...v);
      else walk(v);
    }
  };
  walk(r);
  const seen = new Set();
  return out.filter((n) => { const k = typeof n === "string" ? n : n.field || n.name || n.key; if (!k || seen.has(k)) return false; seen.add(k); return true; });
}

/** generic, safe rendering of any JSON: arrays of objects -> tables, objects -> definition lists */
function render(v, depth = 0) {
  if (v === null || v === undefined) return h("span", { class: "muted" }, "—");
  if (typeof v !== "object") return h("span", {}, String(v));
  if (Array.isArray(v)) {
    if (!v.length) return h("span", { class: "muted" }, "none");
    if (v.every((x) => x && typeof x === "object" && !Array.isArray(x))) {
      const cols = [...new Set(v.flatMap((x) => Object.keys(x)))].slice(0, 8);
      return h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("thead", {}, h("tr", {}, cols.map((c) => h("th", {}, humanKey(c))))),
        h("tbody", {}, v.map((row) => h("tr", { class: "row-anim" }, cols.map((c) => h("td", {}, cell(row[c]))))))));
    }
    return h("span", {}, v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", "));
  }
  if (depth > 3) return h("pre", { class: "json" }, JSON.stringify(v, null, 2));
  return h("dl", { class: "kv", style: { marginBottom: "12px" } }, Object.entries(v).flatMap(([k, x]) => [h("dt", {}, humanKey(k)), h("dd", { class: "row-anim" }, render(x, depth + 1))]));
}
function cell(x) {
  if (x === null || x === undefined) return "—";
  if (typeof x === "object") return JSON.stringify(x).slice(0, 160);
  return String(x);
}
function animateRows(host) {
  if (reduced.on) return;
  gsap.from(host.querySelectorAll(".row-anim"), { opacity: 0, y: 12, duration: 0.7, stagger: 0.03, ease: "expo.out" });
}
