/* ---------------- ② 流程看板（给人看：现在处于哪个环节、谁在做、卡在哪） ---------------- */
import { S } from "../state.js";
import { $, esc, toast } from "../ui.js";
import { api } from "../api.js";
import { loadCase, setTab } from "../app.js";

/* 阶段与 case.json 的 status 对齐；顺序即解题推进方向 */
const STAGES = [
  { key: "todo", label: "待开始", hint: "尚未建 case", color: "#94a3b8",
    match: (s) => !s || s === "new" },
  { key: "recon", label: "侦察 / 假设", hint: "收集信息、验证假设", color: "#5b8def",
    match: (s) => s === "triaged" || s === "in_progress" },
  { key: "blocked", label: "受阻", hint: "被前置卡住", color: "#f87171",
    match: (s) => s === "blocked" },
  { key: "candidate", label: "候选待验", hint: "已有候选 flag", color: "#b08ac0",
    match: (s) => s === "candidate_found" },
  { key: "solved", label: "已解待交", hint: "本地确认，未提交", color: "#34d399",
    match: (s) => s === "solved" },
  { key: "done", label: "已提交", hint: "提交或关闭", color: "#45c48f",
    match: (s) => s === "submitted" || s === "closed" },
];

const STATUS_LABEL = {
  new: "新建", triaged: "已分诊", in_progress: "进行中", blocked: "受阻",
  candidate_found: "候选已找到", solved: "已解", submitted: "已提交",
  closed: "已关闭", abandoned: "已放弃", invalid: "无效",
};

const EVENT_LABEL = {
  case_initialized: "初始化", status_changed: "状态变更", hypothesis_added: "新假设",
  attempt_logged: "新尝试", evidence_added: "新证据", candidate_found: "发现候选",
  candidate_status_changed: "候选更新", flag_scan: "扫描 flag", docs_written: "写文档",
};

