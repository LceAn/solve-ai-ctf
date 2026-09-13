/* ---------------- ③c 系统概况 ---------------- */
import { $, esc } from "../ui.js";
import { api, post } from "../api.js";

export async function renderHealth() {
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
