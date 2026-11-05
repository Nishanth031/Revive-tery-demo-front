// Small reusable marks: disposition chip, provenance/test/placeholder tags, locked (needs API) panel, error message.
import { h, dispIcon } from "../lib/dom.js";
import { DISP_SHORT } from "../lib/format.js";

export function dispChip(d, label) {
  const key = d || "NO_DECISION";
  return h("span", { class: "disp", "data-d": key, title: label || DISP_SHORT[key] }, dispIcon(key), DISP_SHORT[key] || key);
}
export const provTag = (prov) => h("span", { class: "tag prov", title: "data provenance" }, prov ? String(prov) : "provenance —");
export const testTag = () => h("span", { class: "tag test", title: "a deliberately flawed test case" }, "Test case");
export const placeholderTag = () => h("span", { class: "tag placeholder", title: "tariffs and costs are placeholder inputs" }, "modelled · placeholder inputs");
export const synthTag = () => h("span", { class: "tag", title: "the fleet is synthetic" }, "Synthetic");

export function badges(p) {
  return h("span", { class: "badges" },
    p.data_provenance === "synthetic" || /SYNTHETIC/i.test(p.demo_status || "") ? synthTag() : provTag(p.data_provenance),
    p.test_case ? testTag() : null);
}

export function lockedPanel(what) {
  return h("div", { class: "locked" },
    h("span", { class: "label" }, "Live API needed"),
    h("p", {}, `${what} is computed by the engine on request. Start the API (`, h("code", {}, "just api"), ") to unlock this. Nothing here is faked in snapshot mode."));
}

export function errorMsg(err, title = "That did not work.") {
  return h("div", { class: "msg", role: "alert" }, h("b", {}, title), h("span", {}, err?.message || String(err)));
}

export function lfpCaveat(p) {
  if (!p || !p.chemistry || p.chemistry === "LFP") return null;
  return h("p", { class: "caveat" }, h("span", { class: "label" }, "Caveat"), ` The state model is LFP-trained; this pack is ${p.chemistry}. Treat remaining-life figures as indicative.`);
}
