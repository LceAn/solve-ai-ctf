#!/usr/bin/env python3
"""题目容器环境（R192）——每题一个长驻 Docker 环境，协作 AI 经网关 exec 进去解题。

模型（参考 CTF-BTFly 的 per-challenge sandbox）：
- 环境 = docker run -d 的长驻容器，挂载 case ↔ /workspace（附件进/产物出）
- AI 经 `POST /api/agent-gw/env {slug, action:"exec", cmd}` 在容器里执行命令，
  输出实时返回；工具链由按题类别的 ctfbox-* 镜像提供，AI 不再自行装环境
- 生命周期：open（建）→ exec（用）→ renew（续）→ close（删）/ TTL 到期自动回收
- 注册表落盘 workbench-data/env-registry.json，服务重启可对账（孤儿容器按名清理）
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ENV_TTL_SECONDS = 2 * 3600        # 环境默认存活 2h（比认领 45min 长，接手者续用）
EXEC_TIMEOUT = 180
EXEC_OUTPUT_MAX = 120 * 1024      # 单次返回上限 120KB
CONTAINER_PREFIX = "ctfenv-"

DOCKER_BIN = "docker"             # 测试可注入 fake docker


def _docker(argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    # DOCKER_BIN 可为带参前缀（如 '"python" fake_docker.py'），便于测试注入
    import shlex
    prefix = shlex.split(DOCKER_BIN, posix=False) if " " in DOCKER_BIN else [DOCKER_BIN]
    prefix = [str(x).strip('"') for x in prefix]   # Windows：剥引号
    return subprocess.run([*prefix, *argv], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _registry_path(root: Path) -> Path:
    return root / "workbench-data" / "env-registry.json"


def _load(root: Path) -> dict:
    try:
        return json.loads(_registry_path(root).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"envs": {}}


def _save(root: Path, data: dict) -> None:
    p = _registry_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _image_for(category: str, sandbox_cfg: dict) -> str:
    images = sandbox_cfg.get("images") or {}
    return images.get(str(category or "").lower()) or sandbox_cfg.get("image", "ctfbox-misc:0.1.0")


def status(root: Path, slug: str = "") -> dict:
    """环境状态（slug 空返回全部）。容器实际存在性以 docker ps 为准（防注册表漂移）。"""
    data = _load(root)
    envs = data.get("envs", {})
    alive = set()
    try:
        r = _docker(["ps", "--format", "{{.Names}}"])
        alive = {l.strip() for l in (r.stdout or "").splitlines() if l.strip()}
    except Exception:  # noqa: BLE001
        pass
    now = time.time()
    out = {}
    for s, e in envs.items():
        if slug and s != slug:
            continue
        exp = float(e.get("expires_ts", 0))
        out[s] = {
            "container": e.get("container"),
            "image": e.get("image"),
            "running": e.get("container") in alive,
            "started_at": e.get("started_at"),
            "remaining_s": max(0, int(exp - now)) if e.get("container") in alive else 0,
            "last_cmd": e.get("last_cmd", ""),
        }
    return out


def open_env(root: Path, comp_dir: Path, case_dir: Path, slug: str,
             category: str, network: str = "") -> dict:
    """开环境（幂等：同题已有活容器直接续期返回）。"""
    data = _load(root)
    env = data["envs"].get(slug)
    if env:
        st = status(root, slug).get(slug, {})
        if st.get("running"):
            env["expires_ts"] = time.time() + ENV_TTL_SECONDS
            data["envs"][slug] = env
            _save(root, data)
            return {"ok": True, "slug": slug, "container": env["container"],
                    "renewed": True, "expires_ts": env["expires_ts"]}
        close(root, slug)   # 注册表残留但容器已死 → 清掉重建
        data = _load(root)

    import wb_sandbox
    cfg = wb_sandbox.sandbox_config()
    image = _image_for(category, cfg)
    net = network or cfg.get("network", "none")
    container = f"{CONTAINER_PREFIX}{slug}"[:60]
    workbench_dir = Path(__file__).resolve().parent
    argv = ["run", "-d", "--name", container,
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", cfg.get("memory", "2g"), "--cpus", str(cfg.get("cpus", "2")),
            "--pids-limit", str(cfg.get("pids", 256)),
            "--network", net,
            "-v", f"{case_dir}:/workspace",
            "-v", f"{workbench_dir}:/solver:ro",
            "-w", "/workspace", image, "sleep", "infinity"]
    r = _docker(argv, timeout=120)
    if r.returncode != 0:
        return {"ok": False, "error": f"docker run 失败：{(r.stderr or r.stdout).strip()[-200:]}",
                "hint": f"镜像 {image} 是否已构建？（workbench/docker/README.md）"}
    now = time.time()
    data["envs"][slug] = {
        "container": container, "image": image, "category": category,
        "comp": comp_dir.name, "case_dir": str(case_dir),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "expires_ts": now + ENV_TTL_SECONDS,
    }
    _save(root, data)
    return {"ok": True, "slug": slug, "container": container, "image": image,
            "workspace": "/workspace", "expires_ts": now + ENV_TTL_SECONDS,
            "hint": "附件在 /workspace（读写），解题脚本与产物写 /workspace/work/ 会直接落回 case 目录"}


def exec_cmd(root: Path, slug: str, cmd: str, workdir: str = "/workspace") -> dict:
    """在题目环境里执行命令（输出带回；超时/上限保护）。"""
    if not str(cmd or "").strip():
        return {"ok": False, "error": "cmd 必填"}
    env = _load(root)["envs"].get(slug)
    if not env or not status(root, slug).get(slug, {}).get("running"):
        return {"ok": False, "error": "环境未开启（先 action:open）", "code": "E_ENV_NOT_OPEN"}
    r = _docker(["exec", "-w", workdir, env["container"], "sh", "-lc", cmd],
                timeout=EXEC_TIMEOUT)
    data = _load(root)
    if slug in data["envs"]:
        data["envs"][slug]["last_cmd"] = str(cmd)[:120]
        data["envs"][slug]["last_cmd_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _save(root, data)
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return {"ok": r.returncode == 0, "exit": r.returncode,
            "output": out[-EXEC_OUTPUT_MAX:]}


def renew(root: Path, slug: str, seconds: int = ENV_TTL_SECONDS) -> dict:
    data = _load(root)
    if slug not in data["envs"]:
        return {"ok": False, "error": "环境不存在"}
    data["envs"][slug]["expires_ts"] = time.time() + max(300, min(seconds, 12 * 3600))
    _save(root, data)
    return {"ok": True, "expires_ts": data["envs"][slug]["expires_ts"]}


def close(root: Path, slug: str) -> dict:
    data = _load(root)
    env = data["envs"].pop(slug, None)
    _save(root, data)
    if not env:
        return {"ok": True, "closed": 0}
    try:
        _docker(["rm", "-f", env["container"]], timeout=30)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "closed": 1}


def reap_expired(root: Path) -> list[str]:
    """TTL 回收（watchdog 周期调用）。"""
    data = _load(root)
    now = time.time()
    dead = [s for s, e in data.get("envs", {}).items()
            if float(e.get("expires_ts", 0)) < now]
    for s in dead:
        close(root, s)
    return dead
