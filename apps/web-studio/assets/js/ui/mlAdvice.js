// Panels for the ML backend: connection status, how the ML read a file, what it still needs, and its advice
// (1 Recommendation when the battery can go on, 2 Suggestions when it cannot yet).
import { h, clear, card, banner, pill, table, kv, num, field, select, numberInput, toneOfDecision, decisionCard, collapsible } from "./dom.js";
import { getBase, setBase, health, DEFAULT_BASE } from "../lib/mlApi.js";

const DISPOSITION_TONE = { REUSE: "good", REPURPOSE: "good", RECYCLE: "warn", INSPECT: "warn", NO_DECISION: "neutral" };
const NEED_LABEL = { chemistry: "Chemistry", series_cells: "Series cells", rated_capacity_ah: "Rated capacity (Ah)" };

// ---------------------------------------------------------------- connection
/** a status line with the backend address; check() resolves to true when the API answers */
export function connectionBar(onChange = () => {}) {
  const status = h("span");
  const input = h("input", { type: "text", value: getBase(), "aria-label": "ML backend address", style: { width: "220px" } });
  async function check() {
    clear(status).append(pill("checking…", "neutral"));
    try {
      const info = await health();
      clear(status).append(pill(`ML backend connected · ML engine ${info.ml_engine_version}`, "good"));
      onChange(true);
      return true;
    } catch {
      clear(status).append(pill("ML backend not reachable", "bad"),
        h("small", { class: "muted" }, ' start it with "just api" (the in-browser engines below still work)'));
      onChange(false);
      return false;
    }
  }
  const el = h("div", { class: "row", style: { marginBottom: "10px" } }, status, input,
    h("button", { class: "btn small", type: "button", onclick: () => { setBase(input.value.trim() || DEFAULT_BASE); check(); } }, "Check connection"));
  check();
  return { el, check };
}

// ---------------------------------------------------------------- how the ML read the files
function identityPills(identity) {
  const out = [];
  if (identity.brand) out.push(pill(`maker: ${identity.brand}${identity.brand_ambiguous ? " (sells several chemistries)" : ""}`, "neutral"));
  out.push(pill(identity.chemistry ? `chemistry: ${identity.chemistry} · ${identity.chemistry_basis}` : "chemistry: not established",
    identity.chemistry ? "good" : "warn"));
  return out;
}

export function mappingView(analysis) {
  const root = h("div", { class: "stack" });
  root.append(h("div", { class: "row" }, ...identityPills(analysis.identity)));
  if (analysis.identity.evidence?.length) root.append(h("small", { class: "muted" }, analysis.identity.evidence.join(" · ")));
  for (const t of analysis.tables) {
    const body = [];
    if (t.note) body.push(h("small", { class: "muted" }, t.note));
    if (t.role === "metadata") body.push(kv(Object.entries(t.metadata).map(([k, v]) => [k, String(v)])));
    if (t.mapping && t.role === "telemetry") {
      body.push(table([{ key: "column", label: "Column in your file" }, { key: "field", label: "Read as" },
        { key: "conf", label: "Confidence" }, { key: "conv", label: "Unit conversion" }],
      t.mapping.mapped.map((m) => ({ column: m.column, field: m.field, conf: `${Math.round(m.score * 100)} %`,
        conv: m.conversion ? `${m.conversion.unit_from} → ${m.conversion.unit_to}` : "—" }))));
      if (t.mapping.unmapped.length) {
        body.push(h("small", { class: "muted" }, "Not stored: ", t.mapping.unmapped.map((u) => `${u.column} (${u.reason})`).join("; ")));
      }
    }
    root.append(h("div", {}, h("div", { class: "row" }, h("b", {}, t.source), pill(t.role, t.role === "telemetry" ? "good" : t.role === "metadata" ? "info" : "warn"),
      t.rows ? h("small", { class: "muted" }, `${t.rows} rows`) : null), ...body));
  }
  if (analysis.warnings.length) root.append(collapsible("Notes from the ML", h("ul", {}, analysis.warnings.map((w) => h("li", {}, w))), false));
  return root;
}

