/* CTF Workbench 前端（原生 JS，无构建步骤）
 * 数据源：/api/*（由 workbench/server.py 提供），写操作全部经既有脚本执行。
 * G6：主题切换 / 面包屑 / 最近题目 / 焦点圈闭 / 3 新视图接线。 */
"use strict";

import { S } from "./state.js";
import { api, post } from "./api.js";
import { $, $$, esc, toast, busy, openModal, closeModal, skeletonGrid } from "./ui.js";
import { stopEventStream } from "./sse.js";
import { renderBoard } from "./views/board.js";
import { renderDetail, updateCatSubnav } from "./views/detail.js";
import { renderFlags } from "./views/flags.js";
import { renderTimeline } from "./views/timeline.js";
import { renderFiles } from "./views/files.js";
import { renderKb } from "./views/kb.js";
import { renderDocs } from "./views/docs.js";
import { renderOps } from "./views/ops.js";
import { renderTasks, TaskUI } from "./views/tasks.js";
import { renderHealth } from "./views/health.js";
import { renderBoard2 } from "./views/board2.js";
import { renderLeaderboard } from "./views/leaderboard.js";
import { renderAchievements } from "./views/achievements.js";
import { renderResources } from "./views/resources.js";

/* ---------------- 顶部与标签页 ---------------- */
export function setTab(name) {
  $$("#tabs button").forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "view-" + name));
  localStorage.setItem("wb.tab", name);
  if (name !== "timeline") stopEventStream();
  if (name !== "tasks") clearTimeout(TaskUI.timer);
  updateCatSubnav();
  renderBreadcrumb();
  renderCurrent();
  // 视图切换淡入动效
  const view = $("#view-" + name);
  if (view && view.animate) {
    view.animate(
      [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }],
      { duration: 180, easing: "ease-out" }
    );
  }
}
function renderCurrent() {
  const name = localStorage.getItem("wb.tab") || "board";
  if (name !== "detail") S.preserveForms = false; /* 表单快照只服务详情页，切页即失效 */
  ({ board: renderBoard, detail: renderDetail, flags: renderFlags, timeline: renderTimeline,
     files: renderFiles, kb: renderKb, docs: renderDocs, ops: renderOps,
     tasks: renderTasks, health: renderHealth, board2: renderBoard2,
     leaderboard: renderLeaderboard, achievements: renderAchievements,
     resources: renderResources }[name] || renderBoard)();
}

/* ---------------- 面包屑与最近题目 ---------------- */
function renderBreadcrumb() {
  const el = $("#detailBreadcrumb");
  if (!el) return;
  const tab = localStorage.getItem("wb.tab") || "board";
  if (tab !== "detail") { el.innerHTML = ""; return; }
  const parts = [S.comp?.name || "比赛"];
  if (S.slug) {
    const ch = S.comp?.challenges.find((c) => c.slug === S.slug);
    parts.push(ch?.name || S.slug);
  }
  el.innerHTML = parts.map((p, i) =>
    `<span class="crumb ${i === parts.length - 1 ? "last" : ""}">${esc(p)}</span>` +
    (i < parts.length - 1 ? `<span class="sep" aria-hidden="true">›</span>` : "")
  ).join("");
}
function pushRecent(slug, name) {
  if (!slug) return;
  const list = JSON.parse(localStorage.getItem("wb.recent") || "[]")
    .filter((x) => x.slug !== slug);
  list.unshift({ slug, name, t: Date.now() });
  localStorage.setItem("wb.recent", JSON.stringify(list.slice(0, 5)));
}
function renderRecentChips() {
  const el = $("#recentChips");
  if (!el) return;
  const list = JSON.parse(localStorage.getItem("wb.recent") || "[]");
  if (!list.length || !S.comp) { el.innerHTML = ""; return; }
  el.innerHTML = list.map((x) =>
    `<button class="chip" data-slug="${esc(x.slug)}" title="${esc(x.name)}">${esc(x.name)}</button>`
  ).join("");
  $$("#recentChips .chip").forEach((b) => b.onclick = async () => {
    await loadCase(b.dataset.slug);
    pushRecent(b.dataset.slug, S.comp?.challenges.find((c) => c.slug === b.dataset.slug)?.name || b.dataset.slug);
    setTab("detail");
  });
}

