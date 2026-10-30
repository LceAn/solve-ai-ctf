/* ---------------- ②b AI 看板（多 Agent 泳道时间线，源自老 warroom v4） ---------------- */
import { S } from "../state.js";
import { TaskUI } from "./tasks.js";
import { setTab } from "../app.js";
import { $, $$, esc, fmtTime, toast, openModal, closeModal } from "../ui.js";
import { api } from "../api.js";

export const AGENT_PALETTE = ["#6b93d6", "#63b08c", "#b08ac0", "#c09a6b", "#7ba8b8", "#a085b8"];
export // R54 原则05：图表色收敛到 3 系（蓝=过程 / 绿=成果 / 琥珀=里程碑），其余灰阶
const EV_COLORS = { hypothesis_added: "#5b8def", evidence_added: "#8189e0",
  status_changed: "#5d6a84", attempt_logged: "#4e7cc0", candidate_found: "#45c48f",
  case_initialized: "#8a94a8" };

export function agentColor(name) {
  let h = 0;
  for (const ch of String(name || "")) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return AGENT_PALETTE[h % AGENT_PALETTE.length];
}

let b2Timer = null;
let b2BusBound = false;

// R62-A1：SSE 事件触发即时刷新（新题/状态变化/尝试/候选发现）
if (!b2BusBound && typeof window !== "undefined") {
  b2BusBound = true;
  window.addEventListener("wb-event", (ev) => {
    const kind = ev.detail && ev.detail.kind;
    if (["challenges_new", "status_changed", "attempt_logged", "candidate_found",
         "case_initialized"].includes(kind)
        && localStorage.getItem("wb.tab") === "board2") {
      renderBoard2();
    }
  });
}
let B2_FILTER = localStorage.getItem("wb.b2filter") || "all";
let AGENT_FILTER = "";

