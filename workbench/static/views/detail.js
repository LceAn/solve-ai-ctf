/* ---------------- ② 题目详情（工作区式子页签） ---------------- */
import { S } from "../state.js";
import { $, $$, esc, fmtSize, fmtTime, toast, snapshotDetailForms, restoreDetailForms } from "../ui.js";
import { api, post } from "../api.js";
import { statusLabel, catColor, statusColor } from "./board.js";
import { openSubmitModal } from "./flags.js";
import { doAction, loadCase, loadCompetition, refreshCase, setTab } from "../app.js";

export const DETAIL_TABS = [
  ["overview", "概览"], ["collab", "🤝 协作看板"], ["hypo", "假设阶梯"], ["attempt", "尝试记录"], ["evidence", "证据 / 线索"],
  ["excluded", "排除 / 失败"], ["cands", "Flag 历史"], ["prompt", "提示词"], ["rules", "守则"],
];
export const FLOW_STAGES = ["new", "triaged", "in_progress", "candidate_found", "solved", "submitted", "closed"];

export function chOf(slug) { return S.comp?.challenges.find((c) => c.slug === slug); }

export function flowHtml(status) {
  status = status || "new";
  const idx = FLOW_STAGES.indexOf(status);
  const side = ["blocked", "abandoned", "invalid", "closed"].includes(status);
  let html = "<div class='flow'>";
  FLOW_STAGES.forEach((st, i) => {
    const done = side ? i < FLOW_STAGES.length - 1 : idx > i;
    const cur = idx === i;
    html += `<span class="step ${done ? "done" : ""} ${cur ? "cur" : ""}">` +
      `<span class="dot2"></span><span class="lbl">${statusLabel(st)}</span></span>`;
    if (i < FLOW_STAGES.length - 1) html += `<span class="lnk ${done ? "done" : ""}"></span>`;
  });
  return html + "</div>";
}

export const CAT_ORDER = ["crypto", "pwn", "reverse", "web", "misc", "forensics"];

