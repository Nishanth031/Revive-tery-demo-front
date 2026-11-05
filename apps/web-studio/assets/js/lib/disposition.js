// Reuse / repurpose / recycle chip: same prefix rules as services/api/revive_api/disposition.py,
// read from data/decision_map.json (a copy of config/decision_map.json made by `just sync-config`).
let mapPromise = null;

export function loadDecisionMap(fetchJSON = (u) => fetch(u).then((r) => r.json())) {
  if (!mapPromise) mapPromise = fetchJSON("data/decision_map.json").catch(() => null);
  return mapPromise;
}

function applicationKey(decision, application, workloads) {
  const keys = Object.keys(workloads || {});
  const byLabel = Object.fromEntries(keys.map((k) => [String(workloads[k]?.label || "").trim().toLowerCase(), k]));
  const candidates = [application, decision.includes(":") ? decision.split(":").slice(1).join(":") : null].filter(Boolean);
  for (const raw of candidates) {
    const c = String(raw).trim();
    if (keys.includes(c)) return c;
    if (byLabel[c.toLowerCase()]) return byLabel[c.toLowerCase()];
  }
  return null;
}

export function disposition(map, decision, application = null, workloads = null) {
  if (!map) return null;
  const d = String(decision || "").trim();
  for (const rule of map.rules) {
    if (!d.startsWith(rule.match_prefix)) continue;
    let code = rule.disposition;
    if (!code) {
      const key = applicationKey(d, application, workloads);
      if ((rule.application_keys_to_REUSE || []).includes(key)) code = "REUSE";
      else if ((rule.application_keys_to_REPURPOSE || []).includes(key)) code = "REPURPOSE";
      else code = rule.default_disposition || "REPURPOSE";
    }
    return { code, label: map.labels[code] };
  }
  return { code: "NO_DECISION", label: map.labels.NO_DECISION };
}

export const DISPOSITION_TONE = { REUSE: "good", REPURPOSE: "good", RECYCLE: "warn", INSPECT: "warn", NO_DECISION: "neutral" };
