// #/ Home: a scroll film in 8 beats. Every figure is read from the fleet at runtime.
import { h, s, headline, debounce, isMobile } from "../lib/dom.js";
import { loadFleet, loadSummary, loadDecisionMap, snapshotFile, isLive, api, DISPOSITIONS } from "../lib/api.js";
import { ruleDisagreement, featuredPack, appLabels, appLabel } from "../lib/fleet.js";
import { num, usd, median, DISP_SHORT, pct } from "../lib/format.js";
import { countUp, reduced } from "../core/reduced.js";
import { revealLines, revealOnScroll } from "../core/transitions.js";
import { scrollTo } from "../core/smooth.js";
import { layers } from "../main.js";
import { dispositionRing, DISP_FILL } from "../ui/ring.js";
import { arcGauge, tickRing } from "../ui/gauge.js";
import { hbars } from "../ui/bars.js";
import { dispChip, placeholderTag, provTag, lockedPanel } from "../ui/chip.js";
import { toneIcon } from "../lib/dom.js";

export async function mount(root, { ctx }) {
  const [fleet, sum, dmap, configs] = await Promise.all([loadFleet(), loadSummary(), loadDecisionMap(), snapshotFile("configs.json").catch(() => null)]);
  const packs = fleet.packs;
  const labels = { ...appLabels(packs), ...Object.fromEntries(Object.entries(configs?.workloads?.workloads || {}).map(([k, v]) => [k, v.label])) };
  const f = sum.funnel || {};
  const numeral = document.getElementById("decor-numeral");

  // 1 · hero ---------------------------------------------------------------------------------------------------
  const k1 = h("span", { class: "kpi-n num" }), k2 = h("span", { class: "kpi-n num" }), k3 = h("span", { class: "kpi-n num" });
  const hero = h("section", { class: "section hero", id: "beat-hero", "data-tone": "dark", "data-rail": "" },
    h("div", { class: "wrap" },
      h("p", { class: "label eyebrow hero-eyebrow" }, "Retired EV batteries · second-life triage"),
      headline("h1", "Every battery deserves a *second* life.", "hero-title"),
      h("p", { class: "hero-sub" }, "REVIVE-TERY reads a retired EV pack's data, proves it is safe, estimates what it has left, and decides: reuse, repurpose or recycle. With the reasons attached."),
      h("div", { class: "btn-row hero-ctas" },
        h("a", { class: "btn primary", href: "#/fleet", "data-magnetic": "" }, "Enter the Command Center"),
        h("button", { class: "btn", "data-magnetic": "", onclick: () => scrollTo("#beat-stages") }, "See how it decides")),
      h("div", { class: "kpis" },
        h("div", { class: "kpi" }, k1, h("span", { class: "label" }, "Packs assessed")),
        h("div", { class: "kpi" }, h("span", { class: "kpi-line" }, k2, h("small", {}, " kWh")), h("span", { class: "label" }, "Redeployed to a second life")),
        h("div", { class: "kpi" }, k3, h("span", { class: "label" }, "Value routed vs recycling everything"), placeholderTag()))));

  // 2 · the question ---------------------------------------------------------------------------------------------
  const rd = ruleDisagreement(packs);
  const qNum = h("span", { class: "num big-figure" });
  const question = h("section", { class: "section question", id: "beat-question", "data-tone": "paper", "data-rail": "" },
    h("div", { class: "wrap grid12" },
      h("p", { class: "label eyebrow", style: { gridColumn: "1 / -1" } }, "The question"),
      headline("h2", "A single health threshold sees one number. A pack's *future* depends on all of them.", "statement"),
      h("div", { class: "figure-block" }, qNum,
        h("p", {}, `of the ${rd.judged} packs that a simple state-of-health rule would place, the engine disagrees with that rule on this many, once data quality, safety, projected life and value are weighed.`),
        h("p", { class: "muted small" }, "Rule compared: ", (packs.find((p) => p.insight?.rule_gap?.note)?.insight.rule_gap.note) || "the registry's SOH threshold rule"))));

  // 3 · five stages (pinned) -----------------------------------------------------------------------------------------
  const sohMed = median(packs.map((p) => p.soh));
  const yrs = packs.map((p) => p.insight?.years_range).filter(Boolean);
  const yC = median(yrs.map((y) => y.central)), yLo = median(yrs.map((y) => y.mc_p05)), yHi = median(yrs.map((y) => y.mc_p95));
  const dqTotal = packs.find((p) => p.dq_total)?.dq_total ?? 14;
  const funnelSeq = [f.data_quality_ready, f.gate_pass, f.state_ok, f.state_ok, f.second_life_chosen];
  const stageDefs = [
    { n: "01", title: "Data quality", text: `${dqTotal} checks on every record: timestamps, gaps, sign conventions, physical ranges. Packs that are not ready stop here.`, vis: () => tickRing(dqTotal, dqTotal) },
    { n: "02", title: "Safety gate", text: "UL 1974-style triage: screening, not certification. Thermal history, resistance and out-of-distribution checks.", vis: () => gateBar(f.gate_pass, f.data_quality_ready) },
    { n: "03", title: "State of health", text: `Capacity-based state of health with a conformal remaining-life interval. Fleet median: ${pct(sohMed)}.`, vis: () => arcGauge(sohMed, { label: "Fleet median SOH", unit: " %", digits: 1, size: 240 }) },
    { n: "04", title: "Projection", text: `Physics projection with a Monte Carlo band to each application's limit. Median central estimate ${num(yC, 1)} years (band ${num(yLo, 1)}–${num(yHi, 1)}).`, vis: () => projectionSketch(yLo, yC, yHi) },
    { n: "05", title: "Economics", text: "Second life against recycling now, per application, capped by the cost of buying new.", vis: () => econBars(sum) },
  ];
  const counter = h("span", { class: "num funnel-count" }, num(f.total));
  const panels = stageDefs.map((d, i) => h("article", { class: "stage-panel", "data-i": i },
    h("div", { class: "stage-copy" }, h("span", { class: "label" }, `Stage ${d.n}`), h("h3", {}, d.title), h("p", {}, d.text),
      h("p", { class: "stage-left label" }, `${num(funnelSeq[i])} of ${num(f.total)} continue`)),
    h("div", { class: "stage-vis" }, d.vis())));
  const stages = h("section", { class: "section stages", id: "beat-stages", "data-tone": "dark", "data-rail": "" },
    h("div", { class: "stages-pin" },
      h("div", { class: "wrap stages-head" }, h("p", { class: "label eyebrow" }, "Five stages"), h("div", { class: "funnel-box" }, counter, h("span", { class: "label" }, "packs in the funnel"))),
      h("div", { class: "wrap stage-stack" }, panels)));

  // 4 · verdict -----------------------------------------------------------------------------------------------------
  const by = sum.by_disposition || {};
  const order = DISPOSITIONS;
  const ring = dispositionRing(by, order, {
    size: 420, onHover: (d) => { layers.pack?.highlight(d); legend.querySelectorAll(".legend-row").forEach((r) => r.classList.toggle("dim", !!d && r.dataset.d !== d)); },
    onClick: (d) => { location.hash = `#/fleet?disposition=${d}`; },
  });
  const ringCenter = h("div", { class: "ring-center" }, h("span", { class: "num ring-n" }, num(sum.n)), h("span", { class: "label" }, "packs"));
  const legend = h("div", { class: "legend" }, order.map((d) => h("a", { class: "legend-row", href: `#/fleet?disposition=${d}`, "data-d": d,
    onpointerenter: () => layers.pack?.highlight(d), onpointerleave: () => layers.pack?.highlight(null) },
    dispChip(d), h("span", { class: "legend-label" }, dmap?.labels?.[d] || DISP_SHORT[d]), h("span", { class: "num legend-n" }, num(by[d] || 0)))));
  const lsev = packs.filter((p) => (p.options?.low_speed_ev ?? null) !== null);
  const lsevAbove = lsev.filter((p) => p.options.low_speed_ev > (p.recycle_value ?? 0)).length;
  const reuseNote = (by.REUSE || 0) === 0
    ? h("p", { class: "reuse-note muted" }, `Reuse is ${num(0)}: the vehicle option (${appLabel(labels, "low_speed_ev")}) is valued as an ${String(configs?.workloads?.workloads?.low_speed_ev?.valuation_mode || "avoided new pack").replace(/_/g, " ")}, and its modelled net value beats recycling now for ${lsevAbove} of the ${lsev.length} packs where it was computed, so the engine routes none to a vehicle.`)
    : null;
  const verdict = h("section", { class: "section verdict", id: "beat-verdict", "data-tone": "dark", "data-rail": "" },
    h("div", { class: "wrap grid12" },
      h("div", { class: "verdict-copy" }, h("p", { class: "label eyebrow" }, "The verdict"), headline("h2", `${num(sum.n)} packs. *Five* honest outcomes.`, ""), legend, reuseNote),
      h("div", { class: "verdict-ring" }, ring.svg, ringCenter)));

  // 5 · trust ----------------------------------------------------------------------------------------------------------
  const fp = featuredPack(packs);
  const trust = h("section", { class: "section trust", id: "beat-trust", "data-tone": "paper", "data-rail": "" }, h("div", { class: "wrap" },
    h("p", { class: "label eyebrow" }, "Why you can trust the reasons"),
    fp ? trustBlock(fp) : h("p", {}, "— no assessed pack with reasons in this data.")));

  // 6 · what would change it -------------------------------------------------------------------------------------------
  const tariffNow = configs?.economics?.second_life?.value_per_kwh_delivered?.value ?? null;
  const whatif = h("section", { class: "section whatif", id: "beat-whatif", "data-tone": "dark", "data-rail": "" },
    h("div", { class: "wrap" }, h("p", { class: "label eyebrow" }, "What would change it"),
      headline("h2", "Every decision has a *tipping* point.", ""), fp ? tariffTrack(fp, tariffNow) : null));

  // 7 · honest by design -------------------------------------------------------------------------------------------------
  const ledger = [
    ["Synthetic data", "Every pack in this fleet is synthetic. Each one carries its data provenance; deliberately flawed test cases are badged."],
    ["Placeholder prices", "Tariffs and costs are PLACEHOLDER inputs. Every money figure is modelled and tagged as such."],
    ["LFP-trained model", "The state model was trained on LFP cells. For NMC and NCA packs the remaining-life figures are indicative. Confidence is a heuristic, not a probability."],
    ["Monitor-only hardware", "The ESP32 bench is monitor-only and low voltage, never an EV pack. This site has no hardware controls."],
  ];
  const honest = h("section", { class: "section honest", id: "beat-honest", "data-tone": "paper", "data-rail": "" }, h("div", { class: "wrap" },
    h("p", { class: "label eyebrow" }, "Honest by design"), headline("h2", "Four limits, stated *plainly*.", ""),
    h("ol", { class: "ledger" }, ledger.map(([t, d], i) => h("li", {}, h("span", { class: "num ledger-n" }, `0${i + 1}`), h("h3", {}, t), h("p", {}, d))))));

  // 8 · closing ----------------------------------------------------------------------------------------------------------
  const closing = h("section", { class: "section closing", id: "beat-close", "data-tone": "dark", "data-rail": "" }, h("div", { class: "wrap" },
    headline("h2", "Give it a *second* life.", "closing-title"),
    h("div", { class: "btn-row" }, h("a", { class: "btn primary", href: "#/fleet", "data-magnetic": "" }, "Enter the Command Center"),
      h("a", { class: "btn", href: "#/evidence" }, "Read the evidence"), h("a", { class: "btn ghost", href: "http://localhost:8080/#/command?demo=1", target: "_blank", rel: "noopener" }, "Open the engine studio")),
    h("footer", { class: "foot" }, h("span", { class: "brand" }, "REVIVE", h("i", {}, "·"), "TERY"), h("span", { class: "label", "data-status-mirror": "" }, document.querySelector("#status-chip .txt")?.textContent || ""),
      h("span", { class: "label muted" }, "Synthetic data · Screening only"))));

  root.append(hero, question, stages, verdict, trust, whatif, honest, closing);

  // ---------------------------------------------------------------- motion
  ctx.add(() => {
    numeral.textContent = "01";
    const intro = gsap.timeline({ delay: 0.1 });
    intro.add(revealLines(hero.querySelector(".hero-title")), 0)
      .from(hero.querySelectorAll(".hero-eyebrow, .hero-sub, .hero-ctas, .kpi"), { opacity: 0, y: 30, duration: 1.2, stagger: 0.09, ease: "expo.out" }, 0.35);
    countUp(k1, sum.n, { delay: 0.6 });
    countUp(k2, sum.kwh_redeployed, { delay: 0.7, format: (v) => num(v, 1) });
    countUp(k3, sum.value_vs_recycle_all_usd, { delay: 0.8, format: (v) => (v >= 0 ? "+" : "") + usd(v) });
    layers.pack?.setState("hero");

    ScrollTrigger.create({ trigger: question, start: "top 70%", once: true, onEnter: () => countUp(qNum, rd.disagree, { duration: 1.4 }) });
    revealOnScroll(question.querySelectorAll(".statement, .figure-block"));

    const mm = gsap.matchMedia();
    mm.add({ desk: "(min-width: 761px) and (prefers-reduced-motion: no-preference)", mob: "(max-width: 760px), (prefers-reduced-motion: reduce)" }, (c) => {
      if (c.conditions.desk) {
        gsap.set(panels.slice(1), { autoAlpha: 0, y: 60 });
        const tl = gsap.timeline({ scrollTrigger: { trigger: stages, start: "top top", end: () => `+=${innerHeight * 4}`, pin: stages.querySelector(".stages-pin"), scrub: 1,
          onUpdate: (st) => { layers.pack?.setState("pipeline", st.progress); const i = Math.min(4, Math.floor(st.progress * 5)); numeral.textContent = `0${i + 1}`; counter.textContent = num(i === 0 && st.progress < 0.05 ? f.total : funnelSeq[i]); },
          onLeaveBack: () => { layers.pack?.setState("hero"); numeral.textContent = "01"; } } });
        panels.forEach((p, i) => {
          if (i > 0) tl.to(panels[i - 1], { autoAlpha: 0, y: -60, duration: 0.5, ease: "power4.inOut" }).to(p, { autoAlpha: 1, y: 0, duration: 0.5, ease: "expo.out" }, "<0.15");
          tl.add(() => p.querySelector(".stage-vis > *")?.play?.(), "<").to({}, { duration: 0.6 });
        });
      } else {
        panels.forEach((p) => ScrollTrigger.create({ trigger: p, start: "top 80%", once: true, onEnter: () => p.querySelector(".stage-vis > *")?.play?.() }));
        ScrollTrigger.create({ trigger: stages, start: "top center", end: "bottom center", onUpdate: (st) => layers.pack?.setState("pipeline", st.progress), onLeaveBack: () => layers.pack?.setState("hero") });
      }
    });
    ScrollTrigger.create({ trigger: verdict, start: "top 75%", end: "center center", scrub: 1, onUpdate: (st) => layers.pack?.setState("verdict", st.progress),
      onLeave: () => layers.pack?.setState("verdict", 1) });
    ScrollTrigger.create({ trigger: verdict, start: "top 65%", once: true, onEnter: () => { ring.play(); countUp(ringCenter.querySelector(".ring-n"), sum.n); } });
    ScrollTrigger.create({ trigger: trust, start: "top 80%", onEnter: () => layers.pack?.setState("ambient"), onLeaveBack: () => layers.pack?.setState("verdict", 1) });
    revealOnScroll(legend.querySelectorAll(".legend-row"), { stagger: 0.08 });
    trust.querySelectorAll("[data-anim]").forEach((el) => ScrollTrigger.create({ trigger: el, start: "top 85%", once: true, onEnter: () => el.play?.() }));
    revealOnScroll(trust.querySelectorAll(".reason"));
    revealOnScroll(honest.querySelectorAll(".ledger li"), { stagger: 0.12 });
    [question, verdict, trust, whatif, honest, closing].forEach((sec) => { const t = sec.querySelector("h2"); if (t) { gsap.set(t, { opacity: 0 }); ScrollTrigger.create({ trigger: t, start: "top 85%", once: true, onEnter: () => revealLines(t) }); } });
  });

  return { unmount() { numeral.textContent = ""; layers.pack?.highlight(null); } };
}

