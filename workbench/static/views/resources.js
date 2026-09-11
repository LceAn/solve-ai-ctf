/* ---------------- ⑪ 资源库 ---------------- */
import { S } from "../state.js";
import { $, $$, esc, toast, copyText } from "../ui.js";
import { api } from "../api.js";

let PROMPT_BUFFER = "";

export async function renderResources() {
  const body = $("#resourcesBody");
  if (!S.comp) { body.innerHTML = "<p class='muted'>没有可用的比赛目录。</p>"; return; }
  S.resKind = localStorage.getItem("wb.resKind") || "all";
  S.resQ = localStorage.getItem("wb.resQ") || "";
  body.innerHTML = `
    <div class="res-toolbar">
      <input id="resQuery" type="search" value="${esc(S.resQ)}"
        placeholder="搜索 references / writeup / 外部链接…" aria-label="搜索资源">
      <div class="res-kind-tabs" role="tablist" aria-label="资源类型">
        ${[["all", "全部"], ["reference", "📘 参考"], ["writeup", "📄 WP"], ["external", "🔗 外部"]].map(([k, l]) =>
          `<button data-kind="${k}" class="${S.resKind === k ? "on" : ""}" role="tab" aria-selected="${S.resKind === k}">${l}</button>`
        ).join("")}
      </div>
      <button id="resSearch" class="primary">检索</button>
      <button id="resPrompt" class="small" title="查看已加入提示词的内容" aria-label="提示词缓冲区">提示词 (${PROMPT_BUFFER.length})</button>
    </div>
    <div id="resResults"></div>`;
  const q = $("#resQuery");
  q.value = S.resQ;
  q.oninput = (e) => { S.resQ = e.target.value; localStorage.setItem("wb.resQ", S.resQ); };
  q.onkeydown = (e) => { if (e.key === "Enter") doSearch(); };
  $("#resSearch").onclick = () => doSearch();
  $$("#resToolbar .res-kind-tabs button, #resourcesBody .res-kind-tabs button").forEach((b) => b.onclick = () => {
    S.resKind = b.dataset.kind;
    localStorage.setItem("wb.resKind", S.resKind);
    $$("#resourcesBody .res-kind-tabs button").forEach((x) => {
      const on = x.dataset.kind === S.resKind;
      x.classList.toggle("on", on);
      x.setAttribute("aria-selected", on ? "true" : "false");
    });
    doSearch();
  });
  $("#resPrompt").onclick = () => {
    import("../ui.js").then(({ openModal, closeModal }) => {
      openModal(`
        <h3 id="modalTitle">📋 提示词缓冲区</h3>
        <p class="muted">已加入 ${PROMPT_BUFFER.length} 字符。复制后粘贴到「知识库 / 提示词」生成器或 Agent 输入。</p>
        <pre class="out" style="max-height:50vh">${esc(PROMPT_BUFFER) || "（空）"}</pre>
        <div class="row" style="margin-top:10px">
          <button id="pbCopy" class="primary">复制</button>
          <button id="pbClear" class="small">清空</button>
          <button id="pbClose" class="small">关闭</button>
        </div>`);
      $("#pbCopy").onclick = () => copyText(PROMPT_BUFFER, "提示词缓冲区");
      $("#pbClear").onclick = () => { PROMPT_BUFFER = ""; closeModal(); renderResources(); };
      $("#pbClose").onclick = closeModal;
    });
  };
  if (S.resQ || S.resKind !== "all") doSearch();
  else showInitial();
}

function showInitial() {
  $("#resResults").innerHTML = `<div class="empty"><div class="big">🔗</div>
    <strong>资源库</strong>
    <div class="muted">输入关键词检索 references / writeup / 外部链接，<br>或点击「全部」浏览所有资源</div></div>`;
}

async function doSearch() {
  const results = $("#resResults");
  const q = (S.resQ || "").trim();
  if (!q && S.resKind === "all") { showInitial(); return; }
  if (!q) { results.innerHTML = "<p class='muted'>请输入搜索关键词。</p>"; return; }
  results.innerHTML = `<div class="res-grid">${Array.from({ length: 4 }, () => `<div class="skeleton skeleton-card" style="height:120px"></div>`).join("")}</div>`;
  try {
    const r = await api(`/api/resources?q=${encodeURIComponent(q)}&kind=${S.resKind}&dir=${encodeURIComponent(S.dir || "")}`);
    renderResults(r, q);
  } catch (e) {
    results.innerHTML = `<div class="panel" style="color:var(--red)">检索失败：${esc(e.message)}</div>`;
  }
}

function renderResults(r, q) {
  const results = $("#resResults");
  const hits = r.hits || [];
  const kindMeta = {
    reference: { color: "var(--accent)", label: "参考" },
    writeup: { color: "var(--purple)", label: "WP" },
    external: { color: "var(--teal)", label: "外部" },
  };
  results.innerHTML = hits.length ? `
    <div class="muted" style="margin:0 0 12px">${r.count || hits.length} 条命中（kind=${esc(S.resKind)}）</div>
    <div class="res-grid">
      ${hits.map((h) => {
        const km = kindMeta[h.kind] || { color: "var(--muted)", label: h.kind || "?" };
        const title = h.title || h.file || h.url || "未命名";
        const snippet = (h.context || []).join("\n").slice(0, 280);
        const isExternal = h.kind === "external";
        const href = isExternal ? h.url : null;
        return `<div class="res-card" style="--oc:${km.color}">
          <div class="res-kind">${esc(km.label)}</div>
          <div class="res-title">${esc(title)}</div>
          ${h.category ? `<div class="res-meta">分类：${esc(h.category)}</div>` : ""}
          ${snippet ? `<pre class="res-snippet">${esc(snippet)}</pre>` : ""}
          <div class="res-meta">${h.file ? `📄 ${esc(h.file)}:${h.line ?? ""}` : ""}
            ${h.score !== undefined ? ` · score=${h.score}` : ""}</div>
          <div class="res-actions">
            <button class="small" data-prompt="${esc(title + (snippet ? "\n" + snippet : ""))}" aria-label="加入提示词">＋ 提示词</button>
            ${href ? `<a href="${esc(href)}" target="_blank" rel="noreferrer" class="small" style="display:inline-block;padding:3px 10px;font-size:12px;border-radius:7px;background:var(--bg4);border:1px solid var(--border2);color:var(--fg)">打开 ↗</a>` : ""}
          </div>
        </div>`;
      }).join("")}
    </div>` : `<div class="empty"><div class="big">🔎</div>
      <strong>没有命中</strong>
      <div class="muted">试试更宽泛的关键词，或切换 kind 到「全部」</div></div>`;
  $$("#resResults [data-prompt]").forEach((b) => b.onclick = () => {
    const text = b.dataset.prompt;
    PROMPT_BUFFER += (PROMPT_BUFFER ? "\n\n---\n" : "") + text;
    toast(`已加入提示词缓冲区（${PROMPT_BUFFER.length} 字符）`, "ok");
    $("#resPrompt").textContent = `提示词 (${PROMPT_BUFFER.length})`;
  });
}
