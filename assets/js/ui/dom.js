// Tiny DOM toolkit: h() builds elements; helpers format numbers, provenance tags, pills and tables.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElementNS(tag === "svg" || attrs.__svg ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml", tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "__svg" || v === null || v === undefined || v === false) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else if (k === "value" && "value" in el) el.value = v;
    else if (k === "checked" || k === "selected" || k === "disabled") el[k] = Boolean(v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}
export const svg = (tag, attrs = {}, ...children) => h(tag, { ...attrs, __svg: true }, ...children);
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
export const $ = (sel, root = document) => root.querySelector(sel);

// ---------------------------------------------------------------- formatting
export function num(v, digits = 2) {
  if (v === null || v === undefined || (typeof v === "number" && !Number.isFinite(v))) return "—";
  if (typeof v !== "number") return String(v);
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export const usd = (v) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`);
export const pct = (v, d = 1) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : `${num(v, d)} %`);
/** a provenance-tagged value: "12.3 %  MODELLED" */
export function tagged(t, digits = 2, opts = {}) {
  if (!t || typeof t !== "object") return h("span", {}, "—");
  const unit = opts.unit === false ? "" : t.unit ? ` ${t.unit}` : "";
  const val = t.value === null || t.value === undefined ? "—" : typeof t.value === "number" ? num(t.value, digits) + unit : String(t.value);
  return h("span", { title: t.note || "" }, val, " ", prov(t.provenance));
}
export const prov = (p) => (p ? h("span", { class: `prov ${p}`, title: PROV_HELP[p] || "" }, p) : "");
export const PROV_HELP = {
  measured: "read or directly derived from measured data",
  synthetic: "read or derived from synthetic or simulated data",
  modelled: "output of a fitted or physics model",
  assumed: "a literature or configuration constant",
};
export function pill(text, tone = "neutral", title = "") { return h("span", { class: `pill ${tone}`, title }, text); }
export function statusPill(status) {
  const tone = { pass: "good", warn: "warn", fail: "bad", inconclusive: "info", not_applicable: "neutral" }[status] || "neutral";
  return h("span", { class: `pill status-${status}` }, status.replace("_", " "));
}
export function toneOfDecision(d) {
  const s = String(d || "");
  if (/^Second-Life|^Repurpose|Stationary|Low-speed|PASS|Screening pass|Pass$/i.test(s)) return "good";
  if (/Reject|Recycl|Buy New|No reuse|FAIL|DEAD|CRITICAL|End of life/i.test(s)) return "bad";
  if (/Insufficient|Inspection|Quarantine|Unknown|Limited|Inconclusive|LIMITED|INCOMPLETE/i.test(s)) return "warn";
  return "neutral";
}

export function table(columns, rows, opts = {}) {
  const head = h("tr", {}, columns.map((c) => h("th", { class: c.num ? "num" : "" }, c.label ?? c.key)));
  const body = rows.map((r) => h("tr", {}, columns.map((c) => {
    const v = c.render ? c.render(r) : r[c.key];
    return h("td", { class: c.num ? "num" : "" }, v instanceof Node ? v : v === null || v === undefined || (typeof v === "number" && Number.isNaN(v)) ? "—" : typeof v === "number" && c.digits !== undefined ? num(v, c.digits) : String(v));
  })));
  return h("div", { class: "table-wrap", style: opts.maxHeight ? { maxHeight: opts.maxHeight } : null }, h("table", {}, h("thead", {}, head), h("tbody", {}, body)));
}
export function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.filter(Boolean).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v instanceof Node ? v : v ?? "—")]));
}
export function card(title, body, actions = null, cls = "") {
  return h("section", { class: `card ${cls}` }, title || actions ? h("div", { class: "card-head" }, title ? h("h2", {}, title) : h("span"), actions) : null, body);
}
export function kpi(label, value, sub = "", extra = null) {
  return h("div", { class: "kpi" }, h("div", { class: "label" }, h("span", {}, label), extra), h("div", { class: `value ${typeof value === "string" && value.length > 14 ? "long" : ""}` }, value), sub ? h("div", { class: "sub" }, sub) : null);
}
export function banner(tone, title, text) { return h("div", { class: `banner ${tone}` }, title ? h("b", {}, title) : null, h("span", {}, text)); }
export function field(label, control, hint = "") { return h("label", { class: "field" }, label, control, hint ? h("small", {}, hint) : null); }
export function select(options, value, onchange, attrs = {}) {
  return h("select", { ...attrs, onchange: (e) => onchange && onchange(e.target.value) },
    options.map((o) => (typeof o === "string" ? [o, o] : o)).map(([v, l]) => h("option", { value: v, selected: String(v) === String(value) }, l)));
}
export function numberInput(value, onchange, attrs = {}) {
  return h("input", { type: "number", value: value ?? "", step: "any", ...attrs, oninput: (e) => onchange && onchange(e.target.value === "" ? null : Number(e.target.value)) });
}
export function seg(options, value, onchange) {
  const wrap = h("div", { class: "seg", role: "tablist" });
  for (const [v, l] of options) {
    wrap.append(h("button", { type: "button", class: v === value ? "on" : "", onclick: () => { [...wrap.children].forEach((b) => b.classList.remove("on")); wrap.querySelector(`[data-v="${v}"]`).classList.add("on"); onchange(v); }, "data-v": v }, l));
  }
  return wrap;
}
export function tabs(items, onchange, initial = null) {
  const bar = h("div", { class: "tabs", role: "tablist" });
  const body = h("div");
  const show = (id) => {
    [...bar.children].forEach((b) => b.classList.toggle("on", b.dataset.id === id));
    clear(body).append(items.find((i) => i.id === id).render());
    if (onchange) onchange(id);
  };
  for (const it of items) bar.append(h("button", { type: "button", "data-id": it.id, onclick: () => show(it.id) }, it.label));
  setTimeout(() => show(initial || items[0].id));
  return h("div", {}, bar, body);
}
export function toast(text, ms = 3200) {
  const t = h("div", { class: "toast", role: "status" }, text);
  document.body.append(t);
  setTimeout(() => t.remove(), ms);
}
export function download(name, content, type = "application/json") {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const a = h("a", { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
export function details(summary, body, open = false) { return h("details", { open }, h("summary", {}, summary), body); }

// ---------------------------------------------------------------- icons (stroke icons, 24x24)
const ICONS = {
  home: "M3 11l9-8 9 8M5 10v10h14V10",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7l1-8z",
  upload: "M12 16V4m0 0l-5 5m5-5l5 5M4 20h16",
  flask: "M9 3h6M10 3v6L4 20h16L14 9V3",
  db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  wave: "M3 17c3 0 3-10 6-10s3 10 6 10 3-6 6-6",
  coin: "M12 3a9 9 0 100 18 9 9 0 000-18zm3 6c-.5-1-1.6-1.5-3-1.5-1.7 0-3 .8-3 2s1.3 1.6 3 2 3 .8 3 2-1.3 2-3 2c-1.4 0-2.5-.5-3-1.5M12 6v1.5m0 9V18",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5M9 13h6M9 17h6",
  cell: "M7 6h10v15H7zM10 3h4v3h-4zM10 12h4M12 10v4",
  chip: "M7 7h10v10H7zM10 3v4m4-4v4m-4 10v4m4-4v4M3 10h4m-4 4h4m10-4h4m-4 4h4",
  plug: "M9 3v5m6-5v5M7 8h10v4a5 5 0 01-10 0zm5 9v4",
  check: "M5 12l5 5 9-10",
  x: "M6 6l12 12M18 6L6 18",
  alert: "M12 3l9 16H3zm0 6v4m0 3v.5",
  pause: "M12 3a9 9 0 100 18 9 9 0 000-18zM10 9v6m4-6v6",
  sun: "M12 4V2m0 20v-2M4 12H2m20 0h-2M5.6 5.6L4.2 4.2m15.6 15.6l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M12 8a4 4 0 100 8 4 4 0 000-8z",
  moon: "M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z",
  menu: "M4 6h16M4 12h16M4 18h16",
  download: "M12 4v12m0 0l-5-5m5 5l5-5M4 20h16",
  play: "M7 4l13 8-13 8z",
  stop: "M6 6h12v12H6z",
  recycle: "M7 19H4l3-5m10 5h3l-3-5M9 6l3-3 3 3m-3-3v6M6 14l-2-3m14 3l2-3",
};
export function icon(name, size = 18) {
  return svg("svg", { viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" },
    svg("path", { d: ICONS[name] || ICONS.doc }));
}
export function decisionCard(label, verdict, lines = [], tone = null, extra = null) {
  const t = tone || toneOfDecision(verdict);
  const ic = { good: "check", bad: "x", warn: "alert", neutral: "pause" }[t];
  return h("div", { class: `decision ${t}` }, h("div", { class: "icon" }, icon(ic, 24)),
    h("div", {}, h("div", { class: "label" }, label), h("div", { class: "verdict" }, verdict), lines.length ? h("ul", {}, lines.map((l) => h("li", {}, l))) : null, extra));
}
