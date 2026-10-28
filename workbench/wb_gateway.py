#!/usr/bin/env python3
"""R104：Agent 协作网关——多 AI 协作的身份与协调层。

痛点：此前所有 AI 共享一个 admin token——分不清谁做了什么、不能单独吊销、
没有存活感知、两个 AI 可能重复做同一道题。

网关提供：
  注册    POST /api/agent-gw/register（admin 凭证）→ 发放 agw_ 密钥（只显示一次，存哈希）
  心跳    POST /api/agent-gw/heartbeat（agent key）→ last_seen + 当前状态
  认领    POST /api/agent-gw/claim（agent key）→ 题目认领（TTL 45min，防死 agent 占坑）
  释放    POST /api/agent-gw/release（agent key）
  名册    GET  /api/agent-gw/directory → 全部 agent + 认领（admin 或 agent key）
  吊销    POST /api/agent-gw/revoke（admin）→ 立即失效

存储：workbench-data/agent-gateway.json（密钥只存 sha256，零明文）。
鉴权集成：agent key 经 X-Agent-Key 头或 Bearer agw_… 使用，等同 session 权限
（注册的协作者，仍受动作白名单与提交器约束）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

CLAIM_TTL_SECONDS = 45 * 60
KEY_PREFIX = "agw_"
GATEWAY_FILE = "agent-gateway.json"


def _store_path(root: Path) -> Path:
    return root / "workbench-data" / GATEWAY_FILE


def _load(root: Path) -> dict:
    p = _store_path(root)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("agents", [])
            data.setdefault("claims", [])
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"agents": [], "claims": []}


def _save(root: Path, data: dict) -> None:
    p = _store_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _find_agent(data: dict, key: str) -> dict | None:
    """按明文 key 找 agent（常数时间比较防时序侧信道）。"""
    kh = _key_hash(key)
    for a in data.get("agents", []):
        if a.get("revoked"):
            continue
        if hmac.compare_digest(str(a.get("key_hash", "")), kh):
            return a
    return None


def register(root: Path, name: str, capabilities: list[str]) -> dict:
    """注册 agent：返回明文密钥（仅此一次）。"""
    name = str(name or "").strip()[:40]
    if not name:
        raise ValueError("agent name 必填")
    caps = [str(c).strip()[:24] for c in (capabilities or []) if str(c).strip()][:8]
    data = _load(root)
    # 同名复用：删掉旧的（换新密钥，旧密钥自然失效）
    data["agents"] = [a for a in data.get("agents", []) if a.get("name") != name]
    key = KEY_PREFIX + secrets.token_urlsafe(24)
    agent = {
        "id": "agw-" + secrets.token_hex(4),
        "name": name,
        "key_hash": _key_hash(key),
        "capabilities": caps,
        "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "revoked": False,
    }
    data["agents"].append(agent)
    _save(root, data)
    return {"agent": {k: v for k, v in agent.items() if k != "key_hash"},
            "agent_key": key}


def authenticate(root: Path, key: str) -> dict | None:
    """验证 agent key，命中则刷新 last_seen 并返回 agent。失效/吊销返回 None。"""
    if not key or not key.startswith(KEY_PREFIX):
        return None
    data = _load(root)
    agent = _find_agent(data, key)
    if agent is None:
        return None
    agent["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save(root, data)
    return agent


def heartbeat(root: Path, key: str, status: str = "", current_slug: str = "") -> dict:
    agent = authenticate(root, key)
    if agent is None:
        raise PermissionError("无效的 agent key")
    agent["status"] = str(status or "idle")[:32]
    agent["current_slug"] = str(current_slug or "")[:64]
    agent["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data = _load(root)
    _save(root, data)
    return {"ok": True, "agent": agent["name"], "server_time": agent["last_seen"]}


def _expire_claims(data: dict) -> None:
    """R104：过期认领惰性释放（TTL 到期的 claim 直接清除）。"""
    now = time.time()
    alive = []
    for c in data.get("claims", []):
        try:
            if time.mktime(time.strptime(c["expires_at"][:19], "%Y-%m-%dT%H:%M:%S")) > now:
                alive.append(c)
        except (KeyError, ValueError):
            continue
    data["claims"] = alive


def claim(root: Path, key: str, slug: str) -> dict:
    """认领题目：已被其他 agent 活跃认领时拒绝（防重复劳动）。"""
    agent = authenticate(root, key)
    if agent is None:
        raise PermissionError("无效的 agent key")
    slug = str(slug or "").strip()[:64]
    if not slug:
        raise ValueError("slug 必填")
    data = _load(root)
    _expire_claims(data)
    for c in data.get("claims", []):
        if c.get("slug") == slug and c.get("agent_id") != agent["id"]:
            raise ValueError(f"题目已被 {c.get('agent_id', '?')} 认领（未释放/未过期）")
    data["claims"] = [c for c in data.get("claims", []) if c.get("agent_id") != agent["id"]]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["claims"].append({"slug": slug, "agent_id": agent["id"], "agent_name": agent["name"],
                           "claimed_at": now,
                           "expires_at": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                       time.localtime(time.time() + CLAIM_TTL_SECONDS))})
    _save(root, data)
    return {"ok": True, "slug": slug, "ttl_minutes": CLAIM_TTL_SECONDS // 60}


def release(root: Path, key: str, slug: str = "") -> dict:
    agent = authenticate(root, key)
    if agent is None:
        raise PermissionError("无效的 agent key")
    data = _load(root)
    before = len(data.get("claims", []))
    if slug:
        data["claims"] = [c for c in data.get("claims", [])
                          if not (c.get("agent_id") == agent["id"] and c.get("slug") == slug)]
    else:
        data["claims"] = [c for c in data.get("claims", []) if c.get("agent_id") != agent["id"]]
    _save(root, data)
    return {"ok": True, "released": before - len(data.get("claims", []))}


def directory(root: Path) -> dict:
    """名册（脱敏）：agents + 当前 claims。admin 与 agent 均可查看。"""
    data = _load(root)
    _expire_claims(data)
    agents = [{k: v for k, v in a.items() if k != "key_hash"}
              for a in data.get("agents", [])]
    return {"agents": agents, "claims": data.get("claims", [])}


def revoke(root: Path, agent_id: str) -> dict:
    """吊销 agent：密钥立即失效（agent 记录保留供审计）。"""
    data = _load(root)
    hit = False
    for a in data.get("agents", []):
        if a.get("id") == agent_id and not a.get("revoked"):
            a["revoked"] = True
            a["revoked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            hit = True
    # 连带释放其认领
    data["claims"] = [c for c in data.get("claims", []) if c.get("agent_id") != agent_id]
    _save(root, data)
    if not hit:
        raise ValueError(f"未找到活跃 agent：{agent_id}")
    return {"ok": True, "revoked": agent_id}
