/* ---------------- ① 总览 ---------------- */
import { S } from "../state.js";
import { $, esc } from "../ui.js";
import { loadCase, setTab } from "../app.js";

export const CAT_COLORS = { crypto: "#9385d6", pwn: "#e57373", web: "#d98a4f", reverse: "#d9a93f",
  forensics: "#3cb3a3", misc: "#7ba86b" };
export const catColor = (cat) => CAT_COLORS[String(cat || "").toLowerCase()] || "#4f8cff";
export const STATUS_LABELS = {
  new: "待开始", triaged: "已分诊", in_progress: "进行中", candidate_found: "有候选",
  solved: "已解出", submitted: "已提交", closed: "已关闭", blocked: "已阻塞",
  abandoned: "已放弃", invalid: "无效", no_case: "未建 case",
};
export const statusLabel = (status) => STATUS_LABELS[String(status || "")] || String(status || "未知");
export const statusColor = (status) => ({
  solved: "#34d399", submitted: "#a78bfa", closed: "#38bdf8", candidate_found: "#fb923c",
  in_progress: "#fbbf24", blocked: "#f87171", triaged: "#4f8cff",
}[status] || "#94a3b8");

export function renderBoard() {
  const el = $("#boardStats"), tools = $("#boardTools"), grid = $("#boardGrid");
  if (!S.comp) { el.innerHTML = "<p class='muted'>没有可用的比赛目录。</p>"; grid.innerHTML = ""; return; }
  const chs = S.comp.challenges || [];
  const isDone = (c) => ["solved", "submitted", "closed"].includes(c.case?.status);
  const filterStatus = (c) => c.case?.exists ? (c.case.status || "new") : "new";
  const solved = chs.filter(isDone).length;
  const points = chs.reduce((a, c) => a + (c.points || 0), 0);
  const gotPoints = chs.filter(isDone).reduce((a, c) => a + (c.points || 0), 0);
  const active = chs.filter((c) => ["in_progress", "candidate_found", "blocked"].includes(c.case?.status)).length;
  const pct = chs.length ? Math.round((solved / chs.length) * 100) : 0;
  el.innerHTML = `
    <div class="stats">
      <div class="stat" style="--stat-c:var(--accent)"><span class="ic">🎯</span><b>${chs.length}</b><span>题目</span></div>
      <div class="stat" style="--stat-c:var(--green)"><span class="ic">🏁</span><b style="color:var(--green)">${solved}</b><span>已解出</span></div>
      <div class="stat" style="--stat-c:var(--yellow)"><span class="ic">⚡</span><b style="color:var(--yellow)">${active}</b><span>进行中</span></div>
      <div class="stat" style="--stat-c:var(--purple)"><span class="ic">🏆</span><b>${gotPoints}<small> / ${points}</small></b><span>得分</span></div>
      <div class="stat" style="--stat-c:var(--teal)"><span class="ic">📦</span><b>${(S.comp.artifacts || []).length + chs.reduce((n, c) => n + (c.case?.artifacts_count || 0), 0)}</b><span>artifacts</span></div>
      <div class="stat" style="--stat-c:var(--pink)"><span class="ic">📄</span><b>${(S.comp.docs || []).length + chs.reduce((n, c) => n + (c.case?.docs_count || 0), 0)}</b><span>docs / WP</span></div>
    </div>
    <div class="progress" title="解出 ${solved}/${chs.length}（${pct}%）"><i style="width:${pct}%"></i></div>`;

  const statusOptions = [
    ["all", "全部状态"], ["new", "待开始"], ["triaged", "已分诊"],
    ["in_progress", "进行中"], ["candidate_found", "有候选"],
    ["solved", "已解出"], ["submitted", "已提交"], ["closed", "已关闭"], ["blocked", "已阻塞"],
    ["abandoned", "已放弃"], ["invalid", "无效"],
  ];
  tools.innerHTML = `
    <div class="board-search"><span aria-hidden="true">⌕</span>
      <input id="boardQuery" type="search" value="${esc(S.boardQuery)}"
        placeholder="搜索题名、slug 或类别…" aria-label="搜索题名、slug 或类别">
    </div>
    <select id="boardStatus" aria-label="按状态筛选">
      ${statusOptions.map(([value, label]) => `<option value="${value}" ${S.boardStatus === value ? "selected" : ""}>${label}</option>`).join("")}
    </select>
    <button id="boardClear" class="small" type="button">清除</button>
    <span class="board-filter-count muted" aria-live="polite"></span>`;

  const byCat = {};
  const query = String(S.boardQuery || "").trim().toLowerCase();
  const status = S.boardStatus || "all";
  const visibleChs = chs.filter((c) => {
    const haystack = `${c.name || ""} ${c.slug || ""} ${c.category || ""}`.toLowerCase();
    return (!query || haystack.includes(query)) && (status === "all" || filterStatus(c) === status);
  });
  for (const c of visibleChs) (byCat[c.category || "misc"] ||= []).push(c);
  const catRank = { crypto: 0, pwn: 1, reverse: 2, web: 3, misc: 4, forensics: 5 };
  const cats = Object.keys(byCat).sort((a, b) => (catRank[a] ?? 9) - (catRank[b] ?? 9) || a.localeCompare(b));
  grid.innerHTML = cats.length ? cats.map((cat) => {
    const cc = catColor(cat);
    return `
    <div class="cat-head"><span class="chip" style="--cat:${cc}">${esc(cat.toUpperCase())}</span>
      <span class="muted">${byCat[cat].length} 题 · ${byCat[cat].reduce((a, c) => a + (c.points || 0), 0)} 分 · 已解 ${byCat[cat].filter(isDone).length}</span></div>` +
    byCat[cat].map((c) => {
      const st = filterStatus(c);
      const displaySt = c.case?.exists ? (c.case.status || "new") : "no-case";
      const cands = c.case?.candidates || [];
      const valid = cands.filter((x) => ["validated", "submitted", "accepted"].includes(x.status)).length;
      return `
      <div class="ch-card" role="button" tabindex="0" aria-label="打开 ${esc(c.name)}"
        data-slug="${esc(c.slug)}" style="--cat:${cc}">
        <div class="top"><span class="dot s-${esc(st)}" title="${esc(displaySt)}"></span>
          <span class="name">${esc(c.name)}</span><span class="pts">${c.points ?? "?"} 分</span></div>
        <div class="meta">
          <span class="badge" style="--b-c:${statusColor(st)}">${esc(statusLabel(displaySt))}</span>
          ${c.difficulty ? `<span>${esc(c.difficulty)}</span>` : ""}
          <span>假设 ${c.case?.hypotheses ?? 0}</span><span>尝试 ${c.case?.attempts ?? 0}</span>
          ${cands.length ? `<span>候选 ${cands.length}${valid ? ` · ✓${valid}` : ""}</span>` : ""}
        </div>
        ${c.description ? `<div class="desc">${esc(c.description)}</div>` : ""}
      </div>`;
    }).join("");
  }).join("") : `<div class="empty board-empty"><div class="big">🔎</div>
      <strong>没有匹配的题目</strong><div class="muted">试试调整搜索词或状态筛选</div>
      <button class="small" type="button" data-board-empty-clear>清除筛选</button></div>`;
  const filterCount = tools.querySelector(".board-filter-count");
  if (filterCount) filterCount.textContent = (query || status !== "all")
    ? `显示 ${visibleChs.length}/${chs.length}` : `${chs.length} 题`;
  $("#boardQuery").oninput = (e) => {
    S.boardQuery = e.target.value;
    localStorage.setItem("wb.boardQuery", S.boardQuery);
    renderBoard();
    const next = $("#boardQuery");
    next?.focus();
    next?.setSelectionRange(S.boardQuery.length, S.boardQuery.length);
  };
  $("#boardStatus").onchange = (e) => {
    S.boardStatus = e.target.value;
    localStorage.setItem("wb.boardStatus", S.boardStatus);
    renderBoard();
  };
  $("#boardClear").onclick = () => {
    S.boardQuery = ""; S.boardStatus = "all";
    localStorage.removeItem("wb.boardQuery");
    localStorage.removeItem("wb.boardStatus");
    renderBoard();
  };
  if (!grid.dataset.bound) {
    grid.dataset.bound = "1";
    const openCard = async (card) => {
      if (card) { await loadCase(card.dataset.slug); setTab("detail"); }
    };
    grid.addEventListener("click", async (e) => {
      if (e.target.closest("[data-board-empty-clear]")) {
        S.boardQuery = ""; S.boardStatus = "all";
        localStorage.removeItem("wb.boardQuery");
        localStorage.removeItem("wb.boardStatus");
        renderBoard();
        return;
      }
      const card = e.target.closest(".ch-card");
      await openCard(card);
    });
    grid.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const card = e.target.closest(".ch-card");
      if (!card) return;
      e.preventDefault();
      await openCard(card);
    });
  }
}
