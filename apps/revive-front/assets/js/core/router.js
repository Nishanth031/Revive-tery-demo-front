// Hash router: #/, #/fleet, #/pack/<id>, #/plan, #/analyze, #/bench, #/evidence.
// Each page exports mount(root, ctx) -> { unmount?() } and builds its animations inside gsap.context().
import { curtain } from "./transitions.js";
import { scrollTop, parallaxDecor, railTicks } from "./smooth.js";
import { magnetize } from "./cursor.js";

const PAGES = {
  "": { title: "REVIVE·TERY", load: () => import("../pages/home.js"), scene: "home" },
  fleet: { title: "Command Center · REVIVE·TERY", load: () => import("../pages/fleet.js"), scene: "ambient" },
  pack: { title: "Pack · REVIVE·TERY", load: () => import("../pages/pack.js"), scene: "ambient" },
  plan: { title: "Fleet plan · REVIVE·TERY", load: () => import("../pages/plan.js"), scene: "ambient" },
  analyze: { title: "Analyze · REVIVE·TERY", load: () => import("../pages/analyze.js"), scene: "ambient" },
  bench: { title: "Bench · REVIVE·TERY", load: () => import("../pages/bench.js"), scene: "ambient" },
  circuit: { title: "ESP32 circuit · REVIVE·TERY", load: () => import("../pages/studio.js"), scene: "studio" },
  hardware: { title: "Hardware · REVIVE·TERY", load: () => import("../pages/studio.js"), scene: "studio" },
  bms: { title: "BMS engine · REVIVE·TERY", load: () => import("../pages/studio.js"), scene: "studio" },
  live: { title: "Live assessment · REVIVE·TERY", load: () => import("../pages/studio.js"), scene: "studio" },
  engine: { title: "ML engine · REVIVE·TERY", load: () => import("../pages/studio.js"), scene: "studio" },
  dqlab: { title: "DQ lab · REVIVE·TERY", load: () => import("../pages/studio.js"), scene: "studio" },
  history: { title: "History · REVIVE·TERY", load: () => import("../pages/studio.js"), scene: "studio" },
  evidence: { title: "Evidence · REVIVE·TERY", load: () => import("../pages/evidence.js"), scene: "ambient" },
};
export const ROUTE_KEYS = ["", "fleet", "plan", "analyze", "bench", "evidence"];

export function parseHash(hash = location.hash) {
  const raw = hash.replace(/^#\/?/, "");
  const [path, qs = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  return { name: parts[0] || "", arg: parts[1] || null, params: new URLSearchParams(qs) };
}

let current = null, busy = false, pending = false, first = true;
const hooks = { beforeMount: [], afterMount: [] };
export const onRoute = (when, fn) => hooks[when].push(fn);
export const go = (hash) => { if (location.hash === hash) render(); else location.hash = hash; };

export async function render() {
  if (busy) { pending = true; return; }
  busy = true;
  const route = parseHash();
  const def = PAGES[route.name] || PAGES[""];
  const root = document.getElementById("l3");
  const swap = async () => {
    if (current?.unmount) { try { current.unmount(); } catch (e) { console.error(e); } }
    current?.ctx?.revert();
    ScrollTrigger.getAll().forEach((t) => t.kill());
    while (root.firstChild) root.firstChild.remove();
    scrollTop();
    document.title = def.title;
    document.querySelectorAll(".navlinks a").forEach((a) => {
      const n = parseHash(a.getAttribute("href")).name;
      const on = n === route.name || (route.name === "pack" && n === "fleet") || (a.dataset.group || "").split(" ").includes(route.name);
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    hooks.beforeMount.forEach((fn) => fn(def.scene, route));
    try {
      const mod = await def.load();
      const ctx = gsap.context(() => {});
      const page = (await mod.mount(root, { route, ctx })) || {};
      current = { ...page, ctx };
    } catch (e) {
      console.error(e);
      const d = document.createElement("div");
      d.className = "wrap page-head";
      const h = document.createElement("h1"); h.textContent = "This view could not be drawn.";
      const p = document.createElement("p"); p.textContent = String(e?.message || e);
      d.append(h, p); root.append(d);
      current = null;
    }
    ctxParallax();
    magnetize(root);
  };
  let flip = null;
  try { flip = route.name === "pack" ? JSON.parse(sessionStorage.getItem("revive.flip") || "null") : null; } catch { flip = null; }
  if (first) { first = false; await swap(); }
  else if (flip && flip.id === route.arg) { await gsap.to(root, { opacity: 0, duration: 0.25 }); await swap(); gsap.to(root, { opacity: 1, duration: 0.4 }); }
  else await curtain(swap);
  requestAnimationFrame(() => { ScrollTrigger.refresh(); railTicks(); hooks.afterMount.forEach((fn) => fn(def.scene, route)); });
  busy = false;
  if (pending) { pending = false; render(); }
}

function ctxParallax() { parallaxDecor(); }

export function startRouter() {
  addEventListener("hashchange", render);
  return render();
}
