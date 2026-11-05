// Fleet helpers: filtering/sorting like GET /api/fleet, derived facts read from the packs at runtime.
import { SECOND } from "./api.js";

const SOURCE = {
  test: (p) => p.test_case === true,
  user: (p) => (p.registry_source || "").includes("user fleet"),
  platform: (p) => !p.test_case && !(p.registry_source || "").includes("user fleet"),
};

export function filterPacks(packs, { q = "", disposition = "", chemistry = "", source = "", sort = "asset_id", desc = false } = {}) {
  const needle = q.trim().toLowerCase();
  let out = packs.filter((p) => {
    if (disposition && p.disposition !== disposition) return false;
    if (chemistry && p.chemistry !== chemistry) return false;
    if (source && SOURCE[source] && !SOURCE[source](p)) return false;
    if (needle) {
      const hay = [p.asset_id, p.chemistry, p.chemistry_label, p.application, p.best_label, p.decision, p.registry_status].join(" ").toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  });
  const key = {
    net_value: (p) => p.net_value, soh: (p) => p.soh, confidence: (p) => p.insight?.confidence?.score_0_100, asset_id: (p) => p.asset_id,
  }[sort] || ((p) => p.asset_id);
  out = out.slice().sort((a, b) => {
    const x = key(a), y = key(b);
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    const c = typeof x === "string" ? x.localeCompare(y) : x - y;
    return desc ? -c : c;
  });
  return out;
}

export const chemistries = (packs) => [...new Set(packs.map((p) => p.chemistry).filter(Boolean))].sort();
export const applicationKeys = (packs) => [...new Set(packs.flatMap((p) => Object.keys(p.options || {})))];

/** how many packs the engine disagrees with the simple SOH-threshold rule on (rule.agree === false) */
export function ruleDisagreement(packs) {
  const judged = packs.filter((p) => p.rule && typeof p.rule.agree === "boolean");
  return { disagree: judged.filter((p) => p.rule.agree === false).length, judged: judged.length };
}

/** highest-confidence pack among second-life picks (falls back to the highest-confidence pack overall) */
export function featuredPack(packs) {
  const score = (p) => p.insight?.confidence?.score_0_100 ?? -1;
  const pool = packs.filter((p) => SECOND.includes(p.disposition) && p.insight?.reasons?.length);
  const list = (pool.length ? pool : packs.filter((p) => p.insight)).slice().sort((a, b) => score(b) - score(a));
  return list[0] || null;
}

/** application labels discovered from the packs themselves (best_application -> best_label) */
export function appLabels(packs) {
  const m = {};
  for (const p of packs) if (p.best_application && p.best_label) m[p.best_application] = p.best_label;
  return m;
}
export const appLabel = (labels, key) => labels[key] || String(key || "").replace(/_/g, " ");
