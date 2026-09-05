"""wb_sandbox —— Docker 沙箱配置/状态、模型网关记账（N-06 拆包）。"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import env_builder as envb
import wb_core as _core
from wb_core import list_competitions, read_json
from wb_tasks import TASKS, docker_stop_container

# ---------------------------------------------------------------- health

_HEALTH_CACHE: dict = {"at": 0.0, "data": {}}


def health_detail() -> dict:
    """参考 CTF-BTFly 系统概况页：执行链路各环节的健康与统计。"""
    now = time.time()
    if now - _HEALTH_CACHE["at"] < 30 and _HEALTH_CACHE["data"]:
        return _HEALTH_CACHE["data"]

    def probe(argv, key):
        try:
            proc = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=20, cwd=str(_core.ROOT))
            out = (proc.stdout or "").strip().splitlines()
            return {"ok": proc.returncode == 0,
                    "detail": out[0][:120] if out else f"exit={proc.returncode}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": repr(exc)[:120]}

    docker = probe(["docker", "info", "--format", "{{.ServerVersion}}"], "docker")
    selftest = {"ok": None, "detail": "手动运行"}
    comps = list_competitions()
    total_ch = sum(c.get("challenges", 0) for c in comps)
    tasks = TASKS.list()
    data = {
        "server": {"ok": True, "detail": f"workbench @ 127.0.0.1:{_core.RUNTIME['port']}"},
        "scripts": {"ok": True, "detail": f"{_core.SCRIPTS_DIR} ({len(list(_core.SCRIPTS_DIR.glob('*.py')))} scripts)"},
        "selftest": selftest,
        "docker": docker,
        "agent_cmd": {"ok": bool(TASKS.agent_cmd),
                      "detail": TASKS.agent_cmd or "未配置 --agent-cmd / WB_AGENT_CMD；可运行内置演示 Agent",
                      "demo_available": True},
        "stats": {
            "competitions": len(comps),
            "configured": sum(1 for c in comps if c["configured"]),
            "challenges": total_ch,
            "tasks_running": sum(1 for t in tasks if t.get("status") == "running"),
            "tasks_total": len(tasks),
        },
    }
    _HEALTH_CACHE.update({"at": now, "data": data})
    return data




# ---------------------------------------------------------------- sandbox
#
# 参考 CTF-BTFly internal/sandbox/manager.go 的安全模型，落地到 docker CLI 子进程：
# CapDrop ALL + no-new-privileges + 内存/CPU/Pids 三限 + 单一 bind mount
# （case ↔ /workspace，workbench ↔ /solver:ro）。在 BTFly 的留白处加严：
# 默认 --network none（离线解题），服务端超时看门狗强制 docker stop。

SANDBOX_DEFAULTS = {
    "enabled": False,
    "image": "ctfbox-misc:0.1.0",
    "images": {  # 按题目类别选镜像，缺省回落 image
        "misc": "ctfbox-misc:0.1.0",
        "crypto": "ctfbox-crypto:0.1.0",
        "pwn": "ctfbox-pwn:0.1.0",
        "web": "ctfbox-web:0.1.0",
        "reverse": "ctfbox-reverse:0.1.0",
        "forensics": "ctfbox-forensics:0.1.0",
        "ai": "ctfbox-ai:0.1.0",
    },
    "network": "none",          # none（默认，离线解题）| bridge（题目需联网/走模型网关时自动切换）
    "memory": "2g",
    "cpus": "2",
    "pids": 256,
    "timeout_min": 30,
    "max_concurrent_sandbox": 4,  # R2：沙箱并发上限（0 = 不限）；多比赛并行时的主机资源保护
    "cmd": "python -u /solver/demo_solver.py /workspace/scratch/agent-prompt.txt",
    "gateway": False,           # 模型网关：容器内 Agent 经一次性令牌调用上游模型，API key 不下容器
    "upstream_base": "",        # 如 https://api.openai.com 或自建中转
    "upstream_key_env": "OPENAI_API_KEY",
}


def sandbox_concurrency_reason(running: int, cap: int) -> str | None:
    """R2：沙箱并发超限返回可操作提示，未超限返回 None。"""
    if cap <= 0:
        return None
    if running >= cap:
        return (f"沙箱并发已达上限 {cap}（运行中 {running}）：等任务结束，"
                "或调大 workbench-data/sandbox.json 的 max_concurrent_sandbox")
    return None


def sandbox_running_count() -> int:
    return sum(1 for t in TASKS._load().values()
               if t.get("status") == "running" and t.get("sandbox"))


def gateway_usage() -> dict:
    """R3：模型网关按任务聚合的用量报表（字节/请求数/活跃令牌）。"""
    by_task: dict[str, dict] = {}
    for token, v in TASKS._gateway_tokens.items():
        tid = str(v.get("task") or "?")
        entry = by_task.setdefault(tid, {"task": tid, "bytes": 0, "requests": 0,
                                         "tokens": 0, "issued": v.get("issued", 0)})
        entry["bytes"] += int(v.get("bytes", 0))
        entry["requests"] += int(v.get("requests", 0))
        entry["tokens"] += 1
        entry["issued"] = min(entry["issued"], v.get("issued", 0))
    rows = sorted(by_task.values(), key=lambda r: -r["bytes"])
    return {"tasks": rows,
            "total_bytes": sum(r["bytes"] for r in rows),
            "total_requests": sum(r["requests"] for r in rows),
            "active_tokens": len(TASKS._gateway_tokens)}


def upstream_key() -> str:
    cfg = sandbox_config()
    return os.environ.get(cfg.get("upstream_key_env") or "OPENAI_API_KEY", "")


def upstream_base() -> str:
    return (sandbox_config().get("upstream_base") or "").rstrip("/")


def sandbox_config() -> dict:
    return {**SANDBOX_DEFAULTS,
            **read_json(_core.ROOT / "workbench-data" / "sandbox.json", {})}


def sandbox_status() -> dict:
    cfg = sandbox_config()
    prefix = envb.docker_prefix()
    docker_ok, docker_ver = prefix is not None, ""
    if docker_ok:
        try:
            proc = subprocess.run([*prefix, "version", "--format", "{{.Server.Version}}"],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=20)
            docker_ver = (proc.stdout or "").strip()
        except Exception as exc:  # noqa: BLE001
            docker_ver = repr(exc)[:80]
    image_ok = False
    if docker_ok:
        try:
            proc = subprocess.run(["docker", "image", "inspect", cfg["image"], "-f", "{{.Id}}"],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=15)
            image_ok = proc.returncode == 0
        except Exception:  # noqa: BLE001
            pass
    image_states = {}
    if docker_ok:
        for cat, img in (cfg.get("images") or {}).items():
            try:
                proc = subprocess.run(["docker", "image", "inspect", img, "-f", "{{.Id}}"],
                                      capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=10)
                image_states[cat] = {"image": img, "ok": proc.returncode == 0}
            except Exception:  # noqa: BLE001
                image_states[cat] = {"image": img, "ok": False}
    return {**cfg, "docker_ok": docker_ok, "docker_ver": docker_ver, "image_ok": image_ok,
            "image_states": image_states,
            "upstream_configured": bool(upstream_base() and upstream_key()),
            "gateway_tokens": len(TASKS._gateway_tokens),
            "gateway_bytes": sum(v.get("bytes", 0) for v in TASKS._gateway_tokens.values())}


