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


def dispatch(root: Path, comp_dir: Path, key: str, *,
             category: str = "", want_slug: str = "") -> dict:
    """R109-L1：调度协议——"我该干哪题？"

    按 competition.py prioritize 的优先级公式（P×分值×紧迫度÷分钟）排序，
    跳过已解决/已废弃与他人认领的题；已被我认领的题优先返回（续做）。
    返回 assignment（首选+prompt）+ alternatives + situational 全局态势。
    """
    agent = authenticate(root, key)
    if agent is None:
        raise PermissionError("无效的 agent key")
    from wb_core import competition_view, build_prompt, read_json, safe_join

    data = _load(root)
    _expire_claims(data)
    claims = data.get("claims", [])
    claim_by_slug = {c["slug"]: c for c in claims}
    my_claim = next((c for c in claims if c.get("agent_id") == agent["id"]), None)

    view = competition_view(comp_dir)
    chs = view.get("challenges", [])

    def priority_of(entry: dict, case: dict | None) -> float:
        status = case.get("status", "new") if case else "new"
        if status in {"solved", "submitted", "closed", "abandoned", "invalid", "blocked"}:
            return 0.0
        p_solve = float(entry.get("p_solve", 0.3))
        points = float(entry.get("points") or 0.0)
        minutes = max(float(entry.get("expected_minutes") or 60.0), 1.0)
        urgency = 3.0 if status in ("candidate_found", "submitted") else (
            1.0 if status in ("new", "triaged", "in_progress") else 0.0)
        return p_solve * points * urgency / minutes

    scored = []
    for entry in chs:
        slug = entry["slug"]
        if category and (entry.get("category") or "") != category:
            continue
        if want_slug and slug != want_slug:
            continue
        case = entry.get("case") or {}
        status = case.get("status", "new")
        # 显式指定 slug = 明确意图（交接接手场景），跳过状态过滤
        explicit = bool(want_slug)
        if not explicit and status in {"solved", "submitted", "closed",
                                       "abandoned", "invalid", "blocked"}:
            continue
        holder = claim_by_slug.get(slug)
        if holder and holder.get("agent_id") != agent["id"] and not explicit:
            continue  # 他人认领中
        scored.append((priority_of(entry, case), entry, case, bool(holder)))

    scored.sort(key=lambda x: (-x[0], x[1]["slug"]))
    if not scored:
        return {"assignment": None,
                "alternatives": [],
                "situational": {"solved": sum(1 for e in chs
                                              if (e.get("case") or {}).get("status")
                                              in ("solved", "submitted", "closed")),
                                "total": len(chs),
                                "running_tasks": sum(1 for l in lanes_of(comp_dir)
                                                     if l.get("status") == "running"),
                                "unclaimed": 0,
                                "note": "没有可认领的活跃题目"}}

    top_pri, top_entry, top_case, top_mine = scored[0]
    slug = top_entry["slug"]

    # 未认领则顺手完成认领（原子，冲突抛错→降级为 alternatives）
    claimed_now = False
    if not top_mine and not my_claim:
        try:
            claim(root, key, slug)
            claimed_now = True
            my_claim = {"slug": slug}
        except ValueError:
            scored = scored[1:]  # 竞态被抢 → 降级到备选
            if scored:
                top_pri, top_entry, top_case, top_mine = scored[0]
                slug = top_entry["slug"]

    prompt = build_prompt(comp_dir, slug, "continue")
    # R111-L3：注入最近交接简报（接手 AI 秒懂上下文）
    handoff_note = last_handoff(root, slug)
    if handoff_note:
        sep = chr(10)
        prompt += (sep + sep + "# ⚠ 交接简报（来自上一个 agent：" + handoff_note["agent_name"]
                   + " @ " + handoff_note["time"] + "）" + sep + handoff_note["summary"]
                   + sep + sep.join("- " + f for f in handoff_note.get("findings", [])))
    alternatives = [{"slug": e["slug"], "name": e.get("name", ""), "priority": round(p, 2),
                     "points": e.get("points")}
                    for p, e, _c, _m in scored[1:4]]

    return {"assignment": {
                "slug": slug,
                "name": top_entry.get("name", slug),
                "category": top_entry.get("category", ""),
                "points": top_entry.get("points"),
                "priority": round(top_pri, 2),
                "claimed_by_me": True,
                "claimed_now": claimed_now,
                "prompt": prompt,
            },
            "alternatives": alternatives,
            "situational": {
                "solved": sum(1 for e in chs if (e.get("case") or {}).get("status")
                              in ("solved", "submitted", "closed")),
                "total": len(chs),
                "unclaimed": sum(1 for e in chs
                                 if (e.get("case") or {}).get("status")
                                 in ("new", "triaged", "in_progress")
                                 and e["slug"] not in claim_by_slug),
            }}


def handoff(root: Path, key: str, slug: str, summary: str,
            findings: list[str] | None = None) -> dict:
    """R111-L3：弃坑/交接声明——结构化简报写入 claims 历史并返回确认。

    简报随题留存（data["handoffs"]），dispatch 命中同题时自动注入 prompt。
    """
    agent = authenticate(root, key)
    if agent is None:
        raise PermissionError("无效的 agent key")
    slug = str(slug or "").strip()[:64]
    summary = str(summary or "").strip()[:2000]
    if not slug or not summary:
        raise ValueError("slug 与 summary 必填")
    data = _load(root)
    _expire_claims(data)
    record = {
        "slug": slug,
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": summary,
        "findings": [str(f)[:200] for f in (findings or [])[:6]],
    }
    data.setdefault("handoffs", []).append(record)
    # 交接即释放认领
    data["claims"] = [c for c in data.get("claims", []) if c.get("slug") != slug]
    _save(root, data)
    return {"ok": True, "slug": slug, "recorded": record["time"]}


def last_handoff(root: Path, slug: str) -> dict | None:
    """取某题最近一条交接简报（dispatch 注入用）。"""
    data = _load(root)
    hs = [h for h in data.get("handoffs", []) if h.get("slug") == slug]
    return hs[-1] if hs else None


def lanes_of(comp_dir: Path) -> list[dict]:
    """轻量运行任务统计（避免循环 import board_data）。"""
    from wb_tasks import TASKS
    return [t for t in TASKS.list() if t.get("dir") == comp_dir.name]