/* ---------------- 主题切换 ---------------- */
function initTheme() {
  const btn = $("#themeBtn");
  if (!btn) return;
  const update = () => {
    const t = document.documentElement.dataset.theme || "dark";
    btn.querySelector(".ic").textContent = t === "light" ? "☀️" : "🌙";
    btn.setAttribute("aria-label", t === "light" ? "切换到深色主题" : "切换到亮色主题");
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = t === "light" ? "#f6f8fc" : "#070b12";
  };
  update();
  btn.onclick = () => {
    const cur = document.documentElement.dataset.theme || "dark";
    const next = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("wb.theme", next);
    update();
  };
  // 跟随系统主题变化（仅当用户未显式设置过）
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
      if (!localStorage.getItem("wb.theme")) {
        document.documentElement.dataset.theme = e.matches ? "light" : "dark";
        update();
      }
    });
  }
}

/* ---------------- 数据加载 ---------------- */
// 主题在 module 顶层立即应用（比 boot 早，缩短 light 用户从 dark 到 light 的闪烁）
initTheme();

async function boot() {
  const catalog = await api("/api/competitions");
  const competitions = catalog.competitions || [];
  S.competitions = competitions;
  const sel = $("#compSelect");
  sel.innerHTML = competitions.map((c) =>
    `<option value="${esc(c.dir)}">${esc(c.name)}${c.configured ? "" : "（未初始化）"}</option>`).join("")
    || "<option value=''>（比赛/ 目录为空）</option>";
  const saved = localStorage.getItem("wb.dir");
  const savedExists = saved && competitions.some((c) => c.dir === saved);
  const apiDefault = catalog.default && competitions.some((c) => c.dir === catalog.default)
    ? catalog.default : "";
  const configuredDefault = competitions.find((c) => c.configured)?.dir || "";
  const initial = savedExists ? saved : (apiDefault || configuredDefault || competitions[0]?.dir || "");
  if (initial) sel.value = initial;
  sel.onchange = async () => {
    S.dir = sel.value;
    localStorage.setItem("wb.dir", S.dir);
    S.slug = null; S.caseData = null;
    await loadCompetition();
    renderCurrent();
  };
  S.dir = sel.value || null;
  await loadCompetition();

  $$("#tabs button").forEach((b) => b.onclick = () => setTab(b.dataset.tab));
  if (localStorage.getItem("wb.collapsed") === "1") $("#sidebar").classList.add("collapsed");
  $("#collapseBtn").onclick = () => {
    const c = $("#sidebar").classList.toggle("collapsed");
    localStorage.setItem("wb.collapsed", c ? "1" : "0");
    $("#collapseBtn").textContent = c ? "»" : "« 折叠";
  };
  const helpBtn = $("#helpBtn");
  if (helpBtn) helpBtn.onclick = () => showHelp();
  setTab(localStorage.getItem("wb.tab") || "board");
  setInterval(pollTick, 3000);
  setInterval(watchSubmissions, 3000);
}

export async function loadCompetition() {
  if (!S.dir) { S.comp = null; return; }
  S.comp = await api("/api/competition?dir=" + encodeURIComponent(S.dir));
  S.syncAt = new Date();
  $("#syncInfo").innerHTML = `<span class="live-dot"></span>已同步 ${S.syncAt.toLocaleTimeString()}`;
  updateCatSubnav();
  renderRecentChips();
}

export async function loadCase(slug, quiet = false) {
  const ch = S.comp.challenges.find((c) => c.slug === slug);
  if (!ch) return;
  S.slug = slug;
  S.caseDir = (ch.case_dir || "cases/" + slug);
  try {
    S.caseData = await api(`/api/case?dir=${encodeURIComponent(S.dir)}&case_dir=${encodeURIComponent(S.caseDir)}`);
  } catch (e) {
    S.caseData = null;
    if (!quiet) toast("case.json 不存在（尚未初始化该 case）", true);
  }
  pushRecent(slug, ch.name || slug);
  renderRecentChips();
}

export async function refreshCase() {
  if (S.slug) await loadCase(S.slug);
}

/* 提交动态监听：任何页面下，真实提交（--live）发生即弹提示（抢一血反馈） */
async function watchSubmissions() {
  if (!S.dir || document.visibilityState !== "visible") return;
  try {
    const r = await api(`/api/submissions?dir=${encodeURIComponent(S.dir)}` +
                        `&after=${S.subSeen ?? -1}`);
    if (S.subSeen === null || S.subSeen === undefined) { S.subSeen = r.total; return; }
    const fresh = r.entries.filter((e) => !e.dry_run);
    if (!fresh.length) return;
    S.subSeen = r.total;
    const ok = fresh.filter((e) => e.outcome === "accepted");
    const wrong = fresh.filter((e) => e.outcome !== "accepted");
    if (ok.length) {
      const first = ok[ok.length - 1];
      toast(`🎉 ${first.challenge_slug} 已被接受！` +
            (fresh.length > 1 ? `（本时段 ${fresh.length} 条提交动态）` : ""), false);
    } else {
      const last = wrong[wrong.length - 1];
      toast(`📣 提交动态：${last.challenge_slug} → ${last.outcome}` +
            (fresh.length > 1 ? `（${fresh.length} 条）` : ""), true);
    }
    await loadCompetition();
    S.preserveForms = true;
    renderCurrent();
  } catch { /* 静默 */ }
}

