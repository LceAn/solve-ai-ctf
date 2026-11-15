/* ---------------- ④ 时间线（SSE 实时流） ---------------- */
import { S } from "./state.js";
import { $, esc, fmtTime } from "./ui.js";

let eventSource = null;

export function stopEventStream() {
  if (eventSource) { eventSource.close(); eventSource = null; }
}

// R202：与 detail.js 共用的人话化转译器（时间线页 sse.js/detail.js 双源渲染）
export function evLabel(e) {
  const d = (typeof e.detail === "string" ? { raw: e.detail } : e.detail) || {};
  const who = d.agent ? `[${d.agent}] ` : "";
  switch (e.kind) {
    case "status_changed":
      return `${who}状态 ${d.old || "?"} → ${d.new || "?"}${d.reason ? "（" + d.reason + "）" : ""}`;
    case "attempt_added":
      return `${who}尝试 ${d.attempt_id || ""} ${d.outcome ? "· " + d.outcome : ""}`;
    case "hypothesis_added":
      return `${who}新假设 ${d.hypothesis_id || ""}`;
    case "evidence_added":
      return `${who}新证据 ${d.evidence_id || ""}`;
    case "candidate_added":
      return `${who}新 flag 候选 ${d.candidate_id || ""}`;
    case "candidate_status_changed":
      return `${who}候选 ${d.candidate_id || ""}：${d.old || "?"} → ${d.new || "?"}`;
    case "flag_scan":
      return `${who}flag 扫描${d.candidate_count != null ? " · 新增 " + d.candidate_count + " 候选" : ""}`;
    case "case_initialized":
      return "case 初始化";
    case "handoff":
      return `${who}交接${d.summary ? "：" + String(d.summary).slice(0, 60) : ""}`;
    default:
      return typeof e.detail === "string" ? e.detail : e.kind;
  }
}

export function tlItemHtml(e) {
  return `<div class="tl-item">
    <span class="tl-time">${esc(fmtTime(e.time))}</span><span class="tl-kind">${esc(evLabel(e))}</span>
    <span class="tl-detail">${esc(evLabel(e))}</span>
  </div>`;
}

export function startEventStream() {
  // ?nosse=1 断开实时流：无头截图、排查"页面一直转圈是不是 SSE 卡住"时用
  if (new URLSearchParams(location.search).has("nosse")) return;
  if ("EventSource" in window) {
    // 认证走 wb_session cookie（EventSource 不能设请求头，也不再往 URL 塞令牌）
    eventSource = new EventSource(`/api/events/stream?dir=${encodeURIComponent(S.dir)}`);
    eventSource.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data);
        const body = $("#tlBody");
        if (body) body.insertAdjacentHTML("afterbegin", tlItemHtml(e));
        // R62-A1：事件总线——关键事件触发相关视图即时刷新（免等轮询）
        window.dispatchEvent(new CustomEvent("wb-event", { detail: e }));
      } catch { /* 忽略坏帧 */ }
    };
    eventSource.onerror = () => { /* EventSource 自动重连 */ };
  }
}