function gateBar(pass, of) {
  const frac = of ? pass / of : 0;
  const fill = h("i", { class: "gate-fill", style: { transform: `scaleX(${frac})` } });
  const el = h("div", { class: "gate" }, h("div", { class: "gate-track" }, fill, h("b", { class: "gate-mark" })),
    h("div", { class: "gate-legend num" }, h("span", {}, `${num(pass)} pass`), h("span", { class: "muted" }, `${num(of - pass)} held back`)),
    h("p", { class: "label muted" }, "Screening, not certification"));
  el.play = () => (reduced.on ? null : gsap.fromTo(fill, { scaleX: 0 }, { scaleX: frac, duration: 1.6, ease: "expo.out" }));
  return el;
}

function projectionSketch(lo, c, hi) {
  const W = 420, H = 220;
  const x = (y) => 20 + (y / Math.max(hi || 1, 1)) * (W - 60);
  const curve = (yr) => `M20,30 C${x(yr) * 0.45},40 ${x(yr) * 0.8},120 ${x(yr)},190`;
  const band = s("path", { d: `${curve(lo || 0)} L${x(hi || 0)},190 C${x(hi || 0) * 0.8},120 ${x(hi || 0) * 0.45},40 20,30 Z`, fill: "#1F6B4F", "fill-opacity": 0.28 });
  const line = s("path", { d: curve(c || 0), fill: "none", stroke: "#F4EEE3", "stroke-width": 2 });
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart proj-sketch", role: "img", "aria-label": `median years to limit ${num(c, 1)}, band ${num(lo, 1)} to ${num(hi, 1)}` },
    s("line", { x1: 20, x2: W - 20, y1: 190, y2: 190, stroke: "#C98A97", "stroke-dasharray": "4 5" }), s("text", { x: W - 20, y: 210, "text-anchor": "end" }, "application limit"),
    band, line, s("text", { x: x(c || 0), y: 182, "text-anchor": "middle" }, `${num(c, 1)} yr`), s("text", { x: 20, y: 20 }, "shape: illustration · figures: fleet medians"));
  svg.play = () => { if (reduced.on) return null; const L = line.getTotalLength(); return gsap.timeline().fromTo(line, { strokeDasharray: L, strokeDashoffset: L }, { strokeDashoffset: 0, duration: 1.6, ease: "expo.out" }).from(band, { opacity: 0, duration: 1.2 }, 0.3); };
  return svg;
}

