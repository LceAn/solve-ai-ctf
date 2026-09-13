/* ---------------- ②b AI 看板（多 Agent 泳道时间线，源自老 warroom v4） ---------------- */
import { S } from "../state.js";
import { $, esc, fmtTime } from "../ui.js";
import { api } from "../api.js";

export const AGENT_PALETTE = ["#58a6ff", "#3fb950", "#e0823d", "#bc8cff", "#f85149", "#d29922", "#4dd0e1", "#ec6bc5"];
export const EV_COLORS = { hypothesis_added: "#d29922", evidence_added: "#58a6ff", status_changed: "#e0823d",
  attempt_logged: "#bc8cff", candidate_found: "#3fb950", case_initialized: "#6e7681" };

export function agentColor(name) {
  let h = 0;
  for (const ch of String(name || "")) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return AGENT_PALETTE[h % AGENT_PALETTE.length];
}

let b2Timer = null;
let B2_FILTER = localStorage.getItem("wb.b2filter") || "all";

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
           ${localStorage.getItem("wb.b2auto") === "1" ? "checked" : ""}> 自动刷新(30s)</label>`);
    tools.querySelectorAll("[data-b2f]").forEach((b) => b.onclick = () => {
      B2_FILTER = b.dataset.b2f;
      localStorage.setItem("wb.b2filter", B2_FILTER);
      renderBoard2();
    });
    tools.querySelector("#b2auto").onchange = (e) => {
      localStorage.setItem("wb.b2auto", e.target.checked ? "1" : "0");
      renderBoard2();
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
  } catch (e) { wrap.innerHTML = `<p style="color:var(--red)">${esc(e.message)}</p>`; return; }
  legend.innerHTML = "图例：" +
    Object.entries(EV_COLORS).map(([k, c]) => `<span class="legend-dot" style="background:${c}"></span>${k}`).join("") +
    `<span class="legend-dot" style="background:var(--green)"></span>任务(running)
     <span class="legend-dot" style="background:var(--gray)"></span>任务(ended)`;

  let lanes = d.lanes || [];
  if (B2_FILTER !== "all") {
    lanes = lanes.filter((l) => l.kind === "challenge"
      || (B2_FILTER === "running" ? l.status === "running"
                                  : ["failed", "lost"].includes(l.status)));
  }
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
      // R52-A2：泳道任务可点击跳运行任务页并选中
      parts.push(`<g data-goto-task="${esc(lane.id)}" style="cursor:pointer">
        <rect x="${x1}" y="${y + 10}" width="${Math.max(x2 - x1, 6)}" height="18" rx="9"
        fill="${running ? color : "#6e7681"}" opacity="${running ? 0.9 : 0.55}"/>
        <circle cx="${x1}" cy="${y + 19}" r="4" fill="${color}"/>
        <text x="${x1 + 10}" y="${y + 23}" fill="#0d1117" font-size="10" font-weight="700">${esc(lane.agent || "")}</text></g>`);
    } else {
      for (const ev of lane.events || []) {
        const cx = x(ev.ts), cy = y + 19;
        parts.push(`<circle cx="${cx}" cy="${cy}" r="5.5" fill="${EV_COLORS[ev.kind] || "#8b949e"}" opacity="0.92">
          <title>${esc(ev.kind)} ${esc(fmtTime(new Date(ev.ts * 1000).toISOString()))}</title></circle>`);
      }
    }
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
}
