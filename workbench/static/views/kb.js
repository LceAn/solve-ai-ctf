/* ---------------- ⑥ 知识库 / 提示词 ---------------- */
import { S } from "../state.js";
import { $, esc, toast } from "../ui.js";
import { api } from "../api.js";


// R66-K1：命中词高亮（mark 包裹当前查询词，大小写不敏感）
let KB_QUERY = "";
function hi(text) {
  const q = KB_QUERY.trim();
  if (!q) return text;
  const safe = q.split("").map((ch) => "[\^$.|?*+(){}".includes(ch) ? "\\" + ch : ch).join("");
  return text.replace(new RegExp(safe, "gi"), (m) => "<mark>" + m + "</mark>");
}

export function renderKb() {
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
          : "<p class='muted'>无命中。</p>";
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
      try { await navigator.clipboard.writeText(text); toast("已复制到剪贴板 ✓"); }
      catch { toast("复制失败，请手动选择文本", true); }
    };
  }
}