export function updateCatSubnav() {
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

export function renderDetailPicker() {
  const pick = $("#detailPick");
  if (!S.comp || !S.comp.challenges.length) {
    // 空态：此前直接清空，进页面是一片黑，没有任何引导
    pick.innerHTML = `<div class="empty-state">
      <b>还没有题目</b>
      <p>先在「比赛管理」初始化比赛或抓取题目，之后在这里选择题目开始解题。</p>
    </div>`;
    return;
  }
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
    <label class="picker-field"><span class="picker-label muted">方向</span>
      <select id="pickCat" class="pick-select pick-cat">
        <option value="">全部方向（${chs.length} 题）</option>
        ${cats.map((cat) => `<option value="${esc(cat)}" ${S.pickCat === cat ? "selected" : ""}>
          ${esc(cat)}（${cnt(cat)}）</option>`).join("")}
      </select>
    </label>
    <label class="picker-field picker-field-wide"><span class="picker-label muted">题目</span>
      <select id="pickChall" class="pick-select pick-chall">
        ${filtered.map((c) => `<option value="${esc(c.slug)}" ${c.slug === S.slug ? "selected" : ""}>
          ${esc(c.name)} · ${esc(c.category)} · ${c.points ?? "?"}分 · ${esc(statusLabel(c.case?.status || "no_case"))}</option>`).join("")
        || "<option value=''>（该方向暂无题目）</option>"}
      </select>
    </label>
    ${S.slug ? "" : `<span class="picker-hint muted">← 选择题目进入工作区</span>`}`;
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

let challLinkHandled = false;

export async function renderDetail() {
  // R80：看板题目泳道深链接（一次性消费）
  if (!challLinkHandled) {
    challLinkHandled = true;
    const want = localStorage.getItem("wb.slug");
    if (want) {
      localStorage.removeItem("wb.slug");
      if ((S.comp?.challenges || []).some((c) => c.slug === want)) {
        S.slug = want;
        try { await import("../app.js").then((m) => m.loadCase(want, true)); } catch { /* 静默 */ }
      }
    }
  }
  const head = $("#detailHead"), tabs = $("#detailSubtabs"), body = $("#detailBody");
  if (!S.comp) { head.innerHTML = tabs.innerHTML = body.innerHTML = ""; return; }
  renderDetailPicker();
  if (!S.slug) {
    head.innerHTML = "";
    tabs.innerHTML = "";
    const pickCat = localStorage.getItem("wb.pickCat") ?? "";
    S.listQuery = S.listQuery ?? "";
    let filtered = pickCat
      ? S.comp.challenges.filter((c) => (c.category || "misc") === pickCat)
      : S.comp.challenges;
    const q = S.listQuery.trim().toLowerCase();
    if (q) filtered = filtered.filter((c) =>
      (c.name || "").toLowerCase().includes(q)
      || (c.slug || "").toLowerCase().includes(q)
      || (c.description || "").toLowerCase().includes(q));
    const catLbl = pickCat ? `${esc(pickCat)} 方向` : "全部方向";
    body.innerHTML = `
      <div class="panel">
        <h3>${catLbl}题目列表 <span class="muted">${filtered.length} 题 · 点击进入工作区</span></h3>
        <div class="row" style="margin:0 0 10px">
          <input id="listSearch" placeholder="🔍 搜索题名 / 描述 / slug…" value="${esc(S.listQuery)}"
                 style="flex:1;max-width:360px">
        </div>
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
            <span class="badge" style="--b-c:${statusColor(c.case?.status)}">${esc(statusLabel(c.case?.status || "no_case"))}</span>
            ${c.case?.exists
              ? `<button class="small primary" data-enter="${esc(c.slug)}">进入 →</button>`
              : `<button class="small" data-initcase="${esc(c.case_dir || "cases/" + c.slug)}" data-name="${esc(c.name)}" data-slug="${esc(c.slug)}">初始化 case</button>`}
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
    const ls = document.getElementById("listSearch");
    if (ls) {
      ls.oninput = () => { S.listQuery = ls.value; renderDetail(); 
        const nls = document.getElementById("listSearch");
        if (nls) { nls.focus(); nls.setSelectionRange(nls.value.length, nls.value.length); } };
    }
    $$("#detailBody .ready-row[data-slug], #detailBody button[data-enter]").forEach((n) =>
      n.onclick = async (e) => {
        e.stopPropagation();
        const slug = n.dataset.slug || n.closest("[data-slug]")?.dataset.slug;
        await loadCase(slug);
        renderDetail();
      });
    $$("#detailBody [data-initcase]").forEach((b) => b.onclick = async (e) => {
      e.stopPropagation();
      const r = await doAction("case.init", {
        case_dir: b.dataset.initcase, name: b.dataset.name,
        category: chOf(b.closest("[data-slug]")?.dataset.slug)?.category || "misc",
        challenge_id: chOf(b.closest("[data-slug]")?.dataset.slug)?.platform_id || "",
        description: chOf(b.closest("[data-slug]")?.dataset.slug)?.description || "",
      }, { showOutput: false });
      if (r.ok) { await loadCompetition(); renderDetail(); }
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
        ${k?.attempts?.length
          ? `<span class="badge" style="--b-c:#58a6ff" title="参与解题的 AI/人数">🤝 ${new Set(k.attempts.map((a) => agentOf(a, "action")).filter(Boolean)).size}</span>` : ""}
        <span class="muted">${esc(c.slug)} · ${esc(c.category)} · ${c.points ?? "?"}分 · ${esc(c.difficulty || "?")} · ${esc(statusLabel(status || "new"))}</span>
        <span class="spacer" style="flex:1"></span>
        <select id="statusSel">${enums.statuses.map((s) =>
          `<option value="${esc(s)}" ${s === status ? "selected" : ""}>${esc(statusLabel(s))}</option>`).join("")}</select>
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
  // R48-F4：子页签收合——核心 4 常驻，其余收进「更多 ▾」，⇥全部/⇤收起持久化
  const CORE_STABS = ["overview", "hypo", "attempt", "cands"];
  const stabsExpanded = localStorage.getItem("wb.stabsExpanded") === "1";
  const visibleTabs = stabsExpanded ? DETAIL_TABS
    : DETAIL_TABS.filter(([id]) => CORE_STABS.includes(id) || id === S.dtab);
  const hiddenCount = DETAIL_TABS.length - visibleTabs.length;
  const moreOn = !stabsExpanded && DETAIL_TABS.some(([id]) => id === S.dtab) &&
    !visibleTabs.some(([id]) => id === S.dtab);
  const k4count = S.caseData || {};
  const tabCount = (id) => ({
    attempt: k4count.attempts?.length, excluded: k4count.attempts?.filter((a) =>
      a.outcome === "failure" || a.outcome === "error").length,
    evidence: k4count.evidence?.length, cands: k4count.candidates?.length,
  })[id];
  tabs.innerHTML = visibleTabs.map(([id, label]) =>
    `<button data-st="${id}" class="${S.dtab === id ? "on" : ""}">${label}` +
    (tabCount(id) ? ` <span class="tab-count">${tabCount(id)}</span>` : "") + `</button>`).join("")
    + (hiddenCount > 0
      ? `<button data-st="__more" class="${moreOn ? "on" : ""}">更多 ▾ (${hiddenCount})</button>`
      : "")
    + `<button data-st="__expand" title="${stabsExpanded ? "收起次要页签" : "展开全部页签"}">${stabsExpanded ? "⇤ 收起" : "⇥ 全部"}</button>`;
  $$("#detailSubtabs button").forEach((b) => b.onclick = () => {
    if (b.dataset.st === "__expand") {
      localStorage.setItem("wb.stabsExpanded", stabsExpanded ? "0" : "1");
      renderDetail();
      return;
    }
    if (b.dataset.st === "__more") {
      localStorage.setItem("wb.stabsExpanded", "1");
      renderDetail();
      return;
    }
    S.dtab = b.dataset.st;
    localStorage.setItem("wb.dtab", S.dtab);
    renderDetail();
  });
  const sub = ({ collab: dCollab, overview: dOverview, hypo: dHypo, attempt: dAttempt, evidence: dEvidence,
     excluded: dExcluded, cands: dCands, prompt: dPrompt, rules: dRules }[S.dtab] || dOverview);
  const preserve = !!S.preserveForms;
  S.preserveForms = false;
  const snap = preserve ? snapshotDetailForms() : null;
  await sub(c, k);
  if (preserve) restoreDetailForms(snap);
}

/* ---- 概览：状态流 + 题面 + 分诊摘要 + 工作区统计 ---- */
export async function dOverview(c, k) {
  const body = $("#detailBody");
  const files = k?._tree?.filter((f) => f.type === "file").length ?? 0;
  const evs = (k?.events || []).slice(-6).reverse();
  const cands = k?.candidates || [];
  const best = cands.find((x) => x.status === "accepted")
    || cands.find((x) => x.status === "submitted")
    || cands.find((x) => x.status === "validated");
  const parts = new Set((k?.attempts || []).map((a) => a.agent).filter(Boolean));
  const claim = k?._collab?.claim;
  const claimNames = (k?._collab?.claims || []).map((x) => x.agent_tag).join("、");
  const flagStLbl = { accepted: "✅ 已接受", submitted: "📤 已提交", validated: "✓ 已验证可提交" };

  body.innerHTML = `
    ${best
      ? `<div class="flag-banner ${best.status}">
          <div class="fb-left">
            <div class="fb-kicker">🚩 FLAG ${flagStLbl[best.status] || best.status}</div>
            <div class="fb-value">${esc(best.value)}</div>
            <div class="fb-meta">${esc(best.id)} · ${esc(best.note || best.source || "")}</div>
          </div>
          <button class="small copy-btn" data-copy="${esc(best.value)}">复制</button>
        </div>`
      : `<div class="flag-banner none">
          <div class="fb-kicker">🚩 FLAG</div>
          <div class="fb-value muted" style="font-size:15px">未解出${cands.length
            ? `——有 ${cands.length} 个候选待校验（见「Flag 历史」）`
            : "——解出后此处常显 flag"}</div>
        </div>`}
    ${(k?._collab?.handoffs || []).length ? `
    <div class="handoff-strip" title="接手前先读上一棒的结论">
      🤝 <b>上一棒 ${esc(k._collab.handoffs[0].agent_tag || k._collab.handoffs[0].agent_name || "?")}</b>
      <span class="muted">${esc(fmtTime(k._collab.handoffs[0].time))}：</span>
      ${esc((k._collab.handoffs[0].summary || "").slice(0, 110))}
      <span class="muted">（findings ${k._collab.handoffs[0].findings ?? 0} · 共 ${k._collab.handoffs.length} 次交接）</span>
    </div>` : ""}
    <div class="fact-row">
      ${flowHtml(k?.status)}
      ${k?.blocked_on ? `<span class="badge" style="--b-c:#f87171">⛔ ${esc(k.blocked_on.slice(0, 24))}</span>` : ""}
      ${claimNames ? `<span class="badge" style="--b-c:#fbbf24" title="当前认领">🔓 ${esc(claimNames)}</span>` : ""}
      ${parts.size ? `<span class="badge" style="--b-c:#58a6ff">🤝 ${parts.size} 人参与</span>` : ""}
      <span class="muted">假设 ${k?.hypotheses?.length ?? 0} · 尝试 ${k?.attempts?.length ?? 0} ·
        证据 ${k?.evidence?.length ?? 0} · 文件 ${files}</span>
      <button class="small" id="gotoFiles">📁 文件</button>
    </div>
    <div class="panel"><h3>题面</h3><p style="margin:0;white-space:pre-wrap">${esc(c.description || "（无题面描述）")}</p></div>
    <div class="cols">
      <div class="col-main">
        <div class="panel"><h3>分诊摘要 <span class="muted">triage.json（static-only）</span></h3>
          <div id="ovTri" class="muted">读取中…</div></div>
      </div>
      <div class="col-side">
        <div class="panel"><h3>最近动态</h3>
          <div class="tl">${evs.map((e) => `<div class="tl-item">
            <span class="tl-time">${esc(fmtTime(e.time))}</span><span class="tl-kind">${esc(e.kind)}</span>
            <span class="tl-detail">${esc(JSON.stringify(e.detail || {}).slice(0, 90))}</span></div>`).join("")
            || "<p class='muted'>暂无事件。</p>"}</div>
        </div>
      </div>
    </div>`;
  $$("#detailBody [data-copy]").forEach((b) => b.onclick = () => copyText(b.dataset.copy, "flag"));
  $("#gotoFiles").onclick = () => setTab("files");
  const hasTriage = (k?._tree || []).some((f) =>
    f.type === "file" && String(f.path || "").replace(/\\/g, "/") === "triage.json");
  if (!hasTriage) {
    $("#ovTri").innerHTML = "<span class='muted'>尚无 triage.json（附件未分诊）。</span>";
    return;
  }
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
export function dHypo(c, k) {
  const hyps = k?.hypotheses || [];
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>假设阶梯（${hyps.length}）</h3>
      ${hyps.length ? `<table><tr><th>ID</th><th>状态</th><th>假设</th><th>优先级</th><th>预期信号</th><th>预算</th></tr>
        ${hyps.map((h) => `<tr><td class="wrap">${esc(h.id)}</td>
          <td><span class="badge b-${esc(h.status)}">${esc(h.status)}</span></td>
          <td class="wrap"><b>${esc(h.title)}</b><br><span class="muted">${esc(h.rationale || "")}</span></td>
          <td title="P(成功)×分值×时间价值÷预期分钟">${h.priority ?? ""}<button class="small" style="margin-left:4px;padding:0 5px" onclick="alert('优先级 = P(成功) × 分值 × 时间价值 ÷ 预期分钟数
competition.py prioritize 按此公式重排解题顺序')">?</button></td><td class="wrap muted">${esc(h.expected_signal ?? h.expected ?? "")}</td>
          <td class="muted">${h.estimated_minutes ?? h.minutes ?? ""}分</td></tr>`).join("")}
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
let attFilter = "all";

export function dAttempt(c, k) {
  const enums = S.comp.enums;
  const atts = k?.attempts || [];
  const shown = attFilter === "all" ? atts
    : attFilter === "good" ? atts.filter((a) => a.outcome === "success")
    : attFilter === "bad" ? atts.filter((a) => a.outcome === "failure" || a.outcome === "error")
    : atts.filter((a) => a.outcome === "partial");
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>尝试记录（${atts.length}）</h3>
      <div class="chip-row">
        ${[["all", "全部"], ["good", "✓ 成功"], ["partial", "◐ 部分进展"], ["bad", "✗ 失败/出错"]].map(([id, lbl]) =>
          `<button class="${attFilter === id ? "on" : ""}" data-f="${id}">${lbl}</button>`).join("")}
      </div>
      ${shown.length ? `<table><tr><th>#</th><th>时间</th><th>执行者</th><th>动作 → 结果</th><th>结局</th><th>变体</th></tr>
        ${shown.slice(-25).reverse().map((a, ri) => {
          const ag = agentOf(a, "action");
          return `<tr><td class="muted">${shown.length - ri}</td>
          <td class="muted">${esc(fmtTime(a.time))}</td>
          <td>${ag ? `<span class="ag-chip" style="--ac2:${agentColorOf(ag)}">${esc(ag)}</span>` : "<span class='muted'>—</span>"}</td>
          <td class="wrap">${hiFlag(a.action)} <span class="muted">→ ${hiFlag(a.result)}</span></td>
          <td><span class="badge b-${esc(a.outcome)}">${esc(a.outcome)}</span></td>
          <td class="muted">${a.variants ? a.variants.toLocaleString() : ""}</td></tr>`; }).join("")}
        </table>` : "<p class='muted'>该筛选下暂无记录。</p>"}
      <div class="panel" style="margin:0 0 12px;padding:10px 14px">
          <b style="font-size:12px">⚡ 快速记录</b>
          <div class="row" style="margin:6px 0 0">
            <input id="quickAttText" placeholder="一行描述这次尝试做了什么…" style="flex:1;min-width:200px">
            <select id="quickAttOutcome" style="width:110px">
              <option value="partial">部分进展</option>
              <option value="success">成功</option>
              <option value="failure">失败</option>
            </select>
            <button id="quickAttSave" class="small primary">记录</button>
          </div>
        </div>
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
  $$("#detailBody .chip-row button").forEach((b) => b.onclick = () => {
    attFilter = b.dataset.f;
    renderDetail();
  });
    const qa = document.getElementById("quickAttSave");
  if (qa) qa.onclick = async () => {
    const text = document.getElementById("quickAttText").value.trim();
    if (!text) { toast("请填写描述", true); return; }
    const outcome = document.getElementById("quickAttOutcome").value;
    qa.disabled = true;   // R172：防连点重复提交
    try {
      const r = await post("case.attempt", { dir: S.dir,   // R172 修复：裸 post 不像 doAction 会自动补 dir——此前每次快速记录都 missing param: dir 静默失败
        case_dir: k.case_dir || ("cases/" + c.slug),
        hypothesis: "quick", action: text, result: "（快速记录）", outcome,
        minutes: 5, note: "快速记录" });
      if (r.ok) {
        document.getElementById("quickAttText").value = "";
        await refreshCase(); renderDetail();   // R172 修复：成功后刷新列表（此前列表不动，用户必重复提交）
      } else toast(r.error || "记录失败", true);
    } finally { qa.disabled = false; }
  };
  $("#attForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const agent = (f.get("agent") || "").trim();
    const params = { case_dir: S.caseDir, hypothesis: f.get("hypothesis"),
      action: f.get("action"),
      result: f.get("result"), outcome: f.get("outcome") };
    if (agent) params.agent = agent;
    if (f.get("hypothesis_status")) params.hypothesis_status = f.get("hypothesis_status");
    const r = await doAction("case.attempt", params);
    if (r.ok) { await refreshCase(); renderDetail(); }
  };
}

/* ---- R182 协作看板：按解题者分列的题目子看板 ---- */
const AGENT_TAG_COLORS = ["#58a6ff", "#3fb950", "#e0823d", "#bc8cff", "#f85149",
  "#d29922", "#4dd0e1", "#ec6bc5"];
function agentColorOf(tag) {
  let h = 0;
  for (const ch of String(tag || "")) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return AGENT_TAG_COLORS[h % AGENT_TAG_COLORS.length];
}
const AGENT_PREFIX_RE = /^\[([^\]\s]{1,16})\]\s/;
function agentOf(rec, textField) {
  const a = (rec && rec.agent) || "";
  if (a) return a;
  const m = String((rec && (rec[textField] || rec.action)) || "").match(AGENT_PREFIX_RE);
  return m ? m[1] : "";
}
let collabView = localStorage.getItem("wb.collabView") || "lanes";

const FLAG_RE = /(flag\{[^}<\s]{2,100}\}|DASCTF\{[^}<\s]{2,100}\}|FLAG\{[^}<\s]{2,100}\})/g;
function hiFlag(text) {
  return esc(text).replace(FLAG_RE, "<mark class=\"flag-hl\">$1</mark>");
}

export function dCollab(c, k) {
  const collab = (k && k._collab) || { claim: null, claims: [], handoffs: [], agents: [] };
  const atts = k?.attempts || [], evs = k?.evidence || [], hyps = k?.hypotheses || [];
  const roster = {};
  (collab.agents || []).forEach((a) => { if (a.tag) roster[a.tag] = a; });
  const nameOf = (t) => roster[t] ? (roster[t].label || roster[t].name || t) : t;

  // 归集各执行者的记录
  const lanes = {};   // tag -> {atts:[], evs:[], hyps:[], last:0}
  const lane = (t) => (lanes[t] || (lanes[t] = { atts: [], evs: [], hyps: [], last: 0 }));
  atts.forEach((a) => { const t = agentOf(a, "action"); const L = lane(t);
    L.atts.push(a); L.last = Math.max(L.last, +new Date(a.time || 0)); });
  evs.forEach((e) => { const t = agentOf(e, "claim"); lane(t).evs.push(e); });
  hyps.forEach((h) => { const t = agentOf(h, "title"); lane(t).hyps.push(h); });
  (collab.handoffs || []).forEach((h) => { if (h.agent_tag) lane(h.agent_tag).last = Math.max(lane(h.agent_tag).last, +new Date(h.time || 0)); });

  // 列顺序：当前认领者 → 最近活跃 → … → 未标记("")
  const claimTags = new Set((collab.claims || []).map((c) => c.agent_tag)
    .concat(collab.claim ? [collab.claim.agent_tag] : []));
  const claimTag = collab.claim?.agent_tag || "";   // 首持有者（列排序用）
  const tags = Object.keys(lanes).filter((t) => t).sort((a, b) =>
    (a === claimTag ? -1 : 0) - (b === claimTag ? -1 : 0) || lanes[b].last - lanes[a].last);
  if (lanes[""]) tags.push("");

  const laneHtml = (t) => {
    const L = lanes[t] || { atts: [], evs: [], hyps: [] };
    const isClaim = claimTags.has(t);
    const lastAtt = L.atts.slice(-3).reverse();
    const lastEvs = L.evs.slice(-2).reverse();
    const handoffN = (collab.handoffs || []).filter((h) => h.agent_tag === t).length;
    const dot = t ? agentColorOf(t) : "#64748b";
    return `
      <div class="collab-col" style="--cc:${dot}">
        <div class="cc-head">
          <span class="cc-dot" style="background:${dot}"></span>
          <b>${t ? esc(t) : "未标记"}</b>
          ${t ? `<span class="muted" style="font-size:11px">${esc(nameOf(t))}</span>` : ""}
          ${isClaim ? '<span class="badge" style="--b-c:#fbbf24">🔓 认领中</span>'
            : handoffN ? `<span class="badge" style="--b-c:#a78bfa">已交接 ×${handoffN}</span>`
            : t in roster ? "" : ""}
        </div>
        <div class="cc-stats">
          <span>假设 ${L.hyps.length}</span><span>尝试 ${L.atts.length}</span><span>证据 ${L.evs.length}</span>
          ${L.atts.some((a) => a.outcome === "success") ? '<span class="badge" style="--b-c:#34d399">✓ 有成功</span>' : ""}
        </div>
        ${lastAtt.length ? `<div class="cc-atts">${lastAtt.map((a) => `
          <div class="cc-item">
            <span class="badge b-${esc(a.outcome)}">${esc(a.outcome)}</span>
            <span class="cc-txt">${esc((a.action || "").slice(0, 80))}</span>
            <span class="muted" style="font-size:10.5px">${esc(fmtTime(a.time).slice(11, 16))}</span>
          </div>`).join("")}</div>` : `<div class="cc-empty">暂无尝试记录</div>`}
        ${lastEvs.length ? `<div class="cc-evs">${lastEvs.map((e) => `
          <div class="cc-item ev"><span class="cc-txt">💡 ${esc((e.claim || "").slice(0, 60))}</span></div>`).join("")}</div>` : ""}
      </div>`;
  };

  $("#detailBody").innerHTML = `
    <div class="panel">
      <h3>题目子看板 <span class="muted">一条路线 = 一个解题方向，同题共解互不干扰</span></h3>
      <div class="row" style="margin:0 0 10px">
        <div class="chip-row" style="margin:0">
          <button class="${collabView === "lanes" ? "on" : ""}" data-cv="lanes">▤ 分列</button>
          <button class="${collabView === "graph" ? "on" : ""}" data-cv="graph">🧠 思维导图</button>
        </div>
        <span class="spacer" style="flex:1"></span>
        <input id="qHypo" placeholder="＋ 登记解题方向（如：SQL 注入 / 图片隐写）" style="min-width:230px">
        <button id="qHypoSave" class="small">登记方向</button>
        <input id="qFlag" placeholder="＋ 登记 flag 候选" style="min-width:150px;font-family:var(--mono)">
        <button id="qFlagSave" class="small">登记 flag</button>
      </div>
      <div class="collab-summary">
        <span>路线 <b>${tags.filter((t) => t).length}</b></span>
        <span>尝试 <b>${atts.length}</b></span>
        <span>证据 <b>${evs.length}</b></span>
        <span>交接 <b>${(collab.handoffs || []).length}</b> 次</span>
        ${claimTag ? `<span>当前认领：<b style="color:${agentColorOf(claimTag)}">${esc(claimTag)} ${esc(nameOf(claimTag))}</b></span>` : '<span class="muted">当前无人认领</span>'}
      </div>
      ${(collab.handoffs || []).length ? `<details style="margin:8px 0 0"><summary class="muted">交接链（${collab.handoffs.length}）</summary>
        <div class="tl" style="margin-top:8px">${collab.handoffs.slice(0, 5).map((h) => `
          <div class="tl-item"><span class="tl-time">${esc(fmtTime(h.time))}</span>
          <span class="tl-kind">${esc(h.agent_tag || "")}</span>
          <span class="tl-detail">${esc((h.summary || "").slice(0, 100))}（findings ${h.findings}）</span></div>`).join("")}</div></details>` : ""}
    </div>
    ${collabView === "graph" ? mindmapHtml(c, k, lanes, tags, claimTag)
      : tags.length
        ? `<div class="collab-board">${tags.map(laneHtml).join("")}</div>`
        : `<div class="empty"><div class="big">🤝</div>还没有解题记录：上方可直接登记方向/flag；<br>AI 侧发「完整介入提示词」（AI 看板 → 复制）即可自助加入共解。</div>`}`;
  // 视图切换
  $$("#detailBody [data-cv]").forEach((b) => b.onclick = () => {
    collabView = b.dataset.cv;
    localStorage.setItem("wb.collabView", collabView);
    renderDetail();
  });
  // 快速登记方向
  const qh = $("#qHypoSave");
  if (qh) qh.onclick = async () => {
    const t = $("#qHypo").value.trim();
    if (!t) return toast("请填写方向描述", true);
    const r = await doAction("case.hypothesis", { case_dir: S.caseDir,
      title: t, rationale: "协作看板快速登记", expected: "待补充", agent: "本地" });
    if (r.ok) { $("#qHypo").value = ""; await refreshCase(); renderDetail(); }
  };
  // 快速登记 flag
  const qf = $("#qFlagSave");
  if (qf) qf.onclick = async () => {
    const v = $("#qFlag").value.trim();
    if (!v) return toast("请填写 flag 候选", true);
    const r = await doAction("case.candidate_add", { case_dir: S.caseDir,
      flag: v, source: "协作看板快速登记", agent: "本地" });
    if (r.ok) { $("#qFlag").value = ""; toast(`候选 ${r.candidate_id} 已登记 ✓`);
      await refreshCase(); renderDetail(); }
  };
  // 思维导图 pan/zoom（CSP：无 inline handler，统一绑定）
  const canvas = document.getElementById("mmCanvas");
  if (canvas) {
    let vx = 0, vy = 0, scale = 1, drag = null;
    const MM = window.__mmState = { get scale() { return scale; },
      zoom: (f) => { scale = Math.min(3, Math.max(0.35, scale * f)); apply(); },
      reset: () => { vx = 0; vy = 0; scale = 1; apply(); } };
    const apply = () => {
      const svg = document.getElementById("mmSvg");
      if (svg) svg.style.transform = `translate(${vx}px,${vy}px) scale(${scale})`;
    };
    document.querySelectorAll("[data-mmz]").forEach((b) => b.onclick = () => {
      if (b.dataset.mmz === "in") MM.zoom(1.25);
      else if (b.dataset.mmz === "out") MM.zoom(0.8);
      else MM.reset();
    });
    // 富 tooltip（老版 gth 的 CSP 安全版）
    const tip = document.getElementById("mmTip");
    canvas.addEventListener("mouseover", (e) => {
      const c = e.target.closest("circle[data-tip]");
      if (!c || !tip) { if (tip) tip.hidden = true; return; }
      const d = (window.__mmTips || [])[+c.dataset.tip];
      if (!d) return;
      tip.innerHTML = `<b style="color:${d.col}">${esc(d.agent || "?")}</b>
        <span class="muted">${esc(fmtTime(d.a.time))} · ${esc(d.a.outcome)}</span>
        <div class="mm-tip-body">${esc((d.a.action || "").slice(0, 60))}<br>
        <span class="muted">${esc((d.a.result || "").slice(0, 100))}</span></div>`;
      tip.hidden = false;
      const rect = canvas.getBoundingClientRect();
      tip.style.left = Math.min(e.clientX - rect.left + 14, rect.width - 220) + "px";
      tip.style.top = (e.clientY - rect.top + 10) + "px";
    });
    canvas.addEventListener("mouseleave", () => { if (tip) tip.hidden = true; });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      scale = Math.min(3, Math.max(0.35, scale * (e.deltaY < 0 ? 1.12 : 0.89)));
      apply();
    }, { passive: false });
    canvas.addEventListener("mousedown", (e) => { drag = { x: e.clientX - vx, y: e.clientY - vy }; });
    canvas.addEventListener("mousemove", (e) => {
      if (!drag) return;
      vx = e.clientX - drag.x; vy = e.clientY - drag.y; apply();
    });
    canvas.addEventListener("mouseup", () => { drag = null; });
    canvas.addEventListener("mouseleave", () => { drag = null; });
  }
}

/* ---- R183 思维导图：复刻老 warroom 流程图（题目居左 · 每 agent 一条主枝 · 节点按结局着色） ---- */
function mindmapHtml(c, k, lanes, tags, claimTag) {
  const OUT_COLOR = { success: "#3fb950", failure: "#f85149",
    partial: "#d29922", error: "#8b96a8" };
  const atts = k?.attempts || [], evs = k?.evidence || [], cands = k?.candidates || [];
  const evAgents = new Set(evs.map((e) => agentOf(e, "claim")));
  // 突破证据 id 集（evidence kind=breakthrough）→ 命中的 attempt 节点紫圈
  const btIds = new Set(evs.filter((e) => e.kind === "breakthrough").map((e) => e.id));
  const hasFlag = cands.some((x) => ["validated", "submitted", "accepted"].includes(x.status));
  const mmTips = [];   // 节点富 tooltip 数据
  if (!atts.length && !evs.length) {
    return `<div class="empty"><div class="big">🕸️</div>还没有可画的记录——先在上方登记方向或让 AI 写过程。</div>`;
  }
  const leftX = 190, stepX = 140, topY = 40;
  const branchGap = Math.max(96, Math.min(170, 560 / Math.max(tags.length, 1)));
  const maxSteps = Math.max(1, ...tags.map((t) => (lanes[t] ? lanes[t].atts.length : 0)));
  const W = Math.max(860, leftX + maxSteps * stepX + 120);
  const H = topY + tags.length * branchGap + 60;
  const titleY = H / 2;
  let s = "";
  // 题目节点（左侧）
  s += `<rect x="18" y="${titleY - 34}" width="140" height="68" rx="10" fill="#161b22"
    stroke="var(--accent)" stroke-width="2"/>`;
  s += `<text x="88" y="${titleY - 10}" text-anchor="middle" fill="var(--accent)" font-size="12"
    font-weight="bold">${esc((c.name || "").slice(0, 12))}</text>`;
  s += `<text x="88" y="${titleY + 8}" text-anchor="middle" fill="#8b96a8" font-size="9">
    ${esc(c.category || "")} · ${esc(statusLabel(c.case?.status || "new"))}</text>`;
  s += `<text x="88" y="${titleY + 22}" text-anchor="middle" fill="#8b96a8" font-size="8">
    ${tags.filter((t) => t).length} 条路线 · ${atts.length} 次尝试</text>`;
  const candOk = cands.filter((x) => ["validated", "submitted", "accepted"].includes(x.status));
  if (candOk.length) s += `<text x="88" y="${titleY - 24}" text-anchor="middle" font-size="11">🚩</text>`;
  // 主枝
  tags.forEach((t, i) => {
    const y = topY + 30 + i * branchGap;
    const col = t ? agentColorOf(t) : "#64748b";
    const L = lanes[t] || { atts: [], evs: [], hyps: [] };
    s += `<path d="M158,${titleY} C176,${titleY} 176,${(titleY + y) / 2} ${leftX - 26},${y - 14}
      L${leftX},${y}" fill="none" stroke="${col}" stroke-opacity="0.25" stroke-width="1.6"/>`;
    s += `<text x="${leftX - 8}" y="${y - 8}" text-anchor="end" fill="${col}" font-size="11"
      font-weight="bold">${esc(t || "未标记")}</text>`;
    if (L.hyps.length) {
      const h0 = L.hyps[L.hyps.length - 1];
      s += `<text x="${leftX - 8}" y="${y + 5}" text-anchor="end" fill="#8b96a8" font-size="8.5">
        ${esc((h0.title || "").slice(0, 16))}</text>`;
    }
    if (claimTag && t === claimTag) s += `<text x="${leftX - 8}" y="${y + 17}" text-anchor="end"
      fill="#fbbf24" font-size="8">🔓 解题中</text>`;
    s += `<line x1="${leftX}" y1="${y}" x2="${Math.max(leftX + L.atts.length * stepX, leftX + 56)}"
      y2="${y}" stroke="${col}" stroke-opacity="0.18" stroke-width="2"/>`;
    // 尝试节点
    L.atts.forEach((a, j) => {
      const x = leftX + 26 + j * stepX;
      const oc = OUT_COLOR[a.outcome] || "#8b96a8";
      const isBT = (a.evidence_ids || []).some((id) => btIds.has(id));
      const isLastSuccess = hasFlag && a.outcome === "success"
        && !(L.atts.slice(j + 1).some((b) => b.outcome === "success"));
      const r = isBT ? 10 : a.outcome === "success" ? 8 : 6.5;
      if (j > 0) s += `<line x1="${x - stepX + (6.5) + 2}" y1="${y}" x2="${x - r - 2}" y2="${y}"
        stroke="${col}" stroke-width="${a.outcome === "success" ? 2 : 1}"
        stroke-opacity="${a.outcome === "failure" ? 0.25 : 0.5}"/>`;
      mmTips.push({ agent: t, col, a });
      s += `<circle cx="${x}" cy="${y}" r="${r}" fill="${oc}" data-tip="${mmTips.length - 1}"
        fill-opacity="${a.outcome === "failure" ? 0.35 : 0.9}"
        ${isBT ? 'stroke="#bc8cff" stroke-width="2.5"' : ""}></circle>`;
      s += `<text x="${x}" y="${y - r - 6}" text-anchor="middle" fill="${oc}" font-size="8">
        ${esc((a.action || "").slice(0, 14))}</text>`;
      s += `<text x="${x}" y="${y + r + 12}" text-anchor="middle" fill="#8b96a8" font-size="7.5">
        ${esc(fmtTime(a.time).slice(11, 16))}</text>`;
      if (isLastSuccess) s += `<text x="${x}" y="${y - r - 17}" text-anchor="middle" font-size="11">🚩</text>`;
      else if (isBT) s += `<text x="${x}" y="${y - r - 17}" text-anchor="middle" font-size="9">⚡</text>`;
      else if (a.outcome === "success") s += `<text x="${x}" y="${y - r - 16}" text-anchor="middle" font-size="9">💡</text>`;
      else if (a.outcome === "failure") s += `<text x="${x}" y="${y - r - 16}" text-anchor="middle" font-size="8">✗</text>`;
      // 跨枝影响虚线：突破节点 → 时间轴后续（向右贯穿提示）
      if (isBT) s += `<line x1="${x + r + 4}" y1="${y}" x2="${W - 24}" y2="${y}"
        stroke="#bc8cff" stroke-width="1.2" stroke-dasharray="5 5" stroke-opacity="0.45"/>
        <text x="${W - 24}" y="${y - 5}" text-anchor="end" fill="#bc8cff" font-size="7.5" opacity="0.8">⚡ 突破 · 影响后续</text>`;
    });
    // 证据 💡 徽标（枝尾）
    if (evAgents.has(t)) s += `<text x="${leftX + 26 + L.atts.length * stepX}" y="${y + 4}"
      text-anchor="middle" font-size="11">💡</text>`;
  });
  window.__mmTips = mmTips;
  return `<div class="mm-wrap">
    <div class="mm-controls">
      <button data-mmz="in" aria-label="放大">＋</button>
      <button data-mmz="out" aria-label="缩小">−</button>
      <button data-mmz="reset" aria-label="复位">⟲</button>
    </div>
    <div class="mm-tip" id="mmTip" hidden></div>
    <div class="mm-canvas" id="mmCanvas"><svg id="mmSvg" width="${W}" height="${H}"
      viewBox="0 0 ${W} ${H}">${s}</svg></div>
    <div class="mm-legend muted">
      <span><i style="background:#3fb950"></i>成功</span>
      <span><i style="background:#d29922"></i>部分进展</span>
      <span><i style="background:#f85149"></i>失败/排除</span>
      <span><i style="background:transparent;border:2px solid #bc8cff"></i>⚡ 突破（影响后续）</span>
      <span>🚩 flag 节点</span>
      <span>🖱️ 拖拽平移 · 滚轮缩放 · 悬停看详情</span>
    </div></div>`;
}

/* ---- 证据 / 线索 ---- */
export function dEvidence(c, k) {
  const enums = S.comp.enums;
  const evs = k?.evidence || [];
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>证据 / finding（${evs.length}）</h3>
      ${evs.length ? `<table><tr><th>时间</th><th>执行者</th><th>类型</th><th>置信</th><th>结论</th><th>来源</th></tr>
        ${evs.slice(-20).reverse().map((e) => { const eg = agentOf(e, "claim");
        return `<tr><td class="muted">${esc(fmtTime(e.time))}</td>
          <td>${eg ? `<span class="ag-chip" style="--ac2:${agentColorOf(eg)}">${esc(eg)}</span>` : "<span class='muted'>—</span>"}</td>
          <td>${e.kind === "breakthrough"
            ? '<span class="badge" style="--b-c:#bc8cff">⚡ 突破</span>'
            : esc(e.kind || "")}</td><td>${e.confidence ?? ""}</td>
          <td class="wrap">${esc(e.claim || "")}</td>
          <td class="wrap muted">${esc(e.source || "")}</td></tr>`; }).join("")}
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
export function dExcluded(c, k) {
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
      ${atts.length ? `<table><tr><th>时间</th><th>执行者</th><th>动作 → 结果</th><th>结局</th><th>已排变体</th></tr>
        ${atts.slice(-25).reverse().map((a) => { const xg = agentOf(a, "action");
        return `<tr><td class="muted">${esc(fmtTime(a.time))}</td>
          <td>${xg ? `<span class="ag-chip" style="--ac2:${agentColorOf(xg)}">${esc(xg)}</span>` : "—"}</td>
          <td class="wrap">${esc(a.action || "")} <span class="muted">→ ${esc(a.result || "")}</span></td>
          <td><span class="badge b-${esc(a.outcome)}">${esc(a.outcome)}</span></td>
          <td>${a.variants ? `<b>${a.variants.toLocaleString()}</b>` : ""}</td></tr>`; }).join("")}</table>`
        : "<p class='muted'>暂无失败尝试。</p>"}
    </div>`;
}

/* ---- Flag 候选（页内快审） ---- */
export async function dCands(c, k) {
  const cands = (k?.candidates || []).slice().reverse();   // 最新在前
  let subs = [];
  try {
    const r = await api(`/api/submissions?dir=${encodeURIComponent(S.dir)}&after=0`);
    subs = (r.entries || []).filter((e) => e.challenge_slug === S.slug).reverse();
  } catch { /* 提交记录可选 */ }
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>Flag 候选（${cands.length}）
      <span class="muted">unverified → validated 后才可提交</span></h3>
      ${cands.length ? `<table><tr><th>ID</th><th>值</th><th>状态</th><th>来源/备注</th><th>操作</th></tr>
        ${cands.map((x) => {
          const btns = [];
          if (x.status === "unverified") btns.push(`<button class="small primary" data-a="validate" data-id="${esc(x.id)}">✓ 校验通过</button>`);
          if (x.status === "unverified" || x.status === "validated") btns.push(`<button class="small" data-a="reject" data-id="${esc(x.id)}">✗ 驳回</button>`);
          if (x.status === "validated") btns.push(`<button class="small danger" data-a="submit" data-id="${esc(x.id)}">提交…</button>`);
          btns.push(`<button class="small copy-btn" data-copy="${esc(x.value)}">复制</button>`);
          return `<tr><td class="wrap">${esc(x.id)}</td>
            <td class="wrap" style="font-family:var(--mono)">${hiFlag(x.value)}</td>
            <td><span class="badge b-${esc(x.status)}">${esc(x.status)}</span></td>
            <td class="wrap muted">${esc([x.source, x.note].filter(Boolean).join(" · ").slice(0, 40))}</td>
            <td><div class="row" style="margin:0">${btns.join("")}</div></td></tr>`;
        }).join("")}</table>
        <button id="gotoFlags" class="small" style="margin-top:8px">完整审核队列 →</button>`
        : "<p class='muted'>暂无候选——概览页或协作看板可直接登记。</p>"}
      <div class="panel" style="margin-top:14px"><h3>提交记录（submissions） <span class="muted">${subs.length} 条</span></h3>
        ${subs.length ? `<table><tr><th>时间</th><th>模式</th><th>结果</th><th>来源</th></tr>
          ${subs.map((e) => `<tr>
            <td class="muted">${esc(fmtTime(e.time))}</td>
            <td>${e.dry_run ? '<span class="badge" style="--b-c:#8b96a8">dry-run</span>'
              : '<span class="badge" style="--b-c:#fbbf24">LIVE</span>'}</td>
            <td>${e.outcome === "accepted"
              ? '<span class="badge" style="--b-c:#34d399">✅ accepted</span>'
              : `<span class="badge" style="--b-c:#f87171">${esc(e.outcome || "?")}</span>`}</td>
            <td class="muted">${esc(e.source || "")}${e.note ? " · " + esc(e.note) : ""}</td>
          </tr>`).join("")}</table>`
          : "<p class='muted'>还没有提交记录（dry-run / live 都会留痕）。</p>"}
      </div>
      <details style="margin-top:10px"><summary class="muted">＋ 手动登记 flag 候选</summary>
        <form id="candAddForm" class="row" style="margin-top:8px">
          <input name="flag" placeholder="flag{...} 或平台答案" required style="flex:1;min-width:220px;font-family:var(--mono)">
          <input name="source" placeholder="来源（如 手工推导/脚本输出）" style="min-width:180px">
          <input name="agent" placeholder="登记人（可空）" style="width:120px">
          <button class="primary small">登记</button>
        </form></details>
    </div>`;
  $("#gotoFlags").onclick = () => setTab("flags");
  const caf = $("#candAddForm");
  if (caf) caf.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(caf);
    const r = await doAction("case.candidate_add", { case_dir: S.caseDir,
      flag: f.get("flag"), source: f.get("source") || "manual",
      agent: (f.get("agent") || "").trim() });
    if (r.ok) { toast(`候选 ${r.candidate_id} 已登记 ✓`); await refreshCase(); renderDetail(); }
  };
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
export async function dPrompt(c, k) {
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
export function dRules() {
  $("#detailBody").innerHTML = `
    <div class="panel"><h3>多 Agent 协作六步（老 warroom 工作流 · 网关版）</h3>
      <ol style="line-height:1.9">
        <li><b>看名册与认领</b>：<code>GET /api/agent-gw/directory</code>——谁在解什么、哪些题空闲。</li>
        <li><b>读题目上下文</b>：dispatch 的 prompt 已注入题面 + 前任交接简报 + 已有 findings。</li>
        <li><b>选方向再动手</b>：先 <code>case.hypothesis</code> 登记你的解题方向（子看板会按此分列），别重复别人走过的死路。</li>
        <li><b>过程落档</b>：每步 <code>case.attempt</code>（动作/结果/结局/变体数），关键结论 <code>case.finding</code>（突破标 breakthrough）。</li>
        <li><b>出 flag</b>：<code>case.candidate_add</code> 登记 → 校验 → dry-run → 人工放行。</li>
        <li><b>离场交接</b>：<code>handoff</code> 写清阶段结论与线索，认领自动释放，下任 dispatch 自动收到你的简报。</li>
      </ol></div>
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
