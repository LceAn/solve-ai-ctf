#!/usr/bin/env python3
"""R104：Agent 协作网关——多 AI 协作的身份与协调层。

痛点：此前所有 AI 共享一个 admin token——分不清谁做了什么、不能单独吊销、
没有存活感知、两个 AI 可能重复做同一道题。

网关提供：
  注册    POST /api/agent-gw/register（admin 凭证）→ 发放 agw_ 密钥（只显示一次，存哈希）
  入网    POST /api/agent-gw/join（X-Join-Token）→ 其他 AI 自助拿密钥，无需管理员令牌
  标签    POST /api/agent-gw/label（agent key）→ 自己改名/写备注/报能力
  心跳    POST /api/agent-gw/heartbeat（agent key）→ last_seen + 当前状态
  认领    POST /api/agent-gw/claim（agent key）→ 题目认领（TTL 45min，防死 agent 占坑）
  释放    POST /api/agent-gw/release（agent key）
  名册    GET  /api/agent-gw/directory → 全部 agent + 认领（admin 或 agent key）
  吊销    POST /api/agent-gw/revoke（admin）→ 立即失效

身份：每个 agent 注册时分配递增序号 seq 与固定标牌 tag（AI1、AI2…），
吊销不回收号码——多 AI 混战时"谁是谁"必须稳定。label/note 由 agent 自己维护。

存储：workbench-data/agent-gateway.json（密钥只存 sha256，零明文）。
入网码：workbench-data/join-token.txt（明文，需反复出示给其他 AI；可一键轮换）。
鉴权集成：agent key 经 X-Agent-Key 头或 Bearer agw_… 使用，等同 session 权限
（注册的协作者，仍受动作白名单与提交器约束）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path

CLAIM_TTL_SECONDS = 45 * 60
KEY_PREFIX = "agw_"
JOIN_PREFIX = "wbj_"
GATEWAY_FILE = "agent-gateway.json"
JOIN_FILE = "join-token.txt"

_UNSET = object()


def _store_path(root: Path) -> Path:
    return root / "workbench-data" / GATEWAY_FILE


_DIR_CACHE: dict[str, tuple[float, dict]] = {}
_DIR_TTL = 2.0  # R137：读缓存 2s——写路径（register/claim/revoke 等）都直接落盘并清缓存


def _dir_cache_clear() -> None:
    _DIR_CACHE.clear()


def _load(root: Path) -> dict:
    """R137：mtime 签名缓存（写路径清缓存），面板高频刷新免重复读盘解析。"""
    p = _store_path(root)
    try:
        st = p.stat()
        sig = f"{int(st.st_mtime * 1000)}-{st.st_size}"
        hit = _DIR_CACHE.get(str(p))
        if hit and hit[0] == sig:
            return hit[1]
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("agents", [])
            data.setdefault("claims", [])
            _DIR_CACHE[str(p)] = (sig, data)
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"agents": [], "claims": []}


def _save(root: Path, data: dict) -> None:
    p = _store_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _DIR_CACHE.clear()  # R137：写后失效


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 入网码
#
# 为什么入网码是明文文件：协作场景里人需要反复把同一串码贴给多个 AI，
# 只显示一次的设计在这里是负担。文件本身在本机 workbench-data/ 下；
# 唯一的权限边界是"能读这台机器的人"。可随时 POST join-token 轮换，
# 旧码立即作废（已发出去的 agent key 不受影响，需单独 revoke）。

def _join_path(root: Path) -> Path:
    return root / "workbench-data" / JOIN_FILE


def read_join_token(root: Path) -> str:
    try:
        return _join_path(root).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def rotate_join_token(root: Path) -> str:
    """生成新入网码（旧码立即失效）。空串=关闭自助入网。"""
    token = JOIN_PREFIX + secrets.token_urlsafe(18)
    p = _join_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token + "\n", encoding="utf-8")
    try:  # POSIX 上收紧权限；Windows 无实际效果，交给 ACL
        os.chmod(p, 0o600)
    except OSError:
        pass
    return token


def ensure_join_token(root: Path) -> str:
    return read_join_token(root) or rotate_join_token(root)


def disable_join(root: Path) -> None:
    _join_path(root).write_text("", encoding="utf-8")


# ---------------------------------------------------------------- 身份编号

def _next_seq(data: dict) -> int:
    """递增序号，吊销不回收——保证 AI1/AI2 在多轮协作里指代同一个人。"""
    seqs = [int(a.get("seq") or 0) for a in data.get("agents", [])]
    return max(seqs + [int(data.get("seq") or 0)]) + 1


def _tag_of(seq: int) -> str:
    return f"AI{seq}" if seq > 0 else "AI?"


def _find_agent(data: dict, key: str) -> dict | None:
    """按明文 key 找 agent（常数时间比较防时序侧信道）。"""
    kh = _key_hash(key)
    for a in data.get("agents", []):
        if a.get("revoked"):
            continue
        if hmac.compare_digest(str(a.get("key_hash", "")), kh):
            return a
    return None


def register(root: Path, name: str, capabilities: list[str], role: str = "",
             label: str = "", note: str = "", unique: bool = False) -> dict:
    """注册 agent：返回明文密钥（仅此一次）。role: solver | observer。

    同名再注册 = 该 agent 重连：保留原序号/标签/能力，只换密钥。
    unique=True（自助入网用）：同名直接拒绝，防止顶替别人的身份。
    """
    name = str(name or "").strip()[:40]
    if not name:
        raise ValueError("agent name 必填")
    if role and role not in ("solver", "observer"):
        raise ValueError("role 必须是 solver 或 observer")
    caps = [str(c).strip()[:24] for c in (capabilities or []) if str(c).strip()][:8]
    data = _load(root)
    prev = next((a for a in data.get("agents", []) if a.get("name") == name), None)
    if unique and prev and not prev.get("revoked"):
        raise ValueError(f"名称 {name} 已被占用，请换一个（编号由工作台自动分配 AI1/AI2…）")
    seq = int((prev or {}).get("seq") or 0) or _next_seq(data)
    data["seq"] = max(int(data.get("seq") or 0), seq)
    if not caps and prev:
        caps = list(prev.get("capabilities") or [])
    key = KEY_PREFIX + secrets.token_urlsafe(24)
    agent = {
        "id": "agw-" + secrets.token_hex(4),
        "name": name,
        "seq": seq,
        "tag": _tag_of(seq),
        "label": (str(label).strip()[:24] or str((prev or {}).get("label") or "")[:24]),
        "note": (str(note).strip()[:160] or str((prev or {}).get("note") or "")[:160]),
        "key_hash": _key_hash(key),
        "capabilities": caps,
        "role": role or str((prev or {}).get("role") or "solver"),
        "status": "idle",
        "current_slug": "",
        "registered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "revoked": False,
    }
    # 同名复用：删掉旧的（换新密钥，旧密钥自然失效）
    data["agents"] = [a for a in data.get("agents", []) if a.get("name") != name]
    data["agents"].append(agent)
    # 旧认领随旧记录一起失效（新密钥立即接手，不留在名册里指向幽灵 id）
    if prev and prev.get("id") != agent["id"]:
        data["claims"] = [c for c in data.get("claims", [])
                          if c.get("agent_id") != prev.get("id")]
    _save(root, data)
    return {"agent": {k: v for k, v in agent.items() if k != "key_hash"},
            "agent_key": key}


def join(root: Path, join_token: str, name: str = "", label: str = "",
         capabilities: list[str] | None = None, role: str = "solver") -> dict:
    """其他 AI 自助入网：只凭入网码，不需要管理员令牌。

    与 register 的差别：同名不覆盖（防止用别人的名字顶替），返回接入简报。
    """
    expected = read_join_token(root)
    if not expected:
        raise PermissionError("本机未开启自助入网（管理员可在 AI 看板生成入网码）")
    if not join_token or not hmac.compare_digest(str(join_token), expected):
        raise PermissionError("入网码无效（X-Join-Token，向工作台持有者索取）")
    name = str(name or "").strip()[:40]
    if not name:
        peek = _load(root)
        name = f"agent-{_next_seq(peek)}"
    data = _load(root)
    if any(a.get("name") == name and not a.get("revoked") for a in data.get("agents", [])):
        raise ValueError(f"名称 {name} 已被占用，请换一个（标识由工作台自动分配 AI1/AI2…）")
    result = register(root, name, capabilities or [], role=role or "solver",
                      label=label, unique=True)
    return result


def label(root: Path, key: str, label=_UNSET, note=_UNSET,
          role=_UNSET, capabilities=_UNSET) -> dict:
    """agent 给自己打标签：展示名 / 备注 / 角色 / 能力，全部可随时改。"""
    data = _load(root)
    agent = _find_agent(data, key)
    if agent is None:
        raise PermissionError("无效的 agent key")
    if label is not _UNSET:
        agent["label"] = str(label or "").strip()[:24]
    if note is not _UNSET:
        agent["note"] = str(note or "").strip()[:160]
    if role is not _UNSET:
        role = str(role or "")
        if role not in ("solver", "observer"):
            raise ValueError("role 必须是 solver 或 observer")
        agent["role"] = role
    if capabilities is not _UNSET:
        agent["capabilities"] = [str(c).strip()[:24] for c in (capabilities or [])
                                 if str(c).strip()][:8]
    agent["label_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save(root, data)
    return {"ok": True, "agent": {k: v for k, v in agent.items() if k != "key_hash"}}


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


def heartbeat(root: Path, key: str, status: str = "", current_slug: str = "",
              note=_UNSET) -> dict:
    """心跳：一次加载一次落盘（旧实现 authenticate 后再 _load 会把状态写丢）。"""
    data = _load(root)
    agent = _find_agent(data, key)
    if agent is None:
        raise PermissionError("无效的 agent key")
    if status:
        agent["status"] = str(status)[:32]
    if current_slug:
        agent["current_slug"] = str(current_slug)[:64]
    if note is not _UNSET:
        agent["note"] = str(note or "").strip()[:160]
    agent["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save(root, data)
    return {"ok": True, "agent": agent["name"], "tag": agent.get("tag"),
            "server_time": agent["last_seen"]}



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


def active_claims(root: Path) -> list[dict]:
    """R152：只读过期过滤后的活跃认领（内存过滤，不写盘）。

    board_data 等外部读方此前直读 _load().claims——agent 弃坑后过期认领
    未被其他网关调用惰性清除前，题目会滞留在「已认领」态、不进无人认领条。
    """
    data = _load(root)
    _expire_claims(data)
    return data.get("claims", [])


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
            who = c.get("agent_tag") or c.get("agent_name") or "?"
            raise ValueError(f"题目已被 {who} 认领（未释放/未过期）")
    data["claims"] = [c for c in data.get("claims", []) if c.get("agent_id") != agent["id"]]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["claims"].append({"slug": slug, "agent_id": agent["id"], "agent_name": agent["name"],
                           "agent_tag": agent.get("tag", ""),
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
    """名册（脱敏）：agents（含活性分钟数）+ 当前 claims + 最近交接。"""
    data = _load(root)
    _expire_claims(data)
    now = time.time()
    agents = []
    for a in data.get("agents", []):
        a = {k: v for k, v in a.items() if k != "key_hash"}
        # 兼容 R104–R167 的旧记录：没有 seq 的老 agent 按注册顺序补号
        if not a.get("seq"):
            a["seq"] = 0
        a.setdefault("tag", _tag_of(int(a.get("seq") or 0)))
        a.setdefault("label", "")
        a.setdefault("note", "")
        a.setdefault("status", "idle")
        # R115：活性计算——AI 侧和人都需要知道 agent 是否还活着
        try:
            seen = time.mktime(time.strptime(a.get("last_seen", "")[:19],
                                             "%Y-%m-%dT%H:%M:%S"))
            a["last_seen_minutes"] = max(0, int((now - seen) / 60))
        except (ValueError, TypeError):
            a["last_seen_minutes"] = -1
        a["claims_count"] = sum(1 for c in data.get("claims", [])
                                if c.get("agent_id") == a.get("id"))
        agents.append(a)
    # AI1/AI2… 固定顺序：人扫一眼就能对上号，不按名字/时间跳来跳去
    agents.sort(key=lambda x: (int(x.get("seq") or 0), str(x.get("name") or "")))
    # R167：交接记录纳入名册（AI 看板要展示"谁把哪题交给了谁"）
    handoffs = [{k: v for k, v in h.items() if k != "key"}
                for h in data.get("handoffs", [])[-20:]]
    return {"agents": agents, "claims": data.get("claims", []), "handoffs": handoffs}


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
        mine = bool(holder and holder.get("agent_id") == agent["id"])
        if holder and holder.get("agent_id") != agent["id"] and not explicit:
            continue  # 他人认领中
        scored.append((priority_of(entry, case), entry, case, mine))

    scored.sort(key=lambda x: (-x[0], x[1]["slug"]))
    you = {"tag": agent.get("tag", ""), "label": agent.get("label", ""),
           "name": agent["name"]}
    if not scored:
        return {"assignment": None,
                "alternatives": [],
                "you": you,
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
    # R114：显式指定 slug（交接接手）时强制转移认领——上一持有者的 claim 被覆盖
    claimed_now = False
    if not top_mine and not my_claim:
        try:
            claim(root, key, slug)
            claimed_now = True
            my_claim = {"slug": slug}
        except ValueError as exc:
            if want_slug and "已被" in str(exc):
                # 显式接手：抢占他人认领（上一持有者可能已 handoff 释放但 claim 残留过期）
                data_gw = _load(root)
                data_gw["claims"] = [c for c in data_gw.get("claims", [])
                                     if c.get("slug") != slug]
                _save(root, data_gw)
                claim(root, key, slug)
                claimed_now = True
                my_claim = {"slug": slug}
            else:
                scored = scored[1:]  # 竞态被抢 → 降级到备选
                if scored:
                    top_pri, top_entry, top_case, top_mine = scored[0]
                    slug = top_entry["slug"]

    prompt = build_prompt(comp_dir, slug, "continue")
    # R115b：已有候选 flag 提示（AI 需知道前人是否已找到 flag，避免重复寻找）
    cands = top_case.get("candidates") or []
    valid_cands = [c for c in cands if c.get("status") in ("validated", "submitted", "accepted")]
    if valid_cands:
        sep = chr(10)
        prompt += (sep + sep + "# 已有 flag 候选（已验证，检查是否仍有效或直接复核）" + sep
                   + sep.join(f"- {c.get('id')}: [{c.get('status')}] {c.get('value', '')}"
                              for c in valid_cands[:5]))
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

    # R118：该题历史交接（新 AI 看到完整接力史）
    handoffs_hist = [{k: h.get(k) for k in ("agent_name", "time", "summary")}
                     for h in data.get("handoffs", []) if h.get("slug") == slug]
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
            "handoffs": handoffs_hist,
            "you": you,
            "situational": {
                "solved": sum(1 for e in chs if (e.get("case") or {}).get("status")
                              in ("solved", "submitted", "closed")),
                "total": len(chs),
                "unclaimed": sum(1 for e in chs
                                 if (e.get("case") or {}).get("status")
                                 in ("new", "triaged", "in_progress")
                                 and e["slug"] not in claim_by_slug),
                "claims": len(claim_by_slug),
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


def join_brief(base_url: str, join_token: str, name: str = "your-name",
               dir_name: str = "") -> str:
    """生成一段可直接粘给其他 AI 的接入简报（含命令与协作规则）。"""
    base = base_url.rstrip("/") + "/"
    api = base + "api/"
    d = urllib.parse.quote(dir_name) if dir_name else "<比赛目录>"
    return """你是 CTF 工作台的协作 agent。入网后由工作台分配固定编号（AI1、AI2…），
