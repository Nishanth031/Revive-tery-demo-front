// Smoothness engine: GSAP ticker drives Lenis (and the shader + Three via their own ticker callbacks). One rAF loop.
import { reduced } from "./reduced.js";

export let lenis = null;

export function initSmooth() {
  gsap.registerPlugin(ScrollTrigger, SplitText, Flip, ScrollToPlugin);
  gsap.defaults({ ease: "expo.out", duration: 1.1 });
  if (!reduced.on && window.Lenis) {
    lenis = new Lenis({ lerp: 0.085, smoothWheel: true });
    lenis.on("scroll", ScrollTrigger.update);
    gsap.ticker.add((t) => lenis.raf(t * 1000));
    gsap.ticker.lagSmoothing(0);
  }
  railProgress();
}

export function scrollTo(target, opts = {}) {
  if (lenis) lenis.scrollTo(target, { duration: 1.6, easing: (t) => 1 - Math.pow(1 - t, 4), ...opts });
  else {
    const y = typeof target === "number" ? target : (typeof target === "string" ? document.querySelector(target) : target)?.getBoundingClientRect().top + window.scrollY;
    window.scrollTo({ top: y || 0, behavior: reduced.on ? "auto" : "smooth" });
  }
}
export function scrollTop() { if (lenis) lenis.scrollTo(0, { immediate: true, force: true }); else window.scrollTo(0, 0); }
export function stopScroll(stop) { if (!lenis) return; stop ? lenis.stop() : lenis.start(); }

/** left rail: page progress plus a tick per section of the current page */
function railProgress() {
  const fill = document.querySelector(".rail .fill");
  if (!fill) return;
  const update = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    gsap.set(fill, { scaleY: max > 0 ? Math.min(1, scrollY / max) : 0 });
  };
  if (lenis) lenis.on("scroll", update); else addEventListener("scroll", update, { passive: true });
  addEventListener("resize", update);
}
export function railTicks() {
  const rail = document.querySelector(".rail");
  if (!rail) return;
  rail.querySelectorAll(".tick").forEach((t) => t.remove());
  const max = document.documentElement.scrollHeight - innerHeight;
  if (max <= 0) return;
  document.querySelectorAll("#l3 [data-rail]").forEach((sec) => {
    const y = Math.min(1, (sec.getBoundingClientRect().top + scrollY) / max);
    const t = document.createElement("i"); t.className = "tick"; t.style.top = `${(y * 100).toFixed(2)}%`; rail.append(t);
  });
}

/** L2 parallax: every [data-speed] element drifts at its own rate (scrubbed). Rebuilt per route. */
export function parallaxDecor() {
  if (reduced.on) return;
  document.querySelectorAll("#l2 [data-speed]").forEach((el) => {
    const speed = parseFloat(el.dataset.speed) || 0;
    gsap.fromTo(el, { y: 0 }, { y: () => -speed * innerHeight * 1.2, ease: "none",
      scrollTrigger: { trigger: document.body, start: "top top", end: "bottom bottom", scrub: 1.2, invalidateOnRefresh: true } });
  });
}
