/* ---------------- 访问令牌（--token 共享模式） ---------------- */
export function authHeaders(extra) {
  const t = localStorage.getItem("wb.token");
  const h = { ...((window.__extraHeaders) || {}), ...(extra || {}) };
  if (t) h["Authorization"] = "Bearer " + t;
  return h;
}

export async function ensureToken(res, retry) {
  if (res.status !== 401) return null;
  const t = prompt("该工作台已开启令牌鉴权，请输入访问令牌（--token）：");
  if (!t) throw new Error("需要访问令牌");
  localStorage.setItem("wb.token", t.trim());
  return retry();
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
