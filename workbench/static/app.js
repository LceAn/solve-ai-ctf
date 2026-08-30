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

/* ---------------- markdown 迷你渲染 ---------------- */
function mdRender(src) {
  const lines = String(src ?? "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let inCode = false, inQuote = false, listType = null, tableBuf = [];
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\*([^*\n]+)\*/g, "<i>$1</i>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');

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

/* ---------------- 顶部与标签页 ---------------- */
function setTab(name) {
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "view-" + name));
  localStorage.setItem("wb.tab", name);
  if (name !== "timeline") stopEventStream();
  if (name !== "tasks") clearTimeout(TaskUI.timer);
  updateCatSubnav();
  renderCurrent();
}
function renderCurrent() {
  const name = localStorage.getItem("wb.tab") || "board";
  ({ board: renderBoard, detail: renderDetail, flags: renderFlags, timeline: renderTimeline,
     files: renderFiles, kb: renderKb, docs: renderDocs, ops: renderOps,
     tasks: renderTasks, health: renderHealth, board2: renderBoard2 }[name] || renderBoard)();
}

/* ---------------- 数据加载 ---------------- */
async function boot() {
  const { competitions } = await api("/api/competitions");
  S.competitions = competitions;
  const sel = $("#compSelect");
  sel.innerHTML = competitions.map((c) =>
    `<option value="${esc(c.dir)}">${esc(c.name)}${c.configured ? "" : "（未初始化）"}</option>`).join("")
    || "<option value=''>（比赛/ 目录为空）</option>";
  const saved = localStorage.getItem("wb.dir");
  if (saved && competitions.some((c) => c.dir === saved)) sel.value = saved;
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
  setTab(localStorage.getItem("wb.tab") || "board");
  setInterval(pollTick, 3000);
  setInterval(watchSubmissions, 3000);
}

async function loadCompetition() {
  if (!S.dir) { S.comp = null; return; }
  S.comp = await api("/api/competition?dir=" + encodeURIComponent(S.dir));
  S.syncAt = new Date();
  $("#syncInfo").innerHTML = `<span class="live-dot"></span>已同步 ${S.syncAt.toLocaleTimeString()}`;
  updateCatSubnav();
}

async function loadCase(slug) {
  const ch = S.comp.challenges.find((c) => c.slug === slug);
  if (!ch) return;
  S.slug = slug;
  S.caseDir = (ch.case_dir || "cases/" + slug);
  try {
    S.caseData = await api(`/api/case?dir=${encodeURIComponent(S.dir)}&case_dir=${encodeURIComponent(S.caseDir)}`);
  } catch (e) {
    S.caseData = null;
    toast("case.json 不存在（尚未初始化该 case）", true);
  }
}

async function refreshCase() {
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
    renderCurrent();
  } catch { /* 静默 */ }
}

let polling = false;
async function pollTick() {
  if (polling || document.visibilityState !== "visible" || !S.comp) return;
  const tab = localStorage.getItem("wb.tab") || "board";
  if (!["board", "timeline"].includes(tab)) return;
  polling = true;
  try {
    const before = JSON.stringify(S.comp.challenges) + JSON.stringify(S.comp.events);
    await loadCompetition();
    const after = JSON.stringify(S.comp.challenges) + JSON.stringify(S.comp.events);
    if (before !== after) renderCurrent();
  } catch (e) { /* 服务器暂不可达时静默 */ }
  polling = false;
}

