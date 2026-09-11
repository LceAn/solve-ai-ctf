/* ---------------- ⑥ 知识库 / 提示词 ---------------- */
import { S } from "../state.js";
import { $, esc, toast } from "../ui.js";
import { api } from "../api.js";

export function renderKb() {
  const sel = $("#promptCase");
  if (S.comp && !sel.options.length) {
    sel.innerHTML = S.comp.challenges.map((c) => `<option value="${esc(c.slug)}">${esc(c.name)}</option>`).join("");
  }
  if (!$("#kbForm").dataset.bound) {
    $("#kbForm").dataset.bound = "1";
    $("#kbForm").onsubmit = async (e) => {
      e.preventDefault();
      $("#kbResults").innerHTML = "<p class='muted'>检索中…</p>";
      const q = encodeURIComponent($("#kbQuery").value);
      const cat = $("#kbCategory").value ? "&category=" + $("#kbCategory").value : "";
      try {
        const r = await api(`/api/kb?q=${q}${cat}`);
        $("#kbResults").innerHTML = r.hits.length ? r.hits.map((h) => `
          <div class="panel"><b>${esc(h.file)}:${h.line}</b> <span class="muted">score=${h.score}</span>
          <pre class="out">${esc(h.context.join("\n"))}</pre></div>`).join("")
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
