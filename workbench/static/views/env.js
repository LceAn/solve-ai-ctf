/* ---------------- ③c 比赛环境（R47：从旧版 opsEnv 移植为 ES module） ----------------
 * 三页签：当前比赛 / 标准环境（L0/L1 池）/ 仓库推送。
 * 后端：/api/env/status · /api/env/build · /api/env/push · /api/env/registry · /api/env/services/down */
import { $, $$, esc, toast } from "../ui.js";
import { api } from "../api.js";
import { S } from "../state.js";

let ENV_DATA = null, ENV_TAB = localStorage.getItem("wb.etab") || "comp";
let ENV_SELECTED = new Set();

const dispatch = (payload, label) => async () => {
  const r = await fetch("/api/env/build", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dir: S.dir, ...payload }) }).then((x) => x.json())
    .catch((e) => ({ ok: false, error: String(e) }));
  if (r.ok) { toast(`${label} 已派发 ✓（任务 ${r.task.id}）`); }
  else toast(r.error || "派发失败", true);
};

export async function renderEnv(target = "#envBody") {
  const body = $(target);
  if (!body) return;
  body.innerHTML = `<p class="muted">加载环境状态…</p>`;
  try { ENV_DATA = await api(`/api/env/status?dir=${encodeURIComponent(S.dir)}`); }
  catch (e) { body.innerHTML = `<p style="color:var(--red)">环境状态读取失败：${esc(e.message)}</p>`; return; }
  const tabs = [["comp", "🏗️ 当前比赛"], ["pool", "🧱 标准环境"], ["registry", "☁️ 仓库推送"]];
  if (!tabs.some(([id]) => id === ENV_TAB)) ENV_TAB = "comp";
  body.innerHTML = `<div class="subtabs">${tabs.map(([id, label]) =>
    `<button data-et="${id}" class="${ENV_TAB === id ? "on" : ""}">${label}</button>`).join("")}</div>
    <div id="envTabBody"></div>`;
  $$("#envBody [data-et]").forEach((b) => b.onclick = () => {
    ENV_TAB = b.dataset.et; localStorage.setItem("wb.etab", ENV_TAB);
    $$("#envBody [data-et]").forEach((x) => x.classList.toggle("on", x.dataset.et === ENV_TAB));
    renderEnvTab();
  });
  renderEnvTab();
}

function renderEnvTab() {
  const s = ENV_DATA;
  if (!s) return;
  const body = $("#envTabBody");
  if (ENV_TAB === "registry") return renderRegistry(body);
  if (ENV_TAB === "pool") return renderPool(body, s);
  return renderComp(body, s);
}