async function doAction(action, params, opts = {}) {
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

/* ---------------- ① 总览 ---------------- */
const CAT_COLORS = { crypto: "#a78bfa", pwn: "#f87171", web: "#fb923c", reverse: "#fbbf24",
  forensics: "#2dd4bf", misc: "#4ade80" };
const catColor = (cat) => CAT_COLORS[String(cat || "").toLowerCase()] || "#4f8cff";

function renderBoard() {
  const el = $("#boardStats"), grid = $("#boardGrid");
  if (!S.comp) { el.innerHTML = "<p class='muted'>没有可用的比赛目录。</p>"; grid.innerHTML = ""; return; }
  const chs = S.comp.challenges || [];
  const isDone = (c) => ["solved", "submitted", "closed"].includes(c.case?.status);
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
      <div class="stat" style="--stat-c:var(--teal)"><span class="ic">📦</span><b>${(S.comp.artifacts || []).length}</b><span>artifacts</span></div>
      <div class="stat" style="--stat-c:var(--pink)"><span class="ic">📄</span><b>${(S.comp.docs || []).length}</b><span>docs</span></div>
    </div>
    <div class="progress" title="解出 ${solved}/${chs.length}（${pct}%）"><i style="width:${pct}%"></i></div>`;

  const byCat = {};
  for (const c of chs) (byCat[c.category || "misc"] ||= []).push(c);
  const catRank = { crypto: 0, pwn: 1, reverse: 2, web: 3, misc: 4, forensics: 5 };
  const cats = Object.keys(byCat).sort((a, b) => (catRank[a] ?? 9) - (catRank[b] ?? 9) || a.localeCompare(b));
  grid.innerHTML = cats.map((cat) => {
    const cc = catColor(cat);
    return `
    <div class="cat-head"><span class="chip" style="--cat:${cc}">${esc(cat.toUpperCase())}</span>
      <span class="muted">${byCat[cat].length} 题 · ${byCat[cat].reduce((a, c) => a + (c.points || 0), 0)} 分 · 已解 ${byCat[cat].filter(isDone).length}</span></div>` +
    byCat[cat].map((c) => {
      const st = c.case?.exists ? c.case.status : "no-case";
      const cands = c.case?.candidates || [];
      const valid = cands.filter((x) => ["validated", "submitted", "accepted"].includes(x.status)).length;
      return `
      <div class="ch-card" data-slug="${esc(c.slug)}" style="--cat:${cc}">
        <div class="top"><span class="dot s-${esc(st === "no-case" ? "new" : st)}" title="${esc(st)}"></span>
          <span class="name">${esc(c.name)}</span><span class="pts">${c.points ?? "?"} 分</span></div>
        <div class="meta">
          <span class="badge" style="--b-c:${({ solved: "#34d399", submitted: "#a78bfa", candidate_found: "#fb923c", in_progress: "#fbbf24", blocked: "#f87171" }[st] || "#94a3b8")}">${esc(st)}</span>
          ${c.difficulty ? `<span>${esc(c.difficulty)}</span>` : ""}
          <span>假设 ${c.case?.hypotheses ?? 0}</span><span>尝试 ${c.case?.attempts ?? 0}</span>
          ${cands.length ? `<span>候选 ${cands.length}${valid ? ` · ✓${valid}` : ""}</span>` : ""}
        </div>
        ${c.description ? `<div class="desc">${esc(c.description)}</div>` : ""}
      </div>`;
    }).join("");
  }).join("");
  if (!grid.dataset.bound) {
    grid.dataset.bound = "1";
    grid.addEventListener("click", async (e) => {
      const card = e.target.closest(".ch-card");
      if (card) { await loadCase(card.dataset.slug); setTab("detail"); }
    });
  }
}

/* ---------------- ② 题目详情（工作区式子页签） ---------------- */
const DETAIL_TABS = [
  ["overview", "概览"], ["hypo", "假设阶梯"], ["attempt", "尝试记录"], ["evidence", "证据 / 线索"],
  ["excluded", "排除 / 失败"], ["cands", "Flag 候选"], ["prompt", "提示词"], ["rules", "守则"],
];
const FLOW_STAGES = ["new", "triaged", "in_progress", "candidate_found", "solved", "submitted"];

function chOf(slug) { return S.comp?.challenges.find((c) => c.slug === slug); }

function flowHtml(status) {
  status = status || "new";
  const idx = FLOW_STAGES.indexOf(status);
  const side = ["blocked", "abandoned", "invalid", "closed"].includes(status);
  let html = "<div class='flow'>";
  FLOW_STAGES.forEach((st, i) => {
    const done = side ? i < FLOW_STAGES.length - 1 : idx > i;
    const cur = idx === i;
    html += `<span class="step ${done ? "done" : ""} ${cur ? "cur" : ""}">` +
      `<span class="dot2"></span><span class="lbl">${st}</span></span>`;
    if (i < FLOW_STAGES.length - 1) html += `<span class="lnk ${done ? "done" : ""}"></span>`;
  });
  return html + "</div>";
}

const CAT_ORDER = ["crypto", "pwn", "reverse", "web", "misc", "forensics"];

function updateCatSubnav() {
  const el = $("#catSubnav");
  if (!el) return;
  const chs = S.comp?.challenges || [];
  const counts = {};
  for (const c of chs) {
    const k = c.category || "misc";
    counts[k] = (counts[k] || 0) + 1;
  }
  // 六大标准方向常驻（按惯例排序），自定义类别追加在后
  const cats = [...CAT_ORDER, ...Object.keys(counts).filter((c) => !CAT_ORDER.includes(c))];
  const tab = localStorage.getItem("wb.tab");
  const listing = tab === "detail" && !S.slug;
  const active = localStorage.getItem("wb.pickCat") ?? "";
  const item = (cat, n, color) => {
    const dim = n === 0;
    return `<button class="subitem ${listing && active === cat ? "on" : ""} ${dim ? "zero" : ""}" data-cat="${esc(cat)}">
      <span class="cat-dot" style="background:${n ? color : "#3a465c"}"></span>
      <span class="lbl">${esc(cat)}</span><span class="cnt">${n}</span></button>`;
  };
  el.innerHTML =
    `<button class="subitem ${listing && active === "" ? "on" : ""}" data-cat="">
      <span class="cat-dot" style="background:var(--accent)"></span>
      <span class="lbl">全部</span><span class="cnt">${chs.length}</span></button>` +
    cats.map((cat) => item(cat, counts[cat] || 0, catColor(cat))).join("");
  $$("#catSubnav .subitem[data-cat]").forEach((b) => b.onclick = () => {
    localStorage.setItem("wb.pickCat", b.dataset.cat);
    S.slug = null; S.caseData = null;
    setTab("detail");
  });
}

function renderDetailPicker() {
  const pick = $("#detailPick");
  if (!S.comp || !S.comp.challenges.length) { pick.innerHTML = ""; return; }
  const chs = S.comp.challenges;
  const counts = {};
  for (const c of chs) {
    const k = c.category || "misc";
    counts[k] = (counts[k] || 0) + 1;
  }
  const cats = [...CAT_ORDER, ...Object.keys(counts).filter((c) => !CAT_ORDER.includes(c))];
  S.pickCat = localStorage.getItem("wb.pickCat") ?? "";
  const filtered = S.pickCat ? chs.filter((c) => (c.category || "misc") === S.pickCat) : chs;
  const cnt = (cat) => counts[cat] || 0;
  pick.innerHTML = `
    <span class="muted" style="white-space:nowrap">方向</span>
    <select id="pickCat" style="min-width:150px">
      <option value="">全部方向（${chs.length} 题）</option>
      ${cats.map((cat) => `<option value="${esc(cat)}" ${S.pickCat === cat ? "selected" : ""}>
        ${esc(cat)}（${cnt(cat)}）</option>`).join("")}
    </select>
    <span class="muted">题目</span>
    <select id="pickChall" style="min-width:260px">
      ${filtered.map((c) => `<option value="${esc(c.slug)}" ${c.slug === S.slug ? "selected" : ""}>
        ${esc(c.name)} · ${esc(c.category)} · ${c.points ?? "?"}分 · ${esc(c.case?.status || "no-case")}</option>`).join("")
      || "<option value=''>（该方向暂无题目）</option>"}
    </select>
    ${S.slug ? "" : `<span class="muted">← 选择题目进入工作区</span>`}`;
  $("#pickCat").onchange = (e) => {
    localStorage.setItem("wb.pickCat", e.target.value);
    renderDetail();
  };
  $("#pickChall").onchange = async (e) => {
    if (!e.target.value) return;
    await loadCase(e.target.value);
    renderDetail();
  };
}

function renderDetail() {
  const head = $("#detailHead"), tabs = $("#detailSubtabs"), body = $("#detailBody");
  if (!S.comp) { head.innerHTML = tabs.innerHTML = body.innerHTML = ""; return; }
  renderDetailPicker();
  if (!S.slug) {
    head.innerHTML = "";
    tabs.innerHTML = "";
    const pickCat = localStorage.getItem("wb.pickCat") ?? "";
    const filtered = pickCat
      ? S.comp.challenges.filter((c) => (c.category || "misc") === pickCat)
      : S.comp.challenges;
    const catLbl = pickCat ? `${esc(pickCat)} 方向` : "全部方向";
    body.innerHTML = `
      <div class="panel">
        <h3>${catLbl}题目列表 <span class="muted">${filtered.length} 题 · 点击进入工作区</span></h3>
        ${filtered.length ? filtered.map((c) => `
          <div class="ready-row" style="cursor:pointer" data-slug="${esc(c.slug)}">
            <span class="dot s-${esc(c.case?.status || "new")}"></span>
            <div style="flex:1;min-width:0">
              <div style="font-weight:600">${esc(c.name)}
                <span class="badge" style="--b-c:${catColor(c.category)};margin-left:8px">${esc(c.category || "misc")}</span></div>
              <div class="muted">${c.points ?? "?"} 分 · ${esc(c.difficulty || "?")} ·
                假设 ${c.case?.hypotheses ?? 0} · 尝试 ${c.case?.attempts ?? 0} ·
                候选 ${c.case?.candidates?.length ?? 0}</div>
            </div>
            <span class="badge" style="--b-c:#fbbf24">${esc(c.case?.status || "no-case")}</span>
            <button class="small primary" data-enter="${esc(c.slug)}">进入 →</button>
          </div>`).join("")
          : `<div class="empty"><div class="big">🎯</div>
              ${esc(pickCat || "全部方向")}暂无题目
              <div style="margin-top:12px">
                <button class="small primary" data-goreg>去「比赛管理」注册题目</button>
                ${pickCat ? `<button class="small" data-golall>看全部方向</button>` : ""}
              </div></div>`}
      </div>`;
    const go = $("#detailBody [data-goreg]");
    if (go) go.onclick = () => { localStorage.setItem("wb.otab", "register"); setTab("ops"); };
    const gall = $("#detailBody [data-golall]");
    if (gall) gall.onclick = () => { localStorage.setItem("wb.pickCat", ""); renderDetail(); };
    $$("#detailBody .ready-row[data-slug], #detailBody button[data-enter]").forEach((n) =>
      n.onclick = async (e) => {
        e.stopPropagation();
        const slug = n.dataset.slug || n.closest("[data-slug]")?.dataset.slug;
        await loadCase(slug);
        renderDetail();
      });
    return;
  }
  const c = chOf(S.slug);
  const k = S.caseData;
  const enums = S.comp.enums;
  const status = k?.status;
  head.innerHTML = `
    <div class="panel">
      <div class="top" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <span class="dot s-${esc(status || "new")}"></span>
        <b style="font-size:16px">${esc(c.name)}</b>
        <span class="muted">${esc(c.slug)} · ${esc(c.category)} · ${c.points ?? "?"}分 · ${esc(c.difficulty || "?")}</span>
        <span class="spacer" style="flex:1"></span>
        <select id="statusSel">${enums.statuses.map((s) =>
          `<option value="${esc(s)}" ${s === status ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <button id="statusBtn" class="small">更新状态</button>
        <button id="triageBtn" class="small">分诊附件</button>
        <button id="scanBtn" class="small">扫描 flag</button>
        <button id="writeupBtn" class="small">生成 WP 草稿</button>
        <button id="summaryBtn" class="small">生成总结</button>
      </div>
      ${k?.blocked_on ? `<p style="color:var(--red);margin:6px 0 0">⛔ blocked：${esc(k.blocked_on)}</p>` : ""}
    </div>`;
  $("#statusBtn").onclick = () => doAction("case.status",
    { case_dir: S.caseDir, status: $("#statusSel").value });
  $("#triageBtn").onclick = async () => {
    const t = prompt("要分诊的目标（比赛目录内相对路径，如 artifacts/xxx.zip 或 case 内路径）：", `${S.caseDir}/artifacts`);
    if (t) doAction("case.triage", { case_dir: S.caseDir, target: t });
  };
  $("#scanBtn").onclick = async () => {
    const r = prompt("扫描根目录（比赛目录内相对路径）：", S.caseDir);
    if (r) doAction("case.scan_flags", { case_dir: S.caseDir, search_root: r, store: true });
  };
  $("#summaryBtn").onclick = () => doAction("case.summary", { case_dir: S.caseDir });
  $("#writeupBtn").onclick = () => doAction("case.writeup", { case_dir: S.caseDir });

  S.dtab = localStorage.getItem("wb.dtab") || "overview";
  tabs.innerHTML = DETAIL_TABS.map(([id, label]) =>
    `<button data-st="${id}" class="${S.dtab === id ? "on" : ""}">${label}</button>`).join("");
  $$("#detailSubtabs button").forEach((b) => b.onclick = () => {
    S.dtab = b.dataset.st;
    localStorage.setItem("wb.dtab", S.dtab);
    renderDetail();
  });
  ({ overview: dOverview, hypo: dHypo, attempt: dAttempt, evidence: dEvidence,
     excluded: dExcluded, cands: dCands, prompt: dPrompt, rules: dRules }[S.dtab] || dOverview)(c, k);
}

/* ---- 概览：状态流 + 题面 + 分诊摘要 + 工作区统计 ---- */
async function dOverview(c, k) {
  const body = $("#detailBody");
  const files = k?._tree?.filter((f) => f.type === "file").length ?? 0;
  const evs = (k?.events || []).slice(-8).reverse();
  body.innerHTML = `
    <div class="panel"><h3>进度（${esc(k?.status || "new")}）</h3>${flowHtml(k?.status)}
      ${k?.blocked_on ? `<p style="color:var(--red);margin:4px 0 0">⛔ blocked：${esc(k.blocked_on)}</p>` : ""}</div>
    <div class="cols">
      <div class="col-main">
        <div class="panel"><h3>题面</h3><p style="margin:0;white-space:pre-wrap">${esc(c.description || "（无题面描述）")}</p></div>
        <div class="panel"><h3>分诊摘要 <span class="muted">triage.json（static-only）</span></h3>
          <div id="ovTri" class="muted">读取中…（未分诊则点上方「分诊附件」）</div></div>
      </div>
      <div class="col-side">
        <div class="panel"><h3>工作区</h3>
          <p class="muted" style="margin:0 0 8px">比赛/${esc(S.dir)}/${esc(S.caseDir)}</p>
          <div class="stats" style="margin:0">
            <div class="stat"><b>${k?.hypotheses?.length ?? 0}</b><span>假设</span></div>
            <div class="stat"><b>${k?.attempts?.length ?? 0}</b><span>尝试</span></div>
            <div class="stat"><b>${k?.candidates?.length ?? 0}</b><span>候选</span></div>
            <div class="stat"><b>${files}</b><span>文件</span></div>
          </div>
          <button id="gotoFiles" class="small" style="margin-top:10px">打开文件浏览 →</button>
        </div>
        <div class="panel"><h3>最近动态</h3>
          <div class="tl">${evs.map((e) => `<div class="tl-item">
            <span class="tl-time">${esc(fmtTime(e.time))}</span><span class="tl-kind">${esc(e.kind)}</span>
            <span class="tl-detail">${esc(JSON.stringify(e.detail || {}).slice(0, 90))}</span></div>`).join("")
            || "<p class='muted'>暂无事件。</p>"}</div>
        </div>
      </div>
    </div>`;
  $("#gotoFiles").onclick = () => setTab("files");
  try {
    const r = await api(`/api/file?dir=${encodeURIComponent(S.dir)}&path=${encodeURIComponent(S.caseDir + "/triage.json")}`);
    const t = JSON.parse(r.content);
    const rows = (t.files || []).slice(0, 10).map((f) =>
      `<div>${esc(f.path)} <span class="muted">${fmtSize(f.size)} · ${esc(f.suffix || "?")} · ` +
      `${esc(String(f.sha256 || "").slice(0, 10))}</span></div>`).join("");
    $("#ovTri").innerHTML =
      `<p class="muted" style="margin:0 0 4px">${esc(t.execution_policy || "")} · 共 ${t.file_count ?? "?"} 项</p>` +
      (t.classification ? `<p class="muted" style="margin:0 0 6px">类别判定：${esc(JSON.stringify(t.classification))}</p>` : "") +
      `<div class="triage-files">${rows}</div>` +
      (t.warnings || []).map((w) => `<p style="color:var(--yellow);margin:6px 0 0">⚠ ${esc(w)}</p>`).join("");
  } catch (e) {
    $("#ovTri").innerHTML = "<span class='muted'>尚无 triage.json（附件未分诊）。</span>";
  }
}

/* ---- 假设阶梯 ---- */
function dHypo(c, k) {
  const hyps = k?.hypotheses || [];
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>假设阶梯（${hyps.length}）</h3>
      ${hyps.length ? `<table><tr><th>ID</th><th>状态</th><th>假设</th><th>优先级</th><th>预期信号</th><th>预算</th></tr>
        ${hyps.map((h) => `<tr><td class="wrap">${esc(h.id)}</td>
          <td><span class="badge b-${esc(h.status)}">${esc(h.status)}</span></td>
          <td class="wrap"><b>${esc(h.title)}</b><br><span class="muted">${esc(h.rationale || "")}</span></td>
          <td>${h.priority ?? ""}</td><td class="wrap muted">${esc(h.expected || "")}</td>
          <td class="muted">${h.minutes ?? ""}分</td></tr>`).join("")}
        </table>` : "<p class='muted'>尚无假设。先登记 3–7 条再动手（SKILL.md 阶段 3）。</p>"}
      <details><summary class="muted">＋ 登记假设</summary>
        <form id="hypForm" class="grid">
          <label class="f">标题<input name="title" required></label>
          <label class="f">依据<input name="rationale" required></label>
          <label class="f">预期信号<input name="expected" required></label>
          <label class="f">预算(分钟)<input name="minutes" type="number" value="15" step="1"></label>
          <label class="f">优先级<input name="priority" type="number" value="1.0" step="0.1"></label>
          <div class="full"><button class="primary">登记</button></div>
        </form></details>
    </div>`;
  $("#hypForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const r = await doAction("case.hypothesis", {
      case_dir: S.caseDir, title: f.get("title"), rationale: f.get("rationale"),
      expected: f.get("expected"), minutes: f.get("minutes"), priority: f.get("priority"),
    });
    if (r.ok) { await refreshCase(); renderDetail(); }
  };
}

/* ---- 尝试记录 ---- */
function dAttempt(c, k) {
  const enums = S.comp.enums;
  const atts = k?.attempts || [];
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>尝试记录（${atts.length}）</h3>
      ${atts.length ? `<table><tr><th>时间</th><th>假设</th><th>动作 → 结果</th><th>结局</th></tr>
        ${atts.slice(-25).reverse().map((a) => `<tr><td class="muted">${esc(fmtTime(a.time))}</td>
          <td class="wrap">${esc(a.hypothesis || "")}</td>
          <td class="wrap">${esc(a.action || "")} <span class="muted">→ ${esc(a.result || "")}</span></td>
          <td><span class="badge b-${esc(a.outcome)}">${esc(a.outcome)}</span></td></tr>`).join("")}
        </table>` : "<p class='muted'>尚无尝试记录。</p>"}
      <details><summary class="muted">＋ 登记尝试</summary>
        <form id="attForm" class="grid">
          <label class="f">执行者<input name="agent" value="主Agent" style="width:110px"></label>
          <label class="f">假设 ID<input name="hypothesis" placeholder="H0001" required></label>
          <label class="f">动作<input name="action" required></label>
          <label class="f">结果<input name="result" required></label>
          <label class="f">结局<select name="outcome">${enums.outcomes.map((o) =>
            `<option>${esc(o)}</option>`).join("")}</select></label>
          <label class="f">假设状态转移<select name="hypothesis_status"><option value="">（不变）</option>
            ${enums.hypothesis_statuses.map((o) => `<option>${esc(o)}</option>`).join("")}</select></label>
          <div class="full"><button class="primary">登记</button></div>
        </form></details>
    </div>`;
  $("#attForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const agent = (f.get("agent") || "").trim();
    const params = { case_dir: S.caseDir, hypothesis: f.get("hypothesis"),
      action: (agent ? `[${agent}] ` : "") + f.get("action"),
      result: f.get("result"), outcome: f.get("outcome") };
    if (f.get("hypothesis_status")) params.hypothesis_status = f.get("hypothesis_status");
    const r = await doAction("case.attempt", params);
    if (r.ok) { await refreshCase(); renderDetail(); }
  };
}

/* ---- 证据 / 线索 ---- */
function dEvidence(c, k) {
  const enums = S.comp.enums;
  const evs = k?.evidence || [];
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>证据 / finding（${evs.length}）</h3>
      ${evs.length ? `<table><tr><th>时间</th><th>类型</th><th>置信</th><th>结论</th><th>来源</th></tr>
        ${evs.slice(-20).reverse().map((e) => `<tr><td class="muted">${esc(fmtTime(e.time))}</td>
          <td>${esc(e.kind || "")}</td><td>${e.confidence ?? ""}</td>
          <td class="wrap">${esc(e.claim || "")}</td>
          <td class="wrap muted">${esc(e.source || "")}</td></tr>`).join("")}
        </table>` : "<p class='muted'>尚无证据。</p>"}
      <details><summary class="muted">＋ 登记证据</summary>
        <form id="findForm" class="grid">
          <label class="f">结论<input name="claim" required></label>
          <label class="f">来源<input name="source" required></label>
          <label class="f">置信度<input name="confidence" type="number" step="0.1" value="0.5" min="0" max="1"></label>
          <label class="f">类型<select name="kind"><option>observation</option><option>inference</option>
            <option>confirmation</option><option>warning</option></select></label>
          <div class="full"><button class="primary">登记</button></div>
        </form></details>
    </div>`;
  $("#findForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const r = await doAction("case.finding", {
      case_dir: S.caseDir, claim: f.get("claim"), source: f.get("source"),
      confidence: f.get("confidence"), kind: f.get("kind"),
    });
    if (r.ok) { await refreshCase(); renderDetail(); }
  };
}

/* ---- 排除 / 失败（老面板「排除」页签） ---- */
function dExcluded(c, k) {
  const hyps = (k?.hypotheses || []).filter((h) => ["rejected", "parked"].includes(h.status));
  const atts = (k?.attempts || []).filter((a) => ["failure", "error"].includes(a.outcome));
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>已排除假设（${hyps.length}）</h3>
      ${hyps.length ? `<table><tr><th>ID</th><th>状态</th><th>假设</th><th>排除依据</th></tr>
        ${hyps.map((h) => `<tr><td>${esc(h.id)}</td>
          <td><span class="badge b-${esc(h.status)}">${esc(h.status)}</span></td>
          <td class="wrap"><b>${esc(h.title)}</b></td>
          <td class="wrap muted">${esc(h.rationale || "")}</td></tr>`).join("")}</table>`
        : "<p class='muted'>暂无排除记录。rejected / parked 的假设会出现在这里，避免重复踩坑。</p>"}
    </div>
    <div class="panel"><h3>失败 / 出错尝试（${atts.length}）</h3>
      ${atts.length ? `<table><tr><th>时间</th><th>假设</th><th>动作 → 结果</th><th>结局</th></tr>
        ${atts.slice(-25).reverse().map((a) => `<tr><td class="muted">${esc(fmtTime(a.time))}</td>
          <td class="wrap">${esc(a.hypothesis || "")}</td>
          <td class="wrap">${esc(a.action || "")} <span class="muted">→ ${esc(a.result || "")}</span></td>
          <td><span class="badge b-${esc(a.outcome)}">${esc(a.outcome)}</span></td></tr>`).join("")}</table>`
        : "<p class='muted'>暂无失败尝试。</p>"}
    </div>`;
}

/* ---- Flag 候选（页内快审） ---- */
function dCands(c, k) {
  const cands = k?.candidates || [];
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>Flag 候选（${cands.length}）
      <span class="muted">unverified → validated 后才可提交</span></h3>
      ${cands.length ? `<table><tr><th>ID</th><th>值</th><th>状态</th><th>操作</th></tr>
        ${cands.map((x) => {
          const btns = [];
          if (x.status === "unverified") btns.push(`<button class="small primary" data-a="validate" data-id="${esc(x.id)}">✓ 校验通过</button>`);
          if (x.status === "unverified" || x.status === "validated") btns.push(`<button class="small" data-a="reject" data-id="${esc(x.id)}">✗ 驳回</button>`);
          if (x.status === "validated") btns.push(`<button class="small danger" data-a="submit" data-id="${esc(x.id)}">提交…</button>`);
          return `<tr><td class="wrap">${esc(x.id)}</td>
            <td class="wrap" style="font-family:var(--mono)">${esc(x.value)}</td>
            <td><span class="badge b-${esc(x.status)}">${esc(x.status)}</span></td>
            <td><div class="row" style="margin:0">${btns.join("")}</div></td></tr>`;
        }).join("")}</table>
        <button id="gotoFlags" class="small" style="margin-top:8px">完整审核队列 →</button>`
        : "<p class='muted'>暂无候选：可先「扫描 flag」，或由 Agent 经 case.candidate 登记。</p>"}
    </div>`;
  $("#gotoFlags").onclick = () => setTab("flags");
  $$("#detailBody button[data-a]").forEach((b) => b.onclick = async () => {
    const cand = cands.find((x) => x.id === b.dataset.id);
    if (b.dataset.a === "validate") doAction("case.candidate",
      { case_dir: S.caseDir, candidate_id: b.dataset.id, candidate_status: "validated" });
    else if (b.dataset.a === "reject") doAction("case.candidate",
      { case_dir: S.caseDir, candidate_id: b.dataset.id, candidate_status: "rejected", note: "人工驳回" });
    else openSubmitModal(c, cand);
  });
}

/* ---- 提示词（多模板，老面板 PROMPT_TPL 的延伸） ---- */
async function dPrompt(c, k) {
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>给解题 Agent 的提示词</h3>
      <div class="row">模板
        <select id="pStyle">
          <option value="continue">继续当前进度</option>
          <option value="fresh">开局接管（全新假设）</option>
          <option value="submit">验证与提交（只验证不提交）</option>
          <option value="review">复盘总结（WP/根因/知识沉淀）</option>
        </select>
        <button id="pGen" class="primary">生成</button>
        <button id="pCopy">复制</button>
        <a class="muted" href="/api/help" target="_blank">HTTP API（供局域网/Tailscale 上的其他 Agent 协作）</a>
      </div>
      <pre id="promptOut" class="prompt-pre">选择模板后点「生成」。</pre>
    </div>`;
  const gen = async () => {
    $("#promptOut").textContent = "生成中…";
    try {
      const r = await api(`/api/prompt?dir=${encodeURIComponent(S.dir)}&slug=${encodeURIComponent(S.slug)}` +
        `&style=${$("#pStyle").value}`);
      $("#promptOut").textContent = r.prompt;
    } catch (e) { $("#promptOut").textContent = "生成失败：" + e.message; }
  };
  $("#pGen").onclick = gen;
  $("#pCopy").onclick = async () => {
    try { await navigator.clipboard.writeText($("#promptOut").textContent); toast("已复制 ✓"); }
    catch { toast("复制失败，请手动选择", true); }
  };
  gen();
}

/* ---- 守则（老面板「守则」页签，源自 SKILL.md） ---- */
function dRules() {
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>解题守则（solve-ai-ctf/SKILL.md）</h3><ol style="line-height:2">
      <li><b>先分诊，后动手</b>：未知附件只做静态分诊（triage.py），绝不直接执行或解压。</li>
      <li><b>假设先行</b>：3–7 条假设登记后再执行，每条带预期信号与停止条件、时间预算。</li>
      <li><b>有界执行</b>：每个 attempt 记录动作、结果、结局，并同步假设状态转移（running/supported/rejected/parked）。</li>
      <li><b>证据优先</b>：结论必须有 finding 支撑，置信度如实标注。</li>
      <li><b>flag 三关</b>：scan-flags 登记 → validate 校验 → candidate 推进；提交默认 dry-run，<b>--live 必须人工确认</b>。</li>
      <li><b>凭证入环境变量</b>：平台 Token/密码绝不写入任何文件或提交历史。</li>
      <li><b>复盘入库</b>：完成后写 WP 与 summary，沉淀根因与最小复现，供 kb_search 检索。</li>
    </ol>
    <blockquote>自动化的价值不是尝试得更多，而是每次尝试都产生可复用的信息。</blockquote>
    </div>`;
}

/* ---------------- ②b AI 看板（多 Agent 泳道时间线，源自老 warroom v4） ---------------- */
const AGENT_PALETTE = ["#58a6ff", "#3fb950", "#e0823d", "#bc8cff", "#f85149", "#d29922", "#4dd0e1", "#ec6bc5"];
const EV_COLORS = { hypothesis_added: "#d29922", evidence_added: "#58a6ff", status_changed: "#e0823d",
  attempt_logged: "#bc8cff", candidate_found: "#3fb950", case_initialized: "#6e7681" };

function agentColor(name) {
  let h = 0;
  for (const ch of String(name || "")) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return AGENT_PALETTE[h % AGENT_PALETTE.length];
}

async function renderBoard2() {
  const wrap = $("#boardWrap"), legend = $("#boardLegend");
  if (!S.comp) { wrap.innerHTML = "<p class='muted'>请先选择比赛。</p>"; return; }
  const hours = $("#boardHours")?.value || 24;
  wrap.innerHTML = "<p class='muted'>加载看板数据…</p>";
  let d;
  try {
    d = await api(`/api/board?dir=${encodeURIComponent(S.dir)}&hours=${hours}`);
  } catch (e) { wrap.innerHTML = `<p style="color:var(--red)">${esc(e.message)}</p>`; return; }
  legend.innerHTML = "图例：" +
    Object.entries(EV_COLORS).map(([k, c]) => `<span class="legend-dot" style="background:${c}"></span>${k}`).join("") +
    `<span class="legend-dot" style="background:var(--green)"></span>任务(running)
     <span class="legend-dot" style="background:var(--gray)"></span>任务(ended)`;

  const lanes = d.lanes || [];
  if (!lanes.length) {
    wrap.innerHTML = `<div class="panel"><p class='muted'>时间窗内（近 ${esc(hours)} 小时）没有题目事件或任务。
      派发任务或在题目页登记假设/尝试后，这里会出现多 Agent 泳道。</p></div>`;
    return;
  }
  const W = 1400, LBL = 210, ROW = 46, TOP = 34;
  const t0 = d.now - d.window_hours * 3600, t1 = d.now;
  const x = (t) => LBL + ((t - t0) / (t1 - t0)) * (W - LBL - 30);
  const H = TOP + lanes.length * ROW + 16;
  const parts = [];
  // 时间网格
  for (let i = 0; i <= 6; i++) {
    const t = t0 + ((t1 - t0) * i) / 6;
    const gx = x(t);
    const label = new Date(t * 1000).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    parts.push(`<line x1="${gx}" y1="${TOP - 8}" x2="${gx}" y2="${H - 8}" stroke="#30363d" stroke-dasharray="3 4"/>`);
    parts.push(`<text x="${gx}" y="${TOP - 14}" fill="#8b949e" font-size="11" text-anchor="middle">${esc(label)}</text>`);
  }
  lanes.forEach((lane, li) => {
    const y = TOP + li * ROW;
    parts.push(`<line x1="0" y1="${y + ROW - 8}" x2="${W}" y2="${y + ROW - 8}" stroke="#21262d"/>`);
    const sub = lane.kind === "task" ? `task ${esc(lane.id)} · ${esc(lane.status)}` : esc(lane.status || "");
    parts.push(`<text x="12" y="${y + 20}" fill="#e6edf3" font-size="12.5" font-weight="600">${esc(lane.label)}</text>`);
    parts.push(`<text x="12" y="${y + 34}" fill="#8b949e" font-size="10.5">${sub}</text>`);
    if (lane.kind === "task") {
      const color = agentColor(lane.agent);
      const x1 = Math.max(x(lane.start), LBL), x2 = Math.min(x(lane.end || d.now), W - 20);
      const running = lane.status === "running";
      parts.push(`<rect x="${x1}" y="${y + 10}" width="${Math.max(x2 - x1, 6)}" height="18" rx="9"
        fill="${running ? color : "#6e7681"}" opacity="${running ? 0.9 : 0.55}"/>`);
      parts.push(`<circle cx="${x1}" cy="${y + 19}" r="4" fill="${color}"/>
        <text x="${x1 + 10}" y="${y + 23}" fill="#0d1117" font-size="10" font-weight="700">${esc(lane.agent || "")}</text>`);
    } else {
      for (const ev of lane.events || []) {
        const cx = x(ev.ts), cy = y + 19;
        parts.push(`<circle cx="${cx}" cy="${cy}" r="5.5" fill="${EV_COLORS[ev.kind] || "#8b949e"}" opacity="0.92">
          <title>${esc(ev.kind)} ${esc(fmtTime(new Date(ev.ts * 1000).toISOString()))}</title></circle>`);
      }
    }
  });
  wrap.innerHTML = `<div class="swimlane"><svg viewBox="0 0 ${W} ${H}" width="100%" style="min-width:900px">
    ${parts.join("")}</svg></div>`;
  $("#boardRefresh").onclick = renderBoard2;
  $("#boardHours").onchange = renderBoard2;
}
/* ---------------- ③ Flag 审核（状态流水线） ---------------- */
let hunterTimer = null;

