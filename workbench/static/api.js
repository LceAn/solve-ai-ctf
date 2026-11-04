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

export async function ensureToken(res, retry) {
  if (res.status !== 401) return null;
  // 裸令牌不能直接调 /api（只用于换 session）：先 exchange 拿 cookie，再重试。
  let t = localStorage.getItem("wb.token");
  if (!t) {
    t = prompt("该工作台已开启令牌鉴权，请输入访问令牌（启动窗口里的「令牌」一行）：");
    if (!t) throw new Error("需要访问令牌");
  }
  t = t.trim();
  if (await exchange(t)) {
    localStorage.setItem("wb.token", t);  // 仅用于 15 分钟会话过期后静默续期
    return retry();
  }
  localStorage.removeItem("wb.token");
  throw new Error("令牌无效（检查启动窗口打印的令牌）");
}

export async function api(path) {
  let res = await fetch(path, { headers: authHeaders() });
  const again = await ensureToken(res, () => fetch(path, { headers: authHeaders() }));
  if (again) res = again;
  const data = await res.json().catch(() => ({ error: "bad json" }));
  if (!res.ok) throw new Error(data.error || res.status);
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
  return res.json().catch(() => ({ ok: false, error: "bad json" }));
}
