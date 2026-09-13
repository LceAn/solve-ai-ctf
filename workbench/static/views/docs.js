/* ---------------- ⑦ 文档 / WP ---------------- */
import { S } from "../state.js";
import { $, $$, esc, fmtSize } from "../ui.js";
import { api } from "../api.js";
import { mdRender } from "../md.js";
import { chOf } from "./detail.js";

export function renderDocs() {
  if (!S.comp) return;
  const row = (path, label, size, icon = "·") =>
    `<div class="trow" data-p="${esc(path)}"><span>${icon}</span><span style="flex:1">${esc(label)}</span>
     <span class="sz">${fmtSize(size)}</span></div>`;
  $("#docList").innerHTML = (S.comp.docs || []).map((d) =>
    row(`docs/${d.name}`, d.name, d.size)).join("") || "<p class='muted'>比赛级 docs/ 为空。</p>";
  $("#artifactList").innerHTML = (S.comp.artifacts || []).map((a) =>
    row(`artifacts/${a.name}`, a.name, a.size, "◆")).join("") || "<p class='muted'>比赛级 artifacts/ 为空。</p>";

  const tree = S.caseData?._tree || [];
  const caseDocs = tree.filter((f) => f.type === "file" && /\.md$/i.test(f.path || ""));
  const caseFiles = tree.filter((f) => f.type === "file" && !/\.md$/i.test(f.path || "") &&
    (/^(?:artifacts|solution)\//i.test(f.path || "") || /^(?:triage\.json|case\.json)$/i.test(f.path || "")));
  const casePrefix = S.caseDir ? `${S.caseDir}/` : "";
  $("#caseDocsTitle").textContent = S.slug ? `当前题目 WP / 复盘 · ${chOf(S.slug)?.name || S.slug}` : "当前题目 WP / 复盘";
  $("#caseArtifactsTitle").textContent = S.slug ? `当前题目 artifacts / 日志 · ${chOf(S.slug)?.name || S.slug}` : "当前题目 artifacts / 日志";
  $("#caseDocList").innerHTML = S.slug
    ? (caseDocs.map((f) => row(`${casePrefix}${f.path}`, f.path, f.size, "📄")).join("") || "<p class='muted'>该题目还没有 WP / 复盘文档。</p>")
    : "<p class='muted'>先在题目工作区选择一道题。</p>";
  $("#caseArtifactList").innerHTML = S.slug
    ? (caseFiles.map((f) => row(`${casePrefix}${f.path}`, f.path, f.size, "◆")).join("") || "<p class='muted'>该题目还没有 artifacts 或日志。</p>")
    : "<p class='muted'>先在题目工作区选择一道题。</p>";
  $$("#docList .trow, #caseDocList .trow").forEach((item) => item.onclick = () => openDoc(item.dataset.p));
}

export async function openDoc(relPath) {
  const view = $("#docView");
  view.innerHTML = "<p class='muted'>加载中…</p>";
  try {
    const r = await api(`/api/file?dir=${encodeURIComponent(S.dir)}&path=${encodeURIComponent(relPath)}`);
    if (r.binary) { view.innerHTML = "<p class='muted'>二进制文件不支持预览。</p>"; return; }
    view.innerHTML = mdRender(r.content);
    const sum = S.caseData?._tree?.find((f) => f.path === "summary.md");
    view.dataset.open = relPath;
  } catch (e) { view.innerHTML = `<p style="color:var(--red)">读取失败：${esc(e.message)}</p>`; }
}