function pipeStep(label, n, color) {
  return `<div class="pipe-step" ${color ? `style="--pc:${color}"` : ""}>
    <b style="${color ? `color:${color}` : ""}">${n}</b><span class="lbl">${label}</span></div>`;
}

function candRow({ ch, x }, actions) {
  return `<tr><td>${esc(ch.name)}</td><td class="wrap">${esc(x.id)}</td>
    <td class="wrap mono">${esc(x.value)}</td>
    <td class="wrap muted">${esc(x.note || "")}</td>
    <td><div class="row" style="margin:0">${actions}</div></td></tr>`;
}

function renderFlags() {
  const el = $("#flagsWrap");
  if (!S.comp) { el.innerHTML = ""; return; }
  const all = [];
  for (const c of S.comp.challenges)
    for (const x of c.case?.candidates || []) all.push({ ch: c, x });
  const by = (sts) => all.filter((r) => sts.includes(r.x.status));
  const unv = by(["unverified"]), val = by(["validated"]),
        subm = by(["submitted"]), acc = by(["accepted"]), rej = by(["rejected"]);

  el.innerHTML = `
    <div class="panel">
      <h3>Flag 流水线 <span class="muted">每个候选只出现在它所处的状态分区</span></h3>
      <div class="pipe">
        ${pipeStep("扫描发现", all.length, "#8b96a8")}
        <span class="pipe-arrow">→</span>
        ${pipeStep("待校验", unv.length, "#fbbf24")}
        <span class="pipe-arrow">→</span>
        ${pipeStep("可提交", val.length, "#34d399")}
        <span class="pipe-arrow">→</span>
        ${pipeStep("已提交", subm.length, "#a78bfa")}
        <span class="pipe-arrow">→</span>
        ${pipeStep("已接受", acc.length, "#34d399")}
        <span class="pipe-arrow" title="rejected">⌫</span>
        <span class="muted" style="font-size:11px">驳回 ${rej.length}</span>
      </div>
      <div class="row" style="margin:14px 0 0">
        <button id="hunterBtn" class="primary">🚩 启动猎手扫描</button>
        <label class="row" style="margin:0;gap:6px;flex-wrap:nowrap">
          <input type="checkbox" id="autoSub">
          <span class="muted" style="white-space:nowrap">自动提交 · 抢一血（默认开，dry-run 通过即 --live）</span>
        </label>
        <label class="muted" style="white-space:nowrap">每轮上限 <input id="maxLive" type="number" value="3" min="1" max="10" style="width:56px"></label>
        <span class="spacer" style="flex:1"></span>
        <span id="hunterState" class="muted"></span>
      </div>
      <p class="muted" style="margin:6px 0 0">猎手自主扫描全部 case 并校验；「可提交」区逐枚放行，或开启自动提交（受每轮限额 + submitter 限速/去重保护）。</p>
      <details id="hunterDetails" class="hidden" style="margin-top:8px">
        <summary class="sec-sum muted">猎手实时输出</summary>
        <pre class="out" id="hunterOut" style="max-height:180px"></pre>
      </details>
    </div>

    <div class="panel">
      <h3>✅ 可用标志（已验证，可提交）<span class="muted">${val.length} 枚</span></h3>
      ${val.length ? val.map(({ ch, x }) => `
        <div class="ready-row">
          <span class="dot s-solved"></span>
          <div style="flex:1;min-width:0">
            <div class="mono" style="font-size:13.5px;word-break:break-all">${esc(x.value)}</div>
            <div class="muted">${esc(ch.name)} · ${esc(x.id)} · ${esc(x.note || "人工/代理校验")}</div>
          </div>
          <button class="small copy-btn" data-copy="${esc(x.value)}">复制</button>
          <button class="small danger" data-a="submit" data-ch="${esc(ch.slug)}" data-id="${esc(x.id)}">提交…</button>
        </div>`).join("")
        : `<div class="empty"><div class="big">🎯</div>暂无可用标志：启动猎手自主识别，或在下方「待人工校验」区确认。</div>`}
    </div>

    <div class="panel">
      <h3>🔍 待人工校验<span class="muted">${unv.length} 条</span></h3>
      ${unv.length ? `<table><tr><th>题目</th><th>ID</th><th>候选值</th><th>备注</th><th>操作</th></tr>
        ${unv.map((r) => candRow(r, `
          <button class="small primary" data-a="validate" data-ch="${esc(r.ch.slug)}" data-id="${esc(r.x.id)}">✓ 校验通过</button>
          <button class="small" data-a="reject" data-ch="${esc(r.ch.slug)}" data-id="${esc(r.x.id)}">✗ 驳回</button>`)).join("")}
        </table>`
        : `<div class="empty"><div class="big">🔍</div>没有待校验的候选。</div>`}
    </div>

    <details class="panel">
      <summary class="sec-sum">🚀 已提交 / 已接受（${subm.length + acc.length}）</summary>
      <div style="margin-top:10px">
      ${(subm.length + acc.length) ? `<table><tr><th>题目</th><th>ID</th><th>候选值</th><th>状态</th><th>备注</th></tr>
        ${[...subm, ...acc].map((r) => `<tr><td>${esc(r.ch.name)}</td><td class="wrap">${esc(r.x.id)}</td>
          <td class="wrap mono">${esc(r.x.value)}</td>
          <td><span class="badge b-${esc(r.x.status)}">${esc(r.x.status)}</span></td>
          <td class="wrap muted">${esc(r.x.note || "")}</td></tr>`).join("")}</table>`
        : `<p class="muted" style="margin:0">还没有提交记录。</p>`}
      </div>
    </details>

    <details class="panel">
      <summary class="sec-sum">✗ 已驳回（${rej.length}）</summary>
      <div style="margin-top:10px">
      ${rej.length ? `<table><tr><th>题目</th><th>ID</th><th>候选值</th><th>驳回原因</th></tr>
        ${rej.map((r) => `<tr><td>${esc(r.ch.name)}</td><td class="wrap">${esc(r.x.id)}</td>
          <td class="wrap mono">${esc(r.x.value)}</td>
          <td class="wrap muted">${esc(r.x.note || "")}</td></tr>`).join("")}</table>`
        : `<p class="muted" style="margin:0">没有驳回记录。</p>`}
      </div>
    </details>`;

  $$("#flagsWrap button[data-a]").forEach((b) => b.onclick = async () => {
    const a = b.dataset.a;
    if (a === "validate") doAction("case.candidate", { case_dir: chOf(b.dataset.ch).case.case_dir,
      candidate_id: b.dataset.id, candidate_status: "validated" });
    else if (a === "reject") doAction("case.candidate", { case_dir: chOf(b.dataset.ch).case.case_dir,
      candidate_id: b.dataset.id, candidate_status: "rejected", note: "人工驳回" });
    else if (a === "submit") {
      const ch = chOf(b.dataset.ch);
      const cand = ch.case.candidates.find((x) => x.id === b.dataset.id);
      openSubmitModal(ch, cand);
    }
  });

  api(`/api/autosubmit?dir=${encodeURIComponent(S.dir)}`).then((cfg) => {
    $("#autoSub").checked = cfg.enabled;
    $("#maxLive").value = cfg.max_live;
  }).catch(() => {});
  $("#autoSub").onchange = saveAutosubmit;
  $("#maxLive").onchange = saveAutosubmit;
  $("#hunterBtn").onclick = startHunter;
  $$("#flagsWrap [data-copy]").forEach((b) => b.onclick = () => copyText(b.dataset.copy, "flag"));
  if (hunterTimer) { clearTimeout(hunterTimer); hunterTimer = null; }
}