export async function renderBoard2() {
  const wrap = $("#boardWrap"), legend = $("#boardLegend");
  if (!S.comp) { wrap.innerHTML = "<p class='muted'>请先选择比赛。</p>"; return; }
  // R52：过滤 chips + 自动刷新开关（空看板时也要能用——绑定放 fetch 之前）
  $("#boardRefresh").onclick = renderBoard2;
  $("#boardHours").onchange = renderBoard2;
  const tools = $("#boardLegend");
  if (tools && !tools.dataset.wired) {
    tools.dataset.wired = "1";
    tools.insertAdjacentHTML("afterend", ["all", "running", "failed"].map((f) =>
      `<button class="small" data-b2f="${f}" style="margin-right:4px">${{ all: "全部", running: "运行中", failed: "失败/丢失" }[f]}</button>`).join("")
      + `<label class="muted" style="margin-left:8px"><input type="checkbox" id="b2auto"
           ${localStorage.getItem("wb.b2auto") === "1" ? "checked" : ""}> 自动刷新(30s)</label>`
      + `<button class="small" id="b2snapshot" style="margin-left:8px" title="复制当前协作态势为 Markdown（发给其他 AI / 群）">📋 协作快照</button>`);
    document.querySelectorAll("[data-b2f]").forEach((b) => b.onclick = () => {
      B2_FILTER = b.dataset.b2f;
      localStorage.setItem("wb.b2filter", B2_FILTER);
      renderBoard2();
    });
    document.getElementById("b2auto").onchange = (e) => {
      localStorage.setItem("wb.b2auto", e.target.checked ? "1" : "0");
      renderBoard2();
    };
    const snap = tools.querySelector("#b2snapshot");
    if (snap) snap.onclick = () => {
      const d2 = window.__b2data;
      if (!d2) { toast("看板数据未就绪", true); return; }
      const lines = [`# ${S.comp?.name || S.dir} · AI 协作态势快照`, "",
        `> ${new Date().toLocaleString("zh-CN")} · 时间窗 ${d2.window_hours}h`, ""];
      lines.push("## Agents");
      for (const a of (d2.agents || [])) {
        lines.push(`- **${a.agent}**：⚡${a.running} 运行 · ✓${a.done} 完成 · ✗${a.failed} 失败` +
          (a.slugs && a.slugs.length ? ` · 题：${a.slugs.join(", ")}` : ""));
      }
      lines.push("", "## 活动泳道");
      for (const l of (d2.lanes || [])) {
        if (l.kind === "task") {
          lines.push(`- [task] ${l.id} ${l.agent || ""} · ${l.slug || "?"} · ${l.status}` +
            (l.sandbox ? " · 沙箱" : ""));
        } else {
          lines.push(`- [题目] ${l.label}（${l.category || "?"}）· ${l.status} · ${(l.events || []).length} 事件`);
        }
      }
      lines.push("", "## 协作提示", "- GET /api/board 可获取本快照的结构化数据",
        "- POST /api/task/start 派发任务；GET /api/prompt 取题面", "- 候选 flag 用 case.candidate 登记，提交走 submit.dryrun → 人工放行");
      navigator.clipboard.writeText(lines.join("\n")).then(
        () => toast("协作快照已复制到剪贴板 ✓"),
        () => toast("复制失败（浏览器权限）", true));
      // R84：快照采样归档到事件流（协作态势可回溯）
      fetch("/api/action", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "competition.event", params: {
          dir: S.dir, kind: "collab_snapshot",
          detail: (d2.agents || []).map((a) => a.agent + " ✓" + a.done + " ✗" + a.failed
            + (a.running ? " ⚡" + a.running : "")).join("；").slice(0, 300) } })
      }).catch(() => {});
    };
  }
  if (b2Timer) { clearInterval(b2Timer); b2Timer = null; }
  if (localStorage.getItem("wb.b2auto") === "1") {
    b2Timer = setInterval(() => {
      if (localStorage.getItem("wb.tab") === "board2") renderBoard2();
      else { clearInterval(b2Timer); b2Timer = null; }
    }, 30000);
  }
  const hours = $("#boardHours")?.value || 24;
  wrap.innerHTML = "<p class='muted'>加载看板数据…</p>";
  let d;
  try {
    d = await api(`/api/board?dir=${encodeURIComponent(S.dir)}&hours=${hours}`);
    window.__b2data = d;  // R74：供协作快照使用
  } catch (e) { wrap.innerHTML = `<p style="color:var(--red)">${esc(e.message)}</p>`; return; }
  legend.innerHTML = "图例：" +
    Object.entries(EV_COLORS).map(([k, c]) => `<span class="legend-dot" style="background:${c}"></span>${k}`).join("") +
    `<span class="legend-dot" style="background:var(--green)"></span>任务(running)
     <span class="legend-dot" style="background:var(--gray)"></span>任务(ended)`;

  // R106：Agent 网关面板（名册/认领/注册/吊销）
  const gwHost = document.getElementById("gwPanel");
  if (gwHost) {
    gwHost.innerHTML = `<p class="muted">加载网关名册…</p>`;
    api("/api/agent-gw/directory").then((d) => {
      const ags = d.agents || [];
      const claims = d.claims || [];
      // R131：活跃排前，已吊销默认折叠；last_seen 相对时间
      const relTime = (mins) => {
        if (typeof mins !== "number" || mins < 0) return "";
        if (mins === 0) return "刚刚";
        if (mins < 60) return mins + " 分前";
        const h = Math.floor(mins / 60);
        if (h < 24) return h + " 小时前";
        return Math.floor(h / 24) + " 天前";
      };
      const aliveAgents = ags.filter((a) => !a.revoked);
      const deadAgents = ags.filter((a) => a.revoked);
      const rowOf = (a) => {
        const alive = !a.revoked;
        const myClaims = claims.filter((cl) => cl.agent_id === a.id);
        const lastSeen = a.last_seen || "—";
        return `<tr style="${alive ? "" : "opacity:.4"}">
          <td>${esc(a.name)}<div class="muted mono" style="font-size:10px">${esc(a.id)}</div></td>
          <td>${a.capabilities?.length ? a.capabilities.map((cp) =>
              `<span class="badge" style="--b-c:#5d6c86">${esc(cp)}</span>`).join(" ") : "—"}</td>
          <td>${alive
            ? (myClaims.length
                ? myClaims.map((cl) => `<span class="badge" style="--b-c:#d9a93f">${esc(cl.slug)}</span>`).join(" ")
                : `<span class="badge" style="--b-c:#5d6c86">无认领</span>`)
            : `<span class="badge" style="--b-c:#e57373">已吊销</span>`}</td>
          <td class="muted" style="font-size:11px">${esc(lastSeen.slice(5, 16))}
            ${alive && typeof a.last_seen_minutes === "number" && a.last_seen_minutes >= 0
              ? `<div style="font-size:10px;${a.last_seen_minutes > 30 ? "color:var(--red)" : ""}">${relTime(a.last_seen_minutes)}</div>` : ""}</td>
          <td style="white-space:nowrap">
            ${alive ? `<button class="small danger" data-gwrevoke="${esc(a.id)}" data-gwname="${esc(a.name)}">吊销</button>` : "—"}
          </td>
        </tr>`;
      };
      const rows = aliveAgents.map(rowOf).join("")
        + (deadAgents.length
          ? `<tr><td colspan="5" class="muted" style="font-size:11px;padding:4px 12px">
              <details><summary style="cursor:pointer">已吊销（${deadAgents.length}）</summary>
              </td></tr>${deadAgents.map(rowOf).join("")}`
          : "");
      gwHost.innerHTML = `<div class="panel">
        <div class="row" style="justify-content:space-between">
          <h3 style="margin:0">🌐 Agent 网关 <span class="muted">${aliveAgents.length} 活跃 · ${claims.length} 认领${deadAgents.length ? ` · ${deadAgents.length} 已吊销` : ""}</span></h3>
          <button class="small primary" id="gwRegister">＋ 注册 Agent</button>
        </div>
        <p class="muted" style="margin:4px 0 8px;font-size:11.5px">
          其他 AI 用 <code>POST /api/agent-gw/register</code> 注册拿独立密钥（X-Agent-Key 头），
          认领题目防重复劳动，可随时吊销。密钥只存哈希。</p>
        ${ags.length ? `<table style="width:100%">
          <tr><th>Agent</th><th>能力</th><th>认领</th><th>最近心跳</th><th>操作</th></tr>${rows}</table>`
          : `<p class="muted" style="margin:0">尚无注册的 agent。</p>`}
      </div>`;
      const reg = document.getElementById("gwRegister");
      if (reg) reg.onclick = () => {
        openModal(`
          <h3>＋ 注册协作 Agent</h3>
          <p class="muted" style="margin:4px 0 8px">发放独立密钥（仅显示一次）；吊销立即失效，不影响其他 agent。</p>
          <div class="row" style="margin:0 0 8px"><label style="width:60px" class="muted">名称</label>
            <input id="gwName" style="flex:1" placeholder="例：claude-main"></div>
          <div class="row" style="margin:0 0 10px"><label style="width:60px" class="muted">能力</label>
            <input id="gwCaps" style="flex:1" placeholder="逗号分隔：web, pwn"></div>
          <div class="row" style="justify-content:flex-end">
            <button id="gwCancel">取消</button>
            <button id="gwCreate" class="primary">注册</button>
          </div>`);
        document.getElementById("gwCancel").onclick = closeModal;
        document.getElementById("gwCreate").onclick = async () => {
          const r = await fetch("/api/agent-gw/register", { method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: document.getElementById("gwName").value,
              capabilities: document.getElementById("gwCaps").value.split(",").map((x) => x.trim()).filter(Boolean) }) })
            .then((x) => x.json()).catch((e) => ({ error: String(e) }));
          if (r.agent_key) {
            closeModal();
            openModal(`<h3>🔑 密钥已发放（仅显示一次）</h3>
              <pre class="out" style="user-select:all;word-break:break-all">${esc(r.agent_key)}</pre>
              <p class="muted" style="margin:8px 0">AI 侧用法：<code>Authorization: Bearer ${esc(r.agent_key)}</code>
              或 <code>X-Agent-Key: ${esc(r.agent_key)}</code> 头调用全部 /api 端点。</p>
              <div class="row" style="justify-content:flex-end"><button id="gwKeyOk" class="primary">我已保存</button></div>`);
            document.getElementById("gwKeyOk").onclick = () => { closeModal(); renderBoard2(); };
          } else toast(r.error || "注册失败", true);
        };
      };
      gwHost.querySelectorAll("[data-gwrevoke]").forEach((b) => b.onclick = async () => {
        if (!confirm(`确认吊销 ${b.dataset.gwname}？其密钥立即失效，认领自动释放。`)) return;
        const r = await fetch("/api/agent-gw/revoke", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent_id: b.dataset.gwrevoke }) }).then((x) => x.json())
          .catch((e) => ({ error: String(e) }));
        if (r.ok) { toast(`${b.dataset.gwname} 已吊销 ✓`); renderBoard2(); }
        else toast(r.error || "吊销失败", true);
      });
    }).catch(() => { gwHost.innerHTML = ""; });
  }

  // R81：无人认领提醒——活跃状态但无 agent 在跑的题（点题跳工作区）
  const uncl = document.getElementById("unclaimedBar");
  if (uncl) {
    const u = d.unclaimed || [];
    uncl.innerHTML = u.length
      ? `<div class="panel" style="margin:0 0 10px;padding:10px 14px;border-color:rgba(217,169,63,.35);background:rgba(217,169,63,.05)">
          <b style="color:var(--yellow)">⚑ ${u.length} 题活跃但无人认领</b>
          ${u.slice(0, 5).map((x) => `<button class="small" data-unclaim="${esc(x.slug)}"
            style="margin:2px 6px 2px 0" title="${esc(x.status)} · 假设 ${x.hypotheses}"> ${esc(x.name)}${x.points ? ` (${x.points})` : ""}</button>`).join("")}
          ${u.length > 5 ? `<span class="muted">…等 ${u.length} 题</span>` : ""}
        </div>`
      : "";
    uncl.querySelectorAll("[data-unclaim]").forEach((b) => b.onclick = () => {
      localStorage.setItem("wb.slug", b.dataset.unclaim);
      localStorage.setItem("wb.tab", "detail");
      setTab("detail");
    });
  }
  // R72：Agent 状态卡——人一眼看清当前协作态势
  const agents = d.agents || [];
  const agentRow = document.getElementById("agentSummary");
  if (agentRow) {
    agentRow.innerHTML = agents.length ? agents.map((a) => {
      const c = agentColor(a.agent);
      const on = AGENT_FILTER === a.agent;
      const state = a.running ? `<span class="badge" style="--b-c:#d9a93f">⚡ ${a.running} 运行中</span>`
        : `<span class="badge" style="--b-c:#5d6c86">空闲</span>`;
      return `<div class="stat" data-agent-card="${esc(a.agent)}" role="button" tabindex="0"
        style="--stat-c:${c};min-width:150px;flex:1;cursor:pointer;${on ? "border-color:" + c + ";box-shadow:0 0 0 1px " + c : ""}"
        title="${on ? "点击取消过滤" : "点击只看该 agent 的任务泳道"}">
        <span class="ic" style="color:${c}">🤖</span>
        <b style="font-size:15px">${esc(a.agent)}</b>
        <span>${state} · ✓${a.done} ✗${a.failed}${a.slugs.length ? ` · ${a.slugs.length} 题` : ""}${a.gw_claims ? ` · 🔒${a.gw_claims}` : ""}</span>
        <span class="muted" style="font-size:10.5px" title="${esc(a.slugs.join(", "))}">${esc((a.slugs.slice(0, 3).join(", ") + (a.slugs.length > 3 ? "…" : "")) || "—")}</span>
      </div>`;
    }).join("") : `<p class="muted" style="margin:0">时间窗内没有 agent 活动。派发任务后这里会出现协作态势卡。</p>`;
    // R76：点卡过滤该 agent 的任务泳道（再点取消）
    agentRow.querySelectorAll("[data-agent-card]").forEach((card) => {
      card.onclick = () => {
        AGENT_FILTER = AGENT_FILTER === card.dataset.agentCard ? "" : card.dataset.agentCard;
        renderBoard2();
      };
    });
  }

  let lanes = d.lanes || [];
  if (B2_FILTER !== "all") {
    lanes = lanes.filter((l) => l.kind === "challenge"
      || (B2_FILTER === "running" ? l.status === "running"
                                  : ["failed", "lost"].includes(l.status)));
  }
  // R76：agent 过滤——保留题目泳道 + 该 agent 的任务泳道
  if (AGENT_FILTER) {
    lanes = lanes.filter((l) => l.kind === "challenge" || l.agent === AGENT_FILTER);
  }
  if (!lanes.length) {
    wrap.innerHTML = `<div class="panel"><p class='muted'>时间窗内（近 ${esc(hours)} 小时）没有题目事件或任务。
      派发任务或在题目页登记假设/尝试后，这里会出现多 Agent 泳道。</p></div>`;
    return;
  }
  // R72：泳道排序——题目泳道在前，其关联任务泳道紧随（按 slug 聚焦协作上下文）
  const chLanes = lanes.filter((l) => l.kind === "challenge");
  const tLanes = lanes.filter((l) => l.kind === "task");
  const slugSet = new Set(chLanes.map((l) => l.id));
  const orphan = tLanes.filter((l) => !slugSet.has(l.slug));
  const ordered = [];
  for (const cl of chLanes) {
    ordered.push(cl);
    ordered.push(...tLanes.filter((tl) => tl.slug === cl.id));
  }
  ordered.push(...orphan);
  lanes = ordered;
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
    parts.push(`<line x1="${gx}" y1="${TOP - 8}" x2="${gx}" y2="${H - 8}" stroke="#1c2538" stroke-dasharray="2 5"/>`);
    parts.push(`<text x="${gx}" y="${TOP - 14}" fill="#5d6a84" font-size="10" text-anchor="middle">${esc(label)}</text>`);
  }
  lanes.forEach((lane, li) => {
    const y = TOP + li * ROW;
    parts.push(`<line x1="0" y1="${y + ROW - 8}" x2="${W}" y2="${y + ROW - 8}" stroke="#141c30"/>`);
    // R73：泳道副标——题目带类别与事件数，任务带沙箱标记
    const sub = lane.kind === "task"
      ? `task ${esc(lane.id)} · ${esc(lane.status)}${lane.sandbox ? " · 📦沙箱" : ""}`
      : `${esc(lane.category || "")} · ${(lane.events || []).length} 事件 · ${esc(lane.status || "")}`;
    parts.push(`<g data-lane-slug="${esc(lane.kind === "challenge" ? lane.id : (lane.slug || lane.id))}"
      ${lane.kind === "challenge" ? `data-goto-chall="${esc(lane.id)}" style="cursor:pointer"` : ""}>`);
    parts.push(`<text x="12" y="${y + 20}" fill="#e6edf3" font-size="12.5" font-weight="600">${esc(lane.label)}</text>`);
    parts.push(`<text x="12" y="${y + 34}" fill="#8b949e" font-size="10.5">${sub}</text>`);
    if (lane.kind === "task") {
      const color = agentColor(lane.agent);
      const x1 = Math.max(x(lane.start), LBL), x2 = Math.min(x(lane.end || d.now), W - 20);
      const running = lane.status === "running";
      // R52-A2：泳道任务可点击跳运行任务页并选中
      parts.push(`<g data-goto-task="${esc(lane.id)}" data-slug="${esc(lane.slug || "")}" style="cursor:pointer">
        <rect x="${x1}" y="${y + 10}" width="${Math.max(x2 - x1, 6)}" height="18" rx="9"
        fill="${running ? color : "#6e7681"}" opacity="${running ? 0.85 : 0.4}"/>
        <circle cx="${x1}" cy="${y + 19}" r="4" fill="${color}"/>
        <text x="${x1 + 10}" y="${y + 23}" fill="#0d1117" font-size="10" font-weight="700">${esc(lane.agent || "")}</text>
        ${running && lane.last_line ? `<text x="${Math.min(x1 + 14, W - 260)}" y="${y + 8}" fill="#8a94a8" font-size="9" font-family="monospace">${esc(lane.last_line)}</text>` : ""}
        </g>`);
    } else {
      for (const ev of lane.events || []) {
        const cx = x(ev.ts), cy = y + 19;
        const detail = typeof ev.detail === "string" ? ev.detail : JSON.stringify(ev.detail || {});
        parts.push(`<circle cx="${cx}" cy="${cy}" r="4.5" fill="${EV_COLORS[ev.kind] || "#7a869c"}" opacity="0.8">
          <title>${esc(ev.kind)} ${esc(fmtTime(new Date(ev.ts * 1000).toISOString()))}
${esc(detail.slice(0, 140))}</title></circle>`);
      }
    }
    parts.push("</g>");
  });
  wrap.innerHTML = `<div class="swimlane-hint muted">← 左右滑动查看完整时间线 →</div>
    <div class="swimlane" role="region" aria-label="AI 看板时间线，可横向滚动">
      <svg viewBox="0 0 ${W} ${H}" width="100%" style="min-width:900px">
        ${parts.join("")}</svg>
    </div>`;
  $("#boardHours").onchange = renderBoard2;
  $$("#boardWrap [data-goto-task]").forEach((g) => g.onclick = () => {
    TaskUI.selected = g.dataset.gotoTask;
    localStorage.setItem("wb.tab", "tasks");
    setTab("tasks");
  });
  // R80：题目泳道点击 → 跳题目工作区并选中该题
  $$("#boardWrap [data-goto-chall]").forEach((g) => g.onclick = () => {
    localStorage.setItem("wb.slug", g.dataset.gotoChall);
    localStorage.setItem("wb.tab", "detail");
    setTab("detail");
  });
  // R76b：任务条悬停 → 高亮同题泳道、压暗其他（协作上下文一眼可见）
  $$("#boardWrap [data-goto-task]").forEach((g) => {
    const slug = g.dataset.slug;
    if (!slug) return;
    g.addEventListener("mouseenter", () => {
      $$("#boardWrap [data-lane-slug]").forEach((el) => {
        el.style.opacity = el.dataset.laneSlug === slug ? "1" : "0.2";
      });
    });
    g.addEventListener("mouseleave", () => {
      $$("#boardWrap [data-lane-slug]").forEach((el) => { el.style.opacity = ""; });
    });
  });
}
