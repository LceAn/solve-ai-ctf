/* 📶 连接监控 */
import { $, esc } from "../ui.js";
import { api } from "../api.js";

export async function renderConnections() {
  const host = document.getElementById("connectionsBody");
  if (!host) return;
  host.innerHTML = "<p class='muted'>采集中…</p>";
  let d;
  try { d = await api("/api/connections"); }
  catch (e) { host.innerHTML = `<p style="color:var(--red)">${esc(e.message)}</p>`; return; }

  const devRow = (x) => `
    <tr>
      <td class="mono">${esc(x.ip)}</td>
      <td>${x.online
        ? '<span class="badge" style="--b-c:#34d399">🟢 在线</span>'
        : '<span class="badge" style="--b-c:#64748b">离线</span>'}</td>
      <td>${x.creds.map((c2) => `<span class="badge">${esc(c2)}</span>`).join(" ")}</td>
      <td>${x.hits}</td>
      <td class="muted">${esc(x.last_seen_ago)}</td>
      <td class="muted">${esc(x.ua)}</td>
      <td class="muted mono" style="font-size:11px">${esc(x.recent_paths.join(" · "))}</td>
    </tr>`;

  const agentRow = (a) => `
    <tr>
      <td><b>${esc(a.tag)}</b></td>
      <td>${esc(a.name)}${a.label ? ` <span class="muted">· ${esc(a.label)}</span>` : ""}</td>
      <td>${a.online
        ? `<span class="badge" style="--b-c:#34d399">在线</span> <span class="muted">${esc(a.last_seen_ago)}</span>`
        : `<span class="badge" style="--b-c:#64748b">离线</span> <span class="muted">${esc(a.last_seen_ago)}</span>`}</td>
      <td>${esc(a.status_display || "")}${a.current_slug ? ` · ${esc(a.current_slug)}` : ""}</td>
    </tr>`;

  host.innerHTML = `
    <div class="stats">
      <div class="stat" style="--stat-c:var(--green)"><b>${d.online_now}</b><span>在线设备</span></div>
      <div class="stat" style="--stat-c:var(--accent)"><b>${d.total_tracked}</b><span>累计设备</span></div>
      <div class="stat" style="--stat-c:var(--purple)"><b>${d.agents_online}</b><span>在线 AI</span></div>
      <div class="stat" style="--stat-c:var(--teal)"><b>${d.agents_total}</b><span>注册 AI</span></div>
    </div>
    <div class="panel">
      <h3>🖥️ 设备连接 <span class="muted">按 IP（120s 内有请求 = 在线；凭证类型自动识别）</span></h3>
      ${d.devices.length ? `<table><tr><th>IP</th><th>状态</th><th>凭证</th><th>请求数</th><th>最近</th><th>客户端</th><th>最近路径</th></tr>
        ${d.devices.map(devRow).join("")}</table>`
        : "<p class='muted'>暂无记录（服务启动后开始统计）。</p>"}
    </div>
    <div class="panel">
      <h3>🤖 AI 活跃 <span class="muted">按心跳（15 分钟内 = 在线）</span></h3>
      ${d.agents.length ? `<table><tr><th>编号</th><th>名称</th><th>心跳</th><th>状态 / 当前题</th></tr>
        ${d.agents.map(agentRow).join("")}</table>`
        : "<p class='muted'>暂无注册 AI。</p>"}
    </div>`;
}
