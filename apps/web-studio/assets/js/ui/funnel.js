// Stage funnel: counts from the real stage results (lib/fleet.js fleetSummary().funnel).
import { h } from "./dom.js";

export function funnel(steps) {
  const max = Math.max(1, ...steps.map(([, n]) => n));
  return h("div", { class: "funnel" }, steps.map(([label, n], i) => h("div", { class: "step" },
    h("span", {}, label),
    h("div", { style: { background: "var(--surface-2)", borderRadius: "7px" } },
      h("div", { class: "bar", style: { width: `${(100 * n) / max}%`, animationDelay: `${i * 120}ms` } })),
    h("b", { class: "mono", style: { textAlign: "right" } }, String(n)))));
}
