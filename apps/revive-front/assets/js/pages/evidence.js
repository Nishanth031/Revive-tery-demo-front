// #/evidence: the model cards and the judge Q&A from data/docs/*.md, in editorial typography with an index rail.
import { h, headline } from "../lib/dom.js";
import { snapshotText } from "../lib/api.js";
import { renderMarkdown } from "../lib/md.js";
import { scrollTo } from "../core/smooth.js";
import { revealLines, revealOnScroll } from "../core/transitions.js";

const DOCS = [
  ["judge_qa", "Judge Q&A"],
  ["state_rul", "State of health & remaining life"],
  ["state_soh_crosscheck", "SOH cross-check"],
  ["gate_ood", "Safety gate & out-of-distribution"],
  ["physics_projection", "Physics projection"],
];

export async function mount(root, { ctx }) {
  const title = headline("h1", "The *evidence*.", "");
  root.append(h("section", { class: "wrap page-head", "data-rail": "" }, h("p", { class: "label eyebrow" }, "Model cards · read-only copies"), title,
    h("p", {}, "How each stage was built and validated, and where it stops being valid. Written by the engine's authors; copied from the platform's generated docs.")));
  const index = h("nav", { class: "evi-index", "aria-label": "Documents" });
  const body = h("div", {});
  root.append(h("div", { class: "wrap evi" }, index, body));
  const texts = await Promise.all(DOCS.map(([k]) => snapshotText(`data/docs/${k}.md`).catch(() => null)));
  DOCS.forEach(([k, label], i) => {
    const sec = h("article", { class: "doc-sec", id: `doc-${k}`, "data-rail": "" });
    sec.append(texts[i] ? renderMarkdown(texts[i]) : h("p", { class: "muted" }, `— ${label}: the document is missing from data/docs (run npm run sync).`));
    body.append(sec);
    const a = h("a", { href: `#doc-${k}`, onclick: (e) => { e.preventDefault(); scrollTo(sec, { offset: -96 }); } }, label);
    index.append(a);
  });
  ctx.add(() => {
    revealLines(title);
    revealOnScroll(body.querySelectorAll(".doc-sec"), { stagger: 0.05, y: 30 });
    const links = [...index.children];
    body.querySelectorAll(".doc-sec").forEach((sec, i) => ScrollTrigger.create({ trigger: sec, start: "top 40%", end: "bottom 40%", onToggle: (st) => { if (st.isActive) links.forEach((l, j) => l.classList.toggle("on", j === i)); } }));
  });
  return {};
}
