// Donut chart, SOH ring and KPI count-up. Inline SVG, theme-aware CSS variables, no dependencies.
import { h, svg } from "./dom.js";

/** items: [{ label, value, color: "--d-repurpose" }] */
export function donut(items, { size = 168, thick = 22, center = null, sub = "" } = {}) {
  const total = items.reduce((a, i) => a + i.value, 0);
  const r = (size - thick) / 2, c = size / 2, C = 2 * Math.PI * r;
  const root = svg("svg", { viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: "img",
    "aria-label": items.map((i) => `${i.label} ${i.value}`).join(", ") });
  root.append(svg("circle", { cx: c, cy: c, r, fill: "none", stroke: "var(--surface-2)", "stroke-width": thick }));
  let off = 0;
  for (const it of items) {
    if (!it.value) continue;
    const len = (it.value / total) * C;
    root.append(svg("circle", { cx: c, cy: c, r, fill: "none", stroke: `var(${it.color})`, "stroke-width": thick,
      "stroke-dasharray": `${Math.max(0, len - 2)} ${C}`, "stroke-dashoffset": -off, transform: `rotate(-90 ${c} ${c})` },
      svg("title", {}, `${it.label}: ${it.value}`)));
    off += len;
  }
  root.append(svg("text", { x: c, y: c - 2, "text-anchor": "middle", style: "font-size:28px;font-weight:750;fill:var(--text)" }, String(center ?? total)));
  root.append(svg("text", { x: c, y: c + 18, "text-anchor": "middle", style: "font-size:11px;fill:var(--text-3)" }, sub));
  const legend = h("div", { class: "donut-legend" }, items.map((i) => h("span", {}, h("i", { style: { background: `var(${i.color})` } }),
    `${i.label}`, h("b", { style: { marginLeft: "auto" } }, String(i.value)))));
  return h("div", { class: "donut-wrap" }, root, legend);
}

/** small SOH ring (0-100 %) */
export function ring(pct, size = 34) {
  const r = (size - 6) / 2, c = size / 2, C = 2 * Math.PI * r;
  const f = Number.isFinite(pct) ? Math.max(0, Math.min(1, pct / 100)) : 0;
  const color = !Number.isFinite(pct) ? "--text-3" : pct >= 80 ? "--good" : pct >= 60 ? "--warn" : "--bad";
  return svg("svg", { viewBox: `0 0 ${size} ${size}`, width: size, height: size, class: "ring", role: "img", "aria-label": `SOH ${Number.isFinite(pct) ? pct.toFixed(0) : "unknown"} %` },
    svg("circle", { cx: c, cy: c, r, fill: "none", stroke: "var(--surface-2)", "stroke-width": 4 }),
    svg("circle", { cx: c, cy: c, r, fill: "none", stroke: `var(${color})`, "stroke-width": 4, "stroke-linecap": "round",
      "stroke-dasharray": `${f * C} ${C}`, transform: `rotate(-90 ${c} ${c})` }),
    svg("text", { x: c, y: c + 3.5, "text-anchor": "middle", style: "font-size:10px;font-weight:700;fill:var(--text)" }, Number.isFinite(pct) ? pct.toFixed(0) : "–"));
}

/** count a number up into `el` (respects prefers-reduced-motion) */
export function countUp(el, to, fmt = (v) => Math.round(v).toLocaleString("en-US"), ms = 900) {
  if (!Number.isFinite(to)) { el.textContent = "—"; return; }
  const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / ms);
    el.textContent = fmt(to * (1 - (1 - k) ** 3));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