/* ---- 页签 1：当前比赛 ---- */
function renderComp(body, s) {
  const l2 = s.l2
    ? (s.l2.image
        ? `<span class="badge" style="--b-c:#34d399" title="${esc(s.l2.image)}">✓ 已构建</span>`
        : `<span class="badge" style="--b-c:#fbbf24">未构建</span>`)
      + ` <span class="muted mono" style="font-size:11px">最新 spec → ${esc(s.l2.tag_hint || "")}</span>`
    : `<span class="muted">无 comp.yaml</span>`;
  const compContainers = (s.runtime?.containers || [])
    .filter((c) => c.name.includes(S.dir) || c.name.startsWith("ctfwb-"));
  const rows = (s.challenges || []).map((c) => {
    const rec = c.built || {};
    const state = rec.image
      ? `<span class="badge" style="--b-c:#34d399" title="${esc(rec.image)}">✓ 已构建</span>`
      : c.customized ? `<span class="badge" style="--b-c:#fbbf24">未构建</span>`
      : `<span class="badge" style="--b-c:#94a3b8">骨架</span>`;
    return `<tr>
      <td class="mono">${esc(c.slug)}</td>
      <td>${esc(c.category)}</td>
      <td>${c.has_spec ? (c.customized ? "✓ 定制" : "骨架") : "—"}</td>
      <td>${c.services ? "🌐 services" : "—"}</td>
      <td>${state}${c.stale ? ` <span class="badge" style="--b-c:#f87171">spec 已改</span>` : ""}</td>
      <td class="wrap mono muted" style="font-size:11px">${esc(rec.image || c.base || "")}</td>
      <td style="white-space:nowrap">
        <label class="muted" style="white-space:nowrap"><input type="checkbox" data-envsel="${esc(c.slug)}"
          ${ENV_SELECTED.has(c.slug) ? "checked" : ""}> 选</label>
        <button class="small" data-envbuild="${esc(c.slug)}">构建</button>
        ${rec.image ? `<button class="small" data-envverify="${esc(c.slug)}">验证</button>` : ""}
      </td>
    </tr>`;
  }).join("");
  const svcChalls = (s.challenges || []).filter((ch) => ch.services && (ch.built || {}).project);
  body.innerHTML = `
    <div class="panel" style="max-width:1000px">
      <div class="row" style="justify-content:space-between">
        <h3 style="margin:0">当前比赛环境</h3>
        <div class="row">
          <button class="small" id="envBuildSel" ${ENV_SELECTED.size ? "" : "disabled"}>构建所选（${ENV_SELECTED.size}）</button>
          <button class="small" id="envBuildComp">构建 L2 比赛层</button>
          <button class="small" id="envRefresh">刷新</button>
        </div>
      </div>
      <p class="muted" style="margin:6px 0 10px">
        Docker ${s.docker_ok ? "✓ 可用" : "✗ 不可达"} · L2 比赛层 ${l2}
        ${s.problems?.length ? `<br><span style="color:var(--red)">spec 问题：${s.problems.map(esc).join("；")}</span>` : ""}
      </p>
      <div class="panel" style="margin:0 0 10px;background:rgba(79,140,255,.05)">
        <b>本比赛相关容器</b>
        <p class="muted" style="margin:4px 0 6px">沙箱任务容器（ctfwb-*）与题目服务容器（compose）：</p>
        ${compContainers.length
          ? `<table style="width:100%;margin-bottom:6px"><tr><th>容器</th><th>镜像</th><th>状态</th></tr>
             ${compContainers.map((c) => `<tr><td class="mono">${esc(c.name)}</td><td class="mono" style="font-size:11px">${esc(c.image)}</td><td>${esc(c.status)}</td></tr>`).join("")}</table>
             <div class="row">${svcChalls.map((ch) =>
               `<button class="small" data-svcdown="${esc(ch.slug)}">停 ${esc(ch.slug)} 服务</button>`).join("")}</div>`
          : `<p class="muted" style="margin:0 0 6px">当前无本比赛容器（沙箱与题目服务只在任务期间存在）。</p>`}
      </div>
      <table style="width:100%">
        <tr><th>题目</th><th>类别</th><th>spec</th><th>服务</th><th>题目层镜像</th><th>tag / base</th><th>操作</th></tr>
        ${rows || `<tr><td colspan="7" class="muted">暂无题目</td></tr>`}
      </table>
      <p class="muted" style="margin:10px 0 0">spec 在 比赛/${esc(s.dir)}/env/（comp.yaml + challenges/&lt;slug&gt;.yaml）。
        构建/验证是子进程任务，进度在「运行任务」页实时查看。</p>
    </div>`;
  const doBuild = (payload, label) => async () => {
    const r = await fetch("/api/env/build", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir: S.dir, ...payload }) }).then((x) => x.json())
      .catch((e) => ({ ok: false, error: String(e) }));
    if (r.ok) toast(`${label} 已派发 ✓（任务 ${r.task.id}）`);
    else toast(r.error || "派发失败", true);
  };
  $$("#envTabBody [data-envbuild]").forEach((b) =>
    b.onclick = doBuild({ slug: b.dataset.envbuild }, `构建 ${b.dataset.envbuild}`));
  $$("#envTabBody [data-envverify]").forEach((b) =>
    b.onclick = doVerify(b.dataset.envverify));
  $$("#envTabBody [data-envsel]").forEach((cb) => cb.onchange = () => {
    if (cb.checked) ENV_SELECTED.add(cb.dataset.envsel);
    else ENV_SELECTED.delete(cb.dataset.envsel);
    const btn = $("#envBuildSel");
    if (btn) { btn.disabled = !ENV_SELECTED.size;
               btn.textContent = `构建所选（${ENV_SELECTED.size}）`; }
  });
  const selBtn = $("#envBuildSel");
  if (selBtn) selBtn.onclick = async () => {
    const slugs = [...ENV_SELECTED];
    if (!slugs.length) return;
    const r = await fetch("/api/env/build", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir: S.dir, slugs, jobs: Math.min(3, slugs.length) }) })
      .then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
    if (r.ok) { toast(`批量构建 ${slugs.length} 题 ✓（任务 ${r.task.id}）`); ENV_SELECTED.clear(); }
    else toast(r.error || "批量构建派发失败", true);
  };
  $("#envBuildComp").onclick = doBuild({ comp_image: true }, "构建 L2 比赛层");
  $("#envRefresh").onclick = () => renderEnv(target);
  $$("#envTabBody [data-svcdown]").forEach((b) => b.onclick = async () => {
    const slug = b.dataset.svcdown;
    const r = await fetch("/api/env/services/down", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir: S.dir, slug }) }).then((x) => x.json())
      .catch((e) => ({ ok: false, error: String(e) }));
    if (r.ok) { toast(`${slug} 服务已停止 ✓`); renderEnv(target); }
    else toast(r.error || "停止失败", true);
  });
  function doVerify(slug) {
    return async () => {
      const r = await fetch("/api/env/verify", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dir: S.dir, slug }) }).then((x) => x.json())
        .catch((e) => ({ ok: false, error: String(e) }));
      if (r.ok) toast(`验证 ${slug} 已派发 ✓（任务 ${r.task.id}）`);
      else toast(r.error || "派发失败", true);
    };
  }
}

