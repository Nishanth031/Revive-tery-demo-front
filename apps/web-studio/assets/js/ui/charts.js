// Small SVG charts: multi-series line chart with optional bands and hover readout, a radial gauge and a bar list.
import { h, svg } from "./dom.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
export const PALETTE = ["--c1", "--c2", "--c3", "--c4", "--c5", "--c6"];

function niceTicks(lo, hi, n = 5) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (lo === hi) { lo -= 1; hi += 1; }
  const span = hi - lo, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
  const start = Math.floor(lo / step) * step;
  const out = [];
  for (let v = start; v <= hi + step * 0.5; v += step) out.push(Number(v.toFixed(10)));
  return out;
}
const fmtTick = (v) => (Math.abs(v) >= 10000 ? `${(v / 1000).toFixed(0)}k` : Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? String(Number(v.toFixed(2))) : String(Number(v.toFixed(3))));

/**
 * lineChart({ series: [{ name, x: [], y: [], color, dash, width }], bands: [{ name, x, lo, hi, color }],
 *             xLabel, yLabel, height, yMin, yMax, hlines: [{ y, label, color }], xFormat, yFormat })
 */
export function lineChart(opts) {
  const W = 720, H = opts.height || 260, m = { l: 52, r: 16, t: 12, b: 34 };
  const series = (opts.series || []).filter((s) => s.x && s.x.length);
  const bands = (opts.bands || []).filter((b) => b.x && b.x.length);
  const xs = [...series.flatMap((s) => s.x), ...bands.flatMap((b) => b.x)].filter(Number.isFinite);
  const ys = [...series.flatMap((s) => s.y), ...bands.flatMap((b) => [...b.lo, ...b.hi]), ...(opts.hlines || []).map((l) => l.y)].filter(Number.isFinite);
  const wrap = h("div", { class: "chart" });
  if (!xs.length) { wrap.append(h("div", { class: "empty" }, opts.empty || "No data yet")); return wrap; }
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  if (x0 === x1) { x0 -= 1; x1 += 1; }
  let y0 = opts.yMin ?? Math.min(...ys), y1 = opts.yMax ?? Math.max(...ys);
  if (opts.yMin === undefined && opts.yMax === undefined) { const pad = (y1 - y0) * 0.08 || Math.abs(y1) * 0.05 || 1; y0 -= pad; y1 += pad; }
  const yt = niceTicks(y0, y1);
  if (opts.yMin === undefined) y0 = Math.min(y0, yt[0]);
  if (opts.yMax === undefined) y1 = Math.max(y1, yt[yt.length - 1]);
  const X = (v) => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r);
  const Y = (v) => H - m.b - (v - y0) / (y1 - y0) * (H - m.t - m.b);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.ariaLabel || opts.yLabel || "chart" });
  const g = svg("g", { class: "axis" });
  for (const v of yt) if (v >= y0 - 1e-9 && v <= y1 + 1e-9) {
    g.append(svg("line", { class: "gridline", x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }));
    g.append(svg("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end" }, (opts.yFormat || fmtTick)(v)));
  }
  for (const v of niceTicks(x0, x1, 7)) if (v >= x0 - 1e-9 && v <= x1 + 1e-9) {
    g.append(svg("text", { x: X(v), y: H - m.b + 16, "text-anchor": "middle" }, (opts.xFormat || fmtTick)(v)));
  }
  g.append(svg("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }));
  if (opts.xLabel) g.append(svg("text", { x: (m.l + W - m.r) / 2, y: H - 2, "text-anchor": "middle" }, opts.xLabel));
  if (opts.yLabel) g.append(svg("text", { x: 12, y: (m.t + H - m.b) / 2, transform: `rotate(-90 12 ${(m.t + H - m.b) / 2})`, "text-anchor": "middle" }, opts.yLabel));
  root.append(g);
  const colorOf = (c, i) => (c ? (c.startsWith("--") ? css(c) : c) : css(PALETTE[i % PALETTE.length]));
  bands.forEach((b, i) => {
    const pts = b.x.map((x, k) => [x, b.hi[k]]).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
    const ptsLo = b.x.map((x, k) => [x, b.lo[k]]).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y)).reverse();
    const d = [...pts, ...ptsLo].map(([x, y], k) => `${k ? "L" : "M"}${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join("") + "Z";
    root.append(svg("path", { d, fill: colorOf(b.color, i + 1), opacity: b.opacity ?? 0.16, stroke: "none" }));
  });
  for (const l of opts.hlines || []) {
    root.append(svg("line", { x1: m.l, x2: W - m.r, y1: Y(l.y), y2: Y(l.y), stroke: colorOf(l.color || "--text-3"), "stroke-dasharray": "5 4", "stroke-width": 1.2 }));
    if (l.label) root.append(svg("text", { x: W - m.r - 4, y: Y(l.y) - 5, "text-anchor": "end", fill: colorOf(l.color || "--text-3"), "font-size": 11 }, l.label));
  }
  series.forEach((s, i) => {
    let d = "", pen = false;
    s.x.forEach((x, k) => {
      const y = s.y[k];
      if (!Number.isFinite(x) || !Number.isFinite(y)) { pen = false; return; }
      d += `${pen ? "L" : "M"}${X(x).toFixed(1)},${Y(y).toFixed(1)}`; pen = true;
    });
    root.append(svg("path", { d, fill: "none", stroke: colorOf(s.color, i), "stroke-width": s.width || 2, "stroke-dasharray": s.dash || null, "stroke-linejoin": "round" }));
    if (s.points) s.x.forEach((x, k) => Number.isFinite(s.y[k]) && root.append(svg("circle", { cx: X(x), cy: Y(s.y[k]), r: 3, fill: colorOf(s.color, i) })));
  });
  // hover readout
  const cursor = svg("line", { y1: m.t, y2: H - m.b, stroke: css("--border-strong"), visibility: "hidden" });
  root.append(cursor);
  const tip = h("div", { class: "tip", style: { display: "none" } });
  const overlay = svg("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
  root.append(overlay);
  const all = series.concat(bands.map((b) => ({ name: b.name, x: b.x, lo: b.lo, hi: b.hi, band: true })));
  overlay.addEventListener("mousemove", (ev) => {
    const r = root.getBoundingClientRect();
    const px = (ev.clientX - r.left) / r.width * W;
    const xv = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
    cursor.setAttribute("x1", px); cursor.setAttribute("x2", px); cursor.setAttribute("visibility", "visible");
    const lines = [h("div", { style: { color: "var(--text-3)" } }, `${opts.xLabel || "x"}: ${(opts.xFormat || fmtTick)(xv)}`)];
    all.forEach((s, i) => {
      let k = 0, best = Infinity;
      s.x.forEach((x, j) => { const dd = Math.abs(x - xv); if (dd < best) { best = dd; k = j; } });
      const val = s.band ? `${fmtTick(s.lo[k])} – ${fmtTick(s.hi[k])}` : fmtTick(s.y[k]);
      if (s.name) lines.push(h("div", {}, h("span", { style: { color: s.band ? colorOf(bands[i - series.length]?.color, i - series.length + 1) : colorOf(s.color, i) } }, "● "), `${s.name}: ${val}`));
    });
    tip.replaceChildren(...lines);
    tip.style.display = "block";
    const left = (ev.clientX - r.left) + 14;
    tip.style.left = `${Math.min(left, r.width - 180)}px`;
    tip.style.top = `${Math.max(0, ev.clientY - r.top - 20)}px`;
  });
  overlay.addEventListener("mouseleave", () => { tip.style.display = "none"; cursor.setAttribute("visibility", "hidden"); });
  wrap.append(root, tip);
  const legendItems = [...series.filter((s) => s.name).map((s, i) => h("span", {}, h("i", { style: { background: colorOf(s.color, i) } }), s.name)),
    ...bands.filter((b) => b.name).map((b, i) => h("span", {}, h("i", { class: "band", style: { background: colorOf(b.color, i + 1) } }), b.name))];
  if (legendItems.length > 1 || opts.legend) wrap.append(h("div", { class: "legend" }, legendItems));
  return wrap;
}

/** radial gauge 0..max with a value label */
export function gauge(value, max, label, unit = "", tone = "--accent", digits = 1) {
  const W = 160, H = 100, cx = 80, cy = 86, r = 64;
  const frac = Number.isFinite(value) ? Math.max(0, Math.min(1, value / max)) : 0;
  const arc = (f) => { const a = Math.PI * (1 - f); return [cx + r * Math.cos(a), cy - r * Math.sin(a)]; };
  const [ex, ey] = arc(frac);
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", style: "max-width:180px", role: "img", "aria-label": `${label} ${value}` },
    svg("path", { d: `M${cx - r},${cy} A${r},${r} 0 0 1 ${cx + r},${cy}`, fill: "none", stroke: css("--surface-2"), "stroke-width": 12, "stroke-linecap": "round" }),
    frac > 0 ? svg("path", { d: `M${cx - r},${cy} A${r},${r} 0 0 1 ${ex.toFixed(2)},${ey.toFixed(2)}`, fill: "none", stroke: css(tone), "stroke-width": 12, "stroke-linecap": "round" }) : null);
  return h("div", { class: "gauge" }, s, h("div", { class: "gv" }, Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : "—"), h("div", { class: "muted", style: { fontSize: "12px" } }, label));
}

/** horizontal bars: items [{ label, value, color }] */
export function bars(items, fmt = (v) => v.toFixed(0)) {
  const maxAbs = Math.max(1e-9, ...items.map((i) => Math.abs(i.value)));
  const hasNeg = items.some((i) => i.value < 0);
  return h("div", { class: "stack", style: { gap: "6px" } }, items.map((it, k) => {
    const w = Math.abs(it.value) / maxAbs * (hasNeg ? 50 : 100);
    const left = hasNeg ? (it.value < 0 ? 50 - w : 50) : 0;
    return h("div", {}, h("div", { class: "row between", style: { fontSize: "12px" } }, h("span", {}, it.label), h("b", { class: "mono" }, fmt(it.value))),
      h("div", { style: { position: "relative", height: "8px", background: "var(--surface-2)", borderRadius: "4px" } },
        h("div", { style: { position: "absolute", left: `${left}%`, width: `${w}%`, top: 0, bottom: 0, borderRadius: "4px", background: it.color ? `var(${it.color})` : `var(${PALETTE[k % PALETTE.length]})` } })));
  }));
}