请按 1→3 步做完再开始解题。

■ 0. 网关
  地址：%(base)s
  入网码：%(token)s
  默认比赛目录：%(dir_raw)s

■ 1. 入网（拿你自己的 agw_ 密钥，只显示一次）
curl -s -X POST %(api)sagent-gw/join \\
  -H "Content-Type: application/json" -H "X-Join-Token: %(token)s" \\
  -d '{"name":"%(name)s","label":"我的专长"}'
→ 返回 {"agent_key":"agw_...","agent":{"tag":"AI1",...}}
之后所有请求都带 -H "X-Agent-Key: agw_..."
（也接受 Authorization: Bearer agw_...）

■ 2. 给自己打标签（其他 AI 和人类靠这个认你）
curl -s -X POST %(api)sagent-gw/label -H "X-Agent-Key: agw_..." \\
  -H "Content-Type: application/json" \\
  -d '{"label":"主攻 Web","note":"当前思路一句话","capabilities":["web","php"]}'
label ≤24 字、note ≤160 字，随时可改。

■ 3. 领题（不要抢别人的）
curl -s "%(api)sagent-gw/dispatch?dir=%(dir)s" -H "X-Agent-Key: agw_..."
→ assignment.prompt 是题面 + 上下文 + 前任交接简报；认领自动生效（TTL 45 分钟）。
同一时刻只持有一道题；想换题先 handoff。

