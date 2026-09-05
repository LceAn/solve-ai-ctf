"""wb_tasks —— 任务生命周期、argv 词法模板、docker/compose 执行助手（N-06 拆包）。"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import env_builder as envb
import wb_core as _core
from wb_core import competition_view, read_json, resolve_competition, safe_join


def split_cmd_template(template: str, **repl: str) -> list[str]:
    """把命令模板按 argv 词法切成参数列表（N-02：任务派发不再经 shell 解析）。

    先 shlex 切分（posix=False 保留反斜杠，适配 Windows 路径），只剥 token 最外层
    引号（内层引号原样保留，如 -c "print(':start')" 的代码），再把 {prompt_file}
    {case_dir} {solver_dir} 替换为原始路径，并清理替换点紧邻的残余引号。
    模板是 argv 词法：不支持 && | > 等 shell 语法与环境变量展开。
    """
    result: list[str] = []
    for tok in shlex.split(template, posix=False):
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ('"', "'"):
            tok = tok[1:-1]
        for key, val in repl.items():
            tok = tok.replace("{" + key + "}", val)
        for key, val in repl.items():  # "{solver_dir}"/x 写法：清理紧贴替换值的引号
            tok = tok.replace('"' + val, val, 1).replace(val + '"', val, 1)
        if tok:
            result.append(tok)
    return result


def validate_bind_security(host: str, token: str, allow_insecure: bool = False) -> str | None:
    """N-03：非回环绑定必须配令牌；显式 --allow-insecure 才豁免。返回拒绝原因或 None。"""
    if host in ("", "127.0.0.1", "localhost", "::1"):
        return None
    if token:
        return None
    if allow_insecure:
        return None
    return (f"绑定非回环地址 --host {host} 而未配置访问令牌（--token / WB_TOKEN）会把比赛数据"
            "暴露给同网段：请配置 --token，或确认风险后加 --allow-insecure 显式豁免")



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
        d = _core.ROOT / "workbench-data"
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
            teardown: list[dict] = []
            for tid, t in tasks.items():
                proc = self._procs.get(tid)
                if proc is not None and proc.poll() is not None:
                    t["status"] = "done" if proc.returncode == 0 else "failed"
                    t["exit"] = proc.returncode
                    t["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    self._procs.pop(tid, None)
                    self.revoke_task_tokens(tid)
                    if t.get("compose"):
                        teardown.append(t["compose"])
                    changed = True
                elif proc is None and t.get("status") == "running":
                    t["status"] = "lost"
                    self.revoke_task_tokens(tid)
                    if t.get("compose"):
                        teardown.append(t["compose"])
                    changed = True
            if changed:
                self._save(tasks)
            # compose down 放锁外（慢速 docker 调用），失败不影响任务状态
            for meta in teardown:
                threading.Thread(target=_compose_down, kwargs=meta, daemon=True).start()

    def start(self, comp_dir: Path, slug: str, case_dir_rel: str, prompt: str,
              cmd_template: str | None = None, agent: str = "", demo: bool = False) -> dict:
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
        # N-02：模板按 argv 词法切分后 shell=False 执行（占位符路径自动加引号，
        # 不支持 && | > 等 shell 语法——见 --agent-cmd 帮助）
        argv = split_cmd_template(template,
                                  prompt_file=str(prompt_file),
                                  case_dir=str(case_dir),
                                  solver_dir=str(Path(__file__).resolve().parent))
        command = subprocess.list2cmdline(argv)
        with self._lock:
            tasks = self._load()
            tasks[tid] = {
                "id": tid, "dir": comp_dir.name, "slug": slug, "case_dir": case_dir_rel,
                "agent": (agent or "solver").strip() or "solver",
                "command": command, "log": log_rel, "status": "running",
                "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            if demo:
                tasks[tid]["mode"] = "demo"
            self._save(tasks)
        try:
            creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            proc = subprocess.Popen(argv, shell=False, cwd=str(case_dir),
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
                   argv: list[str], cwd: Path, container: str = "",
                   compose: dict | None = None) -> dict:
        """派发内建代理/沙箱任务：与 solver 任务同一生命周期管理。

        N-02：argv 列表 + shell=False，彻底消除命令注入面；任务记录里的
        command 仅为展示串（list2cmdline）。compose 非空时（多服务题目），
        任务结束/超时/手动停止都会连带 `docker compose down -v`。
        """
        argv = [str(a) for a in argv]
        command = subprocess.list2cmdline(argv)
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
                          "compose": compose or None,
                          "status": "running", "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self._save(tasks)
        try:
            creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            proc = subprocess.Popen(argv, shell=False, cwd=str(cwd),
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
            teardown: list[dict] = []
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
                    if t.get("compose"):
                        teardown.append(t["compose"])
            self._save(tasks)
        for meta in teardown:  # 锁外执行：compose down 是慢速 docker 调用
            threading.Thread(target=_compose_down, kwargs=meta, daemon=True).start()

    def get(self, tid: str) -> dict:
        self.reconcile()
        return self._load().get(tid, {})

    def list(self, status: str = "", agent: str = "", limit: int = 0) -> list[dict]:
        """R8：任务列表支持 status/agent 过滤与 limit 截断（默认全量，按时间倒序）。"""
        self.reconcile()
        rows = self._load().values()
        if status:
            rows = [t for t in rows if t.get("status") == status]
        if agent:
            rows = [t for t in rows if t.get("agent") == agent]
        rows = sorted(rows, key=lambda t: t.get("started", ""), reverse=True)
        return rows[:limit] if limit > 0 else rows

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
            if task.get("compose"):
                _compose_down(task["compose"].get("project", ""),
                              task["compose"].get("compose_file", ""))
                return {"stopped": True,
                        "how": "docker stop " + task["container"] + " + compose down"}
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



# ---------------------------------------------------------------- compose services
#
# 多服务题目（env spec services，web 本地复现等）：compose 工程与求解容器同生共死。
# 服务网络默认 internal（无外网出口），solver 以 --network <proj>_challnet 加入。


def _image_exists(tag: str) -> bool:
    prefix = envb.docker_prefix()
    if not prefix:
        return False
    try:
        return subprocess.run([*prefix, "image", "inspect", tag, "-f", "{{.Id}}"],
                              capture_output=True, text=True, timeout=20).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _compose_up(compose_file: Path, project: str) -> dict:
    if not compose_file.is_file():
        raise ValueError(f"compose 文件缺失：{compose_file}（先 env_builder build 生成）")
    prefix = envb.docker_prefix()
    if not prefix:
        raise ValueError("Docker 引擎不可达")
    cfile = envb.docker_path(compose_file)
    argv = [*prefix, "compose", "-p", project, "-f", cfile,
            "up", "-d", "--wait", "--wait-timeout", "120"]
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=200)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")
        if "unknown" in err.lower() and "--wait" in err:  # 旧版 compose 不支持 --wait
            proc = subprocess.run([*prefix, "compose", "-p", project, "-f", cfile, "up", "-d"],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=200)
        if proc.returncode != 0:
            raise ValueError("题目服务启动失败："
                             + (proc.stderr or proc.stdout or "").strip()[-300:])
    return {"project": project, "compose_file": str(compose_file)}


def _compose_down(project: str, compose_file: str) -> None:
    if not project or not compose_file:
        return
    prefix = envb.docker_prefix()
    if not prefix:
        return
    try:
        subprocess.run([*prefix, "compose", "-p", project,
                        "-f", envb.docker_path(compose_file),
                        "down", "-v", "--remove-orphans"],
                       capture_output=True, text=True, timeout=120)
    except Exception:  # noqa: BLE001
        pass


def _mem_bytes(s: str) -> int:
    m = re.fullmatch(r"(\d+)\s*([bkmgt]?)", str(s).strip().lower())
    if not m:
        return 0
    mult = {"": 1, "b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}
    return int(m.group(1)) * mult[m.group(2)]



def docker_stop_container(name: str) -> None:
    prefix = envb.docker_prefix()
    if not prefix:
        return
    try:
        subprocess.run([*prefix, "stop", "-t", "5", name],
                       capture_output=True, text=True, timeout=40)
    except Exception:  # noqa: BLE001
        pass


