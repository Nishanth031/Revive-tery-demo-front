// #/pack/<id>: verdict hero, why, how certain, projection (live), economics, what-if, next actions, evidence, passport.
import { h, debounce, toneIcon } from "../lib/dom.js";
import { loadFleet, loadBattery, loadBatteryHistory, isLive, api, apiBase, snapshotFile, loadDecisionMap } from "../lib/api.js";
import { appLabels, appLabel } from "../lib/fleet.js";
import { num, usd, pct, DISP_SHORT, humanKey, isNum } from "../lib/format.js";
import { dispChip, badges, placeholderTag, lockedPanel, errorMsg, lfpCaveat, provTag } from "../ui/chip.js";
import { arcGauge } from "../ui/gauge.js";
import { hbars } from "../ui/bars.js";
import { rangeBar } from "../ui/rulbar.js";
import { lineChart } from "../ui/lineChart.js";
import { reduced } from "../core/reduced.js";

export async function mount(root, { route, ctx }) {
  const id = route.arg;
  const [fleet, configs, dmap] = await Promise.all([loadFleet(), snapshotFile("configs.json").catch(() => null), loadDecisionMap().catch(() => null)]);
  const p = fleet.packs.find((x) => x.asset_id === id);
  if (!p) {
    root.append(h("section", { class: "wrap page-head" }, h("p", { class: "label eyebrow" }, "Pack"), h("h1", {}, "No such pack."), h("p", {}, `${id || "—"} is not in this fleet.`), h("a", { class: "btn", href: "#/fleet", style: { marginTop: "24px" } }, "Back to the Command Center")));
    return {};
  }
  const labels = { ...appLabels(fleet.packs), ...Object.fromEntries(Object.entries(configs?.workloads?.workloads || {}).map(([k, v]) => [k, v.label])) };
  const ins = p.insight || {};
  const page = h("div", { class: "pack-page" });

  // ---------------------------------------------------------------- hero
  const agree = p.rule ? (p.rule.agree ? "agrees with" : "differs from") : null;
  const heroBlock = h("div", { class: "wrap" },
    h("p", { class: "crumbs label" }, h("a", { href: "#/fleet" }, "Command Center"), "  /  ", p.asset_id),
    h("h1", { class: "num" }, p.asset_id),
    h("div", { class: "row-tags", style: { marginTop: "16px" } }, dispChip(p.disposition), badges(p), h("span", { class: "tag" }, p.chemistry_label || p.chemistry || "—"), p.test_case ? h("span", { class: "tag test" }, "deliberately flawed record") : null),
    h("div", { class: "verdict-word", "data-d": p.disposition }, DISP_SHORT[p.disposition] || "—"),
    h("p", { class: "muted" }, dmap?.labels?.[p.disposition] || ""),
    h("div", { class: "pack-facts" },
      fact("Engine decision", p.decision || "—"), fact("Registry status", p.registry_status ? p.registry_status.replace(/_/g, " ") : "— not in the registry"),
      fact("State of health", pct(p.soh)), fact("Best second life", p.best_label || "— not reached")),
    p.rule ? h("p", { class: "muted", style: { marginTop: "18px" } }, `The simple SOH rule says “${p.rule.existing}”; the engine ${agree} it.`) : h("p", { class: "muted", style: { marginTop: "18px" } }, "— no simple-rule comparison for this pack (it did not reach a state-of-health estimate)."),
    h("p", { class: "muted small" }, `Data provenance: ${p.data_provenance || "—"} · ${p.demo_status || ""}`));
  page.append(h("section", { class: "pack-hero", "data-rail": "" }, heroBlock));

  // ---------------------------------------------------------------- why
  const reasons = (ins.reasons || []).slice().sort((a, b) => (b.impact ?? 0) - (a.impact ?? 0));
  page.append(sec("Why", "why", reasons.length
    ? h("ol", { class: "reasons" }, reasons.map((r) => h("li", { class: `reason tone-${r.tone}` }, toneIcon(r.tone), h("div", {},
        h("h4", {}, r.title), h("p", {}, r.text), h("p", { class: "cite" }, h("code", {}, r.metric || "—"), provTag(r.provenance), h("span", { class: "tag" }, `${r.stage || "—"} · tone ${r.tone}`))))))
    : h("p", { class: "muted" }, "— no reasons were recorded for this pack."), lfpCaveat(p)));

  // ---------------------------------------------------------------- how certain
  const conf = ins.confidence;
  const gauge = arcGauge(conf?.score_0_100 ?? null, { label: `Confidence · ${conf?.level || "—"}`, size: 260 });
  const factors = hbars((conf?.factors || []).map((f) => ({ label: humanKey(f.factor), note: f.detail, value: f.points, display: `${num(f.points, 1)} / ${f.max}` })), { max: Math.max(1, ...(conf?.factors || []).map((f) => f.max)) });
  const rr = ins.rul_range || p.rul || {};
  const yr = ins.years_range || {};
  const rul = rangeBar({ lower: rr.lower, median: rr.median, upper: rr.upper, unit: rr.unit || "cycles", label: "Remaining useful life", note: rr.nominal_level ? `CV+ interval, nominal ${num(rr.nominal_level * 100)} %${isNum(rr.measured_coverage) ? `, measured coverage ${num(rr.measured_coverage * 100, 1)} % (LFP held-out)` : ""}` : "no RUL interval: the pack did not reach the state stage" });
  const yrs = rangeBar({ lower: yr.mc_p05, median: yr.central, upper: yr.mc_p95, unit: "years", digits: 1, label: `Years to the ${appLabel(labels, yr.application) || "application"} limit`, note: yr.note || "no projection for this pack" });
  page.append(sec("How certain", "certain", h("div", { class: "two" }, h("div", { style: { display: "grid", justifyItems: "center", gap: "24px" } }, gauge, h("p", { class: "muted small" }, "A heuristic score, not a probability.")),
    h("div", { style: { display: "grid", gap: "36px" } }, factors, rul, yrs))));

  // ---------------------------------------------------------------- projection (live)
  const projHost = h("div", {});
  page.append(sec("Projection", "projection", projHost));

  // ---------------------------------------------------------------- economics (snapshot has options + recycle)
  const opts = Object.entries(p.options || {});
  const best = p.best_application;
  const econRows = [...opts.map(([k, v]) => ({ label: appLabel(labels, k), value: v, display: usd(v), tone: k === best ? "best" : v != null && v < 0 ? "bad" : "good", note: k === best ? (p.capped_by_buy_new ? "best option · capped by the buy-new benchmark" : "best option") : null })),
    { label: "Recycle now", value: p.recycle_value, display: usd(p.recycle_value), tone: "muted" }];
  const econ = opts.length || p.recycle_value != null ? hbars(econRows, { signed: true }) : h("p", { class: "muted" }, "— the engine stopped before the economics stage.");
  page.append(sec("Economics", "economics", econ, h("div", { class: "row-tags", style: { marginTop: "18px" } }, placeholderTag(), h("span", { class: "tag" }, "net present value, USD"))));

  // ---------------------------------------------------------------- what-if
  const rob = ins.robustness || {};
  const tariffNow = configs?.economics?.second_life?.value_per_kwh_delivered?.value ?? null;
  const wiHost = h("div", { class: "wi-grid" },
    h("div", { class: "panel" }, h("span", { class: "label" }, "Break-even tariff"), h("div", { class: "flip-out num" }, isNum(rob.break_even_tariff) ? `${num(rob.break_even_tariff, 3)} USD/kWh` : "—"),
      h("p", { class: "muted small" }, isNum(rob.break_even_tariff) ? `Placeholder tariff today: ${num(tariffNow, 3)} USD/kWh.` : "— no tariff in the swept range flips this decision."),
      h("p", { class: "muted small" }, isNum(rob.share_same_decision) ? `Same decision in ${num(rob.share_same_decision * 100, 0)} % of ${num(rob.scenarios)} assumption scenarios (a sweep, not a probability).` : "")),
    h("div", { class: "wi-live" }));
  page.append(sec("What would change it", "whatif", wiHost));

  // ---------------------------------------------------------------- next actions
  const acts = ins.next_actions || [];
  page.append(sec("Next best actions", "actions", acts.length ? h("ol", { class: "actions" }, acts.map((a) => h("li", {}, h("div", {}, h("h4", {}, a.action), h("p", {}, `Why: ${a.why}`), h("p", {}, `Expected: ${a.expected_effect}`)))))
    : h("p", { class: "muted" }, "— no further action suggested.")));

  // ---------------------------------------------------------------- evidence
  const eviHost = h("div", { style: { display: "grid", gap: "32px" } },
    h("dl", { class: "kv" }, h("dt", {}, "Data-quality checks"), h("dd", {}, `${num(p.dq_pass)} of ${num(p.dq_total)} pass · ${String(p.readiness || "—").replace(/_/g, " ").toLowerCase()}`),
      h("dt", {}, "Failing"), h("dd", {}, (p.failing || []).length ? p.failing.join(", ") : "none"),
      h("dt", {}, "Safety gate"), h("dd", {}, `${p.gate || "—"} · UL 1974-style triage: screening, not certification`),
      h("dt", {}, "Out-of-distribution"), h("dd", {}, p.ood || "—"),
      h("dt", {}, "Stages reached"), h("dd", {}, Object.entries(p.stages || {}).map(([k, v]) => `${humanKey(k)} ${v ? "✓" : "✗"}`).join(" · ") || "—")),
    h("div", { class: "evi-live" }));
  page.append(sec("Evidence", "evidence", eviHost));
  const passHost = h("div", {});
  page.append(sec("Battery passport", "passport", passHost));
  root.append(page);

  // ---------------------------------------------------------------- live sections
  const live = isLive();
  if (!live) {
    projHost.append(lockedPanel("The projection chart (ML band, Monte Carlo band, workload limit)"));
    wiHost.querySelector(".wi-live").append(lockedPanel("Re-routing this pack under a new tariff or cost"));
    eviHost.querySelector(".evi-live").append(lockedPanel("The full check table and the capacity-test history"));
    passHost.append(lockedPanel("The battery passport download"));
  } else {
    projHost.append(h("div", { class: "skeleton", style: { height: "320px" } }));
    loadBattery(id).then((b) => { projHost.replaceChildren(projection(b, labels)); evidence(b, eviHost.querySelector(".evi-live")); })
      .catch((e) => projHost.replaceChildren(errorMsg(e, "The full report could not be loaded.")));
    loadBatteryHistory(id).then((rows) => eviHost.querySelector(".evi-live").append(historyChart(rows))).catch(() => eviHost.querySelector(".evi-live").append(h("p", { class: "muted" }, "— no capacity-test history for this pack.")));
    wiHost.querySelector(".wi-live").append(whatIf(p, tariffNow));
    passHost.append(h("a", { class: "btn primary", href: `${apiBase()}/api/battery/${encodeURIComponent(id)}/passport`, download: `${id}_passport.json`, target: "_blank", rel: "noopener", "data-magnetic": "" }, "Download passport (JSON)"),
      h("p", { class: "muted small", style: { marginTop: "12px" } }, "Informational only; built from synthetic data."));
  }

  ctx.add(() => {
    let flip = null;
    try { flip = JSON.parse(sessionStorage.getItem("revive.flip") || "null"); sessionStorage.removeItem("revive.flip"); } catch { /* ignore */ }
    if (flip && flip.id === id && !reduced.on) {
      const r = heroBlock.getBoundingClientRect();
      gsap.from(heroBlock, { x: flip.x - r.left, y: flip.y - r.top, scale: Math.min(1, flip.w / r.width), transformOrigin: "top left", opacity: 0.4, duration: 1.1, ease: "power4.inOut" });
    } else gsap.from(heroBlock.children, { opacity: 0, y: 30, duration: 1.1, stagger: 0.07 });
    if (!reduced.on) {
      ScrollTrigger.create({ trigger: gauge, start: "top 85%", once: true, onEnter: () => { gauge.play(); factors.play(); rul.play?.(); yrs.play?.(); } });
      if (econ.play) ScrollTrigger.create({ trigger: econ, start: "top 85%", once: true, onEnter: () => econ.play() });
      gsap.utils.toArray(page.querySelectorAll(".pack-sec > .wrap > h2, .reason, .actions li")).forEach((el) => gsap.from(el, { opacity: 0, y: 30, duration: 1, scrollTrigger: { trigger: el, start: "top 88%", once: true } }));
    }
  });
  return {};
}

