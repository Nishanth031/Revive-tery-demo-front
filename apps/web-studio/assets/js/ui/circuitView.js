// Realistic bench circuit: part graphics by component kind, colour-coded right-angle wires with junction dots, and
// live behaviour ONLY from a snapshot that is passed in (never invented): current flow speed/direction from the
// measured current, V/A/°C tags, an LED blink per received line, link statistics on the USB wire and red pulses on
// the parts an active alert concerns. Hover a pin for its connection, click to highlight its net, keyboard-focusable.
import { h, svg, icon, download } from "./dom.js";

export const WIRE_COLOR = { power: "--w-power", ground: "--w-ground", logic: "--w-power", i2c: "--w-sda", i2c_scl: "--w-scl", onewire: "--w-onewire", usb: "--w-usb" };
export const WIRE_LABEL = { power: "Power (high current)", ground: "Ground", logic: "3V3 sensor power", i2c: "I²C SDA", i2c_scl: "I²C SCL", onewire: "1-Wire", usb: "USB (read-only)" };
const STYLE = `
.cv{--w-power:#e5484d;--w-ground:#3b3f46;--w-sda:#3b82f6;--w-scl:#eab308;--w-onewire:#22c55e;--w-usb:#94a3b8;--pcb:#14532d;--pcb-blue:#1d4ed8}
:root:not([data-theme="light"]) .cv{--w-ground:#cbd5e1}
.cv svg{width:100%;height:auto;display:block}
.cv .wire{fill:none;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}
.cv .wire.dim{opacity:.18}.cv .wire.hot{stroke-width:5}
.cv .flow{fill:none;stroke-width:3;stroke-dasharray:6 10;stroke:#fff;opacity:.85;animation:cvflow linear infinite}
@keyframes cvflow{to{stroke-dashoffset:-32}}
.cv .flow.rev{animation-direction:reverse}
.cv .part{cursor:default}.cv .part:focus{outline:none}.cv .part:focus .frame{stroke:var(--accent);stroke-width:2}
.cv .frame{fill:none;stroke:transparent}
.cv .pin circle{fill:#d4d4d8;stroke:#52525b;stroke-width:1;cursor:pointer}.cv .pin text{font-size:9.5px;fill:var(--text-2)}
.cv .ttl{font-size:11px;font-weight:700;fill:var(--text)}
.cv .tag{font:600 11px var(--mono);fill:#04241d}.cv .tagbg{fill:#3ee6c1;rx:5}
.cv .alert{animation:cvpulse 1.1s ease-in-out infinite}
@keyframes cvpulse{0%,100%{filter:none}50%{filter:drop-shadow(0 0 6px #ff4d4f)}}
.cv .led{fill:#334155}.cv .led.on{fill:#3ee6c1;filter:drop-shadow(0 0 4px #3ee6c1)}
.cv .junction{fill:currentColor}
.cv .tip{position:absolute;pointer-events:none;background:rgba(10,18,34,.95);color:#e8eef8;font-size:12px;padding:6px 9px;border-radius:8px;max-width:320px;display:none;z-index:5}
.cv .legend span{display:inline-flex;gap:6px;align-items:center;margin-right:12px;font-size:12px}.cv .legend i{width:18px;height:4px;border-radius:2px;display:inline-block}
@media (prefers-reduced-motion: reduce){.cv .flow,.cv .alert{animation:none}}
`;
let styled = false;
const ensureStyle = () => { if (!styled) { document.head.append(h("style", {}, STYLE)); styled = true; } };

function bbox(c) {
  const xs = c.pins.map((p) => p.x), ys = c.pins.map((p) => p.y);
  const sides = new Set(c.pins.map((p) => p.side));
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  const w = { mcu: 130, sensor: 130, passive: 52, capacitor: 34, fuse: 60, switch: 52, battery: 70, load: 70, host: 90 }[c.kind] || 110;
  if (sides.size === 1 && sides.has("right")) x0 = x1 - w;
  if (sides.size === 1 && sides.has("left")) x1 = x0 + w;
  if (x1 - x0 < 30) { x0 -= 15; x1 += 15; }
  return { x0, x1, y0: Math.min(...ys) - 30, y1: Math.max(...ys) + 18 };
}

