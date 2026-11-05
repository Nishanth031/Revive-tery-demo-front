// Demo mode (?demo=1 or D): a 60-second scripted scroll tour of the home film with captions. Esc stops.
// Also the "?" shortcuts card.
import { scrollTo, lenis } from "./smooth.js";
import { parseHash } from "./router.js";
import { reduced } from "./reduced.js";

const STEPS = [
  { at: "#beat-hero", hold: 6, text: "A retired EV pack arrives. One question: what should it become next?" },
  { at: "#beat-question", hold: 6, text: "A single health threshold is not enough. The engine reads the whole record." },
  { at: "#beat-stages", hold: 4, text: "Five stages, in order. A pack that fails a stage leaves the funnel." },
  { at: "#beat-stages", end: true, hold: 10, travel: 9, text: "Data quality, safety gate, state of health, projection, economics." },
  { at: "#beat-verdict", hold: 8, text: "The verdict for the whole fleet, read live from the engine's results." },
  { at: "#beat-trust", hold: 8, text: "One pack, its reasons, and how certain the engine is. Every number cites its source." },
  { at: "#beat-whatif", hold: 7, text: "What would change the decision: the tariff where it flips." },
  { at: "#beat-honest", hold: 7, text: "Honest by design: synthetic data, placeholder prices, screening only." },
];
let running = false, timers = [], caption = null;
export const demoRunning = () => running;

export function startDemo() {
  if (running) return;
  if (parseHash().name !== "") { location.hash = "#/"; setTimeout(startDemo, 2200); return; }
  running = true;
  caption = document.createElement("div");
  caption.className = "demo-caption"; caption.setAttribute("role", "status"); caption.setAttribute("aria-live", "polite");
  const p = document.createElement("p"); const l = document.createElement("div"); l.className = "label"; l.textContent = "Demo · Esc to stop";
  caption.append(p, l); document.body.append(caption);
  gsap.fromTo(caption, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.9 });
  let t = 0;
  STEPS.forEach((step) => {
    timers.push(setTimeout(() => {
      if (!running) return;
      const el = document.querySelector(step.at);
      if (el) {
        const y = el.getBoundingClientRect().top + scrollY + (step.end ? Math.max(0, el.offsetHeight - innerHeight) : 0);
        scrollTo(y, { duration: reduced.on ? 0 : (step.travel || 2.2), lock: false });
      }
      gsap.timeline().to(p, { opacity: 0, y: -8, duration: 0.3 }).add(() => { p.textContent = step.text; }).to(p, { opacity: 1, y: 0, duration: 0.8, ease: "expo.out" });
    }, t * 1000));
    t += step.hold;
  });
  timers.push(setTimeout(stopDemo, t * 1000));
}

export function stopDemo() {
  running = false;
  timers.forEach(clearTimeout); timers = [];
  lenis?.stop(); lenis?.start();
  if (caption) { const c = caption; caption = null; gsap.to(c, { opacity: 0, duration: 0.4, onComplete: () => c.remove() }); }
}

export function shortcutsCard() {
  document.querySelector(".overlay-card")?.remove();
  const card = document.createElement("div");
  card.className = "overlay-card"; card.setAttribute("role", "dialog"); card.setAttribute("aria-label", "Keyboard shortcuts");
  const h = document.createElement("h3"); h.textContent = "Shortcuts";
  const rows = [["1 – 6", "Home, Command Center, Plan, Analyze, Bench, Evidence"], ["D", "Start or stop the 60-second demo"], ["?", "This card"], ["Esc", "Close / stop the demo"]];
  const dl = document.createElement("dl"); dl.className = "kv";
  rows.forEach(([k, v]) => { const dt = document.createElement("dt"); const kb = document.createElement("kbd"); kb.textContent = k; dt.append(kb); const dd = document.createElement("dd"); dd.textContent = v; dl.append(dt, dd); });
  const close = document.createElement("button"); close.className = "btn"; close.textContent = "Close"; close.style.marginTop = "24px";
  close.addEventListener("click", () => card.remove());
  card.append(h, dl, close); document.body.append(card); close.focus();
  gsap.fromTo(card, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.6 });
}
