/* ℹ️ 关于 · 产品总览（R204 重做）
 *
 * 定位：这不是"设置页"，是给人（和刚接手的 AI）看的一张产品名片——
 * 我是什么、现在跑得怎么样、能干什么、最近改了什么。
 * 所以改成长页滚动：Hero → 运行现状 → 平台能力 → 更新记录 → 页脚，
 * 不再用两个子页签把能力藏起来。
 */
import { $, esc, toast } from "../ui.js";
import { api } from "../api.js";
import { mdRender } from "../md.js";

const REPO = "https://github.com/LceAn/solve-ai-ctf";

/* 运行链路：从浏览器到 CTF 平台的五段，纯静态说明（改代码时记得同步） */
const CHAIN = [
  ["浏览器", "原生 JS", ""],
  ["HTTP 服务", "Python 标准库", "REST / SSE"],
  ["脚本层", "状态机 + 审计", "12 个脚本"],
  ["沙箱 / Agent", "Docker", "断网 · 限额"],
  ["CTF 平台", "dry-run 先行", "人工确认"],
];

const SHORTCUTS = [
  ["Alt", "1..9", "切换左侧页面"],
  ["?", "", "快捷键与协作帮助"],
  ["Esc", "", "关闭弹窗 / 抽屉"],
  ["Shift", "/", "同「?」"],
];

function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); } finally { ta.remove(); }
  return Promise.resolve();
}

function splitTitle(raw) {
  // "[v0.5.0] — 2026-11-11（多 AI 实战协作大版本）"
  const m = String(raw).match(/^\[([^\]]+)\]\s*(?:[—–-]\s*)?(.*)$/);
  if (!m) return { name: raw, rest: "" };
  return { name: m[1], rest: m[2] || "" };
}

function dateOf(build) {
  return String(build?.commit_at || "").slice(0, 16).replace("T", " ") || "—";
}

