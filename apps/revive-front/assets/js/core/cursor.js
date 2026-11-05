// Custom cursor (desktop, fine pointer, motion allowed): dot + ring; ring grows with "View" over pack cards.
// Magnetic pull on [data-magnetic]; button fill sweeps in from the side the cursor entered.
import { reduced } from "./reduced.js";

export function initCursor() {
  const fine = matchMedia("(pointer: fine) and (min-width: 761px)").matches;
  sweepFromCursorSide();
  if (!fine || reduced.on) return;
  document.documentElement.classList.add("has-cursor");
  const dot = Object.assign(document.createElement("div"), { className: "cursor-dot" });
  const ring = Object.assign(document.createElement("div"), { className: "cursor-ring" });
  ring.append(Object.assign(document.createElement("span"), { textContent: "View" }));
  document.body.append(dot, ring);
  gsap.set([dot, ring], { opacity: 0 });
  addEventListener("pointermove", () => gsap.to([dot, ring], { opacity: 1, duration: 0.4 }), { once: true });
  const dx = gsap.quickTo(dot, "x", { duration: 0.12, ease: "power3.out" }), dy = gsap.quickTo(dot, "y", { duration: 0.12, ease: "power3.out" });
  const rx = gsap.quickTo(ring, "x", { duration: 0.55, ease: "expo.out" }), ry = gsap.quickTo(ring, "y", { duration: 0.55, ease: "expo.out" });
  addEventListener("pointermove", (e) => { dx(e.clientX); dy(e.clientY); rx(e.clientX); ry(e.clientY); }, { passive: true });
  document.addEventListener("pointerover", (e) => { ring.classList.toggle("view", !!e.target.closest?.("[data-cursor='view']")); });
  document.addEventListener("pointerleave", () => gsap.to([dot, ring], { opacity: 0, duration: 0.3 }));
  document.addEventListener("pointerenter", () => gsap.to([dot, ring], { opacity: 1, duration: 0.3 }));
}

/** call after a page mounts: magnetic pull on primary buttons */
export function magnetize(root = document) {
  if (reduced.on || !matchMedia("(pointer: fine)").matches) return;
  root.querySelectorAll("[data-magnetic]").forEach((el) => {
    if (el._mag) return; el._mag = true;
    const xTo = gsap.quickTo(el, "x", { duration: 0.6, ease: "expo.out" }), yTo = gsap.quickTo(el, "y", { duration: 0.6, ease: "expo.out" });
    el.addEventListener("pointermove", (e) => { const r = el.getBoundingClientRect(); xTo((e.clientX - r.left - r.width / 2) * 0.28); yTo((e.clientY - r.top - r.height / 2) * 0.35); });
    el.addEventListener("pointerleave", () => { xTo(0); yTo(0); });
  });
}

function sweepFromCursorSide() {
  document.addEventListener("pointerover", (e) => {
    const b = e.target.closest?.(".btn");
    if (!b || b.contains(e.relatedTarget)) return;
    const r = b.getBoundingClientRect();
    b.style.setProperty("--from", e.clientX < r.left + r.width / 2 ? "left" : "right");
  });
}