const fact = (k, v) => h("div", {}, h("div", { class: "label muted" }, k), h("div", { class: "v" }, v));
function sec(title, key, ...body) { return h("section", { class: "pack-sec", id: `pk-${key}`, "data-rail": "" }, h("div", { class: "wrap" }, h("h2", {}, title), ...body)); }

function projection(b, labels) {
  const projs = b?.report?.projections || {};
  const keys = Object.keys(projs).filter((k) => (projs[k]?.points || []).length);
  if (!keys.length) return h("p", { class: "muted" }, "— the engine made no projection for this pack.");
  const host = h("div", {});
  const btns = keys.map((k) => h("button", { class: "chipbtn", "aria-pressed": "false", onclick: () => draw(k) }, appLabel(labels, k)));
  const wrap = h("div", {}, h("div", { class: "app-select", role: "group", "aria-label": "Application" }, btns), host,
    h("div", { class: "legend-inline" }, h("span", {}, h("i", { style: { background: "#F4EEE3" } }), "SOH projection"), h("span", {}, h("i", { style: { background: "rgba(143,191,169,.5)" } }), "ML band"),
      h("span", {}, h("i", { style: { background: "rgba(201,138,151,.45)" } }), "Monte Carlo band (assumption-conditional)"), h("span", {}, h("i", { style: { background: "#C98A97", height: "2px" } }), "Workload SOH limit")));
  function draw(k) {
    btns.forEach((b2, i) => b2.setAttribute("aria-pressed", String(keys[i] === k)));
    const pr = projs[k];
    const pts = pr.points.filter((q) => isNum(q.year) && isNum(q.soh?.value));
    const band = (key) => pr.points.filter((q) => isNum(q.year) && Array.isArray(q[key]?.values) && q[key].values.every(isNum)).map((q) => [q.year, ...q[key].values]);
    const limit = pr.workload?.values?.min_soh_pct;
    const ys = pts.map((q) => q.soh.value).concat(band("ml_band").flatMap((x) => x.slice(1)), band("mc_band").flatMap((x) => x.slice(1)), isNum(limit) ? [limit] : []);
    const chart = lineChart({ label: `SOH projection for ${appLabel(labels, k)}`,
      x: { min: Math.min(...pts.map((q) => q.year)), max: Math.max(...pts.map((q) => q.year)), label: "years", fmt: (v) => num(v, 0) },
      y: { min: Math.floor(Math.min(...ys) - 2), max: Math.ceil(Math.max(...ys) + 2), label: "SOH %", fmt: (v) => num(v, 0) },
      bands: [{ points: band("mc_band"), color: "#C98A97", opacity: 0.2 }, { points: band("ml_band"), color: "#8FBFA9", opacity: 0.28 }],
      series: [{ points: pts.map((q) => [q.year, q.soh.value]), color: "#F4EEE3" }],
      refs: isNum(limit) ? [{ y: limit, label: `${pr.workload?.label || appLabel(labels, k)} limit ${num(limit)} %` }] : [],
      tooltip: (x) => { const q = pr.points.find((z) => z.year === x); return [`Year ${num(x, 1)}`, `SOH ${num(q?.soh?.value, 1)} %`, q?.ml_band ? `ML ${num(q.ml_band.values?.[0], 1)}–${num(q.ml_band.values?.[1], 1)}` : "", q?.mc_band ? `MC ${num(q.mc_band.values?.[0], 1)}–${num(q.mc_band.values?.[1], 1)}` : ""].filter(Boolean); } });
    host.replaceChildren(chart);
    chart.play();
  }
  draw(keys.includes(b?.report?.economics?.best_application) ? b.report.economics.best_application : keys[0]);
  return wrap;
}