async function saveAutosubmit() {
  const r = await fetch("/api/autosubmit", { method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ dir: S.dir, enabled: $("#autoSub").checked,
                           max_live: parseInt($("#maxLive").value, 10) || 3 }) })
    .then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
  if (r.ok) toast(`自动提交已${r.enabled ? "开启（上限 " + r.max_live + "/轮）" : "关闭"}`);
  else toast("保存失败：" + (r.error || "?"), true);
}

async function startHunter() {
  $("#hunterBtn").disabled = true;
  $("#hunterState").textContent = "猎手派发中…";
  const r = await fetch("/api/hunter/start", { method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ dir: S.dir }) }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
  $("#hunterBtn").disabled = false;
  if (!r.ok) { $("#hunterState").textContent = ""; return toast(r.error || "派发失败", true); }
  const t = r.task;
  $("#hunterState").innerHTML = `任务 ${esc(t.id)} 运行中（agent: ${esc(t.agent)}）· <a href="#" id="hunterTail">查看实时输出</a>`;
  $("#hunterTail").onclick = (e) => { e.preventDefault(); TaskUI.selected = t.id; setTab("tasks"); };
  toast("Flag 猎手已派发 ✓");
  let ticks = 0;
  const poll = async () => {
    if ((localStorage.getItem("wb.tab") || "") !== "flags") return;
    ticks += 1;
    try {
      const tail = await api(`/api/task/tail?id=${encodeURIComponent(t.id)}`);
      if (tail.output) {
        $("#hunterDetails").classList.remove("hidden");
        $("#hunterDetails").open = true;
        $("#hunterOut").textContent = (tail.output || "").slice(-900);
      }
      if (tail.task.status === "running" && ticks < 40) {
        hunterTimer = setTimeout(poll, 2000);
      } else {
        $("#hunterState").innerHTML = `上次运行 ${esc(t.id)}：${esc(tail.task.status)}`;
        await loadCompetition();
        renderFlags();
        return;
      }
    } catch { /* 静默重试 */ }
    if (ticks < 40) hunterTimer = setTimeout(poll, 2000);
  };
  hunterTimer = setTimeout(poll, 1500);
}