export async function renderAbout() {
  const host = $("#aboutBody");
  if (!host) return;
  host.innerHTML = "<p class='muted'>加载中…</p>";
  let d;
  try { d = await api("/api/about"); }
  catch (e) { host.innerHTML = `<p style="color:var(--red)">加载失败：${esc(e.message)}</p>`; return; }

  const b = d.build || {};
  const s = d.stats || {};
  const sections = d.changelog_sections || [];

  const chainHtml = CHAIN.map(([name, sub, tag], i) => `
    ${i ? '<i class="ab-arrow" aria-hidden="true">↓</i>' : ""}
    <div class="ab-node">
      <b>${esc(name)}</b><span>${esc(sub)}</span>
      ${tag ? `<em>${esc(tag)}</em>` : ""}
    </div>`).join("");

  const featureHtml = (d.features || []).map((g) => {
    const [icon, ...rest] = String(g.group || "").split(" ");
    return `<article class="ab-fcard">
      <div class="ab-fhead">
        <span class="ab-fico" aria-hidden="true">${esc(icon || "•")}</span>
        <h4>${esc(rest.join(" ") || g.group || "")}</h4>
        <span class="ab-fn">${(g.items || []).length}</span>
      </div>
      ${g.desc ? `<p class="ab-fdesc">${esc(g.desc)}</p>` : ""}
      <ul>${(g.items || []).map((i) => `<li>${esc(i)}</li>`).join("")}</ul>
    </article>`;
  }).join("");

  const clHtml = sections.length ? sections.map((sec, i) => {
    const { name, rest } = splitTitle(sec.title);
    return `<details class="ab-cl-item" data-idx="${i}"${sec.latest ? " open" : ""}>
      <summary>
        <span class="ab-cl-name">${esc(name)}</span>
        ${rest ? `<span class="ab-cl-rest">${esc(rest)}</span>` : ""}
        ${sec.latest ? '<span class="ab-cl-badge">最新</span>' : ""}
        <span class="ab-cl-lines">${(sec.body || "").split("\n").length} 行</span>
      </summary>
      <div class="md ab-cl-body"></div>
    </details>`;
  }).join("") : `<p class="muted">没有找到 CHANGELOG.md</p>`;

  host.innerHTML = `
    <section class="ab-hero">
      <div class="ab-hero-main">
        <div class="ab-badge" aria-hidden="true">🦋</div>
        <div class="ab-hero-text">
          <h2 id="view-about-title">Solve-AI-CTF
            <span class="ab-ver" title="版本号由 git tag + 提交数推导">${esc(d.version || "")}</span>
          </h2>
          <p class="ab-tagline">AI 驱动的 CTF 解题工作台</p>
          <p class="ab-sub">分诊 → 假设 → 有界执行 → 验证 → 提交 → 复盘，全流程留痕 · 多 AI 同场协作</p>
          <div class="ab-actions">
            <a class="btn ab-repo" href="${esc(REPO)}" target="_blank" rel="noreferrer noopener">GitHub 仓库 ↗</a>
            <button class="small" id="abCopy">复制版本信息</button>
            <button class="small" id="abGoHealth">看系统概况 →</button>
          </div>
          <p class="ab-meta">
            MIT License<span class="ab-dot">·</span>
            <code>${esc(b.commit || "no-git")}</code> ${esc(b.branch || "")}
            <span class="ab-dot">·</span>${esc(dateOf(b))}
          </p>
        </div>
      </div>
      <div class="ab-chain" aria-label="运行链路">
        <div class="ab-chain-title">运行链路</div>
        <div class="ab-chain-flow">${chainHtml}</div>
      </div>
    </section>

    <div class="ab-stats">
      ${[
        { tab: "health", num: `${s.online ?? "—"}<span>/${s.total ?? "—"}</span>`, label: "功能在线" },
        { tab: "board", num: s.competitions ?? 0, label: "场比赛" },
        { tab: "board", num: s.challenges ?? 0, label: "题目" },
        { tab: "board2", num: s.agents_online ?? 0, label: "AI 在线" },
      ].map((x) => `<button class="ab-stat" data-tab="${x.tab}" title="前往对应页面">
        <b>${x.num}</b><em>${esc(x.label)}</em></button>`).join("")}
    </div>

    <section class="ab-sec">
      <div class="ab-sec-head">
        <h3>平台能力</h3>
        <span>${(d.features || []).length} 个方向 · 从单题到整场</span>
      </div>
      <div class="ab-features">${featureHtml}</div>
    </section>

    <section class="ab-sec">
      <div class="ab-sec-head">
        <h3>更新记录</h3>
        <span>${sections.length} 个版本段 · 默认展开最新，其余点开才渲染</span>
        ${sections.length > 1 ? '<button class="small" id="abClToggle" style="margin-left:auto">全部展开</button>' : ""}
      </div>
      <div class="ab-cl">${clHtml}</div>
    </section>

    <footer class="ab-foot">
      <div class="ab-foot-block">
        <h4>技术栈</h4>
        <p>${esc(d.stack || "")}</p>
      </div>
      <div class="ab-foot-block">
        <h4>快捷键</h4>
        <ul class="ab-keys">
          ${SHORTCUTS.map(([k, sub, desc]) => `<li>
            <kbd>${esc(k)}</kbd>${sub ? `<kbd>${esc(sub)}</kbd>` : ""}<span>${esc(desc)}</span></li>`).join("")}
        </ul>
      </div>
      <div class="ab-foot-block">
        <h4>继续</h4>
        <p><a href="${esc(REPO)}" target="_blank" rel="noreferrer noopener">源码与 issue ↗</a></p>
        <p class="muted" style="font-size:11.5px;margin-top:6px">
          本地优先：数据全在 <code>比赛/</code> 与 <code>workbench-data/</code>，不依赖云服务。</p>
      </div>
    </footer>`;

  // 复制版本信息：排查问题时直接粘给别人
  $("#abCopy").onclick = async () => {
    const info = [
      `Solve-AI-CTF ${d.version}`,
      `commit ${b.commit || "?"} (${b.branch || "?"})`,
      `build ${dateOf(b)}`,
      `${d.stack}`,
      `node ${location.host}`,
    ].join("\n");
    try {
      await copyText(info);
      toast("版本信息已复制 ✓");
    } catch {
      toast("复制失败，请手动选择", "err");
    }
  };
  const gotoHealth = () => {
    const btn = document.querySelector('#tabs [data-tab="health"]');
    if (btn) btn.click(); else location.href = "?tab=health";
  };
  $("#abGoHealth").onclick = gotoHealth;
  // 四个数字都是入口：功能在线→系统概况、比赛/题目→总览、AI 在线→AI 看板
  document.querySelectorAll(".ab-stat[data-tab]").forEach((el) => {
    el.onclick = () => {
      const btn = document.querySelector(`#tabs [data-tab="${el.dataset.tab}"]`);
      if (btn) btn.click(); else location.href = `?tab=${el.dataset.tab}`;
    };
  });

  // 更新记录：一键全展开（每段仍是首次展开才渲染）
  const clToggle = $("#abClToggle");
  if (clToggle) {
    let allOpen = false;
    clToggle.onclick = () => {
      allOpen = !allOpen;
      document.querySelectorAll(".ab-cl-item").forEach((el) => { el.open = allOpen; });
      clToggle.textContent = allOpen ? "全部收起" : "全部展开";
    };
  }

  // 更新记录懒渲染：11 段全量 md 一次渲染没必要，展开哪段渲染哪段
  document.querySelectorAll(".ab-cl-item").forEach((el) => {
    const body = el.querySelector(".ab-cl-body");
    const idx = Number(el.dataset.idx);
    const paint = () => {
      if (!body || body.dataset.done) return;
      body.innerHTML = mdRender(sections[idx]?.body || "");
      body.dataset.done = "1";
    };
    if (el.open) paint();
    el.addEventListener("toggle", () => { if (el.open) paint(); });
  });
}
