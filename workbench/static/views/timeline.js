/* ---------------- ④ 时间线（SSE 实时流） ---------------- */
import { S } from "../state.js";
import { $, esc } from "../ui.js";
import { stopEventStream, tlItemHtml, startEventStream } from "../sse.js";

let TL_FILTER = localStorage.getItem("wb.tlfilter") || "";

export function renderTimeline() {
  const el = $("#timelineWrap");
  if (!S.comp) { stopEventStream(); el.innerHTML = ""; return; }
  let evs = [...(S.comp.events || [])].reverse();
  // R59-TL1：按事件类型过滤（chips，状态持久化）
  const kinds = [...new Set(evs.map((e) => e.kind).filter(Boolean))];
  const chips = kinds.slice(0, 12).map((k) =>
    `<button class="small" data-tlf="${esc(k)}"
      style="margin:0 4px 4px 0;${TL_FILTER === k ? "border-color:var(--accent);color:var(--accent)" : ""}">${esc(k)} ${evs.filter((e) => e.kind === k).length}</button>`).join("");
  if (TL_FILTER) evs = evs.filter((e) => e.kind === TL_FILTER);
  el.innerHTML = `<div class="panel"><h3>比赛事件流（events.jsonl · ${evs.length}/${S.comp.events.length} 条 · SSE 实时推送）</h3>
    <div style="margin:0 0 8px">
      <button class="small" data-tlf="" style="margin:0 4px 4px 0;${TL_FILTER === "" ? "border-color:var(--accent);color:var(--accent)" : ""}">全部</button>
      ${chips}
    </div>
    <div id="tlBody">${evs.map(tlItemHtml).join("") || "<p class='muted'>暂无事件。</p>"}</div></div>`;
  el.querySelectorAll("[data-tlf]").forEach((b) => b.onclick = () => {
    TL_FILTER = b.dataset.tlf;
    localStorage.setItem("wb.tlfilter", TL_FILTER);
    renderTimeline();
  });
  stopEventStream();
  startEventStream();
}