function openSubmitModal(ch, cand) {
  const chs = S.comp.challenges;
  openModal(`
    <h3>Flag 提交 <span class="muted">submitter.py · 默认 dry-run</span></h3>
    <form id="subForm" class="grid">
      <label class="f">题目<select name="challenge">${chs.map((c) =>
        `<option value="${esc(c.slug)}" ${ch && ch.slug === c.slug ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></label>
      <label class="f">flag（完整值）<input name="flag" value="${esc(cand?.value || "")}" required style="font-family:var(--mono)"></label>
      <label class="f">候选 ID<input name="candidate" value="${esc(cand?.id || "")}"></label>
      <label class="f">来源<select name="source"><option>workbench</option><option>manual</option></select></label>
      <label class="f">备注<input name="note"></label>
      <label class="f row"><input type="checkbox" name="allow_unvalidated"> 允许未校验候选（--allow-unvalidated）</label>
      <div class="full row">
        <button type="button" id="dryBtn" class="primary">1 · dry-run 预览</button>
        <button type="button" id="liveBtn" class="danger" disabled>2 · 确认真实提交 --live</button>
        <button type="button" id="cancelBtn">取消</button>
      </div>
      <div class="full"><pre class="out" id="subOut">（先执行 dry-run，确认平台响应与去重无误后再真实提交）</pre></div>
    </form>`);
  const f = $("#subForm");
  const collect = () => ({
    challenge: f.challenge.value, flag: f.flag.value,
    candidate: f.candidate.value || undefined, source: f.source.value,
    note: f.note.value || undefined, allow_unvalidated: f.allow_unvalidated.checked,
  });
  $("#cancelBtn").onclick = closeModal;
  $("#dryBtn").onclick = async () => {
    $("#subOut").textContent = "执行 dry-run …";
    const r = await post("submit.dryrun", { dir: S.dir, ...collect() });
    $("#subOut").textContent = `exit=${r.exit}\n` + (r.stdout || "") + (r.stderr ? "\n[stderr]\n" + r.stderr : "");
    $("#liveBtn").disabled = r.exit !== 0;
    if (r.exit !== 0) toast("dry-run 未通过，请检查输出", true);
  };
  $("#liveBtn").onclick = async () => {
    if (!confirm("确认真实提交到比赛平台？该操作会真正调用平台接口（受限速与去重保护）。")) return;
    const r = await post("submit.live", { dir: S.dir, ...collect(), confirm: true });
    $("#subOut").textContent = `exit=${r.exit}\n` + (r.stdout || "") + (r.stderr ? "\n[stderr]\n" + r.stderr : "");
    const slug = collect().challenge;
    if (r.exit === 0) { toast(`🎉 ${slug} 提交被接受 ✓`); await loadCompetition(); }
    else toast(`${slug} 提交未通过（outcome 非 accepted），详见输出`, true);
  };
}

/* ---------------- ③b 运行任务 ---------------- */
const TaskUI = { selected: null, timer: null };

async function renderTasks() {
  if (!S.comp) return;
  const sel = $("#taskCase");
  if (!sel.dataset.bound) {
    sel.dataset.bound = "1";
    $("#taskStart").onclick = startTask;
  }
  const chs = S.comp.challenges.filter((c) => c.case?.exists);
  if (!sel.options.length || sel.options.length !== chs.length) {
    const cur = sel.value;
    sel.innerHTML = chs.map((c) => `<option value="${esc(c.slug)}">${esc(c.name)}</option>`).join("");
    if (cur && chs.some((c) => c.slug === cur)) sel.value = cur;
  }
  let data;
  try { data = await api("/api/tasks"); }
  catch (e) { $("#taskAgentState").textContent = "任务服务不可用：" + e.message; return; }
  $("#taskAgentState").innerHTML = data.agent_cmd
    ? "✓ 已配置求解命令模板"
    : "⚠ 未配置命令模板：启动 server 时加 <code>--agent-cmd \"...\"</code>（占位符 {prompt_file} {case_dir}）";
  // 沙箱状态（Docker + 镜像）
  api("/api/sandbox").then((s) => {
    const gw = s.upstream_configured
      ? (s.gateway ? `✓ 网关开启（已发令牌 ${s.gateway_tokens}，流量 ${(s.gateway_bytes / 1024).toFixed(1)}K）`
                   : "网关未开启（可按任务开启）")
      : "⚠ 网关未配置上游（WB_UPSTREAM_BASE + " + (s.upstream_key_env || "OPENAI_API_KEY") + "）";
    $("#sandboxState").innerHTML = (s.docker_ok
      ? (s.image_ok
          ? `✓ Docker ${esc(s.docker_ver)} · 按类别选镜像（${Object.keys(s.images || {}).length} 类） · 网络默认 <code>${esc(s.network)}</code>`
          : `⚠ Docker ${esc(s.docker_ver)} 正常，但镜像 <code>${esc(s.image)}</code> 未构建（见 docker/README.md）`)
      : "⚠ Docker 不可达：沙箱执行不可用") + `<br>模型网关：${gw}`;
  }).catch(() => {});
  const list = $("#taskList");
  const rows = data.tasks.filter((t) => !S.dir || t.dir === S.dir);
  list.innerHTML = rows.map((t) => `
    <div class="task-row ${TaskUI.selected === t.id ? "on" : ""}" data-id="${esc(t.id)}">
      <span class="dot s-${t.status === "running" ? "in_progress" : t.status === "done" || t.status === "submitted" ? "solved" : t.status === "failed" || t.status === "lost" ? "blocked" : "new"}"></span>
      <span class="tid">${esc(t.id)}</span>
      <span style="flex:1">${esc(t.slug)}</span>
      <span class="agent-tag" style="background:${agentColor(t.agent)}">${esc(t.agent || "solver")}</span>
      ${t.container ? `<span class="badge" style="--b-c:#58a6ff" title="${esc(t.container)}">📦 沙箱</span>` : ""}
      <span class="badge" style="--b-c:${t.status === "running" ? "#fbbf24" : t.status === "done" ? "#34d399" : "#f87171"}">${esc(t.status)}</span>
      <span class="muted" style="font-size:11px">${esc((t.started || "").slice(11, 16))}${t.finished ? "→" + esc(t.finished.slice(11, 16)) : ""}</span>
      ${t.status === "running" ? `<button class="small" data-stop="${esc(t.id)}">停止</button>` : ""}
    </div>`).join("") || `<div class="empty"><div class="big">🛰️</div>尚无任务：选择题目后「启动」派发求解器。</div>`;
  $$("#taskList .task-row").forEach((row) => row.onclick = () => selectTask(row.dataset.id));
  $$("#taskList button[data-stop]").forEach((b) => b.onclick = async (e) => {
    e.stopPropagation();
    if (!confirm("确认停止该任务？")) return;
    await fetch("/api/task/stop", { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ id: b.dataset.stop }) });
    renderTasks();
  });
  if (TaskUI.selected) pollTaskOutput();
}

function selectTask(id) { TaskUI.selected = id; renderTasks(); }

async function startTask() {
  const slug = $("#taskCase").value;
  if (!slug) return toast("请先选择题目", true);
  const r = await fetch("/api/task/start", { method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ dir: S.dir, slug, agent: $("#taskAgent").value.trim(),
                           sandbox: $("#taskSandbox")?.checked || false,
                           gateway: $("#taskGateway")?.checked || false }) }).then((x) => x.json());
  if (r.ok) {
    toast(`任务 ${r.task.id} 已启动 ✓${r.sandbox ? "（Docker 沙箱）" : ""}`);
    TaskUI.selected = r.task.id;
    renderTasks();
  } else toast(r.error || "启动失败", true);
}

let taskPollBusy = false;
async function pollTaskOutput() {
  if (taskPollBusy || !TaskUI.selected) return;
  taskPollBusy = true;
  try {
    const r = await api(`/api/task/tail?id=${encodeURIComponent(TaskUI.selected)}`);
    if (TaskUI.selected === r.task.id) {
      $("#taskMeta").textContent =
        `${r.task.id} · ${r.task.slug} · ${r.task.status}` +
        (r.task.exit !== undefined ? ` · exit=${r.task.exit}` : "") +
        ` · ${r.task.command}`;
      $("#taskOut").textContent = r.output || "（暂无输出）";
      const box = $("#taskOut");
      box.scrollTop = box.scrollHeight;
    }
  } catch (e) { /* 静默 */ }
  taskPollBusy = false;
  if (localStorage.getItem("wb.tab") === "tasks") {
    clearTimeout(TaskUI.timer);
    TaskUI.timer = setTimeout(() => { renderTasks(); }, 1500);
  }
}

/* ---------------- ③c 系统概况 ---------------- */
async function renderHealth() {
  const el = $("#healthWrap");
  el.innerHTML = "<p class='muted'>检测中…</p>";
  let d;
  try { d = await api("/api/health/detail"); }
  catch (e) { el.innerHTML = `<p style="color:var(--red)">检测失败：${esc(e.message)}</p>`; return; }
  const card = (title, ok, detail, extra = "") => `
    <div class="health-card">
      <div class="h-top"><span class="dot ${ok === null ? "s-triaged" : ok ? "s-solved" : "s-blocked"}"></span>
        ${esc(title)}</div>
      <div class="h-detail">${esc(detail)}</div>${extra}</div>`;
  const s = d.stats;
  el.innerHTML = `
    <div class="panel"><h3>执行链路</h3>
      <div class="chain">
        <span class="node">Workbench 服务（Python 标准库）</span><span class="arrow">→</span>
        <span class="node">solve-ai-ctf 脚本层（校验/状态机）</span><span class="arrow">→</span>
        <span class="node">ZCode Agent（SKILL.md 流程）</span><span class="arrow">→</span>
        <span class="node">submitter dry-run → 人工审核</span>
      </div>
      <p class="muted" style="margin-bottom:0">对应 CTF-BTFly 的 Wails→Go→沙箱→Pi 链路：本工作台以脚本层为控制平面、编辑器 Agent 为求解器。</p>
    </div>
    <div class="health-grid">
      ${card("服务", true, d.server.detail)}
      ${card("脚本层", d.scripts.ok, d.scripts.detail)}
      ${card("脚本自检（self_test）", d.selftest.ok, d.selftest.detail,
        `<button class="small" id="selfTestBtn" style="margin-top:8px">运行 self_test.py</button><span id="selfTestOut" class="muted"></span>`)}
      ${card("Docker", d.docker.ok, d.docker.ok ? "引擎可达 · " + d.docker.detail : d.docker.detail)}
      ${d.image_states ? card("题型镜像", Object.values(d.image_states).every((i) => i.ok),
        Object.entries(d.image_states).map(([k, v]) =>
          `${v.ok ? "✓" : "✗"} ${k}`).join(" · ")) : ""}
      ${card("求解命令模板", d.agent_cmd.ok, d.agent_cmd.detail)}
      ${card("数据统计", true,
        `${s.competitions} 场比赛（${s.configured} 已初始化）· ${s.challenges} 题 · ` +
        `任务 ${s.tasks_running} 运行 / ${s.tasks_total} 累计`)}
    </div>`;
  $("#selfTestBtn").onclick = async () => {
    $("#selfTestOut").textContent = "运行中（最多 60s）…";
    const r = await post("selftest.run", {});
    $("#selfTestOut").textContent = r.ok ? "✓ " + (r.stdout || "").trim().split("\n").pop()
      : "✗ 失败：" + ((r.stderr || r.stdout || "").trim().slice(-160));
  };
}
/* ---------------- ④ 时间线（SSE 实时流） ---------------- */
let eventSource = null;

function stopEventStream() {
  if (eventSource) { eventSource.close(); eventSource = null; }
}

function tlItemHtml(e) {
  return `<div class="tl-item">
    <span class="tl-time">${esc(fmtTime(e.time))}</span><span class="tl-kind">${esc(e.kind)}</span>
    <span class="tl-detail">${esc(typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail || {}))}</span>
  </div>`;
}

function renderTimeline() {
  const el = $("#timelineWrap");
  if (!S.comp) { stopEventStream(); el.innerHTML = ""; return; }
  const evs = [...(S.comp.events || [])].reverse();
  el.innerHTML = `<div class="panel"><h3>比赛事件流（events.jsonl · ${evs.length} 条 · SSE 实时推送）</h3>
    <div id="tlBody">${evs.map(tlItemHtml).join("") || "<p class='muted'>暂无事件。</p>"}</div></div>`;
  stopEventStream();
  if ("EventSource" in window) {
    const t = localStorage.getItem("wb.token");
    eventSource = new EventSource(`/api/events/stream?dir=${encodeURIComponent(S.dir)}` +
      (t ? `&token=${encodeURIComponent(t)}` : ""));
    eventSource.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data);
        const body = $("#tlBody");
        if (body) body.insertAdjacentHTML("afterbegin", tlItemHtml(e));
      } catch { /* 忽略坏帧 */ }
    };
    eventSource.onerror = () => { /* EventSource 自动重连 */ };
  }
}

/* ---------------- ⑤ 文件 / 日志 ---------------- */
async function renderFiles() {
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
    ${f.type === "file" ? `<span class="sz">${fmtSize(f.size)}</span>` : ""}</div>`).join("")
    || "<p class='muted'>空目录。</p>";
  $$("#fileTree .trow[data-p]").forEach((row) => row.onclick = () => openFile(row.dataset.p));
}

