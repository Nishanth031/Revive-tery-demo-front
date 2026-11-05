// #/fleet Command Center: sticky glass filters, 70 pack cards, Flip on filter changes, tilt + glare on hover.
import { h, debounce, headline } from "../lib/dom.js";
import { loadFleet, DISPOSITIONS } from "../lib/api.js";
import { filterPacks, chemistries } from "../lib/fleet.js";
import { num, usd, DISP_SHORT, date } from "../lib/format.js";
import { dispChip, badges } from "../ui/chip.js";
import { sohRing } from "../ui/ring.js";
import { reduced } from "../core/reduced.js";
import { revealLines } from "../core/transitions.js";

export async function mount(root, { route, ctx }) {
  const fleet = await loadFleet();
  const packs = fleet.packs;
  const p = route.params;
  const state = { q: p.get("q") || "", disposition: p.get("disposition") || "", chemistry: p.get("chemistry") || "", source: p.get("source") || "", sort: p.get("sort") || "asset_id", desc: p.get("desc") === "1" };

  const title = headline("h1", "The *Command* Center.", "");
  const head = h("section", { class: "wrap page-head", "data-rail": "" },
    h("p", { class: "label eyebrow" }, `Fleet · ${fleet.source === "live" ? "live API" : `snapshot ${date(fleet.generated)}`}`),
    title, h("p", {}, `${num(packs.length)} synthetic packs, each assessed through five stages. Filter, sort, then open a pack to read its reasons.`));

  // ---------------------------------------------------------------- filter bar
  const search = h("input", { class: "input search", type: "search", placeholder: "Search id, chemistry, application", value: state.q, "aria-label": "Search packs" });
  const dispBtns = ["", ...DISPOSITIONS].map((d) => h("button", { class: "chipbtn", "data-d": d, "aria-pressed": String(state.disposition === d) },
    d ? DISP_SHORT[d] : "All", h("span", { class: "n" }, "")));
  const chemBtns = ["", ...chemistries(packs)].map((c) => h("button", { "data-c": c, "aria-pressed": String(state.chemistry === c) }, c || "All"));
  const source = h("select", { class: "input", "aria-label": "Source", style: { width: "auto" } },
    [["", "All sources"], ["user", "User fleet"], ["platform", "Platform demo"], ["test", "Test cases"]].map(([v, l]) => h("option", { value: v, selected: state.source === v }, l)));
  const sort = h("select", { class: "input", "aria-label": "Sort by", style: { width: "auto" } },
    [["asset_id", "Sort: id"], ["net_value", "Sort: net value"], ["soh", "Sort: SOH"], ["confidence", "Sort: confidence"]].map(([v, l]) => h("option", { value: v, selected: state.sort === v }, l)));
  const dir = h("button", { class: "chipbtn", "aria-label": "Sort direction" }, state.desc ? "Desc" : "Asc");
  const count = h("span", { class: "label fleet-count num", "aria-live": "polite" });
  const bar = h("div", { class: "filterbar" }, h("div", { class: "wrap" }, search, h("div", { class: "btn-row", role: "group", "aria-label": "Disposition" }, dispBtns),
    h("div", { class: "seg", role: "group", "aria-label": "Chemistry" }, chemBtns), source, sort, dir, count));

  const grid = h("div", { class: "pack-grid wrap", "data-rail": "" });
  const empty = h("div", { class: "empty wrap", hidden: true }, h("h2", {}, "No pack matches."), h("p", { class: "muted" }, "Loosen a filter or clear the search."),
    h("button", { class: "btn", onclick: () => { Object.assign(state, { q: "", disposition: "", chemistry: "", source: "" }); search.value = ""; source.value = ""; apply(); } }, "Clear filters"));
  root.append(head, bar, grid, empty);

  // ---------------------------------------------------------------- cards (built once; filtering moves them)
  const cards = new Map();
  for (const pk of packs) cards.set(pk.asset_id, card(pk));

  function apply(animate = true) {
    const base = filterPacks(packs, { ...state, disposition: "" });
    dispBtns.forEach((b) => { const d = b.dataset.d; b.setAttribute("aria-pressed", String(state.disposition === d)); b.querySelector(".n").textContent = num(d ? base.filter((x) => x.disposition === d).length : base.length); });
    chemBtns.forEach((b) => b.setAttribute("aria-pressed", String(state.chemistry === b.dataset.c)));
    dir.textContent = state.desc ? "Desc" : "Asc";
    const list = filterPacks(packs, state);
    count.textContent = `${num(list.length)} of ${num(packs.length)}`;
    const flipState = animate && !reduced.on ? Flip.getState(grid.querySelectorAll(".pcard")) : null;
    const keep = new Set(list.map((x) => x.asset_id));
    for (const [id, el] of cards) if (!keep.has(id) && el.isConnected) el.remove();
    list.forEach((x) => grid.append(cards.get(x.asset_id)));
    empty.hidden = list.length > 0;
    if (flipState) Flip.from(flipState, { duration: 0.9, ease: "power4.inOut", absolute: true, stagger: 0.012, onEnter: (els) => gsap.fromTo(els, { opacity: 0, scale: 0.94 }, { opacity: 1, scale: 1, duration: 0.7 }), onLeave: (els) => gsap.to(els, { opacity: 0, duration: 0.3 }) });
    const qs = new URLSearchParams(Object.entries({ q: state.q, disposition: state.disposition, chemistry: state.chemistry, source: state.source, sort: state.sort === "asset_id" ? "" : state.sort, desc: state.desc ? "1" : "" }).filter(([, v]) => v));
    history.replaceState(null, "", `#/fleet${qs.toString() ? "?" + qs : ""}`);
    requestAnimationFrame(() => ScrollTrigger.refresh());
  }

  dispBtns.forEach((b) => b.addEventListener("click", () => { state.disposition = b.dataset.d; apply(); }));
  chemBtns.forEach((b) => b.addEventListener("click", () => { state.chemistry = b.dataset.c; apply(); }));
  source.addEventListener("change", () => { state.source = source.value; apply(); });
  sort.addEventListener("change", () => { state.sort = sort.value; apply(); });
  dir.addEventListener("click", () => { state.desc = !state.desc; apply(); });
  search.addEventListener("input", debounce(() => { state.q = search.value; apply(); }, 200));

  apply(false);
  ctx.add(() => {
    revealLines(title);
    gsap.from(head.querySelectorAll(".eyebrow, p:not(.eyebrow)"), { opacity: 0, y: 24, duration: 1.1, stagger: 0.08, delay: 0.2 });
    gsap.from(bar, { opacity: 0, y: -16, duration: 0.9, delay: 0.3 });
    if (!reduced.on) {
      const io = new IntersectionObserver((entries) => entries.forEach((e) => {
        if (!e.isIntersecting) return;
        io.unobserve(e.target);
        const ring = e.target.querySelector(".soh-ring");
        gsap.fromTo(e.target, { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 1.0, ease: "expo.out", delay: (Number(e.target.dataset.col) || 0) * 0.08 });
        if (ring) gsap.fromTo(ring._arc, { attr: { "stroke-dasharray": `0 ${ring._circ}` } }, { attr: { "stroke-dasharray": ring._full }, duration: 1.4, ease: "expo.out", delay: 0.2 });
      }), { rootMargin: "0px 0px -8% 0px" });
      [...grid.children].forEach((c, i) => { c.dataset.col = String(i % 4); gsap.set(c, { opacity: 0 }); io.observe(c); });
      ctx.add(() => () => io.disconnect());
    }
  });
}