function econBars(sum) {
  const el = hbars([
    { label: "Routed by the engine", value: sum.net_value_routed_usd, display: usd(sum.net_value_routed_usd), tone: "good" },
    { label: "Recycle everything", value: sum.net_value_recycle_all_usd, display: usd(sum.net_value_recycle_all_usd), tone: "bad" },
  ]);
  const wrap = h("div", { class: "econ" }, el, placeholderTag());
  wrap.play = () => el.play();
  return wrap;
}

function trustBlock(p) {
  const reasons = (p.insight?.reasons || []).slice().sort((a, b) => (b.impact ?? 0) - (a.impact ?? 0)).slice(0, 3);
  const conf = p.insight?.confidence;
  const g = arcGauge(conf?.score_0_100 ?? null, { label: `Confidence · ${conf?.level || "—"}`, digits: 0, size: 240, color: "#0B3D2C", track: "rgba(46,7,19,.12)" });
  g.dataset.anim = "";
  const factors = hbars((conf?.factors || []).map((fc) => ({ label: fc.factor.replace(/_/g, " "), note: fc.detail, value: fc.points, display: `${num(fc.points, 1)} / ${fc.max}`, tone: "good" })), { max: Math.max(...(conf?.factors || []).map((fc) => fc.max), 1) });
  factors.dataset.anim = "";
  return h("div", { class: "grid12 trust-grid" },
    h("div", { class: "trust-head" }, h("a", { class: "pack-link", href: `#/pack/${encodeURIComponent(p.asset_id)}`, "data-cursor": "view" }, h("span", { class: "num" }, p.asset_id)),
      h("div", { class: "row-tags" }, dispChip(p.disposition), provTag(p.data_provenance), h("span", { class: "tag" }, p.chemistry || "—")),
      h("ol", { class: "reasons" }, reasons.map((r) => h("li", { class: `reason tone-${r.tone}` }, toneIcon(r.tone), h("div", {}, h("h4", {}, r.title), h("p", {}, r.text),
        h("p", { class: "cite" }, h("code", {}, r.metric || "—"), h("span", { class: "tag prov" }, r.provenance || "—")))))),
      h("p", { class: "muted small" }, "Confidence is a heuristic score, not a probability.")),
    h("div", { class: "trust-side" }, g, factors));
}

