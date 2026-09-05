/* R26：核心工具与全局状态（多 <script> 顺序加载，全局作用域与原单文件语义一致）。*/
/* 来源：app.js 头部工具块。改动需同步回归 test_workbench 与浏览器冒烟。 */
/* CTF Workbench 前端（原生 JS，无构建步骤）
 * 数据源：/api/*（由 workbench/server.py 提供），写操作全部经既有脚本执行。 */
"use strict";

const S = {
  competitions: [],
  dir: null,          // 当前比赛目录名
  comp: null,         // /api/competition 结果
  caseData: null,     // /api/case 结果
  slug: null,         // 当前题目 slug
  caseDir: null,      // 当前题目 case 相对目录
  result: null,       // 最近一次动作结果（ops 页展示）
  boardQuery: localStorage.getItem("wb.boardQuery") || "",
  boardStatus: localStorage.getItem("wb.boardStatus") || "all",
};

/* ---------------- 基础工具 ---------------- */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function fmtSize(n) {
  if (n < 0) return "?";
  if (n < 1024) return n + "B";
  if (n < 1048576) return (n / 1024).toFixed(1) + "K";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + "M";
  return (n / 1073741824).toFixed(2) + "G";
}

/* ---- 表单状态快照（详情区被后台轮询重渲染时，保留未提交输入 / 展开的 details / 焦点）----
 * 仅在后台触发的重渲染（pollTick / watchSubmissions）中启用：
 * 用户主动提交后的重渲染不回填，保持“提交后表单清空”的原有行为。 */
function snapshotDetailForms() {
  const body = $("#detailBody");
  const snap = { fields: [], open: [], focus: -1 };
  if (!body) return snap;
  body.querySelectorAll("input,select,textarea").forEach((el, i) => {
    snap.fields.push(el.type === "checkbox" || el.type === "radio" ? el.checked : el.value);
    if (el === document.activeElement) snap.focus = i;
  });
  body.querySelectorAll("details").forEach((d, i) => { if (d.open) snap.open.push(i); });
  return snap;
}
function restoreDetailForms(snap) {
  const body = $("#detailBody");
  if (!body || !snap) return;
  const els = body.querySelectorAll("input,select,textarea");
  els.forEach((el, i) => {
    if (i >= snap.fields.length) return;
    const v = snap.fields[i];
    if (el.type === "checkbox" || el.type === "radio") el.checked = v;
    else if (el.value !== v) el.value = v;
  });
  (snap.open || []).forEach((i) => {
    const d = body.querySelectorAll("details")[i];
    if (d) d.open = true;
  });
  if (snap.focus >= 0 && els[snap.focus]) {
    try { els[snap.focus].focus(); } catch (e) { /* 元素可能已被替换 */ }
  }
}
function fmtTime(t) {
  if (!t) return "";
  return String(t).replace("T", " ").slice(0, 19);
}
function toast(msg, kind = "info") {
  // kind: info | err | ok | warn —— 队列式，互不覆盖
  if (kind === true) kind = "err";
  if (kind === false) kind = "info";
  const box = $("#toasts");
  while (box.children.length >= 4) box.firstChild.remove();
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s";
    setTimeout(() => el.remove(), 320); }, kind === "err" ? 6000 : 2800);
}
function busy(on) { $("#globalBusy")?.classList.toggle("on", !!on); }

async function copyText(text, label) {
  try { await navigator.clipboard.writeText(text); toast((label || "内容") + " 已复制 ✓", "ok"); }
  catch { toast("复制失败，请手动选择", true); }
}

/* ---------------- 访问令牌（--token 共享模式） ---------------- */
function authHeaders(extra) {
  const t = localStorage.getItem("wb.token");
  const h = { ...((window.__extraHeaders) || {}), ...(extra || {}) };
  if (t) h["Authorization"] = "Bearer " + t;
  return h;
}

async function ensureToken(res, retry) {
  if (res.status !== 401) return null;
  const t = prompt("该工作台已开启令牌鉴权，请输入访问令牌（--token）：");
  if (!t) throw new Error("需要访问令牌");
  localStorage.setItem("wb.token", t.trim());
  return retry();
}

async function api(path) {
  let res = await fetch(path, { headers: authHeaders() });
  const again = await ensureToken(res, () => fetch(path, { headers: authHeaders() }));
  if (again) res = again;
  const data = await res.json().catch(() => ({ error: "bad json" }));
  if (!res.ok) throw new Error(data.error || res.status);
  return data;
}
async function post(action, params) {
  const body = JSON.stringify({ action, params });
  const doFetch = () => fetch("/api/action", {
    method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body,
  });
  let res = await doFetch();
  const again = await ensureToken(res, doFetch);
  if (again) res = again;
  return res.json().catch(() => ({ ok: false, error: "bad json" }));
}

/* ---------------- 模态框 ---------------- */
function openModal(html) {
  $("#modalBox").innerHTML = html;
  $("#modalMask").classList.remove("hidden");
}
function closeModal() { $("#modalMask").classList.add("hidden"); }