// ---------------------------------------------------------------- part graphics (inline SVG)
const G = {
  battery: (b) => [svg("rect", { x: b.x0, y: b.y0 + 14, width: b.x1 - b.x0, height: b.y1 - b.y0 - 14, rx: 8, fill: "#1f2937", stroke: "#4b5563" }),
    svg("rect", { x: b.x0 + 12, y: b.y0 + 24, width: b.x1 - b.x0 - 24, height: b.y1 - b.y0 - 34, rx: 10, fill: "#0e7490" }),
    svg("rect", { x: b.x0 + 12, y: b.y0 + 24, width: b.x1 - b.x0 - 24, height: 10, rx: 4, fill: "#a1a1aa" }),
    svg("text", { x: (b.x0 + b.x1) / 2, y: (b.y0 + b.y1) / 2 + 6, "text-anchor": "middle", style: "font:700 13px var(--mono);fill:#e0f2fe" }, "18650"),
    svg("text", { x: b.x1 - 18, y: b.y0 + 46, style: "font-size:13px;font-weight:800;fill:#fca5a5" }, "+"), svg("text", { x: b.x1 - 18, y: b.y1 - 12, style: "font-size:13px;font-weight:800;fill:#cbd5e1" }, "−")],
  load: (b) => [svg("rect", { x: b.x0 + 6, y: b.y0 + 16, width: b.x1 - b.x0 - 12, height: b.y1 - b.y0 - 20, rx: 4, fill: "#a8a29e", stroke: "#57534e" }),
    ...[0, 1, 2, 3].map((i) => svg("line", { x1: b.x0 + 12, x2: b.x1 - 12, y1: b.y0 + 26 + i * 10, y2: b.y0 + 26 + i * 10, stroke: "#78716c", "stroke-width": 2 })),
    svg("text", { x: (b.x0 + b.x1) / 2, y: b.y1 - 10, "text-anchor": "middle", style: "font:600 10px var(--mono);fill:#1c1917" }, "POWER R")],
  sensor: (b, c) => c.id.startsWith("ds18b20") ? [
    svg("path", { d: `M${b.x0 + 20},${b.y0 + 30} h${b.x1 - b.x0 - 40} a12,12 0 0 1 0,24 v${b.y1 - b.y0 - 60} h-${b.x1 - b.x0 - 40} z`, fill: "#111827", stroke: "#374151" }),
    svg("text", { x: (b.x0 + b.x1) / 2 - 6, y: b.y0 + 52, "text-anchor": "middle", style: "font:600 9px var(--mono);fill:#9ca3af" }, "DS18B20")]
    : [svg("rect", { x: b.x0, y: b.y0 + 14, width: b.x1 - b.x0, height: b.y1 - b.y0 - 14, rx: 6, fill: "var(--pcb-blue)", stroke: "#1e3a8a" }),
      svg("rect", { x: b.x0 + 8, y: b.y0 + 30, width: 26, height: 46, rx: 3, fill: "#16a34a", stroke: "#14532d" }),
      svg("text", { x: b.x0 + 21, y: b.y0 + 58, "text-anchor": "middle", style: "font:700 8px var(--mono);fill:#fff" }, "VIN"),
      svg("rect", { x: (b.x0 + b.x1) / 2 - 16, y: (b.y0 + b.y1) / 2 - 6, width: 32, height: 14, rx: 2, fill: "#111827" }),
      svg("text", { x: (b.x0 + b.x1) / 2, y: (b.y0 + b.y1) / 2 + 5, "text-anchor": "middle", style: "font:700 8px var(--mono);fill:#e5e7eb" }, "R100"),
      svg("text", { x: (b.x0 + b.x1) / 2, y: b.y1 - 8, "text-anchor": "middle", style: "font:700 9px var(--mono);fill:#bfdbfe" }, "INA219")],
  passive: (b) => { const cx = (b.x0 + b.x1) / 2, top = b.y0 + 30, bot = b.y1 - 12;
    return [svg("line", { x1: cx, x2: cx, y1: top, y2: bot, stroke: "#a1a1aa", "stroke-width": 2 }),
      svg("rect", { x: cx - 9, y: (top + bot) / 2 - 22, width: 18, height: 44, rx: 8, fill: "#d6c7a1" }),
      ...["#facc15", "#7c3aed", "#ef4444", "#ca8a04"].map((col, i) => svg("rect", { x: cx - 9, y: (top + bot) / 2 - 16 + i * 9, width: 18, height: 4, fill: col }))]; },
  capacitor: (b) => { const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2 + 6;
    return [svg("rect", { x: cx - 9, y: cy - 10, width: 18, height: 20, rx: 6, fill: "#d97706" }), svg("line", { x1: cx, x2: cx, y1: b.y0 + 24, y2: cy - 10, stroke: "#a1a1aa", "stroke-width": 2 }),
      svg("line", { x1: cx, x2: cx, y1: cy + 10, y2: b.y1 - 8, stroke: "#a1a1aa", "stroke-width": 2 })]; },
  fuse: (b) => [svg("rect", { x: b.x0, y: b.y0 + 30, width: b.x1 - b.x0, height: 22, rx: 11, fill: "#111827", stroke: "#4b5563" }),
    svg("rect", { x: b.x0 + 12, y: b.y0 + 35, width: b.x1 - b.x0 - 24, height: 12, rx: 3, fill: "#e5e7eb", opacity: 0.6 }),
    svg("line", { x1: b.x0 + 14, x2: b.x1 - 14, y1: b.y0 + 41, y2: b.y0 + 41, stroke: "#9ca3af", "stroke-width": 1.5 })],
  switch: (b) => { const cx = (b.x0 + b.x1) / 2; return [svg("rect", { x: b.x0 + 6, y: b.y0 + 24, width: b.x1 - b.x0 - 12, height: b.y1 - b.y0 - 30, rx: 6, fill: "#1f2937", stroke: "#4b5563" }),
    svg("rect", { x: cx - 6, y: b.y0 + 34, width: 12, height: 22, rx: 3, fill: "#f97316" })]; },
  mcu: (b) => [svg("rect", { x: b.x0, y: b.y0 + 14, width: b.x1 - b.x0, height: b.y1 - b.y0 - 14, rx: 6, fill: "#0f172a", stroke: "#334155" }),
    svg("rect", { x: b.x0 + 26, y: b.y0 + 26, width: b.x1 - b.x0 - 52, height: 70, rx: 3, fill: "#9ca3af" }),
    svg("path", { d: `M${b.x0 + 32},${b.y0 + 34} h${b.x1 - b.x0 - 64} m0,8 h-${b.x1 - b.x0 - 64} m0,8 h${b.x1 - b.x0 - 64}`, stroke: "#4b5563", "stroke-width": 2, fill: "none" }),
    svg("text", { x: (b.x0 + b.x1) / 2, y: b.y0 + 82, "text-anchor": "middle", style: "font:700 9px var(--mono);fill:#111827" }, "ESP32-WROOM"),
    svg("rect", { x: (b.x0 + b.x1) / 2 - 14, y: b.y1 - 14, width: 28, height: 12, rx: 2, fill: "#d4d4d8" }),
    svg("circle", { class: "led", cx: b.x1 - 18, cy: b.y0 + 110, r: 4 }),
    ...Array.from({ length: 12 }, (_, i) => svg("rect", { x: b.x0 + 4, y: b.y0 + 104 + i * 12, width: 5, height: 5, fill: "#fbbf24" }))],
  host: (b) => [svg("rect", { x: b.x0, y: b.y0 + 20, width: b.x1 - b.x0, height: 52, rx: 4, fill: "#1e293b", stroke: "#475569" }),
    svg("rect", { x: b.x0 + 6, y: b.y0 + 26, width: b.x1 - b.x0 - 12, height: 40, rx: 2, fill: "#0ea5e9", opacity: 0.35 }),
    svg("path", { d: `M${b.x0 - 8},${b.y0 + 72} h${b.x1 - b.x0 + 16} l-6,8 h-${b.x1 - b.x0 + 4} z`, fill: "#334155" })],
};
const fallback = (b) => [svg("rect", { x: b.x0, y: b.y0 + 14, width: b.x1 - b.x0, height: b.y1 - b.y0 - 14, rx: 8, fill: "var(--surface-2)", stroke: "var(--border-strong)" })];
export const RENDERED_KINDS = Object.keys(G);

