#!/usr/bin/env python3
"""CTF Workbench 本地服务层（纯标准库，仅绑定 127.0.0.1）。

参考 CTF-BTFly 的本地工作台形态：题目看板、事件时间线、Flag 人工审核、
文件/日志浏览。所有写操作都不在服务内重新实现，而是以 list-argv 子进程
调用 solve-ai-ctf/scripts/ 下的既有脚本，保留其全部校验逻辑。

用法：
    python solve-ai-ctf/workbench/server.py [--port 8787] [--competition "比赛/2608 ISG"] [--open]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2]

ROOT = DEFAULT_ROOT
SCRIPTS_DIR = ROOT / "solve-ai-ctf" / "scripts"
STATIC_DIR = Path(__file__).resolve().parent / "static"
COMPETITIONS_DIR = ROOT / "比赛"

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = 1024 * 1024
EVENTS_TAIL = 300

# 枚举与 case_manager.py 保持一致（导入失败时兜底）
CASE_STATUSES = ["abandoned", "blocked", "candidate_found", "closed", "in_progress",
                 "invalid", "new", "solved", "submitted", "triaged"]
HYPOTHESIS_STATUSES = ["parked", "proposed", "rejected", "running", "supported"]
OUTCOMES = ["error", "failure", "partial", "success"]
CANDIDATE_STATUSES = ["accepted", "rejected", "submitted", "unverified", "validated"]


def configure(root: Path | None = None, scripts: Path | None = None,
              static: Path | None = None) -> None:
    """允许测试把数据根指向临时目录，而脚本/静态目录仍用真实资产。"""
    global ROOT, SCRIPTS_DIR, STATIC_DIR, COMPETITIONS_DIR
    global CASE_STATUSES, HYPOTHESIS_STATUSES, OUTCOMES, CANDIDATE_STATUSES
    if root is not None:
        ROOT = Path(root)
        COMPETITIONS_DIR = ROOT / "比赛"
    if scripts is not None:
        SCRIPTS_DIR = Path(scripts)
    if static is not None:
        STATIC_DIR = Path(static)
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import case_manager as _cm
        CASE_STATUSES = sorted(_cm.STATUSES)
        HYPOTHESIS_STATUSES = sorted(_cm.HYPOTHESIS_STATUSES)
        OUTCOMES = sorted(_cm.OUTCOMES)
        CANDIDATE_STATUSES = sorted(_cm.CANDIDATE_STATUSES)
    except Exception:
        pass  # 保留上方兜底枚举


configure()

# ---------------------------------------------------------------- utilities


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_join(base: Path, rel: str) -> Path | None:
    """把相对路径限制在 base 之内，防目录穿越。"""
    if not rel:
        return None
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate


def run_script(argv: list[str], timeout: int = 180) -> dict:
    """以 list-argv 调 scripts/ 下脚本，绝不经过 shell。"""
    argv = [str(a) for a in argv]
    try:
        proc = subprocess.run(
            [sys.executable, *argv],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(ROOT),
        )
        return {"exit": proc.returncode,
                "stdout": proc.stdout[-20000:],
                "stderr": proc.stderr[-20000:]}
    except subprocess.TimeoutExpired:
        return {"exit": 124, "stdout": "", "stderr": f"timeout after {timeout}s"}
    except Exception as exc:  # pragma: no cover
        return {"exit": 125, "stdout": "", "stderr": repr(exc)}


def looks_textual(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    return True


# ---------------------------------------------------------------- data view


def list_competitions() -> list[dict]:
    items = []
    if COMPETITIONS_DIR.is_dir():
        for d in sorted(COMPETITIONS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            cfg = read_json(d / "competition.json", {})
            items.append({
                "dir": d.name,
                "name": cfg.get("name") or d.name,
                "configured": bool(cfg),
                "challenges": len(cfg.get("challenges", [])) if cfg else 0,
            })
    return items


def resolve_competition(dir_name: str) -> Path | None:
    if not dir_name:
        return None
    return safe_join(COMPETITIONS_DIR, dir_name)


def case_summary(comp_dir: Path, case_dir_rel: str) -> dict:
    case_dir = safe_join(comp_dir, case_dir_rel)
    if not case_dir:
        return {}
    case = read_json(case_dir / "case.json", None)
    if not isinstance(case, dict):
        return {"exists": False, "case_dir": case_dir_rel}
    candidates = case.get("candidates", [])
    events = case.get("events", [])
    last = events[-1] if events else None
    return {
        "exists": True,
        "case_dir": case_dir_rel,
        "status": case.get("status"),
        "blocked_on": case.get("blocked_on"),
        "hypotheses": len(case.get("hypotheses", [])),
        "attempts": len(case.get("attempts", [])),
        "findings": len(case.get("evidence", [])),
        "candidates": [
            {"id": c.get("id"), "status": c.get("status"), "value": c.get("value"),
             "source": c.get("source"), "note": c.get("note")}
            for c in candidates
        ],
        "updated_at": case.get("updated_at"),
        "last_event": {"kind": last.get("kind"), "time": last.get("time")} if last else None,
    }


def file_tree(base: Path, limit: int = 400) -> list[dict]:
    rows = []
    if not base.is_dir():
        return rows
    stack = [(base, "")]
    while stack and len(rows) < limit:
        current, rel = stack.pop(0)
        try:
            children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            continue
        for child in children:
            name = f"{rel}/{child.name}" if rel else child.name
            if child.name.startswith(".") and child.is_file():
                continue
            if child.is_dir():
                if child.name in {".venv", "venv", "__pycache__", "node_modules"}:
                    continue
                rows.append({"path": name, "type": "dir"})
                stack.append((child, name))
            else:
                try:
                    size = child.stat().st_size
                except OSError:
                    size = -1
                rows.append({"path": name, "type": "file", "size": size})
    return rows


def competition_view(comp_dir: Path) -> dict:
    cfg = read_json(comp_dir / "competition.json", None)
    events_path = comp_dir / "events.jsonl"
    events = []
    if events_path.exists():
        try:
            lines = events_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-EVENTS_TAIL:]:
                if line.strip():
                    events.append(read_json_line(line))
        except OSError:
            pass

    challenges = []
    if isinstance(cfg, dict):
        for ch in cfg.get("challenges", []):
            entry = dict(ch)
            entry["case"] = case_summary(comp_dir, ch.get("case_dir", f"cases/{ch.get('slug', '')}"))
            challenges.append(entry)

    docs = []
    docs_dir = comp_dir / "docs"
    if docs_dir.is_dir():
        for p in sorted(docs_dir.glob("*.md")):
            try:
                docs.append({"name": p.name, "size": p.stat().st_size})
            except OSError:
                pass

    artifacts = []
    art_dir = comp_dir / "artifacts"
    if art_dir.is_dir():
        for p in sorted(art_dir.iterdir()):
            if p.is_file():
                artifacts.append({"name": p.name, "size": p.stat().st_size})

    return {
        "dir": comp_dir.name,
        "name": (cfg or {}).get("name") or comp_dir.name,
        "configured": cfg is not None,
        "config": cfg,
        "challenges": challenges,
        "events": events,
        "docs": docs,
        "artifacts": artifacts,
        "enums": {
            "statuses": CASE_STATUSES,
            "hypothesis_statuses": HYPOTHESIS_STATUSES,
            "outcomes": OUTCOMES,
            "candidate_statuses": CANDIDATE_STATUSES,
        },
    }


def read_json_line(line: str):
    try:
        return json.loads(line)
    except Exception:
        return {"time": None, "kind": "unparsable", "detail": {"raw": line[:300]}}


# ---------------------------------------------------------------- actions
#
# 每个动作把已校验参数拼成 argv，交给 scripts/ 下既有脚本执行。
# 返回统一带 exit/stdout/stderr，并在写操作后回读最新状态。


def _require(params: dict, key: str) -> str:
    value = params.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError(f"missing param: {key}")
    return str(value)


def _optional(params: dict, key: str, flag: str, argv: list[str]) -> None:
    value = params.get(key)
    if value is not None and str(value).strip() != "":
        argv += [flag, str(value)]


def _float_opt(params: dict, key: str, flag: str, argv: list[str]) -> None:
    value = params.get(key)
    if value not in (None, ""):
        float(value)  # 校验
        argv += [flag, str(value)]


def comp_dir_of(params: dict) -> Path:
    comp = resolve_competition(_require(params, "dir"))
    if not comp or not comp.is_dir():
        raise ValueError("unknown competition dir")
    return comp


def case_dir_of(params: dict) -> tuple[Path, Path]:
    comp = comp_dir_of(params)
    case = safe_join(comp, _require(params, "case_dir"))
    if not case or not (case / "case.json").exists():
        raise ValueError("case.json not found")
    return comp, case


ACTIONS: dict[str, object] = {}


def action(name):
    def register(fn):
        ACTIONS[name] = fn
        return fn
    return register


@action("challenge.register")
def act_challenge_register(params: dict) -> dict:
    comp = comp_dir_of(params)
    argv = [SCRIPTS_DIR / "competition.py", "add-challenge", comp,
            "--name", _require(params, "name"),
            "--category", _require(params, "category")]
    _optional(params, "slug", "--slug", argv)
    _optional(params, "challenge_id", "--challenge-id", argv)
    _optional(params, "difficulty", "--difficulty", argv)
    _optional(params, "description", "--description", argv)
    _optional(params, "scope", "--scope", argv)
    _float_opt(params, "points", "--points", argv)
    _float_opt(params, "p_solve", "--p-solve", argv)
    _float_opt(params, "expected_minutes", "--expected-minutes", argv)
    for pattern in params.get("flag_patterns") or []:
        argv += ["--flag-pattern", str(pattern)]
    return run_script(argv)


@action("competition.prioritize")
def act_prioritize(params: dict) -> dict:
    return run_script([SCRIPTS_DIR / "competition.py", "prioritize", comp_dir_of(params)])


@action("competition.dashboard")
def act_dashboard(params: dict) -> dict:
    return run_script([SCRIPTS_DIR / "competition.py", "dashboard", comp_dir_of(params)])


@action("competition.event")
def act_event(params: dict) -> dict:
    comp = comp_dir_of(params)
    argv = [SCRIPTS_DIR / "competition.py", "event", comp, _require(params, "kind")]
    # competition.py event 的 --detail 只接受 JSON，这里把纯文本包一层
    if params.get("detail"):
        argv += ["--detail", json.dumps({"text": str(params["detail"])}, ensure_ascii=False)]
    return run_script(argv)


@action("case.status")
def act_case_status(params: dict) -> dict:
    comp, case = case_dir_of(params)
    status = _require(params, "status")
    if status not in CASE_STATUSES:
        raise ValueError(f"invalid status: {status}")
    argv = [SCRIPTS_DIR / "case_manager.py", "status", case, status]
    _optional(params, "reason", "--reason", argv)
    _optional(params, "blocked_on", "--blocked-on", argv)
    for when in params.get("unblock_when") or []:
        argv += ["--unblock-when", str(when)]
    result = run_script(argv)
    result["case"] = case_summary(comp, str(case.relative_to(comp)))
    return result


@action("case.hypothesis")
def act_hypothesis(params: dict) -> dict:
    comp, case = case_dir_of(params)
    argv = [SCRIPTS_DIR / "case_manager.py", "hypothesis", case,
            "--title", _require(params, "title"),
            "--rationale", _require(params, "rationale"),
            "--expected", _require(params, "expected")]
    _optional(params, "stop", "--stop", argv)
    _float_opt(params, "minutes", "--minutes", argv)
    _float_opt(params, "priority", "--priority", argv)
    return run_script(argv)


@action("case.finding")
def act_finding(params: dict) -> dict:
    comp, case = case_dir_of(params)
    argv = [SCRIPTS_DIR / "case_manager.py", "finding", case,
            "--claim", _require(params, "claim"),
            "--source", _require(params, "source")]
    _optional(params, "artifact", "--artifact", argv)
    _float_opt(params, "confidence", "--confidence", argv)
    if params.get("kind"):
        argv += ["--kind", str(params["kind"])]
    if params.get("phase"):
        argv += ["--phase", str(params["phase"])]
    return run_script(argv)


@action("case.attempt")
def act_attempt(params: dict) -> dict:
    comp, case = case_dir_of(params)
    argv = [SCRIPTS_DIR / "case_manager.py", "attempt", case,
            "--hypothesis", _require(params, "hypothesis"),
            "--action", _require(params, "action"),
            "--result", _require(params, "result"),
            "--outcome", _require(params, "outcome")]
    _optional(params, "evidence", "--evidence", argv)
    _optional(params, "duration", "--duration", argv)
    if params.get("hypothesis_status"):
        if params["hypothesis_status"] not in HYPOTHESIS_STATUSES:
            raise ValueError("invalid hypothesis_status")
        argv += ["--hypothesis-status", str(params["hypothesis_status"])]
    return run_script(argv)


@action("case.scan_flags")
def act_scan_flags(params: dict) -> dict:
    comp, case = case_dir_of(params)
    root = safe_join(comp, _require(params, "search_root"))
    if not root or not root.exists():
        raise ValueError("search_root not found inside competition dir")
    argv = [SCRIPTS_DIR / "case_manager.py", "scan-flags", case, root]
    if params.get("store"):
        argv += ["--store"]
    return run_script(argv, timeout=300)


@action("case.candidate")
def act_candidate(params: dict) -> dict:
    comp, case = case_dir_of(params)
    status = _require(params, "candidate_status")
    if status not in CANDIDATE_STATUSES:
        raise ValueError(f"invalid candidate status: {status}")
    argv = [SCRIPTS_DIR / "case_manager.py", "candidate", case,
            _require(params, "candidate_id"), status]
    _optional(params, "note", "--note", argv)
    result = run_script(argv)
    result["case"] = case_summary(comp, str(case.relative_to(comp)))
    return result


@action("case.validate")
def act_validate(params: dict) -> dict:
    comp, case = case_dir_of(params)
    result = run_script([SCRIPTS_DIR / "case_manager.py", "validate", case])
    result["case"] = case_summary(comp, str(case.relative_to(comp)))
    return result


@action("case.triage")
def act_triage(params: dict) -> dict:
    comp, case = case_dir_of(params)
    target = safe_join(comp, _require(params, "target"))
    if not target or not target.exists():
        raise ValueError("target not found inside competition dir")
    return run_script([SCRIPTS_DIR / "triage.py", target,
                       "--json-out", case / "triage.json",
                       "--markdown-out", case / "triage.md"], timeout=300)


@action("case.summary")
def act_summary(params: dict) -> dict:
    comp, case = case_dir_of(params)
    return run_script([SCRIPTS_DIR / "case_manager.py", "summary", case,
                       "--output", case / "summary.md"])


@action("submit.dryrun")
def act_submit_dryrun(params: dict) -> dict:
    return _submit(params, live=False)


@action("submit.live")
def act_submit_live(params: dict) -> dict:
    return _submit(params, live=True)


def _submit(params: dict, live: bool) -> dict:
    comp = comp_dir_of(params)
    if live and params.get("confirm") is not True:
        raise ValueError("live submission requires confirm=true")
    argv = [SCRIPTS_DIR / "submitter.py", "submit", comp,
            "--challenge", _require(params, "challenge"),
            "--flag", _require(params, "flag")]
    _optional(params, "candidate", "--candidate", argv)
    _optional(params, "source", "--source", argv)
    _optional(params, "note", "--note", argv)
    if params.get("allow_unvalidated"):
        argv += ["--allow-unvalidated"]
    if live:
        argv += ["--live", "--update-case"]
    return run_script(argv, timeout=120)


# ---------------------------------------------------------------- tasks
#
# 参考 CTF-BTFly 的任务生命周期：每题可派发一个求解命令（Agent/脚本），
# 输出落盘到 case 目录并支持实时 tail 与停止。命令模板可配置
# （--agent-cmd 或环境变量 WB_AGENT_CMD），占位符 {prompt_file} {case_dir}。


class TaskManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()  # 可重入：reconcile 持锁时会调 revoke_task_tokens
        self._procs: dict[str, subprocess.Popen] = {}
        self._gateway_tokens: dict[str, dict] = {}
        self._counter = 0
        self.agent_cmd = os.environ.get("WB_AGENT_CMD", "")
        try:  # 重启后延续任务编号，避免覆盖历史记录
            for tid in self._load():
                if tid.startswith("T") and tid[1:].isdigit():
                    self._counter = max(self._counter, int(tid[1:]))
        except Exception:
            pass

    def _store(self) -> Path:
        d = ROOT / "workbench-data"
        d.mkdir(exist_ok=True)
        return d / "tasks.json"

    def _load(self) -> dict[str, dict]:
        return read_json(self._store(), {})

    def _save(self, tasks: dict[str, dict]) -> None:
        try:
            self._store().write_text(json.dumps(tasks, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
        except OSError:
            pass

    def register_token(self, token: str, tid: str) -> None:
        with self._lock:
            self._gateway_tokens[token] = {"task": tid, "bytes": 0, "requests": 0,
                                           "issued": time.time()}

    def revoke_task_tokens(self, tid: str) -> None:
        with self._lock:
            for token in [t for t, v in self._gateway_tokens.items() if v["task"] == tid]:
                self._gateway_tokens.pop(token, None)

    def reconcile(self) -> None:
        """把已结束进程的状态写回；服务重启后标记 lost 任务。"""
        with self._lock:
            tasks = self._load()
            changed = False
            for tid, t in tasks.items():
                proc = self._procs.get(tid)
                if proc is not None and proc.poll() is not None:
                    t["status"] = "done" if proc.returncode == 0 else "failed"
                    t["exit"] = proc.returncode
                    t["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    self._procs.pop(tid, None)
                    self.revoke_task_tokens(tid)
                    changed = True
                elif proc is None and t.get("status") == "running":
                    t["status"] = "lost"
                    self.revoke_task_tokens(tid)
                    changed = True
            if changed:
                self._save(tasks)

    def start(self, comp_dir: Path, slug: str, case_dir_rel: str, prompt: str,
              cmd_template: str | None = None, agent: str = "") -> dict:
        template = (cmd_template or self.agent_cmd or "").strip()
        if not template:
            raise ValueError("未配置求解命令模板：启动 server 时加 --agent-cmd 或设置 WB_AGENT_CMD")
        case_dir = safe_join(comp_dir, case_dir_rel)
        if not case_dir:
            raise ValueError("bad case dir")
        scratch = case_dir / "scratch"
        scratch.mkdir(exist_ok=True)
        prompt_file = scratch / "agent-prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        with self._lock:
            self._counter += 1
            tid = f"T{self._counter:04d}"
        log_rel = f"{case_dir_rel}/scratch/{tid}-agent-run.log"
        log_path = safe_join(comp_dir, log_rel)
        if not log_path:
            raise ValueError("bad log path")
        def q(p: Path) -> str:
            return '"' + str(p) + '"'

        command = (template.replace("{prompt_file}", q(prompt_file))
                           .replace("{case_dir}", q(case_dir))
                           .replace("{solver_dir}", q(Path(__file__).resolve().parent)))
        with self._lock:
            tasks = self._load()
            tasks[tid] = {
                "id": tid, "dir": comp_dir.name, "slug": slug, "case_dir": case_dir_rel,
                "agent": (agent or "solver").strip() or "solver",
                "command": command, "log": log_rel, "status": "running",
                "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self._save(tasks)
        try:
            creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            proc = subprocess.Popen(command, shell=True, cwd=str(case_dir),
                                    stdout=open(log_path, "wb"),
                                    stderr=subprocess.STDOUT,
                                    creationflags=creation)
        except Exception as exc:
            with self._lock:
                tasks = self._load()
                tasks[tid].update({"status": "failed", "error": repr(exc)})
                self._save(tasks)
            raise ValueError(f"spawn failed: {exc}")
        with self._lock:
            self._procs[tid] = proc
        return self.get(tid)

    def run_custom(self, dir_name: str, slug_label: str, agent: str,
                   command: str, cwd: Path, container: str = "") -> dict:
        """派发内建代理/沙箱任务：与 solver 任务同一生命周期管理。"""
        with self._lock:
            self._counter += 1
            tid = f"T{self._counter:04d}"
        comp = resolve_competition(dir_name)
        (comp / "scratch").mkdir(exist_ok=True)
        log_rel = f"scratch/{slug_label}-{tid}.log"
        log_path = safe_join(comp, log_rel)
        with self._lock:
            tasks = self._load()
            tasks[tid] = {"id": tid, "dir": dir_name, "slug": slug_label, "case_dir": "",
                          "agent": agent, "command": command, "log": log_rel,
                          "container": container, "sandbox": bool(container),
                          "status": "running", "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self._save(tasks)
        try:
            creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            proc = subprocess.Popen(command, shell=True, cwd=str(cwd),
                                    stdout=open(log_path, "wb"),
                                    stderr=subprocess.STDOUT, creationflags=creation)
        except Exception as exc:
            with self._lock:
                tasks = self._load()
                tasks[tid].update({"status": "failed", "error": repr(exc)})
                self._save(tasks)
            raise ValueError(f"spawn failed: {exc}")
        with self._lock:
            self._procs[tid] = proc
        return self.get(tid)

    def enforce_timeouts(self, timeout_min: int) -> None:
        """看门狗：沙箱任务超时强制 docker stop。"""
        with self._lock:
            tasks = self._load()
            for tid, t in tasks.items():
                if t.get("status") != "running" or not t.get("container"):
                    continue
                started = t.get("started", "")
                try:
                    ts = time.mktime(time.strptime(started[:19], "%Y-%m-%dT%H:%M:%S"))
                except (ValueError, TypeError):
                    continue
                if time.time() - ts > timeout_min * 60:
                    docker_stop_container(t["container"])
                    t["status"] = "failed"
                    t["error"] = f"sandbox timeout after {timeout_min} min"
                    t["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._save(tasks)

    def get(self, tid: str) -> dict:
        self.reconcile()
        return self._load().get(tid, {})

    def list(self) -> list[dict]:
        self.reconcile()
        tasks = self._load()
        return sorted(tasks.values(), key=lambda t: t.get("started", ""), reverse=True)

    def tail(self, tid: str, max_bytes: int = 65536) -> dict:
        task = self.get(tid)
        if not task:
            raise ValueError("unknown task")
        text = ""
        log = task.get("log", "")
        comp = resolve_competition(task.get("dir", ""))
        path = safe_join(comp or Path(), log) if log else None
        if path and path.exists():
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - max_bytes))
                text = f.read().decode("utf-8", errors="replace")
        return {"task": task, "output": text[-max_bytes:]}

    def stop(self, tid: str) -> dict:
        with self._lock:
            proc = self._procs.get(tid)
        if proc is None:
            raise ValueError("task not running here")
        task = self.get(tid)
        if task.get("container"):
            docker_stop_container(task["container"])
            return {"stopped": True, "how": "docker stop " + task["container"]}
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
        except OSError as exc:
            proc.kill()
            return {"stopped": False, "error": repr(exc)}
        return {"stopped": True}


TASKS = TaskManager()


def _writeup_case(params: dict) -> dict:
    comp, case = case_dir_of(params)
    case_data = read_json(case / "case.json", {})
    ch = case_data.get("challenge", {})
    cands = case_data.get("candidates", [])
    final = [c for c in cands if c.get("status") in ("validated", "submitted", "accepted")]
    lines = [
        f"# {ch.get('name', case.name)} Writeup（草稿）", "",
        f"- **类别**：{ch.get('category', '?')}　**分值**：{ch.get('points', '?')}　**难度**：{ch.get('difficulty', '?')}",
        f"- **case**：`{case}`",
    ]
    if ch.get("description"):
        lines += ["", "## 题面", "", "> " + str(ch["description"]).replace("\n", "\n> ")]
    if final:
        lines += ["", "## Flag", "", "```text", *[c.get("value", "") for c in final], "```"]
    hyps = case_data.get("hypotheses", [])
    if hyps:
        lines += ["", "## 假设阶梯回顾", "",
                  "| ID | 假设 | 状态 | 预期信号 |", "|---|---|---|---|"]
        lines += [f"| {h.get('id')} | {h.get('title')} | {h.get('status')} | {h.get('expected')} |"
                  for h in hyps]
    atts = case_data.get("attempts", [])
    if atts:
        key = [a for a in atts if a.get("outcome") in ("success", "partial")] or atts[-3:]
        lines += ["", "## 关键尝试", ""]
        lines += [f"- **[{a.get('outcome')}]** {a.get('action')} → {a.get('result')}"
                  for a in key]
    evs = case_data.get("evidence", [])
    if evs:
        lines += ["", "## 证据清单", ""]
        lines += [f"- {e.get('claim')}（来源：{e.get('source')}）" for e in evs]
    events = case_data.get("events", [])
    if events:
        lines += ["", "## 时间线", ""]
        lines += [f"- `{e.get('time', '')[:19]}` {e.get('kind')}" for e in events]
    lines += ["", "---", "", "> 本文件由 workbench 从 case.json 自动生成草稿。",
              "> 请人工补充：根因分析、最小复现脚本路径、可复用的知识点。",
              "> 复盘完成后把要点经 kb_search 可检索的标签写入 docs/。"]
    target = case / ("WRITEUP.md" if not (case / "WRITEUP.md").exists()
                     else "WRITEUP-draft.md")
    target.write_text("\n".join(lines), encoding="utf-8")
    return {"exit": 0, "stdout": f"written: {target.name}", "stderr": ""}


@action("selftest.run")
def act_selftest(params: dict) -> dict:
    _HEALTH_CACHE["at"] = 0.0
    return run_script([SCRIPTS_DIR / "self_test.py"], timeout=120)


ACTIONS["case.writeup"] = _writeup_case


# ---------------------------------------------------------------- prompt


def build_prompt(comp_dir: Path, slug: str, style: str = "continue") -> str:
    view = competition_view(comp_dir)
    entry = next((c for c in view["challenges"] if c.get("slug") == slug), None)
    if not entry:
        raise ValueError("unknown slug")
    case_rel = entry.get("case_dir") or f"cases/{slug}"
    case_dir = safe_join(comp_dir, case_rel)
    case = read_json(case_dir / "case.json", {}) if case_dir else {}

    base = [
        "你是本次 CTF 的解题 Agent，严格按照 solve-ai-ctf/SKILL.md 的流程执行：",
        "分诊 → 假设 → 有界执行 → 验证 → 提交（默认 dry-run）→ 复盘。",
        "所有状态变更用 case_manager.py 登记到本 case，不要绕过审计记录。",
        "",
        f"# 题目：{entry.get('name', slug)}（slug={slug}）",
        f"- 类别：{entry.get('category', '?')}  分值：{entry.get('points', '?')}  难度：{entry.get('difficulty', '?')}",
        f"- case 目录：比赛/{comp_dir.name}/{case_rel}",
    ]
    desc = entry.get("description") or (case.get("challenge") or {}).get("description")
    if desc:
        base += ["- 题面：", "  > " + str(desc).replace("\n", "\n  > ")]
    for pattern in entry.get("flag_pattern") or (case.get("challenge") or {}).get("flag_patterns") or []:
        base.append(f"- flag 格式：`{pattern}`")

    sections = []
    triage = read_json((case_dir or comp_dir) / "triage.json", None)
    if triage:
        rows = ["## 分诊摘要（triage.json）"]
        cls = triage.get("classification")
        if cls:
            rows.append(f"- 类别判定：{json.dumps(cls, ensure_ascii=False)[:200]}")
        files = triage.get("files") or []
        for f in files[:12]:
            rows.append(f"- {f.get('path', '?')} ({f.get('size', '?')}B, {f.get('suffix') or '?'}, "
                        f"sha256={str(f.get('sha256'))[:12]})")
        if len(files) > 12:
            rows.append(f"- …共 {len(files)} 项")
        for w in triage.get("warnings") or []:
            rows.append(f"- ⚠ {w}")
        sections.append(rows)

    hyps = case.get("hypotheses") or []
    if hyps:
        rows = ["## 当前假设阶梯"]
        for h in hyps:
            rows.append(f"- [{h.get('status', '?')}] {h.get('title', '')} "
                        f"(H{h.get('id', '?')}, 优先级 {h.get('priority', '?')})")
        sections.append(rows)
    atts = case.get("attempts") or []
    if atts:
        rows = ["## 最近尝试"]
        for a in atts[-6:]:
            rows.append(f"- [{a.get('outcome', '?')}] H{a.get('hypothesis', '?')}: "
                        f"{a.get('action', '')} → {a.get('result', '')}")
        sections.append(rows)
    cands = case.get("candidates") or []
    if cands:
        rows = ["## Flag 候选"]
        for c in cands:
            rows.append(f"- {c.get('id')}: [{c.get('status')}] {c.get('value')}")
        sections.append(rows)

    tails = {
        "continue": [
            "## 本轮要求",
            "1. 若尚未分诊：先运行 triage.py 对附件做静态分诊，绝不直接执行未知文件。",
            "2. 产出 3–7 条假设并登记，再开始有界执行；每个 attempt 记录结果与假设状态转移。",
            "3. 找到 flag 后用 scan-flags/candidate 登记候选，validate 校验，提交前先 dry-run。",
            "4. 完成后写 WP 到 docs/，并用 case_manager.py summary 生成复盘。",
        ],
        "fresh": [
            "## 本轮要求（开局模式：忽略历史尝试，从头接管）",
            "1. 重新核对分诊结论；对附件建立你自己的清单与怀疑点。",
            "2. 全新登记 3–7 条假设（标注为不同思路，不重复已 rejected 的方向）。",
            "3. 按优先级串行推进，每步登记 attempt；卡住即 park 并换下一假设。",
        ],
        "submit": [
            "## 本轮要求（验证与提交模式）",
            "1. 只做验证：对每个候选 flag 复现推导/本地校验，不合格的标记 rejected。",
            "2. 合格候选推进到 validated，随后调用 submitter.py dry-run 预览请求。",
            "3. 把 dry-run 输出原样贴回，由人工决定是否 --live；你不执行真实提交。",
        ],
        "review": [
            "## 本轮要求（复盘模式）",
            "1. 汇总本 case 全部假设/尝试/证据，区分有效路径与死路。",
            "2. 产出：根因分析、最小复现脚本路径、可复用知识点（写入 docs/）。",
            "3. 调用 case_manager.py summary 生成结构化复盘；给 kb_search 提炼 3–5 个检索标签。",
        ],
    }
    lines = base[:]
    for sec in sections:
        lines += [""] + sec
    lines += [""]
    lines += tails.get(style, tails["continue"])
    return "\n".join(lines)


# ---------------------------------------------------------------- kb search

KB_LINE = re.compile(r"^([A-Za-z0-9_\-\.]+\.md):(\d+) score=([\d\.]+)$")


def kb_search(query: str, category: str | None, top: int) -> list[dict]:
    argv = [SCRIPTS_DIR / "kb_search.py", query, "--top", str(max(1, min(top, 30)))]
    if category:
        argv += ["--category", category]
    result = run_script(argv, timeout=60)
    hits, current = [], None
    for line in (result["stdout"] or "").splitlines():
        m = KB_LINE.match(line.strip())
        if m:
            current = {"file": m.group(1), "line": int(m.group(2)),
                       "score": float(m.group(3)), "context": []}
            hits.append(current)
        elif current is not None and line.startswith("  "):
            current["context"].append(line[2:])
    return {"hits": hits, "exit": result["exit"]}


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
                                  encoding="utf-8", errors="replace", timeout=20, cwd=str(ROOT))
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
        "server": {"ok": True, "detail": f"workbench @ 127.0.0.1:{_port}"},
        "scripts": {"ok": True, "detail": f"{SCRIPTS_DIR} ({len(list(SCRIPTS_DIR.glob('*.py')))} scripts)"},
        "selftest": selftest,
        "docker": docker,
        "agent_cmd": {"ok": bool(TASKS.agent_cmd),
                      "detail": TASKS.agent_cmd or "未配置 --agent-cmd / WB_AGENT_CMD"},
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


_port = 8787
_auth_token = ""


def _client_token(headers, qs) -> str:
    auth = headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (qs.get("token") or "").strip()


def _authorized(headers, qs) -> bool:
    """配置了 --token 时，所有 /api 请求必须携带令牌（多网卡共享下的协作门槛）。"""
    if not _auth_token:
        return True
    import hmac
    return hmac.compare_digest(_client_token(headers, qs), _auth_token)


def local_urls(port: int) -> list[str]:
    """枚举本机所有 IPv4（含局域网 / Tailscale 100.x），生成可共享的访问地址。"""
    urls = [f"http://127.0.0.1:{port}/"]
    try:
        import socket
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip != "127.0.0.1" and not ip.startswith("169.254.") and f"http://{ip}:{port}/" not in urls:
                urls.append(f"http://{ip}:{port}/")
    except OSError:
        pass
    return urls


# ---------------------------------------------------------------- board


def board_data(qs: dict) -> dict:
    """AI 看板：泳道 = 题目事件 + 求解任务跨度，时间窗可调。"""
    comp = resolve_competition(qs.get("dir", ""))
    if not comp or not comp.is_dir():
        raise ValueError("unknown competition")
    hours = max(1, min(int(qs.get("hours", 24)), 24 * 30))
    cutoff = time.time() - hours * 3600

    def parse_ts(value):
        try:
            return time.mktime(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            return None

    lanes = []
    view = competition_view(comp)
    for ch in view["challenges"]:
        case_rel = ch.get("case_dir") or f"cases/{ch.get('slug', '')}"
        case_dir = safe_join(comp, case_rel)
        events = []
        if case_dir:
            case = read_json(case_dir / "case.json", {})
            for e in case.get("events", []):
                ts = parse_ts(e.get("time"))
                if ts and ts >= cutoff:
                    events.append({"ts": ts, "kind": e.get("kind"), "detail": e.get("detail")})
        if events:
            lanes.append({"kind": "challenge", "id": ch.get("slug"),
                          "label": ch.get("name", ch.get("slug")),
                          "status": ch.get("case", {}).get("status"), "events": events})
    now = time.time()
    for t in TASKS.list():
        if t.get("dir") != comp.name:
            continue
        start = parse_ts(t.get("started"))
        if start is None or start < cutoff:
            continue
        end = parse_ts(t.get("finished")) or (now if t.get("status") == "running" else None)
        lanes.append({"kind": "task", "id": t.get("id"),
                      "label": f"{t.get('agent') or 'solver'} · {t.get('slug')}",
                      "status": t.get("status"), "agent": t.get("agent"),
                      "start": start, "end": end})
    return {"lanes": lanes, "window_hours": hours, "now": now}


API_HELP = {
    "description": "CTF Workbench HTTP API（多 Agent 协作接口；配置 --token 后需带 Authorization: Bearer <token>）",
    "read": {
        "GET /api/competitions": "列出 比赛/ 下所有比赛",
        "GET /api/competition?dir=": "比赛视图（题目/case 摘要/事件/文档/枚举）",
        "GET /api/case?dir=&case_dir=": "case.json 全量 + 工作区文件树",
        "GET /api/events?dir=&limit=": "比赛事件尾部",
        "GET /api/board?dir=&hours=": "AI 看板泳道数据（题目事件 + 任务跨度）",
        "GET /api/tree?dir=&path=": "比赛目录内只读文件树",
        "GET /api/file?dir=&path=": "只读文本文件内容（2MB 上限）",
        "GET /api/kb?q=&category=": "知识库检索",
        "GET /api/prompt?dir=&slug=&style=": "解题提示词（style=continue|fresh|submit|review）",
        "GET /api/tasks 与 /api/task/tail?id=": "任务列表与实时输出",
        "GET /api/health/detail": "执行链路健康",
    },
    "write": {
        "POST /api/action": "白名单动作（challenge.register / case.status / case.hypothesis / "
                            "case.finding / case.attempt / case.scan_flags / case.candidate / "
                            "case.validate / case.triage / case.writeup / case.summary / "
                            "submit.dryrun / submit.live / competition.prioritize / "
                            "competition.dashboard / competition.event / selftest.run）",
        "POST /api/task/start": "派发求解任务 {dir, slug, agent?, cmd_template?}",
        "POST /api/task/stop": "停止任务 {id}",
    },
    "agent_workflow": "Agent 协作建议：GET /api/prompt 取题面与上下文 → 用 case.attempt/hypothesis/findings "
                      "登记过程 → flag 用 case.candidate 推进 → 提交必须 submit.dryrun 预览后由人工 submit.live。",
}


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
    },
    "network": "none",          # none（默认，离线解题）| bridge（题目需联网/走模型网关时自动切换）
    "memory": "2g",
    "cpus": "2",
    "pids": 256,
    "timeout_min": 30,
    "cmd": "python -u /solver/demo_solver.py /workspace/scratch/agent-prompt.txt",
    "gateway": False,           # 模型网关：容器内 Agent 经一次性令牌调用上游模型，API key 不下容器
    "upstream_base": "",        # 如 https://api.openai.com 或自建中转
    "upstream_key_env": "OPENAI_API_KEY",
}


def upstream_key() -> str:
    cfg = sandbox_config()
    return os.environ.get(cfg.get("upstream_key_env") or "OPENAI_API_KEY", "")


def upstream_base() -> str:
    return (sandbox_config().get("upstream_base") or "").rstrip("/")


def sandbox_config() -> dict:
    return {**SANDBOX_DEFAULTS,
            **read_json(ROOT / "workbench-data" / "sandbox.json", {})}


def sandbox_status() -> dict:
    cfg = sandbox_config()
    docker_ok, docker_ver = False, ""
    try:
        proc = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=15)
        docker_ok = proc.returncode == 0
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


def docker_stop_container(name: str) -> None:
    try:
        subprocess.run(["docker", "stop", "-t", "5", name],
                       capture_output=True, text=True, timeout=40)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "CTFWorkbench/1.0"

    # -- plumbing
    def log_message(self, fmt, *args):  # 静默默认日志，避免刷屏
        pass

    def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload, status: int = 200):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _error(self, status: int, message: str):
        self._json({"error": message}, status)

    def _static(self, rel: str) -> None:
        target = safe_join(STATIC_DIR, rel)
        if not target or not target.is_file():
            self._error(404, "not found")
            return
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon"}.get(target.suffix.lower(),
                                                                  "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    # -- GET
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        try:
            if route == "/" or route.startswith("/static/"):
                if route == "/":
                    return self._static("index.html")
                return self._static(route[len("/static/"):])
            if route.startswith("/api/") and not _authorized(self.headers, qs):
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("WWW-Authenticate", "Bearer")
                body = json.dumps({"error": "需要访问令牌（--token）"}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if route == "/api/help":
                return self._json(API_HELP)
            if route == "/api/competitions":
                return self._json({"competitions": list_competitions()})
            if route == "/api/competition":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                return self._json(competition_view(comp))
            if route == "/api/case":
                comp = resolve_competition(qs.get("dir", ""))
                case_dir = safe_join(comp or Path(), qs.get("case_dir", ""))
                if not case_dir or not (case_dir / "case.json").exists():
                    return self._error(404, "case.json not found")
                payload = read_json(case_dir / "case.json", {})
                payload["_tree"] = file_tree(case_dir)
                return self._json(payload)
            if route == "/api/events":
                comp = resolve_competition(qs.get("dir", ""))
                events_path = (comp or Path()) / "events.jsonl"
                events = []
                if events_path.exists():
                    lines = events_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    events = [read_json_line(l) for l in lines[-int(qs.get("limit", EVENTS_TAIL)):]
                              if l.strip()]
                return self._json({"events": events})
            if route == "/api/tree":
                comp = resolve_competition(qs.get("dir", ""))
                base = safe_join(comp or Path(), qs.get("path") or ".")
                if not base or not base.is_dir():
                    return self._error(404, "dir not found")
                return self._json({"tree": file_tree(base)})
            if route == "/api/file":
                return self.api_file(qs)
            if route == "/api/tasks":
                return self._json({"tasks": TASKS.list(),
                                   "agent_cmd": bool(TASKS.agent_cmd)})
            if route == "/api/task/tail":
                return self._json(TASKS.tail(qs.get("id", "")))
            if route == "/api/health/detail":
                return self._json(health_detail())
            if route == "/api/events/stream":
                return self.events_stream(qs)
            if route == "/api/sandbox":
                return self._json(sandbox_status())
            if route == "/api/autosubmit":
                # 抢一血场景：自动提交默认开启（限额与 submitter 去重保护仍在）
                cfg = read_json(ROOT / "workbench-data" / "autosubmit.json", {})
                entry = {"enabled": True, "max_live": 3}
                entry.update(cfg.get(qs.get("dir", "")) or {})
                return self._json({"enabled": bool(entry.get("enabled")),
                                   "max_live": int(entry.get("max_live", 3))})
            if route == "/api/submissions":
                comp = resolve_competition(qs.get("dir", ""))
                path = (comp or Path()) / "submissions.jsonl"
                lines = []
                if path.exists():
                    lines = [l for l in path.read_text(encoding="utf-8",
                            errors="replace").splitlines() if l.strip()]
                after = max(0, int(qs.get("after", 0)))
                entries = [read_json_line(l) for l in lines[after:]]
                return self._json({"total": len(lines), "entries": entries})
            if route.startswith("/gw/"):
                return self.gateway(route)
            if route == "/api/board":
                return self._json(board_data(qs))
            if route == "/api/kb":
                if not qs.get("q"):
                    return self._error(400, "missing q")
                return self._json(kb_search(qs["q"], qs.get("category"),
                                            int(qs.get("top", 10))))
            if route == "/api/prompt":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                return self._json({"prompt": build_prompt(comp, qs.get("slug", ""),
                                                          qs.get("style") or "continue")})
            if route == "/api/health":
                return self._json({"ok": True, "root": str(ROOT)})
            return self._error(404, "no such route")
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"{type(exc).__name__}: {exc}")

    def task_start(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as exc:
            return self._error(400, f"bad json: {exc}")
        try:
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            slug = body.get("slug", "")
            entry = next((c for c in competition_view(comp)["challenges"]
                          if c.get("slug") == slug), None)
            if not entry:
                raise ValueError("unknown slug")
            case_dir_rel = entry.get("case_dir") or f"cases/{slug}"
            case_dir = safe_join(comp, case_dir_rel)
            prompt = build_prompt(comp, slug, body.get("style") or "continue")
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "scratch").mkdir(exist_ok=True)
            (case_dir / "scratch" / "agent-prompt.txt").write_text(prompt, encoding="utf-8")

            if body.get("sandbox"):
                cfg = sandbox_status()
                if not cfg["docker_ok"]:
                    raise ValueError("Docker 引擎不可达（启动 Docker Desktop 后重试）")
                category = str(entry.get("category") or "misc").lower()
                image = (cfg.get("images") or {}).get(category) or cfg["image"]
                # 镜像按类别校验，缺失时回落默认镜像
                image_ok = image == cfg["image"] or cfg["image_ok"]
                if image != cfg["image"]:
                    try:
                        proc = subprocess.run(["docker", "image", "inspect", image, "-f", "{{.Id}}"],
                                              capture_output=True, text=True, timeout=15)
                        image_ok = proc.returncode == 0
                    except Exception:  # noqa: BLE001
                        image_ok = False
                if not image_ok:
                    image = cfg["image"]
                    if not cfg["image_ok"]:
                        raise ValueError(f"镜像 {cfg['image']} 不存在：在 workbench/docker/ 下执行 "
                                         f"docker build -f misc/Dockerfile -t {cfg['image']} .")
                gateway_on = bool(body.get("gateway") or cfg.get("gateway"))
                if gateway_on and not upstream_key():
                    raise ValueError(f"模型网关已开启但未配置上游密钥（环境变量 "
                                     f"{cfg.get('upstream_key_env')}）或上游地址（sandbox.json upstream_base）")
                container = f"ctfwb-sbx-{uuid.uuid4().hex[:8]}"
                network = "bridge" if gateway_on else cfg["network"]
                caps = "--cap-drop ALL"
                if category == "pwn":
                    caps += " --cap-add SYS_PTRACE"  # gdb/调试需要（沿用 BTFly 策略）
                # 模型网关：一次性令牌在 docker run 时注入 env，上游 API key 不下容器
                gw_token = uuid.uuid4().hex[:24] if gateway_on else ""
                gw_env = (f' -e OPENAI_API_KEY={gw_token} '
                          f'-e OPENAI_BASE_URL=http://host.docker.internal:{_port}/gw/{gw_token}/v1 '
                          f'-e OPENAI_API_BASE=http://host.docker.internal:{_port}/gw/{gw_token}/v1'
                          ) if gateway_on else ""
                cmd_inside = (cfg["cmd"]
                              .replace("{prompt_file}", "/workspace/scratch/agent-prompt.txt")
                              .replace("{case_dir}", "/workspace")
                              .replace("{solver_dir}", "/solver"))
                command = (f'docker run --rm --name {container} '
                           f'{caps} --security-opt no-new-privileges '
                           f'--memory {cfg["memory"]} --cpus {cfg["cpus"]} '
                           f'--pids-limit {cfg["pids"]} --network {network} '
                           f'--add-host host.docker.internal:host-gateway'
                           f'{gw_env} '
                           f'-v "{case_dir}:/workspace" '
                           f'-v "{Path(__file__).resolve().parent}:/solver:ro" '
                           f'-w /workspace {image} {cmd_inside}')
                task = TASKS.run_custom(comp.name, slug, body.get("agent") or "sandbox",
                                        command, cwd=case_dir, container=container)
                if gw_token:
                    TASKS.register_token(gw_token, task["id"])
                    task = dict(task, gateway_base=f"http://host.docker.internal:{_port}/gw/{gw_token}/v1")
                return self._json({"ok": True, "task": task, "sandbox": True,
                                   "image": image, "category": category,
                                   "gateway": bool(gateway_on)})

            task = TASKS.start(comp, slug, case_dir_rel, prompt,
                               body.get("cmd_template"), body.get("agent") or "")
            return self._json({"ok": True, "task": task})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def task_stop(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            return self._json(TASKS.stop(body.get("id", "")))
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)

    def sandbox_save(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as exc:
            return self._error(400, f"bad json: {exc}")
        cfg_path = ROOT / "workbench-data" / "sandbox.json"
        cfg_path.parent.mkdir(exist_ok=True)
        merged = {**sandbox_config(),
                  **{k: body[k] for k in SANDBOX_DEFAULTS if k in body}}
        cfg_path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        return self._json({"ok": True, **sandbox_status()})

    def agent_start(self):
        """派发开赛自动化代理：kind=platform（对接平台写提交脚本）| fetch（自动抓题注册）。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as exc:
            return self._error(400, f"bad json: {exc}")
        try:
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            kind = body.get("kind", "")
            spec = {"platform": ("platform-agent", "platform_agent.py", "plat"),
                    "fetch": ("chall-agent", "fetch_challs.py", "fetch")}.get(kind)
            if not spec:
                raise ValueError("kind 必须是 platform 或 fetch")
            agent, script, label = spec
            solver_dir = Path(__file__).resolve().parent
            cmd = f'"{sys.executable}" -u "{solver_dir / script}" "{comp}"'
            task = TASKS.run_custom(comp.name, label, agent, cmd, cwd=comp)
            return self._json({"ok": True, "task": task})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def hunter_start(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as exc:
            return self._error(400, f"bad json: {exc}")
        try:
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            solver_dir = Path(__file__).resolve().parent
            cfg_path = ROOT / "workbench-data" / "autosubmit.json"
            max_live = 3
            cfg_all = read_json(cfg_path, {})
            if isinstance(cfg_all.get(comp.name), dict):
                max_live = int(cfg_all[comp.name].get("max_live", 3))
            cmd = (f'"{sys.executable}" -u "{solver_dir / "flag_hunter.py"}" "{comp}" '
                   f'--autosubmit-config "{cfg_path}" --max-live {max_live}')
            task = TASKS.run_custom(comp.name, "flag-hunt", "flag-agent", cmd, cwd=comp)
            return self._json({"ok": True, "task": task})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def autosubmit_save(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            cfg_path = ROOT / "workbench-data" / "autosubmit.json"
            cfg_path.parent.mkdir(exist_ok=True)
            cfg_all = read_json(cfg_path, {})
            cfg_all[comp.name] = {"enabled": bool(body.get("enabled")),
                                  "max_live": max(1, min(int(body.get("max_live", 3)), 10))}
            cfg_path.write_text(json.dumps(cfg_all, ensure_ascii=False, indent=1), encoding="utf-8")
            return self._json({"ok": True, **cfg_all[comp.name]})
        except (ValueError, TypeError) as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def events_stream(self, qs: dict):
        """SSE：推送比赛事件流增量与任务状态变化，断开由客户端触发。"""
        comp = resolve_competition(qs.get("dir", ""))
        if not comp or not comp.is_dir():
            return self._error(404, "unknown competition")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        events_path = comp / "events.jsonl"
        seen = 0
        try:
            if events_path.exists():
                seen = len(events_path.read_text(encoding="utf-8",
                                                 errors="replace").splitlines())
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            idle = 0
            while idle < 600:  # 单连接最长 ~10 分钟，前端 EventSource 自动重连
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                if events_path.exists():
                    total = len(events_path.read_text(encoding="utf-8",
                                                      errors="replace").splitlines())
                    while seen < total:
                        line = events_path.read_text(
                            encoding="utf-8", errors="replace").splitlines()[seen]
                        seen += 1
                        if line.strip():
                            payload = json.dumps(read_json_line(line), ensure_ascii=False)
                            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    if total < seen:  # 文件被轮换/清空
                        seen = total
                self.wfile.flush()
                time.sleep(1.0)
                idle += 1
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def api_file(self, qs: dict):
        comp = resolve_competition(qs.get("dir", ""))
        target = safe_join(comp or Path(), qs.get("path", ""))
        if not target or not target.is_file():
            return self._error(404, "file not found")
        size = target.stat().st_size
        data = target.read_bytes()[:MAX_FILE_BYTES]
        if not looks_textual(data):
            return self._json({"path": qs.get("path"), "size": size, "binary": True,
                               "note": "二进制文件不在浏览器内预览，请用本机工具查看"})
        return self._json({"path": qs.get("path"), "size": size,
                           "truncated": size > MAX_FILE_BYTES,
                           "content": data.decode("utf-8", errors="replace")})

    # -- 模型网关（参考 BTFly modelgateway：上游 key 只在宿主，容器持一次性令牌）
    def gateway(self, route: str):
        parts = route.split("/")  # /gw/<token>/v1/...
        if len(parts) < 3:
            return self._error(404, "bad gateway path")
        token = parts[2]
        with TASKS._lock:
            info = TASKS._gateway_tokens.get(token)
        if info is None:
            return self._error(401, "无效或已撤销的网关令牌")
        rest = "/" + "/".join(parts[3:])  # /v1/...
        base, key = upstream_base(), upstream_key()
        if not base or not key:
            return self._error(503, "网关未配置上游（sandbox.json upstream_base + 环境变量密钥）")
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(base + rest, data=body, method=self.command)
        for h in ("Content-Type", "Accept"):
            if self.headers.get(h):
                req.add_header(h, self.headers[h])
        req.add_header("Authorization", "Bearer " + key)
        try:
            up = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            return self._json({"error": "upstream error"}, e.code)
        except Exception as exc:  # noqa: BLE001
            return self._error(502, f"upstream failed: {exc}")
        self.send_response(up.status)
        self.send_header("Content-Type", up.headers.get("Content-Type", "application/json"))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        total = 0
        try:
            while True:
                chunk = up.read(8192)
                if not chunk:
                    break
                total += len(chunk)
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with TASKS._lock:
                if token in TASKS._gateway_tokens:
                    TASKS._gateway_tokens[token]["bytes"] = TASKS._gateway_tokens[token].get("bytes", 0) + total
                    TASKS._gateway_tokens[token]["requests"] = TASKS._gateway_tokens[token].get("requests", 0) + 1

    # -- POST
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/gw/"):
            return self.gateway(parsed.path)
        if parsed.path.startswith("/api/") and not _authorized(self.headers, {}):
            return self._error(401, "需要访问令牌（--token）")
        if parsed.path == "/api/task/start":
            return self.task_start()
        if parsed.path == "/api/task/stop":
            return self.task_stop()
        if parsed.path == "/api/hunter/start":
            return self.hunter_start()
        if parsed.path == "/api/agent/start":
            return self.agent_start()
        if parsed.path == "/api/autosubmit":
            return self.autosubmit_save()
        if parsed.path == "/api/sandbox":
            return self.sandbox_save()
        if parsed.path != "/api/action":
            return self._error(404, "no such route")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                return self._error(400, "bad body size")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            return self._error(400, f"bad json: {exc}")
        name = body.get("action")
        fn = ACTIONS.get(name)
        if fn is None:
            return self._error(400, f"unknown action: {name}")
        params = body.get("params") or {}
        try:
            result = fn(params)
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
        result.update({"ok": result.get("exit") == 0, "action": name})
        return self._json(result)


def watchdog_loop() -> None:
    """沙箱任务超时看门狗（BTFly 没有的部分）。"""
    while True:
        time.sleep(30)
        try:
            TASKS.enforce_timeouts(sandbox_config()["timeout_min"])
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    global _port, _auth_token
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1",
                        help="绑定地址：127.0.0.1（默认）| 0.0.0.0（局域网/Tailscale 共享）| 指定 IP")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--token", default=os.environ.get("WB_TOKEN", ""),
                        help="访问令牌；非回环绑定时强烈建议配置（亦可用环境变量 WB_TOKEN）")
    parser.add_argument("--competition", default="", help="默认选中的比赛目录名（比赛/ 之下）")
    parser.add_argument("--agent-cmd", default=os.environ.get("WB_AGENT_CMD", ""),
                        help="求解命令模板，占位符 {prompt_file} {case_dir} {solver_dir}；"
                             "例：'python solver.py --prompt {prompt_file}'")
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()
    _port = args.port
    _auth_token = args.token
    TASKS.agent_cmd = args.agent_cmd

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    threading.Thread(target=watchdog_loop, daemon=True).start()
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::', '') else args.host}:{args.port}/"
    print(f"CTF Workbench → {url}   (root={ROOT})", flush=True)
    if args.host in ("0.0.0.0", "::", ""):
        for u in local_urls(args.port):
            print(f"  共享地址: {u}", flush=True)
        if _auth_token:
            print("  已启用令牌鉴权：Agent 请求请带 'Authorization: Bearer <token>'；浏览器首次打开会提示输入一次。",
                  flush=True)
        else:
            print("  ⚠ 对局域网开放且未设令牌（--token）：同网段可读取本机比赛数据。建议配置令牌。",
                  flush=True)
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
