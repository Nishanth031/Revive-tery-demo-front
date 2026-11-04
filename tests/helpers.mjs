// Shared helpers for the Node parity tests (node --test tests/).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const readJSON = (p) => JSON.parse(readFileSync(join(ROOT, p), "utf-8"));
export const readText = (p) => readFileSync(join(ROOT, p), "utf-8");
export const golden = (name) => readJSON(`tests/golden/${name}`);

let assetsPromise = null;
export function assets() {
  if (!assetsPromise) {
    assetsPromise = import("../assets/js/engines/pipeline.js").then((m) => m.loadAssets(async (p) => readJSON(p)));
  }
  return assetsPromise;
}

/** |a - b| <= atol + rtol * |b|, with null == null */
export function close(a, b, msg, rtol = 1e-6, atol = 1e-9) {
  if (b === null || b === undefined) { assert.ok(a === null || a === undefined || Number.isNaN(a), `${msg}: expected null, got ${a}`); return; }
  assert.ok(typeof a === "number" && Math.abs(a - b) <= atol + rtol * Math.abs(b), `${msg}: got ${a}, expected ${b}`);
}

/** golden bundle JSON (metadata + telemetry rows) -> JS bundle */
export async function bundleFromGolden(gb) {
  const { loadBundle } = await import("../assets/js/engines/contract.js");
  const b = loadBundle(gb.metadata, gb.telemetry);
  b.ignored_columns = gb.ignored_columns;
  return b;
}
