// Boot: smoothness engine, layers L0/L1 (persistent across routes), chrome, loader, router, shortcuts, demo mode.
import { initSmooth } from "./core/smooth.js";
import { initCursor } from "./core/cursor.js";
import { runLoader } from "./core/transitions.js";
import { startRouter, onRoute, go, ROUTE_KEYS } from "./core/router.js";
import { sampleFrames, fpsMeter } from "./core/perf.js";
import { initBackground } from "./gl/background.js";
import { probe, startProbing, onMode, health, loadSummary, loadMeta } from "./lib/api.js";
import { date } from "./lib/format.js";
import { startDemo, stopDemo, demoRunning, shortcutsCard } from "./core/demo.js";

export const layers = { bg: null, pack: null };

/** four funnel drop shares (data quality, gate, state, projection+economics), from the real summary */
export function funnelWaves(summary) {
  const f = summary?.funnel;
  if (!f || !f.total) return null;
  const seq = [f.total, f.data_quality_ready, f.gate_pass, f.state_ok, f.second_life_chosen];
  return seq.slice(1).map((v, i) => Math.max(0, (seq[i] - v) / f.total));
}

async function paintChip() {
  const chip = document.getElementById("status-chip");
  const txt = chip.querySelector(".txt");
  const live = health();
  let text;
  if (live) text = `Live · API v${live.api_version ?? "—"} · ML engine v${live.ml_engine_version ?? "—"}`;
  else { let gen = null; try { gen = (await loadMeta()).db_generated_utc; } catch { /* snapshot file missing */ } text = `Snapshot · generated ${date(gen)}`; }
  const flip = chip.dataset.mode !== (live ? "live" : "snapshot");
  chip.dataset.mode = live ? "live" : "snapshot";
  if (flip && window.gsap) {
    gsap.timeline().to(txt, { yPercent: -100, opacity: 0, duration: 0.35, ease: "power4.in" })
      .add(() => { txt.textContent = text; }).fromTo(txt, { yPercent: 100, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.6, ease: "expo.out" });
  } else txt.textContent = text;
  document.querySelectorAll("[data-status-mirror]").forEach((el) => { el.textContent = text; });
}

function menu() {
  const btn = document.getElementById("menu-btn"), links = document.getElementById("navlinks");
  btn.addEventListener("click", () => { const open = links.classList.toggle("open"); btn.setAttribute("aria-expanded", String(open)); });
  links.addEventListener("click", (e) => { if (e.target.closest("a")) { links.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); } });
}

function keyboard() {
  addEventListener("keydown", (e) => {
    if (e.target.closest?.("input, textarea, select, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "Escape") { if (demoRunning()) stopDemo(); document.querySelector(".overlay-card")?.remove(); return; }
    if (e.key === "?") { shortcutsCard(); return; }
    if (e.key === "d" || e.key === "D") { demoRunning() ? stopDemo() : startDemo(); return; }
    const n = Number(e.key);
    if (n >= 1 && n <= 6) go(`#/${ROUTE_KEYS[n - 1]}`);
  });
}

async function boot() {
  if (!window.gsap || !window.ScrollTrigger) throw new Error("GSAP did not load (assets/vendor/gsap).");
  initSmooth();
  initCursor();
  menu();
  keyboard();
  layers.bg = initBackground();
  const ready = (async () => {
    await probe();
    try {
      const { initPack } = await import("./gl/pack.js");
      layers.pack = initPack();
    } catch (e) { console.warn("[revive-front] 3D pack unavailable:", e.message); }
    try {
      const sum = await loadSummary();
      layers.pack?.setData({ waves: funnelWaves(sum), by: sum.by_disposition, n: sum.n });
    } catch (e) { console.warn("[revive-front] summary unavailable:", e.message); }
    await paintChip();
    try { await Promise.all(["300 1em Cormorant", "italic 300 1em Cormorant", "400 1em Manrope"].map((f) => document.fonts.load(f))); } catch { /* fonts optional */ }
    await document.fonts?.ready;
  })();
  onRoute("beforeMount", (scene) => { if (scene !== "home") layers.pack?.setState("ambient"); else layers.pack?.setState("hero"); if (scene === "studio") document.getElementById("l1").style.opacity = "0"; layers.bg?.setTone(scene === "home" ? 0 : 0.35); });
  onMode(async () => {
    await paintChip();
    try { const sum = await loadSummary(); layers.pack?.setData({ waves: funnelWaves(sum), by: sum.by_disposition, n: sum.n }); } catch { /* keep previous */ }
    window.dispatchEvent(new CustomEvent("revive:mode"));
  });
  startProbing();
  await runLoader(ready);
  await startRouter();
  sampleFrames();
  fpsMeter();
  document.fonts?.ready.then(() => ScrollTrigger.refresh());
  if (/[?&]demo=1\b/.test(location.search) || /[?&]demo=1\b/.test(location.hash)) setTimeout(startDemo, 600);
}

addEventListener("DOMContentLoaded", () => boot().catch((e) => {
  console.error(e);
  const l = document.getElementById("loader"); if (l) l.remove();
  const m = document.getElementById("l3");
  const p = document.createElement("p"); p.style.padding = "140px 24px"; p.textContent = `REVIVE·TERY could not start: ${e.message}`;
  m.append(p);
}));
