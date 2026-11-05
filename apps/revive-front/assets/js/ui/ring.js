// Rings: the disposition ring (segments with patterns, not colour alone) and a small SOH ring for pack cards.
import { s } from "../lib/dom.js";
import { reduced } from "../core/reduced.js";

export const DISP_FILL = { REPURPOSE: "#1F6B4F", REUSE: "#8FBFA9", RECYCLE: "#8A1F38", INSPECT: "#E7DFD0", NO_DECISION: "#B9AF9C" };

function patterns() {
  return s("defs", {},
    s("pattern", { id: "pat-none", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
      s("rect", { width: 6, height: 6, fill: "#B9AF9C" }), s("rect", { width: 2, height: 6, fill: "#E7DFD0" })),
    s("pattern", { id: "pat-inspect", width: 8, height: 8, patternUnits: "userSpaceOnUse" },
      s("rect", { width: 8, height: 8, fill: "#E7DFD0" }), s("circle", { cx: 4, cy: 4, r: 1.2, fill: "#8A1F38" })));
}
const fillFor = (d) => (d === "NO_DECISION" ? "url(#pat-none)" : d === "INSPECT" ? "url(#pat-inspect)" : DISP_FILL[d]);

/** by: {DISP: count}; order: list of keys. Returns { svg, segments: [{key, el}], play() } */
export function dispositionRing(by, order, { size = 420, stroke = 34, onHover, onClick } = {}) {
  const r = (size - stroke) / 2 - 4, c = size / 2, circ = 2 * Math.PI * r;
  const total = order.reduce((a, k) => a + (by[k] || 0), 0) || 1;
  const svg = s("svg", { viewBox: `0 0 ${size} ${size}`, class: "disp-ring", role: "img", "aria-label": order.map((k) => `${k}: ${by[k] || 0}`).join(", ") }, patterns());
  svg.append(s("circle", { cx: c, cy: c, r, fill: "none", stroke: "rgba(244,238,227,.08)", "stroke-width": stroke }));
  let acc = 0;
  const gap = 0.004 * circ;
  const segments = [];
  for (const k of order) {
    const n = by[k] || 0;
    if (!n) continue;
    const len = (n / total) * circ;
    const seg = s("circle", { cx: c, cy: c, r, fill: "none", stroke: fillFor(k), "stroke-width": stroke,
      "stroke-dasharray": `${Math.max(0, len - gap)} ${circ}`, "stroke-dashoffset": -acc, transform: `rotate(-90 ${c} ${c})`, class: "seg", "data-d": k, tabindex: 0, role: "button", "aria-label": `${k}: ${n} packs` });
    seg.dataset.len = String(Math.max(0, len - gap));
    if (onHover) { seg.addEventListener("pointerenter", () => onHover(k)); seg.addEventListener("pointerleave", () => onHover(null)); seg.addEventListener("focus", () => onHover(k)); seg.addEventListener("blur", () => onHover(null)); }
    if (onClick) { seg.addEventListener("click", () => onClick(k)); seg.addEventListener("keydown", (e) => { if (e.key === "Enter") onClick(k); }); }
    svg.append(seg); segments.push({ key: k, el: seg });
    acc += len;
  }
  const play = (opts = {}) => {
    if (reduced.on) return null;
    return gsap.from(segments.map((x) => x.el), { attr: { "stroke-dasharray": `0 ${circ}` }, duration: 1.6, ease: "expo.out", stagger: 0.12, ...opts });
  };
  return { svg, segments, play };
}

/** small SOH ring for a pack card; value 0..100 or null */
export function sohRing(value, { size = 64 } = {}) {
  const st = 3, r = (size - st) / 2, c = size / 2, circ = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const arc = s("circle", { cx: c, cy: c, r, fill: "none", stroke: "#8FBFA9", "stroke-width": st, "stroke-linecap": "round",
    "stroke-dasharray": `${(v / 100) * circ} ${circ}`, transform: `rotate(-90 ${c} ${c})`, class: "soh-arc" });
  const svg = s("svg", { viewBox: `0 0 ${size} ${size}`, width: size, height: size, class: "soh-ring", "aria-hidden": "true" },
    s("circle", { cx: c, cy: c, r, fill: "none", stroke: "rgba(244,238,227,.12)", "stroke-width": st }), arc,
    s("text", { x: c, y: c + 4, "text-anchor": "middle", class: "soh-txt" }, value == null ? "—" : `${Math.round(value)}`));
  svg._arc = arc; svg._full = `${(v / 100) * circ} ${circ}`; svg._circ = circ;
  return svg;
}
