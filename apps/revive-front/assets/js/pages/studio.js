// Engine pages: ESP32 circuit (simulation + live test), hardware, BMS engine, live assessment, ML engine, DQ lab, history.
// The engines run unchanged in the embedded studio (studio/). This page owns the look: it injects the REVIVE·TERY skin
// into the studio document, hides the studio chrome, and grows the frame to its content so the page scrolls as one.
import { h, headline } from "../lib/dom.js";
import { revealLines } from "../core/transitions.js";

export const STUDIO = {
  circuit: { nav: "ESP32 circuit", t: "The ESP32 *bench*, simulated and live.", hash: "bench", sub: "ESP32 + INA219 + DS18B20 on a 1-cell bench. Run the simulator, or connect the real board for a live test. Monitor-only, low voltage, never an EV pack." },
  hardware: { nav: "Hardware", t: "Firmware & *hardware*.", hash: "hardware", sub: "The realistic circuit, the test-load calculator, the Wokwi project and firmware v1.1." },
  bms: { nav: "BMS engine", t: "The BMS engine, *live*.", hash: "relife", sub: "Cell readings in, protections and alerts out: how the BMS engine judges every line." },
  live: { nav: "Live test", t: "Live *assessment*.", hash: "live", sub: "Stream a pack through the engine and watch each stage decide, line by line." },
  engine: { nav: "ML engine", t: "The ML *engine*.", hash: "overview", sub: "Every stage the ML runs, its version, and what each stage is allowed to claim." },
  dqlab: { nav: "Data quality", t: "Data quality *lab*.", hash: "dqlab", sub: "The 14 checks, the physics projection and the economics, tab by tab." },
  history: { nav: "History", t: "Assessment *history*.", hash: "history", sub: "Every assessment and ML suggestion stored so far." },
};
const SKIN = new URL("../../css/studio-skin.css", import.meta.url).href;

export async function mount(root, { route, ctx }) {
  const cfg = STUDIO[route.name] || STUDIO.engine;
  const title = headline("h1", cfg.t, "");
  const frame = h("iframe", { src: `studio/index.html#/${cfg.hash}`, title: cfg.nav, class: "studio-frame", scrolling: "no" });
  const veil = h("div", { class: "studio-veil skeleton" });
  const tabs = h("nav", { class: "studio-tabs", "aria-label": "Engine pages" },
    Object.entries(STUDIO).map(([k, v]) => h("a", { href: `#/${k}`, "aria-current": k === route.name ? "page" : null }, v.nav)));
  root.append(
    h("section", { class: "wrap page-head", "data-rail": "" }, h("p", { class: "label eyebrow" }, "The engines"), title, h("p", {}, cfg.sub)),
    h("div", { class: "studio-bar" }, h("div", { class: "wrap" }, tabs)),
    h("section", { class: "wrap studio-host", "data-rail": "" }, veil, frame));

  let ro = null, mo = null;
  frame.addEventListener("load", () => {
    const doc = frame.contentDocument;
    if (!doc) return;
    doc.documentElement.classList.add("rf-embed");
    doc.documentElement.dataset.theme = "dark";
    if (!doc.getElementById("rf-skin")) doc.head.append(Object.assign(doc.createElement("link"), { id: "rf-skin", rel: "stylesheet", href: SKIN }));
    const fit = () => { const hgt = Math.max(doc.documentElement.scrollHeight, doc.body?.scrollHeight || 0, 480); if (Math.abs(frame.offsetHeight - hgt) > 2) { frame.style.height = `${hgt}px`; ScrollTrigger.refresh(); } };
    ro = new ResizeObserver(fit); ro.observe(doc.body);
    mo = new MutationObserver(fit); mo.observe(doc.body, { childList: true, subtree: true });
    // links inside the studio that point at another engine page stay in the shell
    frame.contentWindow.addEventListener("hashchange", () => { const hsh = frame.contentWindow.location.hash.replace(/^#\/?/, "").split("?")[0]; const k = Object.keys(STUDIO).find((x) => STUDIO[x].hash === hsh); if (k && k !== route.name) history.replaceState(null, "", `#/${k}`); fit(); });
    fit();
    gsap.to(veil, { opacity: 0, duration: 0.6, onComplete: () => veil.remove() });
    gsap.fromTo(frame, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 1.1, ease: "expo.out" });
  });
  ctx.add(() => { revealLines(title); gsap.from(tabs.children, { opacity: 0, y: 12, duration: 0.8, stagger: 0.05, delay: 0.2 }); });
  return { unmount() { ro?.disconnect(); mo?.disconnect(); } };
}
