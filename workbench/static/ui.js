/* ---------------- 基础工具 ---------------- */
export const $ = (sel) => document.querySelector(sel);
export const $$ = (sel) => Array.from(document.querySelectorAll(sel));

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
export function fmtSize(n) {
  if (n < 0) return "?";
  if (n < 1024) return n + "B";
  if (n < 1048576) return (n / 1024).toFixed(1) + "K";
  if (n < 1073741824) return (n / 1048576).toFixed(1) + "M";
  return (n / 1073741824).toFixed(2) + "G";
}

/* ---- 表单状态快照（详情区被后台轮询重渲染时，保留未提交输入 / 展开的 details / 焦点）----
 * 仅在后台触发的重渲染（pollTick / watchSubmissions）中启用：
 * 用户主动提交后的重渲染不回填，保持“提交后表单清空”的原有行为。 */
export function snapshotDetailForms() {
  const body = $("#detailBody");
  const snap = { fields: [], open: [], focus: -1 };
  if (!body) return snap;
  body.querySelectorAll("input,select,textarea").forEach((el, i) => {
    snap.fields.push(el.type === "checkbox" || el.type === "radio" ? el.checked : el.value);
    if (el === document.activeElement) snap.focus = i;
  });
  body.querySelectorAll("details").forEach((d, i) => { if (d.open) snap.open.push(i); });
  return snap;
}
export function restoreDetailForms(snap) {
  const body = $("#detailBody");
  if (!body || !snap) return;
  const els = body.querySelectorAll("input,select,textarea");
  els.forEach((el, i) => {
    if (i >= snap.fields.length) return;
    const v = snap.fields[i];
    if (el.type === "checkbox" || el.type === "radio") el.checked = v;
    else if (el.value !== v) el.value = v;
  });
  (snap.open || []).forEach((i) => {
    const d = body.querySelectorAll("details")[i];
    if (d) d.open = true;
  });
  if (snap.focus >= 0 && els[snap.focus]) {
    try { els[snap.focus].focus(); } catch (e) { /* 元素可能已被替换 */ }
  }
}
export function fmtTime(t) {
  if (!t) return "";
  return String(t).replace("T", " ").slice(0, 19);
}
export function toast(msg, kind = "info") {
  // kind: info | err | ok | warn —— 队列式，互不覆盖
  if (kind === true) kind = "err";
  if (kind === false) kind = "info";
  const box = $("#toasts");
  while (box.children.length >= 4) box.firstChild.remove();
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  box.appendChild(el);
  const leave = () => {
    el.style.opacity = "0"; el.style.transition = "opacity .3s, transform .3s";
    el.style.transform = "translateY(8px)";
    setTimeout(() => el.remove(), 320);
  };
  setTimeout(leave, kind === "err" ? 6000 : 2800);
  // 焦点可访问性：toast 容器 aria-live 已在 HTML 声明
}
export function busy(on) { $("#globalBusy")?.classList.toggle("on", !!on); }

export async function copyText(text, label) {
  try { await navigator.clipboard.writeText(text); toast((label || "内容") + " 已复制 ✓", "ok"); }
  catch { toast("复制失败，请手动选择", true); }
}

/* ---------------- 模态框（带焦点圈闭 / Esc / 恢复焦点） ---------------- */
let _lastFocus = null;
let _modalKeyHandler = null;

export function openModal(html) {
  const mask = $("#modalMask");
  const box = $("#modalBox");
  _lastFocus = document.activeElement;
  box.innerHTML = html;
  mask.classList.remove("hidden");
  // 焦点圈闭
  const focusables = () => box.querySelectorAll(
    'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
  );
  const focusFirst = () => {
    const f = focusables();
    if (f.length) { try { f[0].focus(); } catch (e) {} }
    else { try { box.focus(); } catch (e) {} }
  };
  setTimeout(focusFirst, 20);
  if (_modalKeyHandler) document.removeEventListener("keydown", _modalKeyHandler);
  _modalKeyHandler = (e) => {
    if (e.key === "Escape") { closeModal(); return; }
    if (e.key !== "Tab") return;
    const f = focusables();
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  };
  document.addEventListener("keydown", _modalKeyHandler);
  // 点击遮罩关闭
  mask.onclick = (e) => { if (e.target === mask) closeModal(); };
}
export function closeModal() {
  const mask = $("#modalMask");
  mask.classList.add("hidden");
  mask.onclick = null;
  if (_modalKeyHandler) {
    document.removeEventListener("keydown", _modalKeyHandler);
    _modalKeyHandler = null;
  }
  // 恢复触发元素焦点
  if (_lastFocus && typeof _lastFocus.focus === "function") {
    try { _lastFocus.focus(); } catch (e) {}
    _lastFocus = null;
  }
}

/* ---------------- 骨架屏 helper ---------------- */
export function skeletonGrid(n = 6, cls = "skeleton-card") {
  return Array.from({ length: n }, () => `<div class="skeleton ${cls}"></div>`).join("");
}
