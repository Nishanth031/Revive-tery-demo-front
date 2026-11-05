// Tiny DOM helpers. Text always goes in through textContent; never innerHTML with data.
const SVGNS = "http://www.w3.org/2000/svg";

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  setAttrs(el, attrs);
  append(el, kids);
  return el;
}
export function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined && v !== false) el.setAttribute(k, String(v));
  append(el, kids);
  return el;
}
function setAttrs(el, attrs) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
}
function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}
export const clear = (el) => { while (el.firstChild) el.firstChild.remove(); return el; };
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** headline where one word is italic: "Every battery deserves a *second* life." */
export function headline(tag, text, cls = "") {
  const el = h(tag, { class: cls });
  text.split(/(\*[^*]+\*)/).forEach((part) => {
    if (!part) return;
    if (part.startsWith("*")) el.append(h("em", {}, part.slice(1, -1)));
    else el.append(document.createTextNode(part));
  });
  return el;
}

export function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** disposition icon (shape differs per disposition; colour is never the only signal) */
export function dispIcon(d) {
  const paths = {
    REPURPOSE: [s("rect", { x: 3, y: 2, width: 6, height: 9, rx: 1, fill: "none", stroke: "currentColor", "stroke-width": 1.4 }), s("path", { d: "M5 6.5h2", stroke: "currentColor", "stroke-width": 1.4 })],
    REUSE: [s("path", { d: "M2 7a4 4 0 1 0 1.3-3", fill: "none", stroke: "currentColor", "stroke-width": 1.4 }), s("path", { d: "M2 1.5v3h3", fill: "none", stroke: "currentColor", "stroke-width": 1.4 })],
    RECYCLE: [s("path", { d: "M6 1.5l4.5 8h-9z", fill: "none", stroke: "currentColor", "stroke-width": 1.4 })],
    INSPECT: [s("circle", { cx: 5, cy: 5, r: 3.2, fill: "none", stroke: "currentColor", "stroke-width": 1.4 }), s("path", { d: "M7.5 7.5l3 3", stroke: "currentColor", "stroke-width": 1.4 })],
    NO_DECISION: [s("path", { d: "M2.5 6h7", stroke: "currentColor", "stroke-width": 1.6 })],
  };
  return s("svg", { viewBox: "0 0 12 12", "aria-hidden": "true" }, paths[d] || paths.NO_DECISION);
}

/** tone icon for an insight reason (good | bad | warn | info) */
export function toneIcon(tone) {
  const p = {
    good: s("path", { d: "M3 8.5l3 3 7-7", fill: "none", stroke: "currentColor", "stroke-width": 1.5 }),
    bad: s("path", { d: "M4 4l8 8M12 4l-8 8", stroke: "currentColor", "stroke-width": 1.5 }),
    warn: s("path", { d: "M8 2.5l6 11H2zM8 7v3M8 11.6v.4", fill: "none", stroke: "currentColor", "stroke-width": 1.4 }),
    info: s("path", { d: "M8 7v5M8 4.2v.6", stroke: "currentColor", "stroke-width": 1.6 }),
  };
  return s("svg", { viewBox: "0 0 16 16", class: `tone-ic tone-${tone}`, "aria-hidden": "true" }, s("circle", { cx: 8, cy: 8, r: 7.2, fill: "none", stroke: "currentColor", "stroke-width": 0.8, opacity: 0.4 }), p[tone] || p.info);
}

export const prefersReduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
export const isMobile = () => matchMedia("(max-width: 760px)").matches;
