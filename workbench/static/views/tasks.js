/* ---------------- ③b 运行任务 ---------------- */
import { S } from "../state.js";
import { $, $$, esc, toast } from "../ui.js";
import { api, authHeaders } from "../api.js";
import { agentColor } from "./board2.js";

export const TaskUI = { selected: null, timer: null };

export async function renderTasks() {
  if (!S.comp) return;
  const sel = $("#taskCase");
  if (!sel.dataset.bound) {
    sel.dataset.bound = "1";
    $("#taskStart").onclick = startTask;
    $("#taskDemo").onclick = () => startTask(true);
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
  const taskStart = $("#taskStart");
  taskStart.disabled = !data.agent_cmd;
  taskStart.title = data.agent_cmd ? "使用 server 配置的命令模板启动求解任务" : "启动 server 时加 --agent-cmd，或设置 WB_AGENT_CMD";
  taskStart.textContent = data.agent_cmd ? "启动" : "启动（需配置命令）";
  $("#taskAgentState").innerHTML = data.agent_cmd
    ? "✓ 已配置求解命令模板"
    : "⚠ 未配置真实命令模板：启动 server 时加 <code>--agent-cmd \"...\"</code>（占位符 {prompt_file} {case_dir}）；可先运行下方演示 Agent";
  const demoBtn = $("#taskDemo");
  if (demoBtn) {
    demoBtn.disabled = data.demo_agent === false || !chs.length;
    demoBtn.title = demoBtn.disabled ? "暂无已初始化的题目 case" : "运行内置演示 Agent：只读取提示词并输出阶段日志，不提交 flag";
  }
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
      <span class="badge" style="--b-c:${t.status === "running" ? "#fbbf24" : t.status === "done" ? "#34d399" : "#f87171"}">${esc(taskStatusLabel(t.status))}</span>
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

export const TASK_STATUS_LABELS = { running: "运行中", done: "已完成", failed: "失败", lost: "已丢失", submitted: "已提交" };
export const taskStatusLabel = (status) => TASK_STATUS_LABELS[String(status || "")] || String(status || "未知");

export function selectTask(id) { TaskUI.selected = id; renderTasks(); }

export async function startTask(demo = false) {
  const slug = $("#taskCase").value;
  if (!slug) return toast("请先选择题目", true);
  const demoBtn = $("#taskDemo");
  const startBtn = $("#taskStart");
  if (demo) { if (demoBtn) demoBtn.disabled = true; }
  else if (startBtn) startBtn.disabled = true;
  let r;
  try {
    const res = await fetch("/api/task/start", { method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ dir: S.dir, slug, agent: $("#taskAgent").value.trim(),
                             demo,
                             sandbox: $("#taskSandbox")?.checked || false,
                             gateway: $("#taskGateway")?.checked || false }) });
    r = await res.json();
  } catch (e) {
    r = { ok: false, error: `任务服务不可达：${e.message || e}` };
  }
  if (demoBtn) demoBtn.disabled = false;
  if (startBtn) startBtn.disabled = false;
  if (r.ok) {
    toast(`${demo ? "演示 Agent" : "任务"} ${r.task.id} 已启动 ✓${r.sandbox ? "（Docker 沙箱）" : ""}`);
    TaskUI.selected = r.task.id;
    renderTasks();
  } else {
    toast(r.error || "启动失败", true);
    // Re-read the server capability so a transient error cannot leave the
    // real-start button in the wrong enabled/disabled state.
    renderTasks();
  }
}

let taskPollBusy = false;
export async function pollTaskOutput() {
  if (taskPollBusy || !TaskUI.selected) return;
  taskPollBusy = true;
  try {
    const r = await api(`/api/task/tail?id=${encodeURIComponent(TaskUI.selected)}`);
    if (TaskUI.selected === r.task.id) {
      $("#taskMeta").innerHTML =
        `<span class="mono">${esc(r.task.id)}</span> · ${esc(r.task.slug)} · ` +
        `<span class="badge" style="--b-c:${r.task.status === "running" ? "#fbbf24" : r.task.status === "done" ? "#34d399" : "#f87171"}">${esc(taskStatusLabel(r.task.status))}</span>` +
        (r.task.exit !== undefined ? ` · exit=${esc(r.task.exit)}` : "") +
        (r.task.container ? ` · <span title="${esc(r.task.container)}">📦 沙箱</span>` : "") +
        `<br><span class="muted" style="font-size:11px">${esc(r.task.command)}</span>`;
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
