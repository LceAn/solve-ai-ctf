/* ---------------- markdown 迷你渲染 ---------------- */
import { esc } from "./ui.js";

export function mdRender(src) {
  const lines = String(src ?? "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let inCode = false, inQuote = false, listType = null, tableBuf = [];
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\*([^*\n]+)\*/g, "<i>$1</i>")
    // 链接 scheme 白名单：WP/题面等外部内容不可信（SKILL.md 契约第 6 条），
    // 非 http/https/mailto 一律降级为纯文本，杜绝 javascript: / data: XSS。
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, href) =>
      /^(https?:|mailto:)/i.test(href)
        ? `<a href="${href}" target="_blank" rel="noreferrer noopener">${label}</a>`
        : label);

  const flushList = () => { if (listType) { out.push(`</${listType}>`); listType = null; } };
  const flushQuote = () => { if (inQuote) { out.push("</blockquote>"); inQuote = false; } };
  const flushTable = () => {
    if (!tableBuf.length) return;
    const rows = tableBuf.filter((r) => !/^\s*\|?[\s:|-]+\|?\s*$/.test(r));
    const cells = rows.map((r) => r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim()));
    if (cells.length) {
      out.push("<table><thead><tr>" + cells[0].map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>");
      for (const row of cells.slice(1)) out.push("<tr>" + row.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>");
      out.push("</tbody></table>");
    }
    tableBuf = [];
  };

  for (const raw of lines) {
    const line = raw;
    if (line.trim().startsWith("```")) {
      flushTable(); flushList(); flushQuote();
      if (inCode) { out.push("</code></pre>"); inCode = false; }
      else { out.push("<pre><code>"); inCode = true; }
      continue;
    }
    if (inCode) { out.push(esc(line)); continue; }
    if (/^\s*\|/.test(line)) { flushList(); flushQuote(); tableBuf.push(line); continue; }
    flushTable();
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      flushList(); flushQuote();
      const lv = Math.min(h[1].length + 1, 5);
      out.push(`<h${lv}>${inline(h[2])}</h${lv}>`);
      continue;
    }
    if (/^\s*>\s?/.test(line)) {
      flushList();
      if (!inQuote) { out.push("<blockquote>"); inQuote = true; }
      out.push("<div>" + inline(line.replace(/^\s*>\s?/, "")) + "</div>");
      continue;
    }
    flushQuote();
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.、]\s+(.*)$/);
    if (ul) {
      if (listType !== "ul") { flushList(); out.push("<ul>"); listType = "ul"; }
      out.push(`<li>${inline(ul[1])}</li>`); continue;
    }
    if (ol) {
      if (listType !== "ol") { flushList(); out.push("<ol>"); listType = "ol"; }
      out.push(`<li>${inline(ol[1])}</li>`); continue;
    }
    flushList();
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { out.push("<hr>"); continue; }
    if (line.trim() === "") continue;
    out.push(`<p>${inline(line)}</p>`);
  }
  flushTable(); flushList(); flushQuote();
  if (inCode) out.push("</code></pre>");
  return out.join("\n");
}