/** inputs for what the ML will not guess; onSubmit({chemistry, series_cells, rated_capacity_ah}) */
export function needsForm(battery, onSubmit) {
  const needs = battery.spec.needs;
  const vals = { chemistry: battery.spec.chemistry?.value || "", series_cells: null, rated_capacity_ah: null };
  const f = h("div", { class: "form-grid" });
  if (needs.includes("chemistry")) f.append(field("Chemistry", select([["", "choose…"], "LFP", "NMC", "NCA"], vals.chemistry, (v) => { vals.chemistry = v; }),
    battery.spec.chemistry?.note || ""));
  if (needs.includes("series_cells")) f.append(field("Series cells", numberInput(null, (v) => { vals.series_cells = v; }, { min: 1 }),
    "1 for a single cell; a pack's count cannot be told from voltage alone"));
  if (needs.includes("rated_capacity_ah")) f.append(field("Rated capacity (Ah)", numberInput(null, (v) => { vals.rated_capacity_ah = v; }, { min: 0.01 }),
    "no capacity column in the file"));
  return h("div", { class: "stack" },
    banner("warn", `${battery.battery_id} needs:`, needs.map((n) => NEED_LABEL[n] || n).join(", ") + ". The ML will not guess these."),
    f, h("div", {}, h("button", { class: "btn primary", type: "button", onclick: () => onSubmit(vals) }, "Continue with these")));
}

// ---------------------------------------------------------------- the advice: 1 recommend, 2 suggest
function nextSteps(res) {
  const a = res.advice || {}, s = res.summary || {};
  const steps = [];
  if (a.next_step === "recycle") steps.push(`Send it to recycling: ${(s.rationale && s.rationale[0]) || a.headline}`);
  if (a.next_step === "fix_data" || s.readiness === "NOT_READY") {
    for (const c of s.failed_checks || []) steps.push(`Fix the data: ${c.message}`);
    steps.push("Re-run the test once that is fixed; the ML only judges health from data it can trust.");
  }
  for (const c of s.inconclusive_checks || []) steps.push(`Still unclear: ${c.message}`);
  for (const n of a.notes || []) steps.push(n);
  if (a.status === "provisional" && a.suggestions?.length) {
    const t = a.suggestions[0];
    steps.push(`Plan for ${t.label} (fit ${num(t.fit_score, 2)}) if the checks above pass.`);
  }
  if (!steps.length) steps.push(a.headline || "No further suggestion.");
  return steps;
}

function rankedTable(title, rows) {
  return card(title, table([{ key: "rank", label: "#" }, { key: "label", label: "Application" },
    { key: "fit", label: "Fit", num: true }, { key: "why", label: "Why" }, { key: "caution", label: "Cautions" }],
  rows.map((r) => ({ rank: r.rank, label: r.label, fit: num(r.fit_score, 2), why: r.reasons.slice(0, 2).join(" · "),
    caution: r.cautions.join(" · ") || "—" }))));
}

export function adviceView(res) {
  const a = res.advice || {}, s = res.summary || {};
  const wrap = h("div", { class: "stack" });
  wrap.append(h("div", { class: "row" },
    res.engine ? pill(`${res.engine} engine`, "neutral") : null,
    s.decision ? pill(s.decision, toneOfDecision(s.decision)) : null,
    s.disposition ? pill(s.disposition.label, DISPOSITION_TONE[s.disposition.code] || "neutral") : null,
    s.soh_pct !== null && s.soh_pct !== undefined ? pill(`SOH ${num(s.soh_pct, 1)} %`, "neutral") : null));
  if (a.status === "ranked" && a.suggestions.length) {
    const top = a.suggestions[0];
    wrap.append(decisionCard("1 · Recommendation", top.label, [
      `Fit ${num(top.fit_score, 2)} of 1.00 — ${a.headline}`, ...top.reasons, ...top.cautions.map((c) => `Caution: ${c}`)], "good",
    h("p", { class: "muted", style: { fontSize: "12px", margin: "6px 0 0" } },
      `Chemistry ${a.battery.chemistry}${a.battery.brand ? ` · ${a.battery.brand.name}` : ""}; weights are assumed priors, not fitted to second-life outcomes.`)));
    if (a.suggestions.length > 1) wrap.append(rankedTable("Other options, ranked", a.suggestions.slice(1)));
  } else {
    const tone = a.next_step === "recycle" ? "bad" : "warn";
    wrap.append(decisionCard("2 · Not recommended yet: suggestions", a.headline || "No recommendation", nextSteps(res), tone));
    if (a.status === "provisional" && a.suggestions.length) wrap.append(rankedTable("If it passes: ranked fit", a.suggestions));
  }
  if (a.battery?.known) {
    wrap.append(collapsible(`About ${a.battery.label}${a.battery.brand ? ` (${a.battery.brand.name})` : ""}`, h("div", { class: "stack" },
      a.battery.brand ? h("p", { class: "muted" }, a.battery.brand.note) : null,
      h("div", {}, h("b", {}, "Strengths: "), a.battery.strengths.join("; ")),
      h("div", {}, h("b", {}, "Cautions: "), a.battery.cautions.join("; ")),
      h("small", { class: "muted" }, "Qualitative priors from general literature (provenance: assumed).")), false));
  }
  return wrap;
}