function card(p) {
  const el = h("a", { class: "pcard", href: `#/pack/${encodeURIComponent(p.asset_id)}`, "data-cursor": "view", "data-flip-id": p.asset_id, "aria-label": `${p.asset_id}, ${DISP_SHORT[p.disposition] || p.disposition}` },
    h("div", { class: "pcard-top" }, h("div", {}, h("div", { class: "pcard-id" }, p.asset_id), h("div", { class: "pcard-sub" }, [p.chemistry, p.application].filter(Boolean).join(" · ") || "—")), sohRing(p.soh)),
    h("div", {}, dispChip(p.disposition)),
    h("div", { class: "pcard-meta" },
      h("span", {}, "Net value"), h("span", { class: "num" }, p.net_value != null ? usd(p.net_value) : "— not reached"),
      h("span", {}, "Confidence"), h("span", {}, p.insight?.confidence?.level || "—"),
      h("span", {}, "Best use"), h("span", {}, p.best_label || "—")),
    h("div", { class: "pcard-foot" }, badges(p)));
  if (!reduced.on && matchMedia("(pointer: fine)").matches) {
    const rx = gsap.quickTo(el, "rotationX", { duration: 0.6, ease: "expo.out" }), ry = gsap.quickTo(el, "rotationY", { duration: 0.6, ease: "expo.out" });
    gsap.set(el, { transformPerspective: 900 });
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      rx((0.5 - y) * 7); ry((x - 0.5) * 9);
      el.style.setProperty("--gx", `${x * 100}%`); el.style.setProperty("--gy", `${y * 100}%`);
    });
    el.addEventListener("pointerleave", () => { rx(0); ry(0); });
  }
  el.addEventListener("click", () => {
    const r = el.getBoundingClientRect();
    try { sessionStorage.setItem("revive.flip", JSON.stringify({ id: p.asset_id, x: r.left, y: r.top, w: r.width, h: r.height })); } catch { /* ignore */ }
  });
  return el;
}
