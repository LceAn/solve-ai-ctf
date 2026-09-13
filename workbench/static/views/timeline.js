/* ---------------- ④ 时间线（SSE 实时流） ---------------- */
import { S } from "../state.js";
import { $ } from "../ui.js";
import { stopEventStream, tlItemHtml, startEventStream } from "../sse.js";

export function renderTimeline() {
  const el = $("#timelineWrap");
  if (!S.comp) { stopEventStream(); el.innerHTML = ""; return; }
  const evs = [...(S.comp.events || [])].reverse();
  el.innerHTML = `<div class="panel"><h3>比赛事件流（events.jsonl · ${evs.length} 条 · SSE 实时推送）</h3>
    <div id="tlBody">${evs.map(tlItemHtml).join("") || "<p class='muted'>暂无事件。</p>"}</div></div>`;
  stopEventStream();
  startEventStream();
}
