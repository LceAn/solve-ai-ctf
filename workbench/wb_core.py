"""wb_core —— 全局状态与配置、通用工具、数据视图、提示词、知识库检索封装（N-06 拆包）。

可变全局（ROOT/COMPETITIONS_DIR/STATIC_DIR 等）由 configure() 就地更新；
其他模块必须以 `_core.X` 属性访问，禁止 from-import 快照。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(__file__).resolve().parents[2]

ROOT = DEFAULT_ROOT
SCRIPTS_DIR = ROOT / "solve-ai-ctf" / "scripts"
STATIC_DIR = Path(__file__).resolve().parent / "static"
COMPETITIONS_DIR = ROOT / "比赛"
# Optional CLI-selected competition.  The browser still receives a sensible
# configured-first fallback when this is empty or points at a missing folder.
_default_competition = ""

COMPETITIONS_DIR = ROOT / "比赛"
# Optional CLI-selected competition.  The browser still receives a sensible
# configured-first fallback when this is empty or points at a missing folder.
_default_competition = ""

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


def select_default_competition(items: list[dict], requested: str = "") -> str:
    """Choose the initial browser selection from a known competition list.

    A CLI request wins when it names an entry in the list.  Otherwise prefer
    the first initialized competition so a fresh checkout does not open an
    empty placeholder directory.  The final fallback keeps the empty-state UI
    useful when every directory is uninitialized (or when ``比赛/`` is empty).
    """
    normalized = str(requested or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if normalized and any(item.get("dir") == normalized for item in items):
        return normalized
    for item in items:
        if item.get("configured"):
            return str(item.get("dir") or "")
    return str(items[0].get("dir") or "") if items else ""


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
    artifacts_count = 0
    docs_count = 0
    try:
        for path in case_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(case_dir).as_posix()
            if rel.lower().startswith("artifacts/"):
                artifacts_count += 1
            if path.suffix.lower() == ".md":
                docs_count += 1
    except OSError:
        pass
    return {
        "exists": True,
        "case_dir": case_dir_rel,
        "description": (case.get("challenge") or {}).get("description", ""),
        "artifacts_count": artifacts_count,
        "docs_count": docs_count,
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


_VIEW_CACHE: dict = {}


def competition_view(comp_dir: Path) -> dict:
    # mtime 缓存：数据未变时直接复用上一次聚合结果（题目多时显著省 IO）
    key = str(comp_dir)
    sig = []
    for f in (comp_dir / "competition.json", comp_dir / "events.jsonl"):
        try:
            sig.append(f.stat().st_mtime_ns)
        except OSError:
            sig.append(0)
    cases_dir = comp_dir / "cases"
    if cases_dir.is_dir():
        for cj in sorted(cases_dir.glob("*/case.json")):
            try:
                sig.append(cj.stat().st_mtime_ns)
            except OSError:
                sig.append(0)
    cached = _VIEW_CACHE.get(key)
    if cached and cached["sig"] == sig:
        return cached["view"]
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
            if not entry.get("description"):
                entry["description"] = entry["case"].get("description", "")
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

    view = {
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
    _VIEW_CACHE[key] = {"sig": sig, "view": view}
    return view


def read_json_line(line: str):
    try:
        return json.loads(line)
    except Exception:
        return {"time": None, "kind": "unparsable", "detail": {"raw": line[:300]}}



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
                        f"({h.get('id', '?')}, 优先级 {h.get('priority', '?')})")
        sections.append(rows)
    atts = case.get("attempts") or []
    if atts:
        rows = ["## 最近尝试"]
        for a in atts[-6:]:
            rows.append(f"- [{a.get('outcome', '?')}] {a.get('hypothesis_id', a.get('hypothesis', '?'))}: "
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



def prune_task_logs(comp_dir: Path, keep: int = 200) -> int:
    """R12：任务日志轮转——每场比赛只保留最新 keep 个 .log（scratch/ 与 cases/*/scratch/）。"""
    removed = 0
    scratch_dirs = [comp_dir / "scratch"]
    cases_root = comp_dir / "cases"
    if cases_root.is_dir():
        scratch_dirs += [d for d in cases_root.glob("*/scratch") if d.is_dir()]
    for d in scratch_dirs:
        if not d.is_dir():
            continue
        logs = sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in logs[keep:]:
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
    return removed


