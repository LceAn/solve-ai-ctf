/* ℹ️ 关于（子页签：功能 / 更新记录） */
import { S } from "../state.js";
import { $, $$, esc } from "../ui.js";
import { api } from "../api.js";
import { mdRender } from "../md.js";

const ABOUT_TABS = [["features", "🧩 平台功能"], ["changelog", "📜 更新记录"]];
let aboutTab = localStorage.getItem("wb.aboutTab") || "features";

export async function renderAbout() {
  const host = document.getElementById("aboutBody");
  if (!host) return;
  host.innerHTML = "<p class='muted'>加载中…</p>";
  let d;
  try { d = await api("/api/about"); }
  catch (e) { host.innerHTML = `<p style="color:var(--red)">${esc(e.message)}</p>`; return; }

  const tabsEl = document.getElementById("aboutSubtabs");
  if (tabsEl) {
    tabsEl.innerHTML = ABOUT_TABS.map(([id, label]) =>
      `<button class="${aboutTab === id ? "on" : ""}" data-at="${id}">${label}</button>`).join("");
    tabsEl.querySelectorAll("[data-at]").forEach((b) => b.onclick = () => {
      aboutTab = b.dataset.at;
      localStorage.setItem("wb.aboutTab", aboutTab);
      renderAbout();
    });
  }

  const featureCard = (g) => `
    <div class="panel about-feature">
      <h3>${esc(g.group)}</h3>
      <ul>${g.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>
    </div>`;

  let body = "";
  if (aboutTab === "features") {
    body = `<div class="about-features">${(d.features || []).map(featureCard).join("")}</div>`;
  } else {
    body = `<div class="md panel" style="padding:18px 22px">${mdRender(d.changelog_md || "")}</div>`;
  }

  host.innerHTML = `
    <div class="about-head">
      <div class="about-logo">🦋</div>
      <div>
        <h2 style="margin:0">Solve-AI-CTF <span class="muted" style="font-size:13px">${esc(d.version)}</span></h2>
        <p class="muted" style="margin:4px 0 0">AI 驱动的 CTF 解题工作台 —— 分诊 → 假设 → 有界执行 → 验证 → 提交 → 复盘，全流程留痕 · 多 AI 同场协作</p>
        <p class="muted" style="margin:6px 0 0;font-size:12px">
          ${esc(d.stack)} ·
          <a href="${esc(d.repo)}" target="_blank" rel="noreferrer">GitHub 仓库 ↗</a> · MIT License
        </p>
      </div>
    </div>${body}`;
}
