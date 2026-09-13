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
  // R48-F2：本地文档路径（外部目录只读浏览）
  const extHost = document.getElementById("extDocsHost") || document.querySelector("#docList")?.parentElement;
  if (extHost) {
    let host = document.getElementById("extDocsHost");
    if (!host) {
      host = document.createElement("div");
      host.id = "extDocsHost";
      extHost.appendChild(host);
    }
    if (!S.comp.docs_path) { host.innerHTML = "<p class='muted'>本地文档路径未设置（比赛管理 → 运维操作）。</p>"; }
    else {
      host.innerHTML = `<div class="muted" style="margin:8px 0 4px">本地文档路径：<span class="mono">${esc(S.comp.docs_path)}</span></div><div id="extDocList" class="muted">加载中…</div>`;
      api(`/api/docs/tree?dir=${encodeURIComponent(S.dir)}`).then((d) => {
        const list = document.getElementById("extDocList");
        if (!list) return;
        const files = (d.tree || []).filter((f) => f.type === "file");
        list.innerHTML = files.map((f) =>
          `<div class="trow" data-docs-p="${esc(f.path)}"><span>📄</span><span style="flex:1">${esc(f.path)}</span>
           <span class="sz">${fmtSize(f.size)}</span></div>`).join("") || "<p class='muted'>该目录暂无文件。</p>";
        list.querySelectorAll("[data-docs-p]").forEach((b) => b.onclick = async () => {
          try {
            const d2 = await api(`/api/docs/file?dir=${encodeURIComponent(S.dir)}&path=${encodeURIComponent(b.dataset.docsP)}`);
            openModal(`<h3>${esc(b.dataset.docsP)}</h3>
              <pre class="out" style="max-height:60vh;overflow:auto">${esc(d2.content || d2.note || "")}</pre>
              <div class="row" style="justify-content:flex-end;margin-top:8px"><button id="docClose" class="primary">关闭</button></div>`);
            document.getElementById("docClose").onclick = closeModal;
          } catch (err) { toast(err.message, true); }
        });
      }).catch(() => { list.innerHTML = "<p class='muted'>加载失败。</p>"; });
    }
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
