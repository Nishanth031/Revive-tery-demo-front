// Adaptive quality: sample the first 90 frames; under 45 fps -> DPR 1, half the cells, no grain. Logged once.
const listeners = new Set();
export const quality = { level: "high", fps: null, decided: false };
export function onQuality(fn) { listeners.add(fn); if (quality.decided) fn(quality); }

export function sampleFrames() {
  if (!window.gsap) return;
  let n = 0, start = 0;
  const tick = () => {
    if (document.hidden) return;
    if (n === 0) start = performance.now();
    n += 1;
    if (n >= 91) {
      gsap.ticker.remove(tick);
      const fps = 90000 / (performance.now() - start);
      quality.fps = Math.round(fps);
      quality.level = fps < 45 ? "low" : "high";
      quality.decided = true;
      console.info(`[revive-front] quality: ${quality.level} (${quality.fps} fps over the first 90 frames)`);
      if (quality.level === "low") document.getElementById("l4")?.classList.add("off");
      listeners.forEach((fn) => fn(quality));
    }
  };
  gsap.ticker.add(tick);
}

/** rolling fps meter for the HANDOFF log (window.__reviveFps()) */
export function fpsMeter() {
  let frames = 0, last = performance.now(), fps = 0;
  const tick = () => { frames += 1; const now = performance.now(); if (now - last >= 1000) { fps = frames * 1000 / (now - last); frames = 0; last = now; } };
  window.gsap?.ticker.add(tick);
  window.__reviveFps = () => Math.round(fps);
}