let polling = false;
/* case.json 中会变化的部分做指纹，避免 _tree 等大字段抖动触发无意义重渲染 */
function caseFp() {
  const k = S.caseData;
  return JSON.stringify([k?.status, k?.updated_at,
    k?.hypotheses?.length, k?.attempts?.length,
    k?.candidates?.length, k?.evidence?.length]);
}
/* 用户正在详情区输入时不轮询重渲染，避免焦点/输入被打断（配合表单快照双保险） */
function userTypingInDetail() {
  const ae = document.activeElement, body = $("#detailBody");
  return !!(ae && body && body.contains(ae) &&
    /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName));
}
async function pollTick() {
  if (polling || document.visibilityState !== "visible" || !S.comp) return;
  const tab = localStorage.getItem("wb.tab") || "board";
  if (!["board", "timeline", "detail", "leaderboard", "achievements"].includes(tab)) return;
  if (tab === "detail" && userTypingInDetail()) return;
  polling = true;
  try {
    const before = JSON.stringify(S.comp.challenges) + JSON.stringify(S.comp.events) + caseFp();
    await loadCompetition();
    if (tab === "detail" && S.slug) await loadCase(S.slug, true);
    const after = JSON.stringify(S.comp.challenges) + JSON.stringify(S.comp.events) + caseFp();
    if (before !== after) { S.preserveForms = true; renderCurrent(); }
    // 排行榜/成就视图：SSE 缺席时降级为轮询刷新（3s 已足够，避免抖动）
    if (tab === "leaderboard" || tab === "achievements") renderCurrent();
  } catch (e) { /* 服务器暂不可达时静默 */ }
  polling = false;
}

export async function doAction(action, params, opts = {}) {
  busy(true);
  let res;
  try { res = await post(action, { dir: S.dir, ...params }); }
  finally { busy(false); }
  if (res.ok) {
    toast(`${action} ✓${opts.quiet ? "" : ""}`);
    if (!opts.noReload) { await loadCompetition(); if (S.slug) await refreshCase(); }
    renderCurrent();
    if (opts.showOutput !== false) S.result = res;
  } else {
    toast(`${action} 失败：${res.error || "exit=" + res.exit}`, true);
    S.result = res;
  }
  return res;
}

/* ---------------- 快捷键与帮助 ---------------- */
document.addEventListener("keydown", (e) => {
  if (e.altKey && e.key >= "1" && e.key <= "9") {
    const btn = $$("#tabs button")[parseInt(e.key, 10) - 1];
    if (btn) { e.preventDefault(); setTab(btn.dataset.tab); }
  } else if (e.key === "?" || (e.key === "/" && e.shiftKey)) {
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    e.preventDefault(); showHelp();
  }
});

function showHelp() {
  openModal(`
    <h3 id="modalTitle">⌨️ 快捷键与协作</h3>
    <table style="margin:10px 0">
      <tr><td><kbd>Alt</kbd>+<kbd>1..9</kbd></td><td>切换左侧页面</td></tr>
      <tr><td><kbd>?</kbd></td><td>本帮助</td></tr>
      <tr><td><kbd>Esc</kbd></td><td>关闭弹窗</td></tr>
      <tr><td>侧边栏 «</td><td>折叠/展开导航</td></tr>
    </table>
    <h3>🤖 Agent 协作端点</h3>
    <pre class="out" id="helpApi">加载 /api/help …</pre>
    <div class="row" style="margin-top:10px">
      <button id="helpClose" class="primary">关闭</button>
    </div>`);
  $("#helpClose").onclick = closeModal;
  api("/api/help").then((h) => {
    $("#helpApi").textContent = JSON.stringify(h, null, 1).slice(0, 2200);
  }).catch((e) => { $("#helpApi").textContent = e.message; });
}

/* ---------------- 启动 ---------------- */
boot().catch((e) => {
  document.body.insertAdjacentHTML("beforeend",
    `<div class="panel" style="margin:20px;color:var(--red)">初始化失败：${esc(e.message)}（server.py 未启动？）</div>`);
});