// right-angle route with rounded corners; waypoints from circuit.json are Wokwi placement hints, so the route is ours
function route(a, b) {
  const mid = a.x === b.x ? a.x + (a.side === "right" ? 36 : -36) : (a.x + b.x) / 2;
  const r = 6, pts = [[a.x, a.y], [mid, a.y], [mid, b.y], [b.x, b.y]];
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1], [x, y] = pts[i], [nx, ny] = pts[i + 1];
    const d1 = Math.min(r, Math.hypot(x - px, y - py) / 2), d2 = Math.min(r, Math.hypot(nx - x, ny - y) / 2);
    const ux = Math.sign(x - px), uy = Math.sign(y - py), vx = Math.sign(nx - x), vy = Math.sign(ny - y);
    d += ` L${x - ux * d1},${y - uy * d1} Q${x},${y} ${x + vx * d2},${y + vy * d2}`;
  }
  return `${d} L${b.x},${b.y}`;
}

/** circuit: data/circuit.json. live: false | true (running) | { current_a, voltage_v, temperature_c, ambient_c,
 *  lines_per_s, dropped, crc_errors, blink, alerts: [{ part, message }] } — only real values are drawn. */
export function circuitSvg(circuit, live = false, onBattery = null) {
  ensureStyle();
  const snap = live && typeof live === "object" ? live : null;
  const pins = {}, partOf = {};
  for (const c of circuit.components) for (const p of c.pins) { pins[p.id] = p; partOf[p.id] = c; }
  const root = svg("svg", { viewBox: "0 0 1100 620", role: "img", "aria-label": "Bench circuit" });
  const tip = h("div", { class: "tip" });
  const wrap = h("div", { class: "cv", style: { position: "relative" } });
  const wiresG = svg("g"), partsG = svg("g"), tagsG = svg("g");
  const alerted = new Set((snap?.alerts || []).map((a) => a.part));
  const wireEls = [];
  const deg = {};
  for (const w of circuit.wires) for (const e of [w.from, w.to]) deg[e] = (deg[e] || 0) + 1;
  const showTip = (e, text) => { tip.textContent = text; tip.style.display = "block"; const r = wrap.getBoundingClientRect(); tip.style.left = `${e.clientX - r.left + 12}px`; tip.style.top = `${e.clientY - r.top + 12}px`; };
  const hideTip = () => { tip.style.display = "none"; };

  // nets (union of wired pins) for click highlighting
  const parent = {};
  const find = (x) => { parent[x] ??= x; while (parent[x] !== x) x = parent[x] = parent[parent[x]]; return x; };
  for (const w of circuit.wires) parent[find(w.from)] = find(w.to);
  const highlight = (pin) => { const n = pin ? find(pin) : null; for (const { el, w } of wireEls) { el.classList.toggle("dim", Boolean(n) && find(w.from) !== n); el.classList.toggle("hot", Boolean(n) && find(w.from) === n); } };

  const flowSecs = snap && Number.isFinite(snap.current_a) && Math.abs(snap.current_a) > 1e-3 ? Math.max(0.3, 2.4 / Math.min(4, Math.abs(snap.current_a))) : null;
  for (const w of circuit.wires) {
    const a = pins[w.from], b = pins[w.to];
    if (!a || !b) continue;
    const d = route(a, b);
    const color = `var(${WIRE_COLOR[w.type] || "--text-3"})`;
    const el = svg("path", { d, class: "wire", stroke: color }, svg("title", {}, `${WIRE_LABEL[w.type] || w.type}: ${w.description}`));
    if ((w.type === "usb" && snap && (snap.crc_errors || snap.dropped)) || alerted.has(partOf[w.from]?.id) || alerted.has(partOf[w.to]?.id)) el.classList.add("alert");
    wiresG.append(el);
    wireEls.push({ el, w });
    if (flowSecs && w.type === "power") wiresG.append(svg("path", { d, class: `flow ${snap.current_a < 0 ? "rev" : ""}`, style: `animation-duration:${flowSecs}s` }));
    for (const p of [a, b]) if (deg[p.id] > 1) wiresG.append(svg("circle", { cx: p.x, cy: p.y, r: 3.5, class: "junction", style: `color:${color}` }));
    if (w.type === "usb" && snap && Number.isFinite(snap.lines_per_s)) {
      tagsG.append(svg("text", { x: (a.x + b.x) / 2, y: a.y - 10, "text-anchor": "middle", style: "font:600 10.5px var(--mono);fill:var(--text-2)" },
        `${snap.lines_per_s.toFixed(1)} lines/s · dropped ${snap.dropped ?? 0} · CRC errors ${snap.crc_errors ?? 0}`));
    }
  }
  const connectedTo = (pid) => circuit.wires.filter((w) => w.from === pid || w.to === pid).map((w) => {
    const other = w.from === pid ? w.to : w.from; return `${partOf[other]?.title} ${pins[other]?.label}: ${w.description}`; });

  for (const c of circuit.components) {
    const b = bbox(c);
    const draw = G[c.kind] || fallback;
    let shapes;
    try { shapes = draw(b, c); } catch { shapes = fallback(b); }
    const g = svg("g", { class: `part ${alerted.has(c.id) ? "alert" : ""}`, tabindex: 0, role: "group", "aria-label": `${c.title}${c.optional ? " (recommended addition)" : ""}` },
      svg("rect", { class: "frame", x: b.x0 - 4, y: b.y0, width: b.x1 - b.x0 + 8, height: b.y1 - b.y0 + 4, rx: 8 }), ...shapes,
      svg("text", { class: "ttl", x: (b.x0 + b.x1) / 2, y: b.y0 + 9, "text-anchor": "middle" }, c.title.length > 30 ? `${c.title.slice(0, 28)}…` : c.title));
    if (c.optional) g.setAttribute("opacity", "0.92");
    const al = (snap?.alerts || []).find((a) => a.part === c.id);
    if (al) g.append(svg("title", {}, al.message));
    if (c.kind === "battery" && onBattery) {
      g.addEventListener("click", onBattery);
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") onBattery(); });
      g.style.cursor = "pointer";
    }
    for (const p of c.pins) {
      const right = p.side === "right";
      const pg = svg("g", { class: "pin", tabindex: -1 }, svg("circle", { cx: p.x, cy: p.y, r: 4.5 }),
        svg("text", { x: right ? p.x - 8 : p.x + 8, y: p.y + 3, "text-anchor": right ? "end" : "start" }, p.label));
      const text = `${c.title} ${p.label} -> ${connectedTo(p.id).join(" | ") || "not connected"}`;
      pg.addEventListener("mousemove", (e) => showTip(e, text));
      pg.addEventListener("mouseleave", hideTip);
      pg.addEventListener("click", (e) => { e.stopPropagation(); highlight(p.id); });
      g.append(pg);
    }
    if (c.kind === "mcu") { const led = g.querySelector(".led"); if (led && snap?.blink) led.classList.add("on"); }
    partsG.append(g);
  }
  // live value tags (only when the snapshot carries them)
  const tag = (pid, text, dx = 0, dy = -16) => { const p = pins[pid]; if (!p) return; const w = text.length * 6.6 + 10;
    tagsG.append(svg("g", {}, svg("rect", { class: "tagbg", x: p.x + dx - w / 2, y: p.y + dy - 12, width: w, height: 17, rx: 5 }),
      svg("text", { class: "tag", x: p.x + dx, y: p.y + dy, "text-anchor": "middle" }, text))); };
  if (snap) {
    if (Number.isFinite(snap.voltage_v) && Number.isFinite(snap.current_a)) tag("ina_vin_pos", `${snap.voltage_v.toFixed(3)} V · ${snap.current_a.toFixed(3)} A`, 70, -40);
    if (Number.isFinite(snap.temperature_c)) tag("ds_dq", `${snap.temperature_c.toFixed(2)} °C`, -60, 0);
    if (Number.isFinite(snap.ambient_c)) tag("ds2_dq", `amb ${snap.ambient_c.toFixed(2)} °C`, -60, 0);
  }
  root.addEventListener("click", () => highlight(null));
  root.append(wiresG, partsG, tagsG);
  const legend = h("div", { class: "legend row" }, Object.entries(WIRE_LABEL).map(([k, l]) => h("span", {}, h("i", { style: { background: `var(${WIRE_COLOR[k]})` } }), l)));
  const exportSvg = () => {
    const c = root.cloneNode(true);
    c.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    c.setAttribute("class", "cv");
    const st = document.createElementNS("http://www.w3.org/2000/svg", "style");
    st.textContent = STYLE;
    c.prepend(st);
    return new XMLSerializer().serializeToString(c);
  };
  const buttons = h("div", { class: "row no-print", style: { marginTop: "6px" } },
    h("button", { class: "btn small", type: "button", onclick: () => download("revive_tery_circuit.svg", exportSvg(), "image/svg+xml") }, icon("download", 14), "SVG"),
    h("button", { class: "btn small", type: "button", onclick: () => {
      const img = new Image();
      img.onload = () => {
        const cv = document.createElement("canvas"); cv.width = 2200; cv.height = 1240;
        const ctx = cv.getContext("2d");
        ctx.fillStyle = getComputedStyle(document.body).backgroundColor || "#0b1220"; ctx.fillRect(0, 0, cv.width, cv.height);
        ctx.drawImage(img, 0, 0, cv.width, cv.height);
        cv.toBlob((bl) => { const a = h("a", { href: URL.createObjectURL(bl), download: "revive_tery_circuit.png" }); a.click(); });
      };
      img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(exportSvg())}`;
    } }, icon("download", 14), "PNG"));
  wrap.append(h("div", { class: "circuit" }, root), tip, legend, buttons);
  return wrap;
}
