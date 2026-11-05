// L6: the loader (cells assemble while a serif counter runs 0 -> 100) and the route curtain (maroon/green split wipe).
import { reduced } from "./reduced.js";

export function runLoader(ready) {
  const loader = document.getElementById("loader");
  const count = document.getElementById("loader-count");
  const cells = loader.querySelectorAll(".cells i");
  if (reduced.on || document.hidden) {
    return ready.then(() => { loader.remove(); });
  }
  const o = { v: 0 };
  const tl = gsap.timeline();
  tl.to(cells, { opacity: 1, y: 0, duration: 0.9, stagger: 0.08, ease: "expo.out" }, 0)
    .to(o, { v: 82, duration: 1.4, ease: "power2.out", onUpdate: () => { count.textContent = Math.round(o.v); } }, 0);
  const minTime = new Promise((r) => setTimeout(r, 1300));
  return Promise.all([ready, minTime]).then(() => new Promise((resolve) => {
    tl.progress(1);
    if (document.hidden) { loader.remove(); resolve(); return; }   // a background tab gets no animation frames
    setTimeout(() => { if (loader.isConnected) { loader.remove(); resolve(); } }, 4000);
    gsap.timeline({ onComplete: resolve })
      .to(o, { v: 100, duration: 0.6, ease: "power2.out", onUpdate: () => { count.textContent = Math.round(o.v); } })
      .to(cells, { borderColor: "#F4EEE3", backgroundColor: "rgba(31,107,79,.6)", duration: 0.4, stagger: 0.03 }, "<")
      .to(loader.firstElementChild, { y: -30, opacity: 0, duration: 0.6, ease: "power4.in" })
      .to(loader, { clipPath: "inset(0 0 100% 0)", duration: 1.0, ease: "power4.inOut" }, "-=0.15")
      .add(() => loader.remove());
  }));
}

/** cover the screen, run fn (swap the page), uncover */
export async function curtain(fn) {
  const c = document.getElementById("curtain");
  const [a, b] = c.children;
  if (document.hidden) { await fn(); return; }
  if (reduced.on) {
    await gsap.to("#l3", { opacity: 0, duration: 0.2 });
    await fn();
    await gsap.to("#l3", { opacity: 1, duration: 0.3 });
    return;
  }
  c.style.pointerEvents = "auto";
  gsap.set(a, { transformOrigin: "top" }); gsap.set(b, { transformOrigin: "bottom" });
  await gsap.to([a, b], { scaleY: 1, duration: 0.55, ease: "power4.inOut", stagger: 0.06 });
  await fn();
  gsap.set(a, { transformOrigin: "bottom" }); gsap.set(b, { transformOrigin: "top" });
  await gsap.to([a, b], { scaleY: 0, duration: 0.8, ease: "power4.inOut", stagger: 0.06 });
  c.style.pointerEvents = "none";
}

/** reveal a headline through SplitText line masks */
export function revealLines(el, { delay = 0, duration = 1.3 } = {}) {
  if (!el) return null;
  if (reduced.on) { gsap.set(el, { opacity: 1 }); return null; }
  const split = new SplitText(el, { type: "lines", mask: "lines", linesClass: "split-line" });
  gsap.set(el, { opacity: 1 });
  return gsap.from(split.lines, { yPercent: 110, duration, ease: "expo.out", stagger: 0.1, delay });
}

/** fade-up children of a container when it enters the viewport */
export function revealOnScroll(targets, { stagger = 0.08, y = 40 } = {}) {
  const els = gsap.utils.toArray(targets);
  if (!els.length) return;
  if (reduced.on) { gsap.set(els, { opacity: 1, y: 0 }); return; }
  ScrollTrigger.batch(els, {
    start: "top 90%",
    onEnter: (batch) => gsap.fromTo(batch, { opacity: 0, y }, { opacity: 1, y: 0, duration: 1.1, ease: "expo.out", stagger, overwrite: true }),
  });
  gsap.set(els, { opacity: 0 });
}
