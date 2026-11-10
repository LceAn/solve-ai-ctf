/* ---------------- ③c 系统概况 ---------------- */
import { $, esc } from "../ui.js";
import { api, post } from "../api.js";

let HEALTH_RETRIES = 0; // R151：stale 轮询上限（20 次 × 15s ≈ 5 分钟冷启动窗口）

export async function renderHealth() {
  const el = $("#healthWrap");
  if (!HEALTH_RETRIES) el.innerHTML = "<p class='muted'>检测中…</p>";
  let d;
  try { d = await api("/api/health/detail"); }
  catch (e) { el.innerHTML = `<p style="color:var(--red)">检测失败：${esc(e.message)}</p>`; return; }
  if (d.stale || !d.server) {
    // 后台单飞探测中（R86）：Docker 首次冷启动可达 1–3 分钟，友好等待+自动重试
    if (++HEALTH_RETRIES <= 20) {
      el.innerHTML = `<p class="muted">后台探测中（首次 Docker 冷启动可达 1–3 分钟，已等待 ${HEALTH_RETRIES * 15}s）…</p>`;
      setTimeout(() => renderHealth(), 15000);
    } else {
      el.innerHTML = `<p class="muted">探测耗时较长——Docker/WSL 可能未就绪。稍后刷新本页重试。</p>`;
    }
    return;
  }
  HEALTH_RETRIES = 0;
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
      ${card("Docker", d.docker?.ok, d.docker
        ? (d.docker.ok ? "引擎可达 · " + d.docker.detail : d.docker.detail)
        : "探测未完成")}
      ${'<div class="health-card" id="gwUsageCard"><div class="h-top">模型网关用量</div>' +
          '<div class="h-detail">读取中…</div></div>'}
      ${d.image_states ? card("题型镜像", Object.values(d.image_states).every((i) => i.ok),
        Object.entries(d.image_states).map(([k, v]) =>
          `${v.ok ? "✓" : "✗"} ${k}`).join(" · ")) : ""}
      ${card("求解命令模板", d.agent_cmd.ok, d.agent_cmd.detail)}
      ${card("数据统计", true,
        `${s.competitions} 场比赛（${s.configured} 已初始化）· ${s.challenges} 题 · ` +
        `任务 ${s.tasks_running} 运行 / ${s.tasks_total} 累计`)}
    </div>`;
  api("/api/gateway/usage").then((u) => {
    const el = document.getElementById("gwUsageCard");
    if (el) el.innerHTML = `<div class="h-top">模型网关用量</div>
      <div class="h-detail">活跃令牌 ${u.active_tokens ?? 0} · 请求 ${u.total_requests ?? 0} ·
      流量 ${(((u.total_bytes || 0)) / 1024).toFixed(1)} KB</div>`;
  }).catch(() => {});
  $("#selfTestBtn").onclick = async () => {
    const out = $("#selfTestOut");
    out.textContent = "启动中…";
    const r = await post("selftest.run", {});
    if (!r.started) { out.textContent = r.error || "启动失败"; return; }
    // R161：异步启动 + 轮询（此前同步等待，前端转圈两分钟）
    const poll = async () => {
      let s;
      try { s = await api("/api/selftest"); }
      catch (e) { out.textContent = "状态查询失败：" + e.message; return; }
      if (s.running) {
        out.textContent = `运行中（${s.elapsed}s，约需 60–90s）…`;
        setTimeout(poll, 1000);
        return;
      }
      const full = (s.output || "").trim();
      const ok = s.exit === 0;
      // R61-H2：输出全文折叠展示（成功默认收起，失败默认展开）
      out.innerHTML = ok
        ? `<details style="margin-top:6px"><summary style="cursor:pointer;color:var(--green)">✓ 通过（点击展开全文）</summary>
            <pre class="out" style="max-height:220px;overflow:auto;margin-top:6px">${esc(full)}</pre></details>`
        : `<details open style="margin-top:6px"><summary style="cursor:pointer;color:var(--red)">✗ 失败（exit ${s.exit}，展开查看）</summary>
            <pre class="out" style="max-height:220px;overflow:auto;margin-top:6px">${esc(full.slice(-2000))}</pre></details>`;
    };
    poll();
  };
}
