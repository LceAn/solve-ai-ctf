/* ---------------- ⑧ 比赛动作 ---------------- */
import { S } from "../state.js";
import { $, $$, esc, toast } from "../ui.js";
import { authHeaders, api, post } from "../api.js";
import { TaskUI } from "./tasks.js";
import { doAction, loadCompetition, setTab } from "../app.js";

export const OPS_TABS = [
  ["agents", "🔌 开赛自动化"], ["register", "📝 注册题目"], ["scoring", "🎯 训练模式"],
  ["grades", "⭐ 难度分级"], ["opsrun", "🛠️ 运维操作"],
];

export function renderOps() {
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
  ({ agents: opsAgents, register: opsRegister, scoring: opsScoring,
     grades: opsGrades, opsrun: opsRun }[S.otab] || opsAgents)(plat);
}

export function platRows(plat) {
  const archived = plat.migration?.status === "archived" || plat.submission_mode === "browser_ui";
  const platColor = archived ? "#fbbf24" : plat.status === "auto-configured" ? "#34d399"
    : plat.status && plat.status !== "unconfigured" ? "#fbbf24" : "#94a3b8";
  const displayStatus = archived ? "需浏览器 UI 提交" : (plat.status || "unconfigured");
  return `
    <table style="max-width:640px">
      <tr><th>状态</th><td><span class="badge" style="--b-c:${platColor}">${esc(displayStatus)}</span></td></tr>
      <tr><th>平台基址</th><td class="wrap mono">${esc(plat.base_url || "未配置")}</td></tr>
      <tr><th>令牌环境变量</th><td class="mono">${esc(plat.auth?.value_env || "CTF_TOKEN")}</td></tr>
      <tr><th>已注册题目</th><td>${(S.comp.challenges || []).length} 题</td></tr>
      <tr><th>门户</th><td class="wrap mono">${esc(plat.portal?.login_url || "未填写")}</td></tr>
      ${archived ? `<tr><th>迁移平台</th><td class="wrap"><b>${esc(plat.migration?.name || "新平台")}</b>` +
        `${plat.migration?.base_url ? ` · <a href="${esc(plat.migration.base_url)}" target="_blank" rel="noreferrer">打开平台</a>` : ""}` +
        `<div class="muted" style="margin-top:4px">${esc(plat.migration?.note || "旧平台已归档，需先在浏览器 UI 完成提交，再记录脱敏回执。")}</div></td></tr>` : ""}
    </table>`;
}

/* R48-F2：本地文档路径设置（写入 competition.json docs_path，文档页只读浏览） */
export function bindDocsPath() {
  const wrap = document.getElementById("docsPathWrap");
  if (!wrap) return;
  const input = document.getElementById("docsPathInput");
  const save = document.getElementById("docsPathSave");
  const msg = document.getElementById("docsPathMsg");
  input.value = S.comp?.docs_path || "";
  save.onclick = async () => {
    const r = await post("competition.set_docs", { dir: S.dir, path: input.value.trim() });
    if (r.ok) { toast("文档路径已保存 ✓"); await loadCompetition(); msg.textContent = "✓ 已保存"; }
    else { msg.textContent = "✗ " + (r.error || "保存失败"); }
  };
}

export function bindAgentButtons() {
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
  if (bb) bb.onclick = () => {
    const preset = $("#presetSel")?.value || "buuctf";
    startAgent("buuctf", `预设 ${preset} 对接`, { preset })();
  };
  api("/api/presets").then((r) => {
    const sel = $("#presetSel");
    if (!sel || !r.presets?.length) return;
    sel.innerHTML = r.presets.map((x) =>
      `<option value="${esc(x.name)}">${esc(x.name)}${x.base_url ? " · " + esc(x.base_url.replace("https://", "")) : ""}</option>`).join("");
  }).catch(() => {});
}

/* ---- 子页签 1：开赛自动化 ---- */
export function opsAgents(plat) {
  const body = $("#opsBody");
  const archived = plat.migration?.status === "archived" || plat.submission_mode === "browser_ui";
  body.innerHTML = `
    ${archived ? `<div class="panel" style="border-color:rgba(251,191,36,.45);background:rgba(251,191,36,.06)">
      <b style="color:var(--yellow)">⚠ 旧平台已归档</b>
      <p class="muted" style="margin:6px 0 0">当前 BUUCTF 提交不能再走 buuoj.cn API。请在 ${esc(plat.migration?.name || "迁移平台")} 浏览器 UI 完成提交；成功后用 <code>submitter.py record</code> 写入脱敏回执。下面的自动对接按钮仅用于重新探测，不会替代浏览器提交。</p>
    </div>` : ""}
    <div class="agent-grid">
      <div class="panel agent-big" style="--oc:var(--accent)">
        <div class="ag-top">
          <span class="oc-ic">🔌</span>
          <div class="ag-tt"><b>自动对接平台</b>
            <p class="muted">探测平台 API 形态（CTFd 系优先）→ 自动写入提交脚本配置（platform 段）。完成后先用 submitter dry-run 验证提交端点，再放行 --live。</p></div>
        </div>
        <span class="ag-badge" data-agent-badge="platform-agent"></span>
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
      <div class="row" style="margin:0 0 8px">
        <label class="muted" style="white-space:nowrap">预设
          <select id="presetSel" style="min-width:150px"></select></label>
      </div>
      <button id="agentBuu" class="primary">${archived ? "重新套用旧站预设" : "套用预设并自动对接"}</button>
    </div>
    <div class="panel">
      <h3>平台状态</h3>
      ${platRows(plat)}
    </div>`;
  bindAgentButtons();
  if (typeof bindDocsPath === "function") bindDocsPath();
}

