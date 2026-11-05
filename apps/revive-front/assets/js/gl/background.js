// L0: full-screen WebGL shader at half resolution (CSS upscales it). Driven by the GSAP ticker; paused when hidden.
import { VERT, FRAG } from "./shaders.js";
import { reduced } from "../core/reduced.js";

const u = { time: 0, scroll: 0, mx: 0, my: 0, tone: 0, toneTarget: 0 };

export function initBackground() {
  const host = document.getElementById("l0");
  if (reduced.on) { host.classList.add("fallback"); return { setTone() {} }; }
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl", { antialias: false, alpha: false, powerPreference: "high-performance" });
  if (!gl) { host.classList.add("fallback"); return { setTone() {} }; }
  host.append(canvas);

  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
  let prog;
  try {
    prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  } catch (e) { console.warn("[revive-front] shader fallback:", e.message); canvas.remove(); host.classList.add("fallback"); return { setTone() {} }; }
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "aPos");
  gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = Object.fromEntries(["uTime", "uScroll", "uMouse", "uTone", "uRes"].map((n) => [n, gl.getUniformLocation(prog, n)]));

  const resize = () => {
    const scale = 0.5;
    canvas.width = Math.max(2, Math.round(innerWidth * scale)); canvas.height = Math.max(2, Math.round(innerHeight * scale));
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(U.uRes, canvas.width, canvas.height);
  };
  resize(); addEventListener("resize", resize);
  addEventListener("pointermove", (e) => { u.mx = (e.clientX / innerWidth) * 2 - 1; u.my = (e.clientY / innerHeight) * 2 - 1; }, { passive: true });

  let sm = { x: 0, y: 0 };
  const tick = (time) => {
    if (document.hidden) return;
    u.time = time;
    const max = document.documentElement.scrollHeight - innerHeight;
    u.scroll += ((max > 0 ? scrollY / max : 0) - u.scroll) * 0.08;
    u.tone += (u.toneTarget - u.tone) * 0.04;
    sm.x += (u.mx - sm.x) * 0.04; sm.y += (u.my - sm.y) * 0.04;
    gl.uniform1f(U.uTime, u.time); gl.uniform1f(U.uScroll, u.scroll); gl.uniform2f(U.uMouse, sm.x, -sm.y); gl.uniform1f(U.uTone, u.tone);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  };
  gsap.ticker.add(tick);
  return { setTone(v) { u.toneTarget = v; } };
}
