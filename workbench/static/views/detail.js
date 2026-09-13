/* ---------------- ② 题目详情（工作区式子页签） ---------------- */
import { S } from "../state.js";
import { $, $$, esc, fmtSize, fmtTime, toast, snapshotDetailForms, restoreDetailForms } from "../ui.js";
import { api } from "../api.js";
import { statusLabel, catColor, statusColor } from "./board.js";
import { openSubmitModal } from "./flags.js";
import { doAction, loadCase, loadCompetition, refreshCase, setTab } from "../app.js";

export const DETAIL_TABS = [
  ["overview", "概览"], ["hypo", "假设阶梯"], ["attempt", "尝试记录"], ["evidence", "证据 / 线索"],
  ["excluded", "排除 / 失败"], ["cands", "Flag 候选"], ["prompt", "提示词"], ["rules", "守则"],
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

export async function renderDetail() {
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
  tabs.innerHTML = DETAIL_TABS.map(([id, label]) =>
    `<button data-st="${id}" class="${S.dtab === id ? "on" : ""}">${label}</button>`).join("");
  $$("#detailSubtabs button").forEach((b) => b.onclick = () => {
    S.dtab = b.dataset.st;
    localStorage.setItem("wb.dtab", S.dtab);
    renderDetail();
  });
  const sub = ({ overview: dOverview, hypo: dHypo, attempt: dAttempt, evidence: dEvidence,
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
  const evs = (k?.events || []).slice(-8).reverse();
  body.innerHTML = `
    <div class="panel"><h3>进度（${esc(statusLabel(k?.status || "new"))}）</h3>${flowHtml(k?.status)}
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
          <td>${h.priority ?? ""}</td><td class="wrap muted">${esc(h.expected_signal ?? h.expected ?? "")}</td>
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
      ${shown.length ? `<table><tr><th>时间</th><th>假设</th><th>动作 → 结果</th><th>结局</th></tr>
        ${shown.slice(-25).reverse().map((a) => `<tr><td class="muted">${esc(fmtTime(a.time))}</td>
          <td class="wrap">${esc(a.hypothesis || "")}</td>
          <td class="wrap">${esc(a.action || "")} <span class="muted">→ ${esc(a.result || "")}</span></td>
          <td><span class="badge b-${esc(a.outcome)}">${esc(a.outcome)}</span></td></tr>`).join("")}
        </table>` : "<p class='muted'>该筛选下暂无记录。</p>"}
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
export function dEvidence(c, k) {
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
      ${atts.length ? `<table><tr><th>时间</th><th>假设</th><th>动作 → 结果</th><th>结局</th></tr>
        ${atts.slice(-25).reverse().map((a) => `<tr><td class="muted">${esc(fmtTime(a.time))}</td>
          <td class="wrap">${esc(a.hypothesis || "")}</td>
          <td class="wrap">${esc(a.action || "")} <span class="muted">→ ${esc(a.result || "")}</span></td>
          <td><span class="badge b-${esc(a.outcome)}">${esc(a.outcome)}</span></td></tr>`).join("")}</table>`
        : "<p class='muted'>暂无失败尝试。</p>"}
    </div>`;
}

/* ---- Flag 候选（页内快审） ---- */
export function dCands(c, k) {
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