/* ---- 子页签 2：注册题目 ---- */
export function opsRegister(plat) {
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

/* ---- 子页签 3：训练模式 ----
 * 平台定位：CTF 解题训练系统。本子页签不再暴露竞技评分策略（dynamic/static/decay/
 * first_blood_bonus），而是组织三种训练场景：自由练习 / 模拟赛 / 复盘。
 * 评分策略仍由 case.difficulty_grade 驱动（见「难度分级」子页签），
 * 后端 set_mode/set_scoring 动作保留兼容，但前端不再提供评分策略 UI。
 */
export function opsScoring(plat) {
  const body = $("#opsBody");
  const cfg = S.comp?.config || {};
  const mode = cfg.mode || "individual";
  const teams = cfg.teams || [];
  const modes = [
    { id: "individual", icon: "📖", label: "自由练习",
      hint: "无时限 · 按 operator 个人进度统计 · 适合刷题与技能补强" },
    { id: "team", icon: "🤝", label: "模拟赛",
      hint: "组队限时模拟 · 按 training group 聚合 · 适合赛前备战" },
    { id: "review", icon: "🔄", label: "复盘",
      hint: "跳转时间线 + 训练进度仪表盘 · 复盘历史提交与薄弱方向" },
  ];
  body.innerHTML = `
    <div class="panel">
      <h3>训练模式 <span class="muted">自由练习 / 模拟赛 / 复盘</span></h3>
      <div class="row" role="tablist" aria-label="训练模式">
        ${modes.map((m) =>
          `<button data-mode="${m.id}" data-is-review="${m.id === "review"}" class="op-card mode-seg ${mode === m.id || (m.id === "individual" && mode === "timed") ? "on" : ""}" style="--oc:var(--accent);width:auto;flex:1;max-width:240px" role="tab" aria-selected="${mode === m.id}">
            <span class="oc-ic">${m.icon}</span>
            <span class="oc-tt">${m.label}<small>${m.hint}</small></span>
          </button>`).join("")}
      </div>
      <p class="muted" style="margin:8px 0 0">当前： <code>${esc(mode)}</code> · 自由练习与模拟赛切换会写入 competition.json 顶层 mode 字段；复盘模式不切换 mode，直接跳转时间线。</p>
    </div>
    <div class="panel">
      <h3>训练小组 <span class="muted">teams[] · 模拟赛模式下用于组队统计</span></h3>
      ${teams.length ? `
        <table style="margin-bottom:12px">
          <tr><th>team_id</th><th>name</th><th>color</th><th>创建</th></tr>
          ${teams.map((t) => `<tr><td class="mono">${esc(t.team_id || t.id || "")}</td>
            <td>${esc(t.name || "")}</td>
            <td><span class="cat-dot" style="background:${esc(t.color || "#4f8cff")}"></span> <code>${esc(t.color || "")}</code></td>
            <td class="muted">${esc(t.created_at || "")}</td></tr>`).join("")}
        </table>` : `<p class="muted">还没有训练小组，使用下方表单添加。</p>`}
      <form id="teamForm" class="row" aria-label="添加训练小组">
        <label class="f" style="min-width:140px">team_id（留空自动）<input name="team_id" placeholder="auto"></label>
        <label class="f" style="flex:1;min-width:180px">名称 *<input name="name" required placeholder="例如：赛前备战组"></label>
        <label class="f" style="min-width:120px">颜色<input name="color" type="color" value="#4f8cff"></label>
        <button class="primary">添加小组</button>
      </form>
    </div>
    <div class="panel" style="border-color:rgba(79,140,255,.4);background:rgba(79,140,255,.05)">
      <h3>📌 关于评分</h3>
      <p class="muted" style="margin:0">本系统是 CTF 解题训练工具，不暴露竞技评分策略（dynamic/static/decay/first_blood_bonus）。
      题目难度由 <code>case.difficulty_grade</code>（1-5 星，见「难度分级」子页签）标识；训练进度由
      <code>/api/leaderboard?mode=individual</code> 的 <code>progress</code> 字段（六维技能雷达 + 类别覆盖率 + 近 7 天活跃）呈现。
      如需调整难度基础分值，请使用「难度分级」子页签。</p>
    </div>`;
  $$("#opsBody .mode-seg").forEach((b) => b.onclick = async () => {
    if (b.dataset.isReview === "true") { setTab("timeline"); return; }
    const r = await doAction("competition.set_mode", { mode: b.dataset.mode }, { noReload: true });
    if (r.ok) { await loadCompetition(); renderOps(); }
  });
  const teamForm = $("#teamForm");
  if (teamForm) teamForm.onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const params = { name: f.get("name") };
    if (f.get("team_id")) params.team_id = f.get("team_id");
    if (f.get("color")) params.color = f.get("color");
    const r = await doAction("competition.add_team", params, { noReload: true });
    if (r.ok) { await loadCompetition(); renderOps(); }
  };
}