function evidence(b, host) {
  const checks = b?.report?.data_quality?.checks || [];
  if (!checks.length) return;
  const name = (c) => c.name ?? c.check ?? c.id ?? c.rule ?? "—";
  const status = (c) => (typeof c.passed === "boolean" ? (c.passed ? "pass" : "fail") : c.status ?? c.result ?? "—");
  const detail = (c) => c.detail ?? c.message ?? c.reason ?? "";
  host.prepend(h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("thead", {}, h("tr", {}, h("th", {}, "Check"), h("th", {}, "Result"), h("th", {}, "Detail"))),
    h("tbody", {}, checks.map((c) => h("tr", {}, h("td", {}, humanKey(name(c))), h("td", {}, String(status(c))), h("td", {}, typeof detail(c) === "string" ? detail(c) : JSON.stringify(detail(c)))))))));
  if (b?.report?.gate) host.append(h("p", { class: "muted small" }, `Gate verdict: ${b.report.gate.verdict ?? b.report.gate.status ?? JSON.stringify(b.report.gate).slice(0, 160)}`));
}

function historyChart(rows) {
  if (!Array.isArray(rows) || rows.length < 2) return h("p", { class: "muted" }, "— fewer than two capacity tests recorded.");
  const dateKey = Object.keys(rows[0]).find((k) => /date|time/i.test(k));
  const valKey = Object.keys(rows[0]).find((k) => /soh/i.test(k) && rows.some((r) => isNum(r[k]))) || Object.keys(rows[0]).find((k) => /capacity/i.test(k) && rows.some((r) => isNum(r[k])));
  if (!dateKey || !valKey) return h("p", { class: "muted" }, "— the history rows carry no dated health value.");
  const pts = rows.filter((r) => isNum(r[valKey]) && r[dateKey]).map((r) => [new Date(r[dateKey]).getTime(), Number(r[valKey])]);
  if (pts.length < 2) return h("p", { class: "muted" }, "— fewer than two dated values.");
  const ys = pts.map((x) => x[1]);
  const c = lineChart({ label: `Health history (${valKey})`, height: 260, x: { min: pts[0][0], max: pts[pts.length - 1][0], ticks: 4, fmt: (v) => new Date(v).getFullYear() },
    y: { min: Math.floor(Math.min(...ys) - 1), max: Math.ceil(Math.max(...ys) + 1), label: humanKey(valKey), fmt: (v) => num(v, 0) }, series: [{ points: pts, color: "#8FBFA9" }],
    tooltip: (x) => [new Date(x).toLocaleDateString("en-GB"), `${humanKey(valKey)}: ${num(pts.find((q) => q[0] === x)?.[1], 1)}`] });
  requestAnimationFrame(() => c.play());
  return h("div", {}, h("h3", { style: { fontSize: "1.4rem", margin: "12px 0" } }, "Health history"), c);
}

