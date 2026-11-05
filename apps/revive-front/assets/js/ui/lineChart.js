// Hand-written SVG line chart: series lines, shaded bands, horizontal reference lines, draw-on animation, hover tooltip.
import { s, h } from "../lib/dom.js";
import { reduced } from "../core/reduced.js";

let tip;
export function tooltip() {
  if (!tip) { tip = h("div", { class: "tooltip", role: "tooltip" }); document.body.append(tip); }
  return {
    show(x, y, lines) { tip.replaceChildren(...lines.map((l) => h("div", {}, l))); tip.style.left = `${Math.min(x + 14, innerWidth - 270)}px`; tip.style.top = `${y + 14}px`; tip.classList.add("on"); },
    hide() { tip.classList.remove("on"); },
  };
}

/**
 * opts: { width, height, x: {min,max,label,fmt}, y: {min,max,label,fmt},
 *   series: [{ name, color, points:[[x,y]], dash }], bands: [{ name, color, opacity, points:[[x,lo,hi]] }],
 *   refs: [{ y, label, color }] }
 */
export function lineChart(opts) {
  const W = opts.width || 760, H = opts.height || 340, m = { l: 52, r: 18, t: 18, b: 40 };
  const xs = (v) => m.l + ((v - opts.x.min) / (opts.x.max - opts.x.min || 1)) * (W - m.l - m.r);
  const ys = (v) => H - m.b - ((v - opts.y.min) / (opts.y.max - opts.y.min || 1)) * (H - m.t - m.b);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": opts.label || "chart" });
  const fx = opts.x.fmt || ((v) => v), fy = opts.y.fmt || ((v) => v);
  // grid
  const grid = s("g", {});
  for (let i = 0; i <= 4; i++) {
    const v = opts.y.min + ((opts.y.max - opts.y.min) * i) / 4;
    grid.append(s("line", { x1: m.l, x2: W - m.r, y1: ys(v), y2: ys(v), stroke: "rgba(244,238,227,.08)" }), s("text", { x: m.l - 8, y: ys(v) + 4, "text-anchor": "end" }, fy(v)));
  }
  const xticks = opts.x.ticks || 6;
  for (let i = 0; i <= xticks; i++) {
    const v = opts.x.min + ((opts.x.max - opts.x.min) * i) / xticks;
    grid.append(s("text", { x: xs(v), y: H - m.b + 18, "text-anchor": "middle" }, fx(v)));
  }
  if (opts.x.label) grid.append(s("text", { x: W - m.r, y: H - 4, "text-anchor": "end" }, opts.x.label));
  if (opts.y.label) grid.append(s("text", { x: m.l, y: 10 }, opts.y.label));
  svg.append(grid);
  const bands = (opts.bands || []).map((b) => {
    const top = b.points.map(([x, , hi]) => `${xs(x)},${ys(hi)}`), bot = b.points.slice().reverse().map(([x, lo]) => `${xs(x)},${ys(lo)}`);
    const el = s("polygon", { points: [...top, ...bot].join(" "), fill: b.color, "fill-opacity": b.opacity ?? 0.22, stroke: "none" });
    svg.append(el); return el;
  });
  (opts.refs || []).forEach((r) => {
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: ys(r.y), y2: ys(r.y), stroke: r.color || "#C98A97", "stroke-dasharray": "4 5", "stroke-width": 1.2 }),
      s("text", { x: W - m.r, y: ys(r.y) - 6, "text-anchor": "end", style: `fill:${r.color || "#C98A97"}` }, r.label));
  });
  const lines = (opts.series || []).map((se) => {
    const d = se.points.map(([x, y], i) => `${i ? "L" : "M"}${xs(x).toFixed(1)},${ys(y).toFixed(1)}`).join(" ");
    const el = s("path", { d, fill: "none", stroke: se.color, "stroke-width": se.width || 2, "stroke-dasharray": se.dash || null, "stroke-linejoin": "round", "stroke-linecap": "round" });
    svg.append(el); return el;
  });
  // hover
  const cross = s("line", { y1: m.t, y2: H - m.b, stroke: "rgba(244,238,227,.35)", opacity: 0 });
  svg.append(cross);
  const t = tooltip();
  const all = (opts.series || [])[0]?.points || [];
  svg.addEventListener("pointermove", (e) => {
    if (!all.length) return;
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = all[0];
    for (const p of all) if (Math.abs(xs(p[0]) - px) < Math.abs(xs(best[0]) - px)) best = p;
    cross.setAttribute("x1", xs(best[0])); cross.setAttribute("x2", xs(best[0])); cross.setAttribute("opacity", 1);
    t.show(e.clientX, e.clientY, opts.tooltip ? opts.tooltip(best[0]) : [`${fx(best[0])}: ${fy(best[1])}`]);
  });
  svg.addEventListener("pointerleave", () => { cross.setAttribute("opacity", 0); t.hide(); });
  svg.play = (vars = {}) => {
    if (reduced.on) return null;
    const tl = gsap.timeline(vars);
    lines.forEach((l, i) => { const len = l.getTotalLength?.() || 1000; tl.fromTo(l, { strokeDasharray: `${len} ${len}`, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 1.8, ease: "expo.out", clearProps: "strokeDasharray,strokeDashoffset" }, i * 0.12); });
    if (bands.length) tl.from(bands, { opacity: 0, duration: 1.2, ease: "sine.inOut", stagger: 0.1 }, 0.3);
    return tl;
  };
  return svg;
}
