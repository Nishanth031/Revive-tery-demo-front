// engines/firmware/wokwi/diagram.json (connections, the single source of truth) + circuit_meta.json (titles, kinds,
// pin positions, wire text, parts Wokwi cannot simulate) -> apps/web-studio/data/circuit.json.
// Run from apps/web-studio:  node tools/wokwi_to_circuit.mjs   (part of `just wokwi-sync`)
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const WOKWI = join(WEB, "../../engines/firmware/wokwi");
const diagram = JSON.parse(readFileSync(join(WOKWI, "diagram.json"), "utf-8"));
const meta = JSON.parse(readFileSync(join(WOKWI, "circuit_meta.json"), "utf-8"));

// "<wokwi part id>:<wokwi pin>" -> our pin id
const pinOf = {};
for (const c of meta.components) {
  if (c.wokwi === false) continue;
  for (const p of c.pins) if (p[5]) pinOf[`${c.wokwi_id}:${p[5]}`] = p[0];
}
const key = (a, b) => [`${a}|${b}`, `${b}|${a}`];
const wires = [];
const missing = [];
for (const [from, to, color, route] of diagram.connections) {
  if (from.startsWith("$") || to.startsWith("$")) continue;          // serial monitor plumbing
  const a = pinOf[from], b = pinOf[to];
  if (!a || !b) { missing.push(`${from} -> ${to}`); continue; }
  const [k1, k2] = key(a, b);
  wires.push({ from: a, to: b, type: meta.wire_types?.[k1] || meta.wire_types?.[k2] || meta.wire_colors[color] || "logic",
    color, description: meta.wire_text[k1] || meta.wire_text[k2] || "", waypoints: route || [], wokwi: [from, to] });
}
if (missing.length) { console.error("unmapped diagram connections:", missing); process.exit(1); }
for (const [a, b, type, description] of meta.extra_wires) wires.push({ from: a, to: b, type, description, waypoints: [], wokwi: null });
const components = meta.components.map((c) => ({ id: c.id, title: c.title, kind: c.kind, optional: Boolean(c.optional),
  recommended: Boolean(c.recommended), conditional: c.conditional || null, wokwi: c.wokwi !== false ? c.wokwi_id : null,
  pins: c.pins.map(([id, label, x, y, side]) => ({ id, label, x, y, side })) }));
const out = { generated_from: "engines/firmware/wokwi/diagram.json + circuit_meta.json (tools/wokwi_to_circuit.mjs)",
  max_bus_voltage_v: 26, components, wires, legend: [] };
// OneDrive can hold a just-synced file for a moment (EUNKNOWN/EBUSY on Windows): retry a few times
for (let attempt = 1; ; attempt++) {
  try { writeFileSync(join(WEB, "data/circuit.json"), JSON.stringify(out, null, 1)); break; }
  catch (e) { if (attempt >= 8) throw e; Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500 * attempt); }
}
console.log(`circuit.json: ${components.length} components, ${wires.length} wires (${wires.filter((w) => w.wokwi).length} from diagram.json)`);
