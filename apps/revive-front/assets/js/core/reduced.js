// prefers-reduced-motion: one switch read everywhere. Count-ups jump, no Lenis, no pinning, no parallax, no cursor.
const mq = matchMedia("(prefers-reduced-motion: reduce)");
export const reduced = { get on() { return mq.matches; } };
export function onReducedChange(fn) { mq.addEventListener?.("change", () => fn(mq.matches)); }

/** count a number up in place (tabular numerals), or set it directly when motion is reduced */
export function countUp(el, to, { format = (v) => Math.round(v).toLocaleString("en-US"), duration = 1.6, from = 0, delay = 0 } = {}) {
  if (to === null || to === undefined || !Number.isFinite(Number(to))) { el.textContent = "—"; return null; }
  if (reduced.on || !window.gsap) { el.textContent = format(Number(to)); return null; }
  const o = { v: from };
  el.textContent = format(from);
  return gsap.to(o, { v: Number(to), duration, delay, ease: "expo.out", onUpdate: () => { el.textContent = format(o.v); } });
}
