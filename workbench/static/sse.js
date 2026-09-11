/* ---------------- ④ 时间线（SSE 实时流） ---------------- */
import { S } from "./state.js";
import { $, esc, fmtTime } from "./ui.js";

let eventSource = null;

export function stopEventStream() {
  if (eventSource) { eventSource.close(); eventSource = null; }
}

export function tlItemHtml(e) {
  return `<div class="tl-item">
    <span class="tl-time">${esc(fmtTime(e.time))}</span><span class="tl-kind">${esc(e.kind)}</span>
    <span class="tl-detail">${esc(typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail || {}))}</span>
  </div>`;
}

export function startEventStream() {
  if ("EventSource" in window) {
    const t = localStorage.getItem("wb.token");
    eventSource = new EventSource(`/api/events/stream?dir=${encodeURIComponent(S.dir)}` +
      (t ? `&token=${encodeURIComponent(t)}` : ""));
    eventSource.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data);
        const body = $("#tlBody");
        if (body) body.insertAdjacentHTML("afterbegin", tlItemHtml(e));
      } catch { /* 忽略坏帧 */ }
    };
    eventSource.onerror = () => { /* EventSource 自动重连 */ };
  }
}