/* ---- 页签 2：标准环境（L0/L1 池 + 磁盘） ---- */
function renderPool(body, s) {
  const rows = Object.entries(s.l1 || {}).map(([cat, v]) => `
    <tr>
      <td class="mono">${esc(v.image)}</td>
      <td>${v.ok ? `<span class="badge" style="--b-c:#34d399">✓ 就绪</span>` : `<span class="badge" style="--b-c:#f87171">未构建</span>`}</td>
      <td class="muted">${esc(v.size || "—")}${v.created ? " · " + esc(v.created) : ""}</td>
      <td><button class="small" data-envrebuild="${esc(cat)}" title="强制重建该题型层（继承最新 L0）">${v.ok ? "重建" : "构建"}</button></td>
    </tr>`).join("");
  const disk = s.runtime?.disk && Object.keys(s.runtime.disk).length
    ? Object.entries(s.runtime.disk).map(([k, v]) =>
        `${esc(k)} ${esc(v.size)}（可回收 ${esc(v.reclaimable)}）`).join(" · ") : "—";
  body.innerHTML = `
    <div class="panel" style="max-width:1000px">
      <div class="row" style="justify-content:space-between">
        <h3 style="margin:0">标准默认环境（L0/L1 池）</h3>
        <div class="row">
          <button class="small" id="envPoolPreheat">构建缺失层</button>
          <button class="small" id="envPoolClean" title="删除 7 天前构建且未登记在 .built.json 的 ctf-* 镜像">清理旧镜像</button>
        </div>
      </div>
      <p class="muted" style="margin:6px 0 8px">L0 底座 <span class="badge" style="--b-c:${s.l0?.ok ? "#34d399" : "#f87171"}">${esc(s.l0?.image || "")}</span>
        <button class="small" id="envL0Rebuild" title="同步约束层资产并重建 L0（L1/L2/L3 需各自重建后继承）">重建 L0</button> ·
        磁盘：${disk} · 重建 L1 会继承最新 L0（约束层/skill 包随 L0 更新）</p>
      <table style="width:100%">
        <tr><th>题型层镜像</th><th>状态</th><th>大小 / 构建时间</th><th>操作</th></tr>${rows}
      </table>
    </div>`;
  $$("#envTabBody [data-envrebuild]").forEach((b) =>
    b.onclick = doBuild({ preheat: true, categories: b.dataset.envrebuild, rebuild: true },
                        `重建 ${b.dataset.envrebuild} 层`));
  $("#envPoolPreheat").onclick = doBuild(
    { preheat: true, categories: Object.keys(s.l1 || {}).join(",") }, "构建缺失题型层");
  $("#envPoolClean").onclick = doBuild({ clean: true }, "清理旧镜像");
  $("#envL0Rebuild").onclick = doBuild({ base_rebuild: true }, "重建 L0 底座");
}

/* ---- 页签 3：仓库推送 ---- */
async function renderRegistry(body) {
  body.innerHTML = `<p class="muted">加载仓库配置…</p>`;
  let reg = "";
  try { reg = (await api("/api/env/registry")).registry || ""; }
  catch (e) { /* 按空处理 */ }
  const built = (ENV_DATA?.challenges || []).filter((c) => (c.built || {}).image);
  const rows = built.map((c) => `
    <tr><td class="mono">${esc(c.slug)}</td>
        <td class="mono muted" style="font-size:11px">${esc(c.built.image)}</td>
        <td><button class="small" data-push="${esc(c.slug)}">推送</button></td></tr>`).join("");
  body.innerHTML = `
    <div class="panel" style="max-width:1000px">
      <h3 style="margin:0 0 8px">仓库推送</h3>
      <p class="muted" style="margin:0 0 10px">仓库地址保存到 workbench-data/registry.json（不入 git）；
        <b>凭证只在本机 docker login</b>，绝不写进仓库或配置文件。</p>
      <div class="row" style="margin:0 0 10px">
        <input id="registryInput" class="mono" style="flex:1;min-width:280px" placeholder="registry.example.com/namespace"
               value="${esc(reg)}">
        <button id="registrySave" class="primary">保存地址</button>
      </div>
      ${built.length ? `<table style="width:100%">
        <tr><th>题目</th><th>本地镜像</th><th>推送</th></tr>${rows}
        <tr><td colspan="3"><button id="pushAll" class="small">推送全部（含比赛层）</button></td></tr>
      </table>` : `<p class="muted">尚无已构建镜像：先在「当前比赛」页签构建。</p>`}
    </div>`;
  $("#registrySave").onclick = async () => {
    const r = await fetch("/api/env/registry", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ registry: $("#registryInput").value }) }).then((x) => x.json());
    if (r.ok) { toast("仓库地址已保存 ✓"); renderRegistry(body); }
    else toast(r.error || "保存失败", true);
  };
  const doPush = (payload, label) => async () => {
    const r = await fetch("/api/env/push", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir: S.dir, ...payload }) }).then((x) => x.json())
      .catch((e) => ({ ok: false, error: String(e) }));
    if (r.ok) { toast(`${label} 已派发 ✓（任务 ${r.task.id}）`); }
    else toast(r.error || "推送派发失败", true);
  };
  $$("#envTabBody [data-push]").forEach((b) => b.onclick = doPush({ slugs: [b.dataset.push] }, `推送 ${b.dataset.push}`));
  const pa = $("#pushAll");
  if (pa) pa.onclick = doPush({}, "推送全部镜像");
}
