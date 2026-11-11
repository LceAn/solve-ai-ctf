/* Competition overview: summary, composable filters and keyboard-accessible cards. */
import { S } from "../state.js";
import { $, esc } from "../ui.js";
import { api } from "../api.js";
import { loadCase, setTab } from "../app.js";
import { categoryOf, categoriesOf, challengeStatus, isDone, boardSummary, filterChallenges } from "./board-model.js";

export const CAT_COLORS = { crypto: "#8b79c9", pwn: "#d86e7b", web: "#c48740", reverse: "#b79c48",
  forensics: "#329c97", misc: "#7e9c61" };
export const catColor = (cat) => CAT_COLORS[String(cat || "").toLowerCase()] || "#698eb8";
export const STATUS_LABELS = {
  new: "待开始", triaged: "已分诊", in_progress: "进行中", candidate_found: "有候选",
  solved: "已解出", submitted: "已提交", closed: "已关闭", blocked: "已阻塞",
  abandoned: "已放弃", invalid: "无效", no_case: "未建 case",
};
export const statusLabel = (status) => STATUS_LABELS[String(status || "")] || String(status || "未知");
export const statusColor = (status) => ({
  solved: "var(--green)", submitted: "var(--purple)", closed: "var(--teal)", candidate_found: "var(--orange)",
  in_progress: "var(--yellow)", blocked: "var(--red)", triaged: "var(--accent)",
}[status] || "var(--muted)");

let runningBySlug = {};
let runningFetched = 0;
let runningDir = null;
let runningRequest = 0;
let firstClearRequest = 0;
let boardRefreshTimer = null;
window.addEventListener("wb-event", (ev) => {
  if (!["challenges_new", "status_changed", "case_initialized"].includes(ev.detail?.kind)) return;
  runningFetched = 0;
  if (localStorage.getItem("wb.tab") !== "board") return;
  clearTimeout(boardRefreshTimer);
  boardRefreshTimer = setTimeout(async () => {
    try { await (await import("../app.js")).loadCompetition(); } catch { /* Keep the last received view. */ }
    renderBoard();
  }, 300);
});

function lastActivity() {
  const evs = S.comp?.events || [];
  if (!evs.length) return "暂无活动";
  const ts = new Date(evs[evs.length - 1].time).getTime();
  if (isNaN(ts)) return "暂无活动";
  const m = Math.max(0, Math.floor((Date.now() - ts) / 60000));
  if (m < 1) return "刚刚";
  if (m < 60) return m + " 分钟前";
  const h = Math.floor(m / 60);
  return h < 24 ? h + " 小时前" : Math.floor(h / 24) + " 天前";
}

function clearFilters() {
  S.boardQuery = ""; S.boardStatus = "all"; S.boardCategory = "all";
  ["wb.boardQuery", "wb.boardStatus", "wb.boardCategory"].forEach((key) => localStorage.removeItem(key));
  renderFilters(); renderCards();
  $("#boardQuery")?.focus();
}

function renderFilters() {
  const chs = S.comp?.challenges || [];
  const cats = categoriesOf(chs);
  if (S.boardCategory !== "all" && !cats.includes(S.boardCategory)) {
    S.boardCategory = "all";
    localStorage.removeItem("wb.boardCategory");
  }
  const statuses = [["all", "全部状态"], ...Object.entries(STATUS_LABELS).filter(([key]) => key !== "no_case")];
  $("#boardTools").innerHTML = `
    <div class="board-search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>
      <input id="boardQuery" type="search" value="${esc(S.boardQuery)}" placeholder="搜索题名、描述或关键词…" aria-label="搜索题名、slug 或类别">
    </div>
    <select id="boardStatus" aria-label="按状态筛选">${statuses.map(([value, label]) =>
      `<option value="${value}" ${S.boardStatus === value ? "selected" : ""}>${label}</option>`).join("")}</select>
    <label class="group-switch"><input id="boardGrouped" type="checkbox" ${S.boardGrouped ? "checked" : ""}> 按题型分组</label>
    <button id="boardClear" class="small" type="button">重置筛选</button>`;
  $("#boardCategories").innerHTML = `<div class="category-options">${["all", ...cats].map((cat) =>
    `<button type="button" data-board-category="${esc(cat)}" aria-pressed="${S.boardCategory === cat}" class="category-filter ${S.boardCategory === cat ? "on" : ""}">
      ${cat === "all" ? "全部题目" : `<i style="--cat:${catColor(cat)}" aria-hidden="true"></i>${esc(cat.toUpperCase())}`}
      <span>${cat === "all" ? chs.length : chs.filter((c) => categoryOf(c) === cat).length}</span></button>`).join("")}</div>
    <span class="board-filter-count muted" aria-live="polite"></span>`;
  $("#boardQuery").oninput = (e) => {
    S.boardQuery = e.target.value;
    localStorage.setItem("wb.boardQuery", S.boardQuery);
    renderCards(); // Keep input DOM, IME composition, caret and keyboard focus intact.
  };
  $("#boardStatus").onchange = (e) => {
    S.boardStatus = e.target.value; localStorage.setItem("wb.boardStatus", S.boardStatus); renderCards();
  };
  $("#boardGrouped").onchange = (e) => {
    S.boardGrouped = e.target.checked; localStorage.setItem("wb.boardGrouped", S.boardGrouped ? "1" : "0"); renderCards();
  };
  $("#boardClear").onclick = clearFilters;
  $("#boardCategories").onclick = (e) => {
    const button = e.target.closest("[data-board-category]");
    if (!button) return;
    S.boardCategory = button.dataset.boardCategory;
    localStorage.setItem("wb.boardCategory", S.boardCategory);
    $("#boardCategories").querySelectorAll("[data-board-category]").forEach((b) => {
      const on = b.dataset.boardCategory === S.boardCategory;
      b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on));
    });
    renderCards();
  };
}