async function openFile(relPath) {
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

/* ---------------- ⑥ 知识库 / 提示词 ---------------- */
function renderKb() {
  const sel = $("#promptCase");
  if (S.comp && !sel.options.length) {
    sel.innerHTML = S.comp.challenges.map((c) => `<option value="${esc(c.slug)}">${esc(c.name)}</option>`).join("");
  }
  if (!$("#kbForm").dataset.bound) {
    $("#kbForm").dataset.bound = "1";
    $("#kbForm").onsubmit = async (e) => {
      e.preventDefault();
      $("#kbResults").innerHTML = "<p class='muted'>检索中…</p>";
      const q = encodeURIComponent($("#kbQuery").value);
      const cat = $("#kbCategory").value ? "&category=" + $("#kbCategory").value : "";
      try {
        const r = await api(`/api/kb?q=${q}${cat}`);
        $("#kbResults").innerHTML = r.hits.length ? r.hits.map((h) => `
          <div class="panel"><b>${esc(h.file)}:${h.line}</b> <span class="muted">score=${h.score}</span>
          <pre class="out">${esc(h.context.join("\n"))}</pre></div>`).join("")
          : "<p class='muted'>无命中。</p>";
      } catch (e2) { $("#kbResults").innerHTML = `<p style="color:var(--red)">${esc(e2.message)}</p>`; }
    };
    $("#promptGen").onclick = async () => {
      const slug = $("#promptCase").value;
      if (!slug) return toast("请先选择比赛与题目", true);
      $("#promptOut").textContent = "生成中…";
      try {
        const r = await api(`/api/prompt?dir=${encodeURIComponent(S.dir)}&slug=${encodeURIComponent(slug)}`);
        $("#promptOut").textContent = r.prompt;
      } catch (e2) { $("#promptOut").textContent = "生成失败：" + e2.message; }
    };
    $("#promptCopy").onclick = async () => {
      const text = $("#promptOut").textContent;
      if (!text) return;
      try { await navigator.clipboard.writeText(text); toast("已复制到剪贴板 ✓"); }
      catch { toast("复制失败，请手动选择文本", true); }
    };
  }
}

/* ---------------- ⑦ 文档 / WP ---------------- */
function renderDocs() {
  if (!S.comp) return;
  $("#docList").innerHTML = (S.comp.docs || []).map((d) =>
    `<div class="trow" data-p="docs/${esc(d.name)}"><span>·</span><span style="flex:1">${esc(d.name)}</span>
     <span class="sz">${fmtSize(d.size)}</span></div>`).join("") || "<p class='muted'>docs/ 为空。</p>";
  $("#artifactList").innerHTML = (S.comp.artifacts || []).map((a) =>
    `<div class="trow" style="cursor:default"><span>◆</span><span style="flex:1">${esc(a.name)}</span>
     <span class="sz">${fmtSize(a.size)}</span></div>`).join("") || "<p class='muted'>artifacts/ 为空。</p>";
  $$("#docList .trow").forEach((row) => row.onclick = () => openDoc(row.dataset.p));
}

async function openDoc(relPath) {
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

/* ---------------- ⑧ 比赛动作 ---------------- */
const OPS_TABS = [
  ["agents", "🔌 开赛自动化"], ["register", "📝 注册题目"], ["opsrun", "🛠️ 运维操作"],
];

function renderOps() {
  const tabsEl = $("#opsSubtabs"), body = $("#opsBody");
  if (!S.comp) { tabsEl.innerHTML = ""; body.innerHTML = "<p class='muted'>没有可用比赛。</p>"; return; }
  const plat = S.comp.config?.platform || {};
  S.otab = localStorage.getItem("wb.otab") || "agents";
  tabsEl.innerHTML = OPS_TABS.map(([id, label]) =>
    `<button data-t="${id}" class="${S.otab === id ? "on" : ""}">${label}</button>`).join("");
  $$("#opsSubtabs button").forEach((b) => b.onclick = () => {
    S.otab = b.dataset.t;
    localStorage.setItem("wb.otab", S.otab);
    renderOps();
  });
  ({ agents: opsAgents, register: opsRegister, opsrun: opsRun }[S.otab] || opsAgents)(plat);
}

function platRows(plat) {
  const platColor = plat.status === "auto-configured" ? "#34d399"
    : plat.status && plat.status !== "unconfigured" ? "#fbbf24" : "#94a3b8";
  return `
    <table style="max-width:640px">
      <tr><th>状态</th><td><span class="badge" style="--b-c:${platColor}">${esc(plat.status || "unconfigured")}</span></td></tr>
      <tr><th>平台基址</th><td class="wrap mono">${esc(plat.base_url || "未配置")}</td></tr>
      <tr><th>令牌环境变量</th><td class="mono">${esc(plat.auth?.value_env || "CTF_TOKEN")}</td></tr>
      <tr><th>已注册题目</th><td>${(S.comp.challenges || []).length} 题</td></tr>
      <tr><th>门户</th><td class="wrap mono">${esc(plat.portal?.login_url || "未填写")}</td></tr>
    </table>`;
}

function bindAgentButtons() {
  const startAgent = (kind, label, extra) => async () => {
    const r = await fetch("/api/agent/start", { method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ dir: S.dir, kind, ...(extra || {}) }) }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
    if (r.ok) {
      toast(`${label} 已派发 ✓（任务 ${r.task.id}）· 进度见「运行任务」`);
      TaskUI.selected = r.task.id;
    } else toast(r.error || "派发失败", true);
  };
  const bp = $("#agentPlat"), bf = $("#agentFetch"), bb = $("#agentBuu");
  if (bp) bp.onclick = startAgent("platform", "平台对接代理");
  if (bf) bf.onclick = () => startAgent("fetch", "抓题代理", {
    limit: parseInt($("#fetchLimit")?.value, 10) || 0,
    categories: $("#fetchCats")?.value.trim() || "" })();
  if (bb) bb.onclick = startAgent("buuctf", "BUUCTF 对接代理");
}

/* ---- 子页签 1：开赛自动化 ---- */
function opsAgents(plat) {
  const body = $("#opsBody");
  body.innerHTML = `
    <div class="agent-grid">
      <div class="panel agent-big" style="--oc:var(--accent)">
        <div class="ag-top">
          <span class="oc-ic">🔌</span>
          <div class="ag-tt"><b>自动对接平台</b>
            <p class="muted">探测平台 API 形态（CTFd 系优先）→ 自动写入提交脚本配置（platform 段）。完成后先用 submitter dry-run 验证提交端点，再放行 --live。</p></div>
        </div>
        <button id="agentPlat" class="primary">派发对接代理</button>
        <p class="muted" style="margin:8px 0 0">前置：环境变量设置平台令牌（见下方状态表）。</p>
      </div>
      <div class="panel agent-big" style="--oc:var(--teal)">
        <div class="ag-top">
          <span class="oc-ic">📥</span>
          <div class="ag-tt"><b>自动抓题注册</b>
            <p class="muted">拉取题目列表 → 逐题注册 case（名称/类别/分值/平台 ID 自动填，已存在自动跳过）。附件需手动放入对应 artifacts/。</p></div>
        </div>
        <div class="row" style="margin:0 0 8px">
          <label class="muted" style="white-space:nowrap">上限 <input id="fetchLimit" type="number" value="0" min="0" style="width:64px" title="0=不限"></label>
          <input id="fetchCats" placeholder="类别过滤 web,crypto" style="flex:1;min-width:150px">
        </div>
        <button id="agentFetch" class="primary">派发抓题代理</button>
        <p class="muted" style="margin:8px 0 0">前置：平台对接完成（或人工填好 platform.challenges）。</p>
      </div>
    </div>
    <div class="panel agent-big" style="--oc:var(--pink)">
      <div class="ag-top">
        <span class="oc-ic">🦋</span>
        <div class="ag-tt"><b>BUUCTF（buuoj.cn）一键对接</b>
          <p class="muted">套用 BUUCTF 预设（表单登录 + 会话拉题）→ 自动探测并写入配置。需环境变量
          <code>CTF_CREDENTIALS_JSON</code>（JSON：username/password）。</p></div>
      </div>
      <button id="agentBuu" class="primary">套用预设并自动对接</button>
    </div>
    <div class="panel">
      <h3>平台状态</h3>
      ${platRows(plat)}
    </div>`;
  bindAgentButtons();
}

/* ---- 子页签 2：注册题目 ---- */
function opsRegister(plat) {
  const body = $("#opsBody");
  body.innerHTML = `
    <div class="panel">
      <h3>注册新题目 <span class="muted">add-challenge · 常用字段在前，其余按需</span></h3>
      <form id="regForm">
        <div class="form-sec">
          <div class="fs-lbl">基本信息</div>
          <div class="fgrid c3">
            <label class="f">题目名 *<input name="name" required></label>
            <label class="f">类别 *
              <select name="category"><option>crypto</option><option>pwn</option><option>reverse</option>
              <option>web</option><option>misc</option><option>forensics</option></select></label>
            <label class="f">slug（留空自动）<input name="slug"></label>
          </div>
        </div>
        <div class="form-sec">
          <div class="fs-lbl">评分与平台</div>
          <div class="fgrid c5">
            <label class="f">平台题目 ID<input name="challenge_id"></label>
            <label class="f">难度<input name="difficulty" placeholder="Easy…"></label>
            <label class="f">分值<input name="points" type="number" step="1"></label>
            <label class="f">预期(分)<input name="expected_minutes" type="number" step="1" value="30"></label>
            <label class="f">p_solve<input name="p_solve" type="number" step="0.05" value="0.3" min="0" max="1"></label>
          </div>
        </div>
        <div class="form-sec">
          <div class="fs-lbl">题面与 Flag</div>
          <label class="f" style="margin-bottom:8px">题面描述<textarea name="description" rows="2"></textarea></label>
          <label class="f">flag 正则（可选，多条换行）<textarea name="flag_patterns" rows="2"></textarea></label>
        </div>
        <div class="row" style="margin:12px 0 0">
          <button class="primary">注册题目</button>
          <span class="muted">注册后自动生成独立 case 目录，出现在总览与题目工作区</span>
        </div>
      </form>
    </div>`;
  $("#regForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const nl = String.fromCharCode(10);
    const params = {
      name: f.get("name"), category: f.get("category"),
      slug: f.get("slug") || undefined, challenge_id: f.get("challenge_id") || undefined,
      difficulty: f.get("difficulty") || undefined, description: f.get("description") || undefined,
      points: f.get("points") || undefined, p_solve: f.get("p_solve") || undefined,
      expected_minutes: f.get("expected_minutes") || undefined,
      flag_patterns: String(f.get("flag_patterns") || "").split(nl).map((s) => s.trim()).filter(Boolean),
    };
    const r = await doAction("challenge.register", params);
    if (r.ok) { await loadCompetition(); renderOps(); }
  };
}

/* ---- 子页签 3：运维操作 ---- */
function opsRun(plat) {
  const body = $("#opsBody");
  body.innerHTML = `
    <div class="cols">
      <div class="col-main">
        <div class="panel">
          <h3>比赛级操作</h3>
          <button id="prioBtn" class="op-card" style="--oc:var(--purple);width:100%">
            <span class="oc-ic">🧮</span>
            <span class="oc-tt">重算解题优先级<small>P×分值×时间价值 ÷ 预期耗时</small></span>
          </button>
          <button id="dashBtn" class="op-card" style="--oc:var(--teal);width:100%;margin-top:8px">
            <span class="oc-ic">🖥️</span>
            <span class="oc-tt">重生成 warroom.html<small>静态看板快照（降级备用）</small></span>
          </button>
          <button id="eventBtn" class="op-card" style="--oc:var(--orange);width:100%;margin-top:8px">
            <span class="oc-ic">📌</span>
            <span class="oc-tt">追加比赛事件<small>写入 events.jsonl 审计流</small></span>
          </button>
        </div>
        <div class="panel">
          <h3>目录状态</h3>
          <p class="muted" style="margin:0;line-height:1.8">比赛/${esc(S.dir)}<br>
          ${S.comp.configured ? "✅ 已初始化（competition.json）" : "⛔ 未初始化：先 competition.py init"}
          <br>事件 ${(S.comp.events || []).length} 条 · 文档 ${(S.comp.docs || []).length} 篇</p>
        </div>
      </div>
      <div class="col-side">
        <div class="panel term">
          <div class="term-bar"><span></span><span></span><span></span><b>动作输出</b></div>
          ${S.result ? `<pre class="term-body">[${esc(S.result.action)}] exit=${esc(S.result.exit)}
${esc((S.result.stdout || "") + (S.result.stderr ? " | [stderr] | " + S.result.stderr : ""))}</pre>`
            : "<p class='muted' style='margin:10px 0 0'>尚无动作输出：任何按钮动作的 stdout/stderr 都会显示在这里。</p>"}
        </div>
      </div>
    </div>`;
  $("#prioBtn").onclick = () => doAction("competition.prioritize", {}, { noReload: true });
  $("#dashBtn").onclick = () => doAction("competition.dashboard", {}, { noReload: true });
  $("#eventBtn").onclick = async () => {
    const kind = prompt("事件 kind（如 manual_note）：");
    if (!kind) return;
    const detail = prompt("detail（可选）：") || undefined;
    doAction("competition.event", { kind, detail });
  };
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
    <h3>⌨️ 快捷键与协作</h3>
    <table style="margin:10px 0">
      <tr><td><kbd>Alt</kbd>+<kbd>1..9</kbd></td><td>切换左侧页面</td></tr>
      <tr><td><kbd>?</kbd></td><td>本帮助</td></tr>
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
