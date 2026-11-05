// Guided demo: a bottom bar with Play/Pause/Next/Back/Exit, progress dots and keyboard control (arrows, space, Esc).
// Steps navigate by hash (with query parameters), so a reload lands on the same view. Packs are picked by their
// real disposition from the fleet; a missing kind of pack is skipped with an honest caption, never an error.
import { h, clear, icon } from "./dom.js";
import { loadFleet } from "../lib/fleet.js";

const KEY = "rt-tour-step";
let bar = null, timer = null, playing = false, steps = [], i = 0;

async function buildSteps(app) {
  let packs = [];
  try { packs = (await loadFleet(app)).packs || []; } catch { packs = []; }
  const first = (pred) => packs.find(pred);
  const repurpose = first((p) => p.disposition === "REPURPOSE" && p.insight?.robustness?.break_even_tariff);
  const reuse = first((p) => p.disposition === "REUSE");
  const reject = first((p) => String(p.decision).startsWith("Reject"));
  const bad = first((p) => p.test_case && p.disposition === "NO_DECISION");
  const s = [["#/command", "<b>Command Center.</b> Every pack in the fleet through the full engine: the split, where packs leave the pipeline, and the engine status."]];
  if (repurpose) {
    s.push([`#/pack?id=${repurpose.asset_id}`, `<b>A Repurpose pack (${repurpose.asset_id}).</b> Why the engine chose it, how certain it is, and the projection with its uncertainty bands.`]);
    const be = repurpose.insight.robustness.break_even_tariff;
    s.push([`#/pack?id=${repurpose.asset_id}&tariff=${Math.max(0, be - 0.02).toFixed(3)}`, `<b>What-if.</b> The tariff is set just below the break-even (${be.toFixed(3)} USD/kWh): the decision flips. Drag the slider back above it to flip it again.`]);
  }
  s.push(reuse ? [`#/pack?id=${reuse.asset_id}`, `<b>A Reuse pack (${reuse.asset_id}).</b> A second life in a vehicle.`]
    : ["#/command?disp=REPURPOSE", "<b>No Reuse pack in this fleet.</b> With today's valuation stationary storage beats reuse in a vehicle for every pack; the banner on the Command Center gives the numbers."]);
  if (reject) s.push([`#/pack?id=${reject.asset_id}`, `<b>A safety-rejected pack (${reject.asset_id}).</b> The gate overrules everything else: no second-life suggestion.`]);
  if (bad) s.push([`#/live?pack=${bad.asset_id}`, `<b>A bad-data pack (${bad.asset_id}, test case).</b> Data quality stops the engine; the later stages stay grey with the reason.`]);
  s.push(["#/command", "<b>Fleet plan.</b> Scroll down: packs are assigned to applications under demand limits, with the value gap against greedy routing."]);
  s.push(["#/hardware", "<b>Firmware & hardware.</b> The monitor-only ESP32 bench: circuit, resistor calculator and the Wokwi project."]);
  s.push(["#/bench?preset=overvoltage", "<b>Circuit Studio.</b> The simulated ESP32 with an over-voltage fault injected: watch the readings and the alerts."]);
  s.push(["#/evidence", "<b>Model evidence.</b> Known limits: synthetic fleet, placeholder prices, an LFP-trained state model (91.5 % coverage vs 90 % nominal), monitor-only hardware."]);
  return s;
}

function paint() {
  if (!bar) return;
  const [, cap] = steps[i];
  clear(bar).append(
    h("div", {}, h("div", { class: "cap", html: cap }), h("div", { class: "dots" }, steps.map((_, k) => h("i", { class: k === i ? "on" : "" })))),
    h("div", { class: "row" },
      h("button", { class: "btn small", type: "button", "aria-label": "Back", onclick: back }, icon("prev", 14)),
      h("button", { class: "btn small", type: "button", "aria-label": playing ? "Pause" : "Play", onclick: toggle }, icon(playing ? "pause" : "play", 14)),
      h("button", { class: "btn small", type: "button", "aria-label": "Next", onclick: next }, icon("next", 14)),
      h("button", { class: "btn small", type: "button", "aria-label": "Exit", onclick: stopTour }, icon("x", 14))));
}
function go(k) {
  i = Math.max(0, Math.min(steps.length - 1, k));
  try { sessionStorage.setItem(KEY, String(i)); } catch { /* ignore */ }
  location.hash = steps[i][0];
  paint();
}
const next = () => (i < steps.length - 1 ? go(i + 1) : stopTour());
const back = () => go(i - 1);
function toggle() {
  playing = !playing;
  clearInterval(timer);
  if (playing) timer = setInterval(() => (i < steps.length - 1 ? go(i + 1) : toggle()), 15000);
  paint();
}
function onKey(e) {
  if (!bar || ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
  if (e.key === "ArrowRight") next(); else if (e.key === "ArrowLeft") back();
  else if (e.key === " ") { e.preventDefault(); toggle(); } else if (e.key === "Escape") stopTour();
}

export async function startTour(app) {
  if (bar) return;
  steps = await buildSteps(app);
  bar = h("div", { class: "tour", role: "region", "aria-label": "Guided demo" });
  document.body.append(bar);
  document.addEventListener("keydown", onKey);
  let saved = 0;
  try { saved = Number(sessionStorage.getItem(KEY)) || 0; } catch { /* ignore */ }
  i = Math.min(saved, steps.length - 1);
  paint();
  if (i > 0) go(i);
}
export function stopTour() {
  clearInterval(timer); playing = false;
  document.removeEventListener("keydown", onKey);
  if (bar) bar.remove();
  bar = null;
  try { sessionStorage.removeItem(KEY); } catch { /* ignore */ }
}