function renderCards() {
  const chs = S.comp?.challenges || [];
  const visible = filterChallenges(chs, { query: S.boardQuery, status: S.boardStatus, category: S.boardCategory });
  const grid = $("#boardGrid");
  const count = $(".board-filter-count");
  if (count) count.textContent = `显示 ${visible.length} / ${chs.length} 题`;
  grid.innerHTML = categoriesOf(visible).map((cat) => {
    const members = visible.filter((c) => categoryOf(c) === cat);
    return (S.boardGrouped ? `<div class="cat-head"><span class="chip" style="--cat:${catColor(cat)}">${esc(cat.toUpperCase())}</span>
      <span class="muted">${members.length} 题 · 已解 ${members.filter(isDone).length}</span><span class="category-rule"></span></div>` : "")
      + members.map((c) => {
        const st = challengeStatus(c);
        const displaySt = c.case?.exists ? st : "no_case";
        const cands = c.case?.candidates || [];
        const valid = cands.filter((x) => ["validated", "submitted", "accepted"].includes(x.status)).length;
        const running = runningBySlug[c.slug] || [];
        return `<button type="button" class="ch-card ${isDone(c) ? "is-solved" : ""}" aria-label="打开 ${esc(c.name)}" data-slug="${esc(c.slug)}" style="--cat:${catColor(cat)}">
          <span class="card-topline"><span class="card-category">${esc(cat.toUpperCase())}</span><span class="pts">${esc(c.points ?? "?")} <small>分</small></span></span>
          <span class="name">${esc(c.name)}</span>
          <span class="card-statusline"><span class="badge" style="--b-c:${statusColor(st)}"><span class="status-dot" aria-hidden="true"></span>${esc(statusLabel(displaySt))}</span>
            ${(window.__envRunning || new Set()).has(c.slug) ? '<span title="容器运行中" aria-label="容器运行中" style="font-size:11px">🟢</span>' : ""}
            ${c.difficulty ? `<span class="difficulty">${esc(c.difficulty)}</span>` : ""}
            ${running.length ? `<span class="running-label" title="${esc(running.map((t) => t.id + " " + (t.agent || "solver")).join(" · "))}">求解器运行中</span>` : ""}</span>
          <span class="desc ${c.description ? "" : "no-description"}">${esc(c.description || "暂无题面描述，进入工作区查看附件与线索。")}</span>
          <span class="card-footer"><span>假设 <b>${c.case?.hypotheses ?? 0}</b></span><span>尝试 <b>${c.case?.attempts ?? 0}</b></span>
            <span title="${valid} 个已验证、已提交或已接受的候选">候选 <b>${cands.length}</b>${valid ? '<i class="candidate-check" aria-label="含有效候选">✓</i>' : ""}</span>
            ${c.case?.participants ? `<span>${c.case.participants} 人</span>` : ""}<span class="card-arrow" aria-hidden="true">↗</span></span>
        </button>`;
      }).join("");
  }).join("") || `<div class="empty board-empty"><div class="empty-symbol" aria-hidden="true">${chs.length ? "⌕" : "+"}</div>
    <strong>${chs.length ? "没有匹配的题目" : "比赛工作区已就绪"}</strong>
    <div class="muted">${chs.length ? "调整关键词、题型或状态，继续寻找下一道题。" : "前往比赛管理，注册或导入第一道题目。"}</div>
    <button type="button" class="small" ${chs.length ? "data-board-empty-clear" : "data-board-register"}>${chs.length ? "重置筛选" : "去比赛管理"}</button></div>`;
  if (!grid.dataset.bound) {
    grid.dataset.bound = "1";
    grid.addEventListener("click", async (e) => {
      if (e.target.closest("[data-board-empty-clear]")) { clearFilters(); return; }
      if (e.target.closest("[data-board-register]")) { setTab("ops"); return; }
      const card = e.target.closest(".ch-card");
      if (card) { await loadCase(card.dataset.slug); setTab("detail"); }
    }); // Native buttons handle Enter and Space without duplicate key handlers.
  }
}

