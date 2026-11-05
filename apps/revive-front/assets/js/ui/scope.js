// Glowing oscilloscope canvas for the bench: a rolling trace of one reading. Drawn on the GSAP ticker only when dirty.
import { h } from "../lib/dom.js";
import { num } from "../lib/format.js";

export function scope({ label, unit, digits = 2, color = "#8FBFA9", window = 120 }) {
  const canvas = h("canvas", { "aria-hidden": "true" });
  const val = h("span", { class: "scope-val num" }, "—");
  const unitEl = h("small", { class: "muted" }, ` ${unit}`);
  const el = h("div", { class: "scope", role: "group", "aria-label": label },
    h("div", { class: "scope-head" }, h("span", { class: "label" }, label), h("span", {}, val, unitEl)), canvas);
  let pts = [], dirty = true;
  const ctx2d = canvas.getContext("2d");
  const draw = () => {
    if (!dirty || !canvas.isConnected) return;
    dirty = false;
    const dpr = Math.min(devicePixelRatio, 2), w = canvas.clientWidth, hh = canvas.clientHeight;
    if (!w || !hh) return;
    if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(hh * dpr); }
    const c = ctx2d;
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, hh);
    c.strokeStyle = "rgba(244,238,227,.07)"; c.lineWidth = 1;
    for (let i = 1; i < 4; i++) { c.beginPath(); c.moveTo(0, (hh * i) / 4); c.lineTo(w, (hh * i) / 4); c.stroke(); }
    for (let i = 1; i < 8; i++) { c.beginPath(); c.moveTo((w * i) / 8, 0); c.lineTo((w * i) / 8, hh); c.stroke(); }
    const vals = pts.filter((p) => p != null);
    if (vals.length < 2) return;
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (hi - lo < 1e-6) { lo -= 0.5; hi += 0.5; }
    const pad = (hi - lo) * 0.15;
    const y = (v) => hh - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * hh;
    c.shadowColor = color; c.shadowBlur = 10; c.strokeStyle = color; c.lineWidth = 1.6;
    c.beginPath();
    let started = false;
    pts.forEach((v, i) => { const x = (i / (window - 1)) * w; if (v == null) { started = false; return; } if (!started) { c.moveTo(x, y(v)); started = true; } else c.lineTo(x, y(v)); });
    c.stroke(); c.shadowBlur = 0;
  };
  gsap.ticker.add(draw);
  return {
    el,
    push(v, nullLabel = "—") {
      pts.push(v == null || !Number.isFinite(Number(v)) ? null : Number(v));
      if (pts.length > window) pts = pts.slice(-window);
      val.textContent = v == null ? nullLabel : num(v, digits);
      unitEl.hidden = v == null;
      dirty = true;
    },
    reset() { pts = []; val.textContent = "—"; dirty = true; },
    dispose() { gsap.ticker.remove(draw); },
  };
}
