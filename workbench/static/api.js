/* ---------------- 访问令牌（--token / --lan 共享模式） ---------------- */
export function authHeaders(extra) {
  // 认证靠 HttpOnly 的 wb_session cookie；localStorage 只留裸令牌用于静默续期
  return { ...((window.__extraHeaders) || {}), ...(extra || {}) };
}

async function exchange(token) {
  try {
    const r = await fetch("/api/auth/exchange", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    return r.ok;
  } catch { return false; }
}

let authPending = null;   // 并发 401 只弹一次输入框

async function resolveAuth() {
  // 裸令牌不能直接调 /api（只用于换 session）：先 exchange 拿 cookie，再重试。
  let t = localStorage.getItem("wb.token");
  let ok = t ? await exchange(t) : false;
  if (!ok) {
    t = prompt("该工作台已开启令牌鉴权，请输入访问令牌（启动窗口里的「令牌」一行）：");
    if (!t) throw new Error("需要访问令牌");
    t = t.trim();
    ok = await exchange(t);
  }
  if (!ok) {
    localStorage.removeItem("wb.token");
    throw new Error("令牌无效（检查启动窗口打印的令牌）");
  }
  localStorage.setItem("wb.token", t);  // 仅用于 15 分钟会话过期后静默续期
}

let guestMode = false;   // R196：队员浏览模式——401 不再弹窗骚扰，静默降级

export function setGuestMode(on) { guestMode = !!on; }
// 开机首个请求成功 → 非队员模式，恢复弹窗续期能力
let _bootProbed = false;
export function noteBootOk() { if (_bootProbed) return; _bootProbed = true; guestMode = false; }
export function isGuestMode() { return guestMode; }

export async function ensureToken(res, retry) {
  if (res.status !== 401) return null;
  // 已有令牌（本机管理员/已登录队员）→ 正常续期流程
  if (localStorage.getItem("wb.token")) {
    if (!authPending) authPending = resolveAuth().finally(() => { authPending = null; });
    await authPending;
    return retry();
  }
  // 队员浏览模式：无令牌且已拒绝过一次 → 不再弹窗，静默返回空结果
  // （只读数据已由白名单放行；走到这说明该操作需要写权限）
  guestMode = true;
  return null;
}

export async function api(path) {
  let res = await fetch(path, { headers: authHeaders() });
  const again = await ensureToken(res, () => fetch(path, { headers: authHeaders() }));
  if (again) res = again;
  const data = await res.json().catch(() => ({ error: "bad json" }));
  if (!res.ok) {
    if (guestMode && res.status === 401) return { _guestDenied: true };
    throw new Error(data.error || res.status);
  }
  return data;
}
export async function post(action, params) {
  const body = JSON.stringify({ action, params });
  const doFetch = () => fetch("/api/action", {
    method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body,
  });
  let res = await doFetch();
  const again = await ensureToken(res, doFetch);
  if (again) res = again;
  if (res.status === 401 && guestMode) {
    return { ok: false, error: "写操作需要访问令牌（队员浏览模式只读）——找工作台持有者获取",
             code: "E_GUEST_READONLY" };
  }
  return res.json().catch(() => ({ ok: false, error: "bad json" }));
}
