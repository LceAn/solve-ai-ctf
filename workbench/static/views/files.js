/* ---------------- ⑤ 文件 / 日志 ---------------- */
import { S } from "../state.js";
import { $, $$, esc, fmtSize } from "../ui.js";
import { api } from "../api.js";
import { chOf } from "./detail.js";

export async function renderFiles() {
  const sel = $("#fileCaseSelect");
  if (!S.comp) { sel.innerHTML = ""; $("#fileTree").innerHTML = ""; return; }
  const withCase = S.comp.challenges.filter((c) => c.case?.exists);
  const current = sel.dataset.root !== undefined ? sel.dataset.root
    : (S.slug && withCase.some((c) => c.slug === S.slug) ? (chOf(S.slug).case_dir || "cases/" + S.slug) : "");
  sel.innerHTML = `<option value="">（比赛根目录）</option>` + withCase.map((c) =>
    `<option value="${esc(c.case_dir || "cases/" + c.slug)}" ${c.case_dir === current ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  sel.onchange = () => { sel.dataset.root = sel.value; renderFiles(); };
  S.fileRoot = current;
  const tree = await api(`/api/tree?dir=${encodeURIComponent(S.dir)}&path=${encodeURIComponent(current || ".")}`)
    .then((r) => r.tree).catch(() => []);
  $("#fileTree").innerHTML = tree.map((f) => `<div class="trow ${f.type}" data-p="${esc(f.path)}">
    <span>${f.type === "dir" ? "▸" : "·"}</span><span style="flex:1">${esc(f.path.split("/").pop())}</span>
    ${f.type === "file" ? `<span class="sz">${fmtSize(f.size)}</span>
      <button class="small" data-dl="${esc(f.path)}" title="下载">⬇</button>` : ""}</div>`).join("")
    || "<p class='muted'>空目录。</p>";
  $$("#fileTree [data-dl]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    const root = S.fileRoot ? S.fileRoot + "/" : "";
    window.open(`/api/file?dir=${encodeURIComponent(S.dir)}&path=${encodeURIComponent(root + b.dataset.dl)}&download=1`, "_blank");
  });
  $$("#fileTree .trow[data-p]").forEach((row) => row.onclick = () => openFile(row.dataset.p));
}

export async function openFile(relPath) {
  const meta = $("#fileMeta"), view = $("#fileView");
  if (relPath.endsWith("/")) { view.textContent = ""; meta.textContent = "目录：" + relPath; return; }
  const fullPath = S.fileRoot ? S.fileRoot + "/" + relPath : relPath;
  meta.textContent = "读取中… " + relPath;
  try {
    const r = await api(`/api/file?dir=${encodeURIComponent(S.dir)}&path=${encodeURIComponent(fullPath)}`);
    if (r.binary) { view.textContent = `（二进制文件，${fmtSize(r.size)}）\n路径：比赛/${S.dir}/${fullPath}`; meta.textContent = r.note; return; }
    meta.textContent = `比赛/${S.dir}/${fullPath} · ${fmtSize(r.size)}${r.truncated ? " · 已截断至 2MB" : ""}`;
    view.textContent = r.content;
  } catch (e) { meta.textContent = "读取失败：" + e.message; view.textContent = ""; }
}