/* ---- 子页签 4：难度分级 ---- */
export function opsGrades(plat) {
  const body = $("#opsBody");
  const chs = S.comp?.challenges || [];
  const gradeLabel = (g) => "★".repeat(g || 1) + " " + ({ 1: "入门", 2: "简单", 3: "中等", 4: "进阶", 5: "困难" })[g || 1];
  const gradeColor = (g) => ["", "#34d399", "#2dd4bf", "#fbbf24", "#fb923c", "#f87171"][g || 1];
  const cfg = S.comp?.config || {};
  const scoring = cfg.scoring || { base_by_difficulty: { 1: 100, 2: 200, 3: 300, 4: 400, 5: 500 } };
  const base = scoring.base_by_difficulty || { 1: 100, 2: 200, 3: 300, 4: 400, 5: 500 };
  body.innerHTML = `
    <div class="panel">
      <h3>难度分级体系 <span class="muted">每题 1-5 星 · 驱动动态评分基础分值</span></h3>
      <table>
        <tr><th>星级</th><th>标签</th><th>基础分值</th><th>当前题数</th></tr>
        ${[1, 2, 3, 4, 5].map((g) => {
          const n = chs.filter((c) => (c.difficulty_grade || c.case?.difficulty_grade) === g).length;
          return `<tr><td><span style="color:${gradeColor(g)}">★${g}</span></td>
            <td>${gradeLabel(g)}</td>
            <td class="mono">${base[g] ?? g * 100}</td>
            <td>${n}</td></tr>`;
        }).join("")}
      </table>
      <p class="muted" style="margin:8px 0 0">调整分值请到「模式与评分」子页签；调整某题难度请用下方表格或题目详情。</p>
    </div>
    <div class="panel">
      <h3>逐题分级 <span class="muted">case.set_grade · 写入 case.json challenge.difficulty_grade</span></h3>
      ${chs.length ? `
        <table>
          <tr><th>题目</th><th>类别</th><th>当前分值</th><th>难度</th><th>实算分值（动态）</th><th>调整</th></tr>
          ${chs.map((c) => {
            const g = c.difficulty_grade || c.case?.difficulty_grade || 1;
            const pts = c.points ?? 0;
            return `<tr data-slug="${esc(c.slug)}">
              <td>${esc(c.name)} <span class="muted">${esc(c.slug)}</span></td>
              <td><span class="cat-dot" style="background:${esc(c.case?.category_color || "#4f8cff")}"></span>${esc(c.category)}</td>
              <td class="mono">${pts}</td>
              <td><span class="star" style="color:${gradeColor(g)}">${"★".repeat(g)}${"☆".repeat(5 - g)}</span></td>
              <td class="mono">${base[g] ?? pts}</td>
              <td>
                <select class="grade-select" data-slug="${esc(c.slug)}" aria-label="调整 ${esc(c.name)} 难度">
                  ${[1, 2, 3, 4, 5].map((gg) =>
                    `<option value="${gg}" ${gg === g ? "selected" : ""}>★${gg} ${gradeLabel(gg).split(" ").slice(1).join(" ")}</option>`
                  ).join("")}
                </select>
              </td></tr>`;
          }).join("")}
        </table>` : `<p class="muted">还没有题目，请先到「注册题目」子页签添加。</p>`}
    </div>`;
  $$("#opsBody .grade-select").forEach((sel) => sel.onchange = async (e) => {
    const slug = e.target.dataset.slug;
    const grade = parseInt(e.target.value, 10);
    const r = await doAction("case.set_grade", { slug, grade }, { noReload: true });
    if (r.ok) { await loadCompetition(); renderOps(); }
  });
}

/* ---- 子页签 5：运维操作 ---- */
export function opsRun(plat) {
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
          <div id="docsPathWrap" style="margin-top:10px;padding-top:10px;border-top:1px dashed var(--border, #2a3140)">
            <h4 style="margin:0 0 6px">本地文档路径</h4>
            <p class="muted" style="margin:0 0 6px;font-size:12px">指向比赛资料目录（本机任意路径，只读浏览），保存后「文档 / WP」页列出该目录文件。</p>
            <div class="row" style="margin:0">
              <input id="docsPathInput" class="mono" style="flex:1;min-width:240px"
                     placeholder="D:/ctf-docs/2608isg" value="${esc(S.comp?.docs_path || "")}">
              <button id="docsPathSave" class="small primary">保存</button>
            </div>
            <div id="docsPathMsg" class="muted" style="margin-top:4px;font-size:12px"></div>
          </div>
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
