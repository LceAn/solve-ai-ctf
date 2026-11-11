/* ---------------- ③c 系统概况（R200 功能在线矩阵） ---------------- */
import { $, esc } from "../ui.js";
import { api, post } from "../api.js";

let HEALTH_RETRIES = 0; // stale 轮询上限（20 次 × 15s ≈ 5 分钟冷启动窗口）
let AUTO_TIMER = null;
let AUTO_ON = localStorage.getItem("wb.health.auto") !== "0";
const AUTO_MS = 30000;

const STATE_LABEL = { online: "在线", degraded: "注意", off: "未启用" };
const GROUP_HINT = {
  "核心运行时": "服务、脚本、数据与事件流——这些挂了页面本身就不对劲",
  "求解环境": "派发任务、跑沙箱、提交 flag 的链路",
  "协作接入": "多 AI 协同与外部设备的入口",
  "数据与交付": "检索、文档、成品与积分",
};

function stopAuto() {
  if (AUTO_TIMER) { clearInterval(AUTO_TIMER); AUTO_TIMER = null; }
}

/** 卡片：一句话说明 + 实测指标 + 探测依据（有问题的补一行怎么办）。 */
function cardHtml(m) {
  const metrics = (m.metrics || []).map((x) => `
    <div><b>${esc(String(x.value))}</b><span>${esc(x.label)}</span></div>`).join("");
  const hint = m.state !== "online" && m.hint
    ? `<div class="hm-hint">${esc(m.hint)}</div>` : "";
  const link = m.link
    ? `<a class="hm-go" href="${esc(m.link)}" title="前往相关页面" aria-label="前往相关页面">→</a>` : "";
  return `<div class="hm-card s-${m.state}">
    <div class="hm-card-top">
      <i class="hm-dot ${m.state}" aria-hidden="true"></i>
      <span class="hm-name">${esc(m.name)}</span>
      <span class="hm-state">${STATE_LABEL[m.state] || m.state}</span>${link}
    </div>
    <div class="hm-detail">${esc(m.detail)}</div>
    ${metrics ? `<div class="hm-metrics">${metrics}</div>` : ""}
    ${hint}
    <div class="hm-probe">探测 · ${esc(m.probe || "—")}</div>
  </div>`;
}

