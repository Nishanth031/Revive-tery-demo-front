// Small safe Markdown renderer: builds DOM nodes, never innerHTML. Headings, paragraphs, lists, tables, code, quotes,
// emphasis, inline code and links (http(s), relative or #anchors only).
import { h } from "./dom.js";

function inline(text) {
  const out = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(_[^_\s][^_]*_)|(\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (m[1]) out.push(h("code", {}, t.slice(1, -1)));
    else if (m[2]) out.push(h("strong", {}, ...inline(t.slice(2, -2))));
    else if (m[3] || m[4]) out.push(h("em", {}, ...inline(t.slice(1, -1))));
    else {
      const [, label, href] = t.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
      const safe = /^(https?:\/\/|#|\.{0,2}\/|[\w.-]+(\.md)?$)/i.test(href) && !/^javascript:/i.test(href);
      out.push(safe ? h("a", { href, ...(href.startsWith("http") ? { target: "_blank", rel: "noopener" } : {}) }, label) : label);
    }
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function renderMarkdown(src) {
  const root = h("div", { class: "prose" });
  const lines = String(src).replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  const isTableSep = (l) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(l);
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    let m;
    if ((m = line.match(/^```/))) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++; root.append(h("pre", {}, h("code", {}, buf.join("\n")))); continue;
    }
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) { root.append(h(`h${Math.min(4, m[1].length)}`, {}, ...inline(m[2]))); i++; continue; }
    if (/^\s*([-*_])\s*\1\s*\1[\s\1]*$/.test(line)) { root.append(h("hr", {})); i++; continue; }
    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const head = cells(line); i += 2;
      const body = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) body.push(cells(lines[i++]));
      root.append(h("table", {}, h("thead", {}, h("tr", {}, head.map((c) => h("th", {}, ...inline(c))))), h("tbody", {}, body.map((r) => h("tr", {}, r.map((c) => h("td", {}, ...inline(c))))))));
      continue;
    }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      root.append(h("blockquote", {}, h("p", {}, ...inline(buf.join(" "))))); continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const list = h(ordered ? "ol" : "ul", {});
      while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
        let item = lines[i++].replace(/^\s*([-*+]|\d+[.)])\s+/, "");
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) item += " " + lines[i++].trim();
        list.append(h("li", {}, ...inline(item)));
      }
      root.append(list); continue;
    }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>|\s*([-*+]|\d+[.)])\s+)/.test(lines[i]) && !(lines[i].includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1]))) buf.push(lines[i++].trim());
    root.append(h("p", {}, ...inline(buf.join(" "))));
  }
  return root;
}
