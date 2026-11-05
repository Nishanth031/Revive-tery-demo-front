// Screenshots of every route at 1440, 1024 and 390 px into docs/shots/, driving a locally installed Edge or Chrome over
// the DevTools protocol (Node's built-in WebSocket; no npm install). It also reports console errors, page exceptions,
// "NaN/undefined/[object" in the visible text and horizontal overflow per shot.
// Serve the site first (npm run serve), then: node tools/shoot.mjs [baseUrl]
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "../docs/shots");
mkdirSync(out, { recursive: true });
const base = (process.argv[2] || "http://127.0.0.1:8090").replace(/\/$/, "");
const ROUTES = [["home", "#/"], ["fleet", "#/fleet"], ["pack", "#/pack/DEMO-EV-PACK-002"], ["plan", "#/plan"], ["analyze", "#/analyze"], ["bench", "#/bench"], ["evidence", "#/evidence"]];
const SIZES = [[1440, 900], [1024, 768], [390, 844]];
const PORT = 9333;

const browser = [process.env.BROWSER, "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"]
  .filter(Boolean).find((p) => existsSync(p));
if (!browser) { console.error("No Edge/Chrome found. Set BROWSER=/path/to/chrome."); process.exit(1); }

const profile = join(tmpdir(), "revive-front-shoot-profile");
const proc = spawn(browser, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--no-first-run", "--hide-scrollbars", "--enable-webgl", "--use-angle=swiftshader", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let target;
for (let i = 0; i < 40 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page"); } catch { await sleep(250); }
}
if (!target) { console.error("DevTools did not answer."); proc.kill(); process.exit(1); }

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let seq = 0;
const pending = new Map();
const problems = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === "Runtime.exceptionThrown") problems.push(`exception: ${m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text}`);
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") problems.push(`console.error: ${m.params.args.map((a) => a.value ?? a.description).join(" ")}`);
  if (m.method === "Log.entryAdded" && m.params.entry.level === "error") problems.push(`log: ${m.params.entry.text} ${m.params.entry.url || ""}`);
});
const send = (method, params = {}) => new Promise((r) => { const id = ++seq; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
await send("Runtime.enable"); await send("Log.enable"); await send("Page.enable");

let failed = 0;
const report = [];
for (const [w, hgt] of SIZES) {
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: hgt, deviceScaleFactor: 1, mobile: w < 761 });
  for (const [name, hash] of ROUTES) {
    problems.length = 0;
    await send("Page.navigate", { url: "about:blank" });
    await sleep(200);
    await send("Page.navigate", { url: `${base}/${hash}` });
    await sleep(6500);
    const ev = await send("Runtime.evaluate", { returnByValue: true, expression: `(() => { const t = document.getElementById("l3")?.innerText || ""; return { bad: (t.match(/.{0,30}(NaN|undefined|\\[object)/) || [null])[0], sw: document.documentElement.scrollWidth, w: innerWidth, len: t.length }; })()` });
    const v = ev.result?.result?.value || {};
    const shot = await send("Page.captureScreenshot", { format: "png" });
    const file = join(out, `${name}-${w}.png`);
    writeFileSync(file, Buffer.from(shot.result.data, "base64"));
    const errs = problems.filter((p) => !/127\.0\.0\.1:8000|ERR_CONNECTION_REFUSED/.test(p));   // the API being down is expected in snapshot mode
    const ok = !v.bad && v.sw <= v.w && v.len > 0 && !errs.length;
    if (!ok) failed += 1;
    const line = `${ok ? "ok  " : "FAIL"} ${name.padEnd(8)} ${String(w).padStart(4)}px  text=${v.len} overflow=${v.sw > v.w ? v.sw - v.w + "px" : "none"}${v.bad ? ` bad="${v.bad}"` : ""}${errs.length ? ` errors=${JSON.stringify(errs)}` : ""}`;
    report.push(line); console.log(line);
  }
}
ws.close(); proc.kill();
try { rmSync(profile, { recursive: true, force: true }); } catch { /* the browser may still hold it */ }
writeFileSync(join(out, "report.txt"), report.join("\n") + "\n");
process.exit(failed ? 1 : 0);
