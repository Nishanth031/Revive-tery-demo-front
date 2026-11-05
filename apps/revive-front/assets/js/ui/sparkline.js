// Small inline sparkline (health history, plan values).
import { s } from "../lib/dom.js";

export function sparkline(values, { width = 160, height = 40, color = "#8FBFA9" } = {}) {
  const v = values.filter((x) => x != null && Number.isFinite(Number(x))).map(Number);
  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "spark", "aria-hidden": "true" });
  if (v.length < 2) return svg;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const d = v.map((y, i) => `${i ? "L" : "M"}${((i / (v.length - 1)) * (width - 4) + 2).toFixed(1)},${(height - 3 - ((y - lo) / span) * (height - 6)).toFixed(1)}`).join(" ");
  svg.append(s("path", { d, fill: "none", stroke: color, "stroke-width": 1.5, "stroke-linejoin": "round" }));
  return svg;
}