export async function renderHealth(force = false) {
  const el = $("#healthWrap");
  if (!el) return;
  stopAuto();
  if (!HEALTH_RETRIES) el.innerHTML = "<p class='muted'>检测中…</p>";

  let d;
  try { d = await api("/api/health/detail" + (force ? "?fresh=1" : "")); }
  catch (e) { el.innerHTML = `<p style="color:var(--red)">检测失败：${esc(e.message)}</p>`; return; }

  if (d.stale || !d.server) {
    // Docker 首次冷启动可达 1–3 分钟：友好等待 + 自动重试，别让人对着空白猜
    if (++HEALTH_RETRIES <= 20) {
      el.innerHTML = `<p class="muted">后台探测中（首次 Docker 冷启动可达 1–3 分钟，已等待 ${HEALTH_RETRIES * 15}s）…</p>`;
      setTimeout(() => renderHealth(), 15000);
    } else {
      el.innerHTML = `<p class="muted">探测耗时较长——Docker/WSL 可能未就绪。稍后刷新本页重试。</p>`;
    }
    return;
  }
  HEALTH_RETRIES = 0;

  if (d.matrix_error) {
    el.innerHTML = `<p style="color:var(--red)">功能矩阵构建失败：${esc(d.matrix_error)}</p>`;
    return;
  }

  const modules = d.modules || [];
  const summary = d.summary || { online: 0, total: modules.length };
  const ov = d.overview || {};
  const attention = (d.attention || []);
  const degraded = attention.filter((a) => a.state === "degraded");
  const offItems = attention.filter((a) => a.state === "off");
  const pct = Math.round((summary.online || 0) * 100 / Math.max(summary.total || 1, 1));
  const heroState = summary.state === "warn" ? "warn" : "ok";

  const groups = (d.groups || []).map((g) => {
    const items = modules.filter((m) => m.group === g);
    if (!items.length) return "";
    const on = items.filter((m) => m.state === "online").length;
    return `<section class="hm-group">
      <div class="hm-group-head">
        <h3>${esc(g)}</h3>
        <span class="hm-group-n">${on}/${items.length} 在线</span>
        <span class="hm-group-hint">${esc(GROUP_HINT[g] || "")}</span>
      </div>
      <div class="hm-grid">${items.map(cardHtml).join("")}</div>
    </section>`;
  }).join("");

  const attnHtml = degraded.length ? `<div class="hm-attn">
      <div class="hm-attn-title"><i class="hm-dot degraded" aria-hidden="true"></i>
        需要关注 <span>${degraded.length}</span></div>
      <ul>${degraded.map((a) => `<li><b>${esc(a.name)}</b><span>${esc(a.hint)}</span></li>`).join("")}</ul>
    </div>` : "";
  const offHtml = offItems.length ? `<details class="hm-off">
      <summary>${offItems.length} 项未启用 <span class="muted">（不是故障，需要时再开）</span></summary>
      <ul>${offItems.map((a) => `<li><b>${esc(a.name)}</b><span>${esc(a.hint)}</span></li>`).join("")}</ul>
    </details>` : "";

  el.innerHTML = `
    <div class="hm-hero hm-hero-${heroState}">
      <div class="hm-score" role="img" aria-label="功能在线 ${summary.online}/${summary.total}">
        <div class="hm-score-n"><b>${summary.online}</b><span>/${summary.total}</span></div>
        <div class="hm-score-l">功能在线</div>
        <div class="hm-score-track"><i style="width:${pct}%"></i></div>
      </div>
      <div class="hm-hero-main">
        <div class="hm-hero-title">${esc(summary.headline || "")}</div>
        <div class="hm-hero-meta">
          <span>运行 ${esc(ov.uptime || "—")}</span>
          <span class="hm-sep">·</span>
          <span class="mono">${esc(ov.host || "")}:${esc(String(ov.port || ""))}</span>
          <span class="hm-sep">·</span>
          <span>${ov.exposed ? "局域网共享中" : "仅本机可访问"}</span>
          <span class="hm-sep">·</span>
          <span>检测于 ${esc((ov.server_time || "").slice(11, 19))}</span>
        </div>
        <div class="hm-legend">
          <span><i class="hm-dot online" aria-hidden="true"></i>在线 ${summary.online}</span>
          <span><i class="hm-dot degraded" aria-hidden="true"></i>注意 ${summary.degraded}</span>
          <span><i class="hm-dot off" aria-hidden="true"></i>未启用 ${summary.off}</span>
        </div>
      </div>
      <div class="hm-actions">
        <button id="hmRefresh" class="small" title="重新探测全部子系统">重新检测</button>
        <button id="hmAuto" class="small ${AUTO_ON ? "primary" : ""}"
          title="每 30 秒自动刷新">自动刷新 ${AUTO_ON ? "开" : "关"}</button>
        <button id="hmSelftest" class="small primary">运行自检</button>
      </div>
    </div>
    ${attnHtml}
    ${offHtml}
    <div id="hmSelftestOut" class="hm-selftest" hidden></div>
    ${groups}`;

  $("#hmRefresh").onclick = () => renderHealth(true);
  $("#hmAuto").onclick = () => {
    AUTO_ON = !AUTO_ON;
    localStorage.setItem("wb.health.auto", AUTO_ON ? "1" : "0");
    renderHealth(true);
  };
  $("#hmSelftest").onclick = runSelftest;
  if (AUTO_ON) {
    AUTO_TIMER = setInterval(() => {
      if (document.visibilityState === "visible") renderHealth();
    }, AUTO_MS);
  }
}

async function runSelftest() {
  const out = $("#hmSelftestOut");
  if (!out) return;
  out.hidden = false;
  out.innerHTML = '<span class="muted">启动中…</span>';
  const r = await post("selftest.run", {}).catch((e) => ({ error: String(e) }));
  if (!r.started) { out.innerHTML = `<span style="color:var(--red)">${esc(r.error || "启动失败")}</span>`; return; }
  const poll = async () => {
    let s;
    try { s = await api("/api/selftest"); }
    catch (e) { out.innerHTML = `<span style="color:var(--red)">状态查询失败：${esc(e.message)}</span>`; return; }
    if (s.running) {
      out.innerHTML = `<span class="muted">自检运行中（${s.elapsed}s，约需 60–90s）…</span>`;
      setTimeout(poll, 1000);
      return;
    }
    const full = (s.output || "").trim();
    const ok = s.exit === 0;
    out.innerHTML = ok
      ? `<details><summary style="color:var(--green);cursor:pointer">✓ 自检通过（点击展开全文）</summary>
          <pre class="out" style="max-height:240px;overflow:auto;margin-top:6px">${esc(full)}</pre></details>`
      : `<details open><summary style="color:var(--red);cursor:pointer">✗ 自检失败（exit ${s.exit}）</summary>
          <pre class="out" style="max-height:240px;overflow:auto;margin-top:6px">${esc(full.slice(-2000))}</pre></details>`;
  };
  poll();
}
