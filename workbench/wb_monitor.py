"""R199：连接监控——设备/IP 级访问追踪 + agent 活跃度聚合。

数据源：Handler._track_client() 每请求调用（内存聚合，30s 窗口过期清理）。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict

_LOCK = threading.Lock()
_CLIENTS: dict[str, dict] = {}      # ip -> {first_seen, last_seen, hits, paths, cred, ua}
_MAX_CLIENTS = 200
_MAX_PATHS = 8


def track(handler) -> None:
    ip = handler.client_address[0] if handler.client_address else "?"
    now = time.time()
    path = handler.path.split("?")[0] if handler.path else "/"
    # 凭证类型判定
    cred = "匿名（只读）"
    ak = handler.headers.get("X-Agent-Key", "")
    if ak.startswith("agw_"):
        cred = "agent-key"
    elif handler.headers.get("Authorization", "").lower().startswith("bearer agw_"):
        cred = "agent-key"
    elif handler.headers.get("Cookie", "").find("wb_session") >= 0:
        cred = "浏览器会话"
    elif handler.headers.get("X-Join-Token"):
        cred = "入网请求"
    ua = (handler.headers.get("User-Agent", "") or "")[:80]
    with _LOCK:
        c = _CLIENTS.get(ip)
        if c is None:
            if len(_CLIENTS) >= _MAX_CLIENTS:
                _CLIENTS.pop(next(iter(_CLIENTS)), None)
            c = _CLIENTS[ip] = {"first_seen": now, "hits": 0, "paths": [],
                                "cred": set(), "ua": ua}
        c["last_seen"] = now
        c["hits"] += 1
        c["cred"].add(cred)
        if path not in c["paths"]:
            c["paths"] = (c["paths"] + [path])[-_MAX_PATHS:]


def _fmt_ago(ts: float) -> str:
    s = max(0, int(time.time() - ts))
    if s < 60: return f"{s}s 前"
    if s < 3600: return f"{s // 60}m 前"
    return f"{s // 3600}h 前"


def snapshot() -> dict:
    """设备级连接快照 + agent 心跳活跃。"""
    with _LOCK:
        devices = []
        now = time.time()
        for ip, c in sorted(_CLIENTS.items(), key=lambda kv: -kv[1]["last_seen"]):
            devices.append({
                "ip": ip, "hits": c["hits"],
                "last_seen_ago": _fmt_ago(c["last_seen"]),
                "last_seen_ts": c["last_seen"],
                "online": now - c["last_seen"] < 120,
                "creds": sorted(c["cred"]),
                "recent_paths": c["paths"][-4:],
                "ua": ("curl" if "curl" in c["ua"] else
                       "浏览器" if "Mozilla" in c["ua"] else c["ua"][:30] or "?"),
            })
    return {
        "devices": devices,
        "total_tracked": len(devices),
        "online_now": sum(1 for d in devices if d["online"]),
        "server_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