function tariffTrack(p, now) {
  const be = p.insight?.robustness?.break_even_tariff;
  const max = Math.max(0.2, (be ?? 0) * 2, (now ?? 0) * 2);
  const pos = (v) => `${(v / max) * 100}%`;
  const decisionEl = h("span", { class: "wi-decision" }, p.decision || "—");
  const valEl = h("span", { class: "num" }, now != null ? `${num(now, 3)} USD/kWh` : "—");
  const track = h("div", { class: "wi-track" },
    be != null ? h("b", { class: "wi-be", style: { left: pos(be) } }, h("span", { class: "label" }, `break-even ${num(be, 3)}`)) : null,
    now != null ? h("i", { class: "wi-now", style: { left: pos(now) } }) : null);
  const wrap = h("div", { class: "wi" },
    h("p", { class: "wi-intro" }, `${p.asset_id}: today the engine says `, decisionEl, ". The tariff is the price of a delivered kilowatt-hour in its second life."),
    track, h("div", { class: "wi-row" }, h("span", { class: "label" }, "Tariff (placeholder)"), valEl, placeholderTag()));
  if (be == null) wrap.append(h("p", { class: "muted" }, "— no tariff in the swept range flips this pack's decision."));
  if (!isLive()) { wrap.append(lockedPanel("Dragging the tariff and re-routing the pack")); return wrap; }
  const input = h("input", { type: "range", min: 0, max, step: max / 400, value: now ?? 0, "aria-label": "Tariff in USD per kWh" });
  const go = debounce(async (v) => {
    try {
      const r = await api.post("/api/whatif", { asset_id: p.asset_id, overrides: { tariff: v } });
      const next = r.rerouted ? r.decision : (r.decision || p.decision);
      if (next !== decisionEl.textContent) gsap.timeline().to(decisionEl, { opacity: 0, y: -10, duration: 0.3 }).add(() => { decisionEl.textContent = next; }).to(decisionEl, { opacity: 1, y: 0, duration: 0.6 });
    } catch (e) { decisionEl.textContent = `— ${e.message}`; }
  }, 150);
  input.addEventListener("input", () => { valEl.textContent = `${num(Number(input.value), 3)} USD/kWh`; go(Number(input.value)); });
  wrap.insertBefore(input, track.nextSibling);
  return wrap;
}
