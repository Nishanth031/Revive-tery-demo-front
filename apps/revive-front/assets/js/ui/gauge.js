// Arc gauge (SOH, confidence) and the 14-tick data-quality ring.
import { s, h } from "../lib/dom.js";
import { reduced } from "../core/reduced.js";

/** 240° arc gauge. value in [min,max]; label under the number. */
export function arcGauge(value, { min = 0, max = 100, size = 260, label = "", unit = "", digits = 0, color = "#8FBFA9", track = "rgba(244,238,227,.12)" } = {}) {
  const st = 6, r = size / 2 - st * 2, c = size / 2, sweep = 240, start = -210;
  const arcLen = (2 * Math.PI * r * sweep) / 360;
  const pathD = (() => {
    const a0 = (start * Math.PI) / 180, a1 = ((start + sweep) * Math.PI) / 180;
    return `M ${c + r * Math.cos(a0)} ${c + r * Math.sin(a0)} A ${r} ${r} 0 1 1 ${c + r * Math.cos(a1)} ${c + r * Math.sin(a1)}`;
  })();
  const frac = value == null ? 0 : Math.max(0, Math.min(1, (value - min) / (max - min)));
  const arc = s("path", { d: pathD, fill: "none", stroke: color, "stroke-width": st, "stroke-linecap": "round", "stroke-dasharray": `${arcLen} ${arcLen}`, "stroke-dashoffset": arcLen * (1 - frac) });
  const ticks = s("g", {});
  for (let i = 0; i <= 24; i++) {
    const a = ((start + (sweep * i) / 24) * Math.PI) / 180;
    const r1 = r + 12, r2 = r + (i % 6 === 0 ? 20 : 16);
    ticks.append(s("line", { x1: c + r1 * Math.cos(a), y1: c + r1 * Math.sin(a), x2: c + r2 * Math.cos(a), y2: c + r2 * Math.sin(a), stroke: "currentColor", "stroke-opacity": 0.3, "stroke-width": 1 }));
  }
  const numEl = h("div", { class: "gauge-num num" }, value == null ? "—" : `${Number(value).toFixed(digits)}`, h("small", {}, unit));
  const wrap = h("div", { class: "gauge", style: { width: `${size}px`, maxWidth: "100%" } },
    s("svg", { viewBox: `0 0 ${size} ${size}`, role: "img", "aria-label": `${label} ${value == null ? "not available" : Number(value).toFixed(digits) + unit}` },
      s("path", { d: pathD, fill: "none", stroke: track, "stroke-width": st, "stroke-linecap": "round" }), ticks, arc),
    h("div", { class: "gauge-center" }, numEl, h("div", { class: "label" }, label)));
  wrap.play = (opts = {}) => {
    if (reduced.on || value == null) return null;
    const o = { v: min };
    const small = numEl.querySelector("small");
    return gsap.timeline(opts)
      .fromTo(arc, { attr: { "stroke-dashoffset": arcLen } }, { attr: { "stroke-dashoffset": arcLen * (1 - frac) }, duration: 1.6, ease: "expo.out" }, 0)
      .to(o, { v: value, duration: 1.6, ease: "expo.out", onUpdate: () => { numEl.firstChild.textContent = o.v.toFixed(digits); } }, 0)
      .add(() => small && numEl.append(small));
  };
  return wrap;
}

/** ring of `total` ticks; the first `pass` drawn solid */
export function tickRing(pass, total = 14, { size = 220 } = {}) {
  const c = size / 2, r1 = size / 2 - 30, r2 = size / 2 - 8;
  const g = s("g", {});
  for (let i = 0; i < total; i++) {
    const a = (i / total) * Math.PI * 2 - Math.PI / 2;
    g.append(s("line", { x1: c + r1 * Math.cos(a), y1: c + r1 * Math.sin(a), x2: c + r2 * Math.cos(a), y2: c + r2 * Math.sin(a),
      stroke: "currentColor", "stroke-width": 3, "stroke-linecap": "round", "stroke-opacity": i < pass ? 1 : 0.2, class: "tk" }));
  }
  const svg = s("svg", { viewBox: `0 0 ${size} ${size}`, class: "tick-ring", role: "img", "aria-label": `${total} data-quality checks` }, g);
  svg.play = (opts = {}) => (reduced.on ? null : gsap.from(g.children, { opacity: 0, scale: 0.4, transformOrigin: `${c}px ${c}px`, duration: 0.8, stagger: 0.06, ease: "expo.out", ...opts }));
  return svg;
}