■ 4. 干活期间
- 心跳（每 5 分钟）：
  POST %(api)sagent-gw/heartbeat  {"status":"working","current_slug":"<slug>"}
  status 取值：working / thinking / idle
- 假设、尝试、候选 flag 走 %(api)saction（case.hypothesis / case.attempt / case.candidate）
- 放弃或换人：
  POST %(api)sagent-gw/handoff
  {"slug":"<slug>","summary":"试过什么、结论如何","findings":["线索1","线索2"]}
  交接自动释放认领，并把简报注入下一个接手的 AI。

■ 规则
- 已被别人认领的题：claim 返回 409、写 case 返回 403，别硬抢。
- 密钥不要贴进聊天记录或日志；泄露请让人类在 AI 看板吊销（立即失效）。
- 名册公开可读：GET %(api)sagent-gw/directory
""" % {"base": base, "api": api, "token": join_token, "name": name,
      "dir": d, "dir_raw": dir_name or "<比赛目录>"}


def lanes_of(comp_dir: Path) -> list[dict]:
    """轻量运行任务统计（避免循环 import board_data）。"""
    from wb_tasks import TASKS
    return [t for t in TASKS.list() if t.get("dir") == comp_dir.name]


def can_write_case(root: Path, key: str, slug: str) -> tuple[bool, str]:
    """R112-L4：agent 对某题的写权限校验。

    solver：必须已认领该题（或题未被任何人认领且即将由 claim 建立）；
    observer：一律拒绝写。返回 (ok, reason)。
    """
    agent = authenticate(root, key)
    if agent is None:
        return False, "无效的 agent key"
    if agent.get("role") == "observer":
        return False, "observer 角色只读"
    data = _load(root)
    _expire_claims(data)
    mine = any(c.get("slug") == slug and c.get("agent_id") == agent["id"]
               for c in data.get("claims", []))
    if mine:
        return True, ""
    other = next((c for c in data.get("claims", []) if c.get("slug") == slug), None)
    if other:
        return False, f"题目已被 {other.get('agent_name', '?')} 认领"
    # 未认领：solver 先 claim 再写（自动代为认领）
    claim(root, key, slug)
    return True, ""