function relTime(iso) {
  if (!iso) return "—";
  const raw = String(iso);
  const t = Date.parse(raw.includes("T") ? raw : raw.replace(" ", "T"));
  if (!Number.isFinite(t)) return "—";
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.round(hours / 24)} 天前`;
}

function staleHours(iso) {
  if (!iso) return 0;
  const raw = String(iso);
  const t = Date.parse(raw.includes("T") ? raw : raw.replace(" ", "T"));
  return Number.isFinite(t) ? (Date.now() - t) / 3600000 : 0;
}

function cardHtml(ch, status, owner, isRunning) {
  const c = ch.case || {};
  const finished = ["solved", "submitted", "closed"].includes(status);
  const stale = !finished && staleHours(c.updated_at) >= 24;
  const nums = [
    c.hypotheses ? `假设 ${c.hypotheses}` : "",
    c.attempts ? `尝试 ${c.attempts}` : "",
    (c.candidates || []).length ? `候选 ${c.candidates.length}` : "",
  ].filter(Boolean).join(" · ") || "尚无过程记录";
  const last = c.last_event
    ? (EVENT_LABEL[c.last_event.kind] || c.last_event.kind)
    : (c.exists ? "" : "未初始化 case");
  const full = `${ch.name || ch.slug}｜${ch.category || "misc"}｜${nums}｜${relTime(c.updated_at)}`
    + (last ? " · " + last : "") + (owner ? `｜负责：${owner}` : "");
  return `<button class="pl-card${stale ? " stale" : ""}" data-slug="${esc(ch.slug || "")}" title="${esc(full)}">
    <span class="pl-t"><b>${esc(ch.name || ch.slug || "")}</b><span>${ch.points == null ? "—" : ch.points}</span></span>
    <span class="pl-sub">${esc(ch.category || "misc")}${c.blocked_on ? ` · ${esc(c.blocked_on)}` : ""}</span>
    <span class="pl-n">${nums}</span>
    <span class="pl-f">
      ${owner ? `<em class="pl-owner">@${esc(owner)}</em>` : ""}
      ${isRunning ? `<em class="pl-run">运行中</em>` : ""}
      ${relTime(c.updated_at)}${last ? ` · ${last}` : ""}${stale ? " · 停滞" : ""}
    </span>
  </button>`;
}

export function renderPipeline() {
  const host = $("#pipelineWrap");
  if (!host) return;
  if (!S.comp) {
    host.innerHTML = `<div class="empty-state"><b>没有可用的比赛</b>
      <p>先在「比赛管理」初始化比赛或抓取题目。</p></div>`;
    return;
  }
  const challenges = S.comp.challenges || [];

  const paint = (claimBySlug = {}, running = new Set()) => {
    const buckets = new Map(STAGES.map((s) => [s.key, []]));
    const parked = [];
    for (const ch of challenges) {
      const status = ch.case?.exists ? (ch.case.status || "new") : "";
      const stage = STAGES.find((s) => s.match(status));
      if (stage) buckets.get(stage.key).push({ ch, status });
      else parked.push({ ch, status });
    }

    const done = (buckets.get("done") || []).length + (buckets.get("solved") || []).length;
    const blocked = (buckets.get("blocked") || []).length;
    const candidate = (buckets.get("candidate") || []).length;
    const pct = challenges.length ? Math.round((done / challenges.length) * 100) : 0;
    const stalled = challenges
      .map((ch) => ({ ch, status: ch.case?.status, h: staleHours(ch.case?.updated_at) }))
      .filter((x) => x.h >= 24 && !["solved", "submitted", "closed"].includes(x.status))
      .sort((a, b) => b.h - a.h)[0];

    const summary = `<div class="pl-summary">
      <div class="pl-sum-item"><b>${challenges.length}</b><span>题目</span></div>
      <div class="pl-sum-item"><b>${done}</b><span>已解 / 已交</span></div>
      <div class="pl-sum-item${blocked ? " warn" : ""}"><b>${blocked}</b><span>受阻</span></div>
      <div class="pl-sum-item${candidate ? " accent" : ""}"><b>${candidate}</b><span>候选待验</span></div>
      <div class="pl-sum-track" title="完成度 ${pct}%"><i style="width:${pct}%"></i></div>
      <span class="pl-sum-pct">${pct}%</span>
    </div>${stalled ? `<p class="pl-stall">停滞最久：<b>${esc(stalled.ch.name || stalled.ch.slug)}</b>
      （${Math.floor(stalled.h / 24)} 天未更新，状态「${STATUS_LABEL[stalled.status] || stalled.status}」）</p>` : ""}`;

    const flow = STAGES.map((s) => {
      const n = buckets.get(s.key).length;
      return `<button class="pl-node${n ? "" : " zero"}" data-jump="${s.key}" title="${esc(s.hint)}">
        <i class="pl-dot" style="--c:${s.color}"></i><b>${n}</b><span>${s.label}</span>
      </button>`;
    }).join('<i class="pl-arrow">→</i>');

    const cols = STAGES.map((s) => {
      const items = buckets.get(s.key);
      return `<section class="pl-col" data-stage="${s.key}">
        <header><i class="pl-dot" style="--c:${s.color}"></i><b>${s.label}</b><em>${items.length}</em></header>
        <div class="pl-cards">${items.length
          ? items.map(({ ch, status }) => cardHtml(
              ch, status, claimBySlug[ch.slug], running.has(ch.slug))).join("")
          : `<p class="pl-empty">暂无</p>`}</div>
      </section>`;
    }).join("");

    const parkedLine = parked.length
      ? `<p class="pl-parked">另有 ${parked.length} 题处于已放弃 / 无效：${
          parked.map(({ ch, status }) => `${esc(ch.name || ch.slug)}（${STATUS_LABEL[status] || status}）`).join("、")}</p>`
      : "";

    host.innerHTML = `<div class="pipeline">
      ${summary}
      <div class="pl-flow">${flow}</div>
      <div class="pl-board" id="plBoard">${cols}</div>
      ${parkedLine}
    </div>`;

    const board = $("#plBoard");
    host.querySelectorAll("[data-jump]").forEach((btn) => {
      btn.onclick = () => {
        const col = board?.querySelector(`[data-stage="${btn.dataset.jump}"]`);
        if (col && board) board.scrollTo({ left: col.offsetLeft - 12, behavior: "smooth" });
      };
    });
    host.querySelectorAll("[data-slug]").forEach((card) => {
      card.onclick = async () => {
        const slug = card.dataset.slug;
        if (!slug) return;
        try {
          await loadCase(slug);
          setTab("detail");
        } catch (e) {
          toast("打开失败：" + e.message, true);
        }
      };
    });
  };

  paint();   // 先按已知数据渲染，网关/任务异步补上
  Promise.all([
    api("/api/agent-gw/directory").catch(() => ({ claims: [] })),
    api("/api/tasks").catch(() => ({ tasks: [] })),
  ]).then(([dir, tasks]) => {
    const claimBySlug = {};
    for (const c of (dir.claims || [])) {
      if (c.slug) claimBySlug[c.slug] = c.agent_name || "agent";
    }
    const running = new Set((tasks.tasks || [])
      .filter((t) => t.status === "running" && t.slug).map((t) => t.slug));
    if (Object.keys(claimBySlug).length || running.size) paint(claimBySlug, running);
  }).catch(() => {});

  const refresh = $("#plRefresh");
  if (refresh) {
    refresh.onclick = async () => {
      refresh.disabled = true;
      const label = refresh.textContent;
      refresh.textContent = "刷新中…";
      try {
        const { loadCompetition } = await import("../app.js");
        await loadCompetition();
        renderPipeline();
        toast("已刷新");
      } catch (e) {
        toast("刷新失败：" + e.message, true);
      } finally {
        refresh.disabled = false;
        refresh.textContent = label;
      }
    };
  }
}

/* 看板停留期间，状态变化即时刷新（与 AI 看板同一套 SSE 事件） */
let plBusBound = false;
function bindPipelineBus() {
  if (plBusBound || typeof window === "undefined") return;
  plBusBound = true;
  window.addEventListener("wb-event", (ev) => {
    const kind = ev.detail && ev.detail.kind;
    if (!["status_changed", "candidate_found", "case_initialized",
          "attempt_logged", "hypothesis_added"].includes(kind)) return;
    if (localStorage.getItem("wb.tab") === "pipeline") renderPipeline();
  });
}
bindPipelineBus();
