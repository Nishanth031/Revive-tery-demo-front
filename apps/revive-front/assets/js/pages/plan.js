// #/plan Fleet plan: a pack limit per application; POST /api/fleet/plan assigns packs to bins (live only).
import { h, headline, debounce } from "../lib/dom.js";
import { loadFleet, isLive, api, snapshotFile, SECOND } from "../lib/api.js";
import { applicationKeys, appLabels, appLabel } from "../lib/fleet.js";
import { num, usd } from "../lib/format.js";
import { placeholderTag, lockedPanel, errorMsg } from "../ui/chip.js";
import { countUp, reduced } from "../core/reduced.js";
import { revealLines } from "../core/transitions.js";

export async function mount(root, { ctx }) {
  const [fleet, configs] = await Promise.all([loadFleet(), snapshotFile("configs.json").catch(() => null)]);
  const packs = fleet.packs;
  const keys = applicationKeys(packs);
  const labels = { ...appLabels(packs), ...Object.fromEntries(Object.entries(configs?.workloads?.workloads || {}).map(([k, v]) => [k, v.label])) };
  const eligible = packs.filter((p) => SECOND.includes(p.disposition)).length;
  const title = headline("h1", "Plan the *fleet*, not the pack.", "");
  root.append(h("section", { class: "wrap page-head", "data-rail": "" }, h("p", { class: "label eyebrow" }, "Fleet plan"), title,
    h("p", {}, `Each site can only take so many packs. Set a limit per application; the engine assigns the ${num(eligible)} second-life candidates to maximise total value (greedy, then 2-opt), and shows what that is worth against choosing pack by pack.`)));
  const grid = h("div", { class: "wrap plan-grid", "data-rail": "" });
  root.append(grid);

  const limits = Object.fromEntries(keys.map((k) => [k, Math.max(1, Math.ceil(eligible / Math.max(1, keys.length)))]));
  let run = () => {};
  const ctrl = h("div", { class: "plan-ctrl panel" }, h("span", { class: "label" }, "Pack limit per application"));
  keys.forEach((k) => {
    const out = h("span", { class: "num" }, String(limits[k]));
    const input = h("input", { type: "range", min: 0, max: Math.max(1, eligible), step: 1, value: limits[k], "aria-label": `${appLabel(labels, k)} pack limit` });
    input.addEventListener("input", () => { limits[k] = Number(input.value); out.textContent = input.value; run(); });
    ctrl.append(h("div", { class: "field" }, h("label", { class: "label" }, appLabel(labels, k), " · ", out), input));
  });
  ctrl.append(placeholderTag());
  const right = h("div", {});
  grid.append(ctrl, right);

  if (!isLive()) {
    right.append(lockedPanel("The fleet assignment (it solves the plan on the server)"),
      h("p", { class: "muted", style: { marginTop: "24px" } }, `In snapshot mode the limits above are inert. The ${num(eligible)} candidates are those the engine routed to reuse or repurpose.`));
    ctrl.querySelectorAll("input").forEach((i) => { i.disabled = true; });
  } else {
    const kTotal = h("span", { class: "v num" }, "—"), kGreedy = h("span", { class: "v num" }, "—"), kGap = h("span", { class: "v num" }, "—");
    const algo = h("p", { class: "muted small" });
    const bins = h("div", { class: "bins" });
    const err = h("div", {});
    right.append(h("div", { class: "plan-kpis" }, h("div", {}, h("span", { class: "label muted" }, "Total value"), kTotal),
      h("div", {}, h("span", { class: "label muted" }, "Greedy value"), kGreedy), h("div", {}, h("span", { class: "label muted" }, "Gain vs pack-by-pack"), kGap)), algo, err, bins);
    const binEls = {};
    [...keys, "_recycle"].forEach((k) => {
      const dots = h("div", { class: "bin-dots" });
      const meta = h("p", { class: "muted small num" }, "—");
      binEls[k] = { dots, meta };
      bins.append(h("div", { class: "bin" }, h("h3", {}, k === "_recycle" ? "Not placed (recycle)" : appLabel(labels, k)), meta, dots));
    });
    const dotEls = new Map();
    packs.filter((p) => SECOND.includes(p.disposition)).forEach((p) => dotEls.set(p.asset_id, h("a", { class: "dotp", href: `#/pack/${encodeURIComponent(p.asset_id)}`, title: p.asset_id, "aria-label": p.asset_id })));
    run = debounce(async () => {
      try {
        const lim = Object.fromEntries(Object.entries(limits).map(([k, v]) => [k, { packs: v }]));
        const r = await api.post("/api/fleet/plan", { limits: lim });
        err.replaceChildren();
        const state = reduced.on ? null : Flip.getState([...dotEls.values()]);
        const placed = new Set();
        (r.plan || []).forEach(({ asset_id, application }) => { const d = dotEls.get(asset_id); const bin = binEls[application]; if (d && bin) { d.classList.remove("recycle"); bin.dots.append(d); placed.add(asset_id); } });
        for (const [id, d] of dotEls) if (!placed.has(id)) { d.classList.add("recycle"); binEls._recycle.dots.append(d); }
        Object.entries(r.by_application || {}).forEach(([k, v]) => { if (binEls[k]) binEls[k].meta.textContent = `${num(v.packs)} packs · ${num(v.kwh, 1)} kWh · limit ${v.limit?.packs ?? v.limit ?? "—"}`; });
        binEls._recycle.meta.textContent = `${num(dotEls.size - placed.size)} candidates not placed`;
        if (state) Flip.from(state, { duration: 1.0, ease: "power4.inOut", stagger: 0.008 });
        countUp(kTotal, r.total_value, { format: (v) => usd(v), duration: 1 });
        countUp(kGreedy, r.greedy_value, { format: (v) => usd(v), duration: 1 });
        countUp(kGap, r.value_gap_vs_per_pack_greedy, { format: (v) => usd(v), duration: 1 });
        algo.textContent = `${r.algorithm || "—"} · ${r.provenance || "modelled"}`;
      } catch (e) { err.replaceChildren(errorMsg(e, "The plan could not be solved.")); }
    }, 250);
    run();
  }
  ctx.add(() => { revealLines(title); gsap.from(grid, { opacity: 0, y: 40, duration: 1.1, delay: 0.2 }); });
  return {};
}
