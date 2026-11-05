// Range bar: lower..upper with a median marker (RUL cycles, years to the limit).
import { h } from "../lib/dom.js";
import { num } from "../lib/format.js";
import { reduced } from "../core/reduced.js";

export function rangeBar({ lower, median, upper, unit = "", digits = 0, label = "", note = "" }) {
  const have = [lower, median, upper].filter((v) => v != null && Number.isFinite(Number(v)));
  if (!have.length) return h("div", { class: "rangebar empty" }, h("span", { class: "label" }, label), h("p", { class: "muted" }, `— ${note || "no interval for this pack"}`));
  const lo = lower ?? median, hi = upper ?? median;
  const span = Math.max(1e-9, hi * 1.15);
  const pos = (v) => `${(Math.max(0, v) / span) * 100}%`;
  const band = h("i", { class: "band", style: { left: pos(lo), width: `calc(${pos(hi)} - ${pos(lo)})` } });
  const mark = median != null ? h("b", { class: "mark", style: { left: pos(median) } }) : null;
  const el = h("div", { class: "rangebar" },
    h("div", { class: "rb-head" }, h("span", { class: "label" }, label), h("span", { class: "num" }, median != null ? `${num(median, digits)} ${unit}` : "—")),
    h("div", { class: "rb-track" }, band, mark),
    h("div", { class: "rb-ends num muted" }, h("span", {}, lower != null ? `${num(lower, digits)}` : "—"), h("span", {}, upper != null ? `${num(upper, digits)} ${unit}` : "—")),
    note ? h("p", { class: "rb-note muted" }, note) : null);
  el.play = (vars = {}) => (reduced.on ? null : gsap.timeline(vars).from(band, { scaleX: 0, transformOrigin: "left", duration: 1.3, ease: "expo.out" }).from(mark, { opacity: 0, y: -10, duration: 0.6 }, "-=0.6"));
  return el;
}
