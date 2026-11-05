// #/bench: the simulated ESP32 bench only (source "simulated"). Four scopes from the SSE stream, faults, alert timeline.
// Monitor-only: this page never sends source "hardware" and never calls /api/ports.
import { h, headline } from "../lib/dom.js";
import { isLive, api, apiBase } from "../lib/api.js";
import { num, datetime } from "../lib/format.js";
import { lockedPanel, errorMsg } from "../ui/chip.js";
import { scope } from "../ui/scope.js";
import { revealLines } from "../core/transitions.js";

export async function mount(root, { ctx }) {
  const title = headline("h1", "The *bench*, simulated.", "");
  root.append(h("section", { class: "wrap page-head", "data-rail": "" }, h("p", { class: "label eyebrow" }, "Simulated. Monitor-only. No hardware."), title,
    h("p", {}, "A software ESP32 discharges a virtual low-voltage cell and streams the same JSON lines the real firmware prints. Inject a fault and watch how the monitor reports it.")));
  const body = h("div", { class: "wrap", "data-rail": "", style: { paddingBottom: "var(--s8)" } });
  root.append(body);
  ctx.add(() => revealLines(title));
  if (!isLive()) { body.append(lockedPanel("The simulated bench (it runs inside the API)")); return {}; }

  const status = h("span", { class: "label" }, "Idle");
  const startBtn = h("button", { class: "btn primary", "data-magnetic": "" }, "Start simulated run");
  const stopBtn = h("button", { class: "btn", disabled: true }, "Stop");
  const faultRow = h("div", { class: "btn-row" });
  const err = h("div", {});
  const withheld = h("div", { class: "withheld", hidden: true, role: "alert" });
  const sV = scope({ label: "Voltage", unit: "V", digits: 3, color: "#F4EEE3" });
  const sI = scope({ label: "Current", unit: "A", digits: 3, color: "#8FBFA9" });
  const sT = scope({ label: "Temperature", unit: "°C", digits: 1, color: "#C98A97" });
  const sS = scope({ label: "State of charge", unit: "%", digits: 1, color: "#1F6B4F" });
  const timeline = h("ol", { class: "timeline", "aria-live": "polite" });
  const counts = h("p", { class: "muted small num" }, "—");
  body.append(
    h("div", { class: "bench-ctrl" }, startBtn, stopBtn, status),
    h("p", { class: "warn-line" }, "Starting a run stores its readings in the database (simulated provenance)."),
    err, withheld,
    h("div", { class: "bench-grid" }, sV.el, sI.el, sT.el, sS.el), counts,
    h("div", { class: "two", style: { marginTop: "var(--s5)" } },
      h("div", {}, h("h2", { style: { fontSize: "var(--fs-h3)", marginBottom: "16px" } }, "Inject a fault"), faultRow),
      h("div", {}, h("h2", { style: { fontSize: "var(--fs-h3)", marginBottom: "16px" } }, "Alert timeline"), timeline)));

  const seen = new Set();
  const addAlert = (text, kind = "") => {
    if (!text || seen.has(text)) return;
    seen.add(text);
    const li = h("li", {}, h("span", { class: "label muted" }, `${new Date().toLocaleTimeString("en-GB")} ${kind}`), h("div", {}, text));
    timeline.prepend(li);
    gsap.from(li, { opacity: 0, x: -12, duration: 0.6 });
  };

  try {
    const faults = await api.get("/api/faults");
    faults.forEach((f) => faultRow.append(h("button", { class: "chipbtn", disabled: true, "data-fault": f.id, onclick: async () => {
      try { await api.post("/api/runs/fault", { fault: f.id }); addAlert(`Injected: ${f.label}`, "fault"); } catch (e) { err.replaceChildren(errorMsg(e)); }
    } }, f.label)));
  } catch (e) { faultRow.append(errorMsg(e, "Faults could not be listed.")); }

  const setRunning = (running) => {
    startBtn.disabled = running; stopBtn.disabled = !running;
    faultRow.querySelectorAll("button").forEach((b) => { b.disabled = !running; });
  };
  startBtn.addEventListener("click", async () => {
    err.replaceChildren();
    try {
      [sV, sI, sT, sS].forEach((x) => x.reset()); seen.clear(); timeline.replaceChildren();
      await api.post("/api/runs", { source: "simulated", simulation: { fault: "none" } });
    } catch (e) { err.replaceChildren(errorMsg(e, "The run did not start.")); }
  });
  stopBtn.addEventListener("click", async () => { try { await api.post("/api/runs/stop", {}); } catch (e) { err.replaceChildren(errorMsg(e)); } });

  let es = null;
  const connect = () => {
    es = new EventSource(`${apiBase()}/api/runs/stream`);
    es.addEventListener("snapshot", (ev) => {
      let s; try { s = JSON.parse(ev.data); } catch { return; }
      setRunning(!!s.running);
      status.textContent = `${s.status || "—"} · ${s.mode || "—"}${s.stale ? " · stale" : ""}`;
      (s.readings || []).forEach((r) => {
        sV.push(r.voltage_v); sI.push(r.current_a, "withheld"); sT.push(r.temperature_c, "no sensor"); sS.push(r.soc_pct);
      });
      const c = s.counts || {};
      counts.textContent = `${num(c.good_lines)} good lines · ${num(c.bad_lines)} bad · ${num(c.message_lines)} messages · ${num(c.readings_held)} readings held`;
      if (s.notice) addAlert(s.notice, "notice");
      if (s.error) addAlert(s.error, "error");
      if (s.log_note) addAlert(s.log_note, "log");
      const f = s.fault || {};
      if (f.last) addAlert(f.last, f.severity || "");
      const critical = f.active && (f.severity === "critical" || /withheld/i.test(f.last || ""));
      withheld.hidden = !critical;
      if (critical) withheld.replaceChildren(h("span", { class: "label" }, f.severity === "critical" ? "Critical" : "Readings withheld"), h("p", {}, f.last));
      if (s.decision && typeof s.decision === "object") addAlert(`Result: ${s.decision.decision || s.decision.label || JSON.stringify(s.decision).slice(0, 120)}`, "result");
      else if (s.decision) addAlert(`Result: ${s.decision}`, "result");
    });
    es.onerror = () => { status.textContent = "Stream interrupted, retrying…"; };
  };
  connect();
  return { unmount() { es?.close(); [sV, sI, sT, sS].forEach((x) => x.dispose()); } };
}
