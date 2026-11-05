// The circuit (data/circuit.json, generated from the Wokwi diagram) is drawable: pins exist, kinds have renderers.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readJSON } from "./helpers.mjs";
import { RENDERED_KINDS, WIRE_COLOR } from "../assets/js/ui/circuitView.js";

const c = readJSON("data/circuit.json");

test("every wire references existing pins and has a known type", () => {
  const pins = new Set(c.components.flatMap((x) => x.pins.map((p) => p.id)));
  for (const w of c.wires) {
    assert.ok(pins.has(w.from), w.from); assert.ok(pins.has(w.to), w.to);
    assert.ok(w.type in WIRE_COLOR, `${w.type} has a colour`);
  }
});

test("every component kind has a renderer (unknown kinds would fall back to a labelled box)", () => {
  for (const x of c.components) assert.ok(RENDERED_KINDS.includes(x.kind), `${x.id}: ${x.kind}`);
});

test("the fuse sits between battery + and the INA219, and the recommended parts are marked", () => {
  assert.ok(!c.wires.some((w) => [w.from, w.to].sort().join() === ["bat_pos", "ina_vin_pos"].sort().join()));
  assert.ok(c.wires.some((w) => w.from === "bat_pos" && w.to === "fuse_a"));
  for (const id of ["fuse", "switch", "c1", "c2", "ds18b20_amb"]) assert.ok(c.components.find((x) => x.id === id).recommended, id);
});
