// Horizontal bars (economics options, confidence factors). Negative values grow left from a zero line.
import { h } from "../lib/dom.js";
import { reduced } from "../core/reduced.js";

/** rows: [{ label, value, display, tone ("good"|"bad"|"muted"|"best"), note }] */
export function hbars(rows, { max = null, signed = false } = {}) {
  const vals = rows.map((r) => Math.abs(r.value ?? 0));
  const top = max ?? Math.max(1e-9, ...vals);
  const wrap = h("div", { class: `hbars${signed ? " signed" : ""}` });
  const fills = [];
  for (const r of rows) {
    const frac = r.value == null ? 0 : Math.min(1, Math.abs(r.value) / top);
    const fill = h("i", { class: `fill tone-${r.tone || "good"}${r.value != null && r.value < 0 ? " neg" : ""}`, style: { transform: `scaleX(${frac})` } });
    fill.dataset.frac = String(frac);
    fills.push(fill);
    wrap.append(h("div", { class: "hbar" },
      h("div", { class: "hbar-label" }, r.label, r.note ? h("small", {}, r.note) : null),
      h("div", { class: "hbar-track" }, fill),
      h("div", { class: "hbar-val num" }, r.display ?? "—")));
  }
  wrap.play = (vars = {}) => (reduced.on ? null : gsap.fromTo(fills, { scaleX: 0 }, { scaleX: (i, el) => Number(el.dataset.frac), duration: 1.3, ease: "expo.out", stagger: 0.08, ...vars }));
  return wrap;
}