function whatIf(p, tariffNow) {
  const out = h("div", { class: "flip-out" }, p.decision || "—");
  const note = h("p", { class: "muted small" }, "Engine decision today. Move a lever to re-route only the economics stage.");
  const tVal = h("span", { class: "num" }), cVal = h("span", { class: "num" });
  const tMax = Math.max(0.2, (p.insight?.robustness?.break_even_tariff ?? 0) * 2, (tariffNow ?? 0) * 3);
  const t = h("input", { type: "range", min: 0, max: tMax, step: tMax / 400, value: tariffNow ?? 0, "aria-label": "Tariff USD per kWh" });
  const c = h("input", { type: "range", min: 0.25, max: 3, step: 0.05, value: 1, "aria-label": "Cost multiplier" });
  const paint = () => { tVal.textContent = `${num(Number(t.value), 3)} USD/kWh`; cVal.textContent = `× ${num(Number(c.value), 2)}`; };
  paint();
  const run = debounce(async () => {
    try {
      const r = await api.post("/api/whatif", { asset_id: p.asset_id, overrides: { tariff: Number(t.value), cost_mult: Number(c.value) } });
      const next = r.rerouted ? `${r.decision}${r.application ? "" : ""}` : r.decision;
      note.textContent = r.rerouted ? `Best second-life net ${usd(r.best_net)} vs recycling ${usd(r.recycle_net)} (modelled · placeholder inputs).` : `Not re-routed: ${r.reason}.`;
      if (next !== out.textContent) gsap.timeline().to(out, { opacity: 0, y: -12, duration: 0.3, ease: "power4.in" }).add(() => { out.textContent = next; }).to(out, { opacity: 1, y: 0, duration: 0.7 });
    } catch (e) { note.textContent = `— ${e.message}`; }
  }, 150);
  t.addEventListener("input", () => { paint(); run(); });
  c.addEventListener("input", () => { paint(); run(); });
  return h("div", { class: "panel" }, h("span", { class: "label" }, "Live what-if"), out, note,
    h("div", { class: "field" }, h("label", { class: "label" }, "Tariff (placeholder) ", tVal), t),
    h("div", { class: "field" }, h("label", { class: "label" }, "Cost multiplier ", cVal), c), placeholderTag());
}
