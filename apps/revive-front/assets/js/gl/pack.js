// L1: the battery pack as an InstancedMesh of cells. States: hero | pipeline | verdict | ambient.
// Instance matrices/colours are rewritten only when a blend weight changes (dirty flag), never every frame.
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { reduced } from "../core/reduced.js";
import { onQuality } from "../core/perf.js";

const DISP_ORDER = ["REPURPOSE", "REUSE", "RECYCLE", "INSPECT", "NO_DECISION"];
const DISP_COLOR = { REPURPOSE: 0x1F6B4F, REUSE: 0x8FBFA9, RECYCLE: 0x8A1F38, INSPECT: 0xE7DFD0, NO_DECISION: 0xB9AF9C };

export function initPack() {
  const host = document.getElementById("l1");
  const mobile = matchMedia("(max-width: 760px)").matches;
  let count = mobile ? 140 : 384;
  let renderer;
  try {
    const test = document.createElement("canvas");
    if (!(test.getContext("webgl2") || test.getContext("webgl"))) throw new Error("no webgl");
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  } catch (e) { return svgFallback(host); }

  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(innerWidth, innerHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.append(renderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environment = envTex;
  const camera = new THREE.PerspectiveCamera(32, innerWidth / innerHeight, 0.1, 400);
  camera.position.set(0, 26, 58); camera.lookAt(0, 0, 0);

  const key = new THREE.DirectionalLight(0xF4EEE3, 2.2); key.position.set(10, 30, 20); scene.add(key);
  const rim = new THREE.DirectionalLight(0x8A1F38, 3.0); rim.position.set(-30, 8, -12); scene.add(rim);
  const fill = new THREE.DirectionalLight(0x1F6B4F, 1.6); fill.position.set(30, 4, 10); scene.add(fill);
  scene.add(new THREE.AmbientLight(0x2E0713, 0.6));

  const bodyGeo = new THREE.CylinderGeometry(0.5, 0.5, 1.8, 24);
  const capGeo = new THREE.CylinderGeometry(0.34, 0.34, 0.12, 24);
  const bodyMat = new THREE.MeshStandardMaterial({ color: 0xffffff, metalness: 0.6, roughness: 0.35 });
  const capMat = new THREE.MeshStandardMaterial({ color: 0xF4EEE3, metalness: 0.6, roughness: 0.35 });
  const group = new THREE.Group();
  scene.add(group);

  let bodies, caps, cells = [];
  const W = { drop: 0, cluster: 0, ring: 0, highlight: null };
  const data = { waves: [0.2, 0.15, 0.1, 0.2], by: null, n: 0 };
  let dirty = true, visible = true;

  function build() {
    if (bodies) { group.remove(bodies, caps); bodies.dispose(); caps.dispose(); }
    bodies = new THREE.InstancedMesh(bodyGeo, bodyMat, count);
    caps = new THREE.InstancedMesh(capGeo, capMat, count);
    group.add(bodies, caps);
    const cols = mobile ? 14 : 24, rows = Math.ceil(count / cols), sp = 1.12;
    cells = [];
    for (let i = 0; i < count; i++) {
      const c = i % cols, r = Math.floor(i / cols);
      const seed = fract(Math.sin(i * 12.9898) * 43758.5453);
      cells.push({
        pack: new THREE.Vector3((c - (cols - 1) / 2) * sp, 0, (r - (rows - 1) / 2) * sp),
        cluster: new THREE.Vector3(), ring: new THREE.Vector3(), seed,
        base: new THREE.Color(seed < 0.08 ? 0x5C0F22 : 0x0B3D2C), tint: new THREE.Color(0x0B3D2C), disp: null, wave: -1,
      });
    }
    // ring layout (ambient)
    cells.forEach((c, i) => { const a = (i / count) * Math.PI * 2; const rad = 12 + (i % 3) * 1.2; c.ring.set(Math.cos(a) * rad, ((i % 5) - 2) * 0.6, Math.sin(a) * rad); });
    assignData();
  }
  const fract = (x) => x - Math.floor(x);

  function assignData() {
    // drop waves: wave k claims a share of cells equal to the real funnel drop share; cells picked by seed so waves look scattered
    const order = cells.map((c, i) => i).sort((a, b) => cells[a].seed - cells[b].seed);
    let k = 0, acc = 0;
    const bounds = []; data.waves.forEach((w) => { acc += w; bounds.push(Math.round(acc * count)); });
    order.forEach((idx, j) => { while (k < bounds.length && j >= bounds[k]) k++; cells[idx].wave = k < bounds.length ? k : -1; });
    // verdict clusters sized by real by_disposition counts
    const by = data.by || {};
    const total = DISP_ORDER.reduce((s, d) => s + (by[d] || 0), 0) || 1;
    let start = 0;
    const present = DISP_ORDER.filter((d) => (by[d] || 0) > 0);
    DISP_ORDER.forEach((d) => {
      const n = Math.round(((by[d] || 0) / total) * count);
      const slot = present.indexOf(d);
      const cx = (slot - (present.length - 1) / 2) * 9;
      const side = Math.max(1, Math.ceil(Math.sqrt(n)));
      for (let j = 0; j < n && start + j < count; j++) {
        const c = cells[order[start + j]];
        c.disp = d; c.tint.setHex(DISP_COLOR[d]);
        c.cluster.set(cx + ((j % side) - (side - 1) / 2) * 1.12, 0, (Math.floor(j / side) - (side - 1) / 2) * 1.12);
      }
      start += n;
    });
    for (let j = start; j < count; j++) { const c = cells[order[j]]; c.disp = null; c.tint.copy(c.base); c.cluster.copy(c.pack); }
    dirty = true;
  }

  const m = new THREE.Matrix4(), m2 = new THREE.Matrix4(), capOff = new THREE.Matrix4().makeTranslation(0, 0.96, 0), q = new THREE.Quaternion(), sc = new THREE.Vector3(), p = new THREE.Vector3(), col = new THREE.Color();
  function writeInstances() {
    const waves = data.waves.length;
    for (let i = 0; i < count; i++) {
      const c = cells[i];
      let s = 1;
      p.copy(c.pack);
      if (c.wave >= 0) {
        const t = THREE.MathUtils.clamp(W.drop * waves - c.wave, 0, 1);
        const e = t * t * (3 - 2 * t);
        p.y -= e * (10 + c.seed * 8); p.x += e * (c.seed - 0.5) * 6; s = 1 - e;
      }
      p.lerp(c.cluster, W.cluster);
      s = s + (1 - s) * W.cluster;
      p.lerp(c.ring, W.ring);
      if (W.highlight && W.cluster > 0.5) s *= c.disp === W.highlight ? 1.18 : 0.7;
      sc.set(s, s, s);
      m.compose(p, q, sc);
      bodies.setMatrixAt(i, m);
      caps.setMatrixAt(i, m2.multiplyMatrices(m, capOff));
      col.copy(c.base).lerp(c.tint, W.cluster);
      bodies.setColorAt(i, col);
    }
    bodies.instanceMatrix.needsUpdate = true; caps.instanceMatrix.needsUpdate = true;
    if (bodies.instanceColor) bodies.instanceColor.needsUpdate = true;
    dirty = false;
  }

  // group pose: hero tilt 18°, idle rotation, mouse parallax ±6°
  const pose = { x: 0, y: 0, z: 0, tilt: THREE.MathUtils.degToRad(18), scale: 1, mx: 0, my: 0 };
  addEventListener("pointermove", (e) => { pose.mx = (e.clientX / innerWidth - 0.5) * 2; pose.my = (e.clientY / innerHeight - 0.5) * 2; }, { passive: true });
  let idle = 0, smx = 0, smy = 0;
  const layoutForViewport = () => (innerWidth > 1060 ? 16 : innerWidth > 760 ? 14 : 0);

  const tick = (time, dt) => {
    if (!visible || document.hidden) return;
    if (dirty) writeInstances();
    idle += (reduced.on ? 0 : dt / 1000) * 0.06;
    smx += (pose.mx - smx) * 0.05; smy += (pose.my - smy) * 0.05;
    const par = THREE.MathUtils.degToRad(6);
    group.rotation.set(pose.tilt + smy * par, idle + smx * par + W.ring * idle * 2, 0);
    group.position.set(pose.x, pose.y, pose.z);
    group.scale.setScalar(pose.scale);
    renderer.render(scene, camera);
  };
  gsap.ticker.add(tick);

  const resize = () => { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); };
  addEventListener("resize", resize);
  document.addEventListener("visibilitychange", () => { visible = !document.hidden; });
  onQuality((qq) => { if (qq.level === "low") { renderer.setPixelRatio(1); count = Math.max(70, Math.round(count / 2)); build(); } });
  build();

  const tw = (vars, dur = 1.4) => gsap.to(W, { ...vars, duration: reduced.on ? 0 : dur, ease: "power4.inOut", overwrite: "auto", onUpdate: () => { dirty = true; } });
  const poseTo = (vars, dur = 1.6) => gsap.to(pose, { ...vars, duration: reduced.on ? 0 : dur, ease: "power4.inOut", overwrite: "auto" });

  let current = null;
  return {
    /** waves: four funnel drop shares; by: by_disposition counts */
    setData({ waves, by, n }) { if (waves) data.waves = waves; if (by) data.by = by; data.n = n || 0; assignData(); },
    setState(name, progress = 0) {
      if (name === "pipeline") { W.drop = progress; W.cluster = 0; W.ring = 0; dirty = true; }
      else if (name === "verdict") { W.drop = 1; W.cluster = progress; W.ring = 0; dirty = true; }
      if (name === current && (name === "pipeline" || name === "verdict")) return;
      current = name;
      const wide = innerWidth > 1060;
      host.style.opacity = name === "ambient" ? (innerWidth <= 760 ? "0.16" : "0.35") : name === "hero" ? (innerWidth <= 760 ? "0.4" : "1") : (wide ? (name === "verdict" ? "0.6" : "0.8") : "0.28");
      if (name === "hero") { tw({ drop: 0, cluster: 0, ring: 0 }); poseTo({ x: layoutForViewport(), y: -2, z: 0, scale: innerWidth > 1060 ? 0.8 : 0.7, tilt: THREE.MathUtils.degToRad(18) }); }
      if (name === "pipeline" || name === "verdict") poseTo({ x: innerWidth > 1060 ? 8 : 0, y: 0, z: 0, scale: 0.9, tilt: THREE.MathUtils.degToRad(name === "verdict" ? 34 : 22) });
      if (name === "ambient") { tw({ ring: 1, cluster: 0, drop: 0 }, 1.6); poseTo({ x: innerWidth > 760 ? 30 : 14, y: 4, z: -10, scale: 0.75, tilt: THREE.MathUtils.degToRad(64) }); }
    },
    highlight(d) { W.highlight = d; dirty = true; },
    dispose() { gsap.ticker.remove(tick); bodyGeo.dispose(); capGeo.dispose(); bodyMat.dispose(); capMat.dispose(); envTex.dispose(); pmrem.dispose(); renderer.dispose(); renderer.domElement.remove(); },
  };
}

function svgFallback(host) {
  document.getElementById("l0").classList.add("fallback");
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 240 160"); svg.setAttribute("class", "pack-svg");
  for (let r = 0; r < 6; r++) for (let c = 0; c < 10; c++) {
    const e = document.createElementNS(ns, "ellipse");
    e.setAttribute("cx", 22 + c * 21 + (r % 2) * 10); e.setAttribute("cy", 24 + r * 22); e.setAttribute("rx", 9); e.setAttribute("ry", 9);
    e.setAttribute("fill", (r * 10 + c) % 13 === 0 ? "#5C0F22" : "#0B3D2C"); e.setAttribute("stroke", "#F4EEE3"); e.setAttribute("stroke-opacity", ".35");
    svg.append(e);
  }
  host.append(svg);
  return { setData() {}, setState(name) { host.style.opacity = name === "ambient" ? "0.25" : "1"; }, highlight() {}, dispose() { svg.remove(); } };
}
