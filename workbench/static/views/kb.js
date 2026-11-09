/* ---------------- ⑥ 知识库 / 提示词 ---------------- */
import { S } from "../state.js";
import { $, esc, toast, copyText } from "../ui.js";
import { api } from "../api.js";


// R66-K1：命中词高亮（mark 包裹当前查询词，大小写不敏感）
// R176：转义改标准正则集——旧字符集漏 [ ] - 等，查询 "[" 直接 SyntaxError 变「读取失败」
let KB_QUERY = "";
function hi(text) {
  const q = KB_QUERY.trim();
  if (!q) return text;
  const safe = q.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&");
  return text.replace(new RegExp(safe, "gi"), (m) => "<mark>" + m + "</mark>");
}

export function renderKb() {
  // 结果区空态：否则进页面只有表单，下方一片空白
  const results = $("#kbResults");
  if (results && !results.innerHTML.trim()) {
    results.innerHTML = `<div class="empty-state"><b>还没有检索结果</b>
      <p>输入关键词（如 <code>堆利用</code>、<code>SSTI</code>）后回车，或点「检索」。</p></div>`;
  }
  // R55-K2：检索统计卡（命中率 + 零命中补洞清单）
  api("/api/kb/stats").then((st) => {
    const host = document.getElementById("kbStats");
    if (!host || !st.total) return;
    const zero = (st.zero_queries || []).map((z) =>
      `<span class="badge" style="--b-c:#f87171;margin:2px" title="出现 ${z.count} 次">${esc(z.query)} ×${z.count}</span>`).join("");
    host.innerHTML = `<b>${st.rate}%</b> 命中（${st.hit}/${st.total}）
      ${zero ? ` · 补洞候选：${zero}` : " · 暂无零命中"}`;
  }).catch(() => {});
  const sel = $("#promptCase");
  if (S.comp && !sel.options.length) {
    sel.innerHTML = S.comp.challenges.map((c) => `<option value="${esc(c.slug)}">${esc(c.name)}</option>`).join("");
  }
  if (!$("#kbForm").dataset.bound) {
    $("#kbForm").dataset.bound = "1";
    $("#kbForm").onsubmit = async (e) => {
      e.preventDefault();
      KB_QUERY = $("#kbQuery").value || "";
      $("#kbResults").innerHTML = "<p class='muted'>检索中…</p>";
      const q = encodeURIComponent($("#kbQuery").value);
      const cat = $("#kbCategory").value ? "&category=" + $("#kbCategory").value : "";
      try {
        const r = await api(`/api/kb?q=${q}${cat}`);
        $("#kbResults").innerHTML = r.hits.length ? r.hits.map((h) => `
          <div class="panel"><b>${esc(h.file)}:${h.line}</b> <span class="muted">score=${h.score}</span>
          <pre class="out">${hi(esc(h.context.join("\n")))}</pre></div>`).join("")
          : `<div class='empty'><div class='big'>🔍</div><strong>无命中</strong>
             <div class='muted' style='margin-top:6px'>试试更短的关键词（如 "rsa"、"pwn"），
             或切换上方分类重试。</div></div>`;
      } catch (e2) { $("#kbResults").innerHTML = `<p style="color:var(--red)">${esc(e2.message)}</p>`; }
    };
    $("#promptGen").onclick = async () => {
      const slug = $("#promptCase").value;
      if (!slug) return toast("请先选择比赛与题目", true);
      $("#promptOut").textContent = "生成中…";
      try {
        const r = await api(`/api/prompt?dir=${encodeURIComponent(S.dir)}&slug=${encodeURIComponent(slug)}`);
        $("#promptOut").textContent = r.prompt;
      } catch (e2) { $("#promptOut").textContent = "生成失败：" + e2.message; }
    };
    $("#promptCopy").onclick = async () => {
      const text = $("#promptOut").textContent;
      if (!text) return;
      // R176：copyText 带 execCommand 兜底——裸 navigator.clipboard 在局域网 http
      // （非 secure context）下是 undefined，共享模式复制必失败
      copyText(text, "提示词已复制 ✓");
    };
  }
}