export async function renderBoard() {
  try {
    const er = await api(`/api/env/container?dir=${encodeURIComponent(S.dir)}`);
    window.__envRunning = new Set(Object.entries(er.envs || {}).filter(([, v]) => v.running).map(([s]) => s));
  } catch { window.__envRunning = new Set(); }
  const el = $("#boardStats");
  if (!S.comp) {
    el.innerHTML = "<div class='empty-state'><b>还没有可用的比赛</b><p>使用顶部比赛选择器创建一个工作区。</p></div>";
    ["#boardTools", "#boardCategories", "#boardGrid"].forEach((id) => $(id).innerHTML = "");
    return;
  }
  const chs = S.comp.challenges || [];
  const stats = boardSummary(chs);
  const artifacts = (S.comp.artifacts || []).length + chs.reduce((n, c) => n + (c.case?.artifacts_count || 0), 0);
  const docs = (S.comp.docs || []).length + chs.reduce((n, c) => n + (c.case?.docs_count || 0), 0);
  el.innerHTML = `<div class="overview-summary">
    <div class="summary-progress"><div class="metric-label">解题进度 <span>${stats.percent}%</span></div>
      <div class="metric-value">${stats.solved}<small>/ ${stats.total} 题</small></div>
      <div class="progress" role="progressbar" aria-label="解题完成度" aria-valuenow="${stats.percent}" aria-valuemin="0" aria-valuemax="100"><i style="width:${stats.percent}%"></i></div>
      <span class="metric-note">已解出 · 已提交 · 已关闭</span></div>
    <div class="summary-metric"><span class="metric-label">正在推进</span><div class="metric-value">${stats.active}<small>题</small></div><span class="metric-note">进行中与已有候选</span></div>
    <button class="summary-metric blocked-metric" type="button" id="boardBlocked" aria-label="筛选已阻塞的 ${stats.blocked} 道题"><span class="metric-label">需要关注 <span aria-hidden="true">↗</span></span>
      <span class="metric-value ${stats.blocked ? "has-blocked" : ""}">${stats.blocked}<small>题</small></span><span class="metric-note">已阻塞 · 点击查看</span></button>
    <div class="summary-metric"><span class="metric-label">已解题目分值</span><div class="metric-value">${stats.solvedPoints}<small>/ ${stats.points}</small></div><span class="metric-note">按本地题目状态统计</span></div>
    </div><div class="overview-meta"><span>附件 <b>${artifacts}</b></span><span>文档 / WP <b>${docs}</b></span><span>首清 <b id="statFC">—</b></span><span class="last-activity">最近活动 · ${lastActivity()}</span></div>`;
  $("#boardBlocked").onclick = () => {
    S.boardQuery = ""; S.boardCategory = "all"; S.boardStatus = "blocked";
    localStorage.removeItem("wb.boardQuery"); localStorage.removeItem("wb.boardCategory"); localStorage.setItem("wb.boardStatus", "blocked");
    renderFilters(); renderCards(); $("#boardStatus")?.focus();
  };
  $("#boardPipeline").onclick = () => setTab("pipeline");
  $("#boardCollab").onclick = () => setTab("board2");
  renderFilters(); renderCards();

  const dir = S.dir, request = ++firstClearRequest;
  api(`/api/leaderboard?dir=${encodeURIComponent(dir)}&mode=individual`).then((r) => {
    if (request !== firstClearRequest || S.dir !== dir) return;
    const fc = $("#statFC");
    if (fc) fc.textContent = (r.progress?.by_operator || []).reduce((n, o) => n + (o.first_clears || 0), 0);
  }).catch(() => { /* Unknown is not the same as zero; retain the dash. */ });
  if (runningDir !== dir || Date.now() - runningFetched > 10000) {
    runningFetched = Date.now(); runningDir = dir; runningBySlug = {};
    const taskRequest = ++runningRequest;
    api("/api/tasks?status=running").then((r) => {
      if (S.dir !== dir || taskRequest !== runningRequest) return;
      const nextRunning = {};
      for (const t of r.tasks || []) {
        if (t.slug && t.dir === dir) (nextRunning[t.slug] ||= []).push(t);
      }
      runningBySlug = nextRunning;
      if (localStorage.getItem("wb.tab") === "board") renderCards();
    }).catch(() => {});
  }
}
