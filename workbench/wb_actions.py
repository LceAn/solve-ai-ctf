"""wb_actions —— 动作白名单注册表（list-argv 子进程调用 scripts/，N-06 拆包）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import wb_core as _core
from wb_core import case_summary, competition_view, read_json, run_script, safe_join, resolve_competition
from wb_sandbox import _HEALTH_CACHE  # selftest.run 需要失效健康缓存（R24 拆包时漏导入）

# ---------------------------------------------------------------- actions
#
# 每个动作把已校验参数拼成 argv，交给 scripts/ 下既有脚本执行。
# 返回统一带 exit/stdout/stderr，并在写操作后回读最新状态。


# 自检后台进程状态（R161：self_test 异步化，避免 HTTP 请求阻塞两分钟）
_SELFTEST: dict = {"proc": None, "started": 0.0, "log": None, "path": None, "code": None}


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


def action(name, required=None):
    """required：必填参数声明（AG-02）——/api/action 入口据此一次报全缺失。"""
    def register(fn):
        if required:
            fn.wb_required = list(required)
        ACTIONS[name] = fn
        return fn
    return register


@action("challenge.register")
def act_challenge_register(params: dict) -> dict:
    comp = comp_dir_of(params)
    argv = [_core.SCRIPTS_DIR / "competition.py", "add-challenge", comp,
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


@action("competition.init")
def act_competition_init(params: dict) -> dict:
    """R43-F1：从工作台直接新建比赛（目录名限定安全字符）。"""
    import re as _re
    # 未知参数直接报错：此前误传 dir 会被静默忽略、改用 name 生成目录名
    unknown = set(params) - {"name", "dir_name", "scope"}
    if unknown:
        raise ValueError(f"未知参数：{', '.join(sorted(unknown))}（可用：name / dir_name / scope）")
    name = _require(params, "name")
    dir_name = str(params.get("dir_name") or "").strip() or _re.sub(
        r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")[:40] or "new-ctf"
    if not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", dir_name) or ".." in dir_name:
        raise ValueError(f"目录名不合法：{dir_name}")
    comp_dir = _core.COMPETITIONS_DIR / dir_name
    if comp_dir.exists():
        raise ValueError(f"比赛目录已存在：{dir_name}")
    argv = [_core.SCRIPTS_DIR / "competition.py", "init", comp_dir, "--name", name]
    _optional(params, "scope", "--scope", argv)
    return run_script(argv)


@action("competition.set_docs")
def act_competition_set_docs(params: dict) -> dict:
    """R43-F2：设置比赛本地文档路径（外部目录只读浏览）。"""
    argv = [_core.SCRIPTS_DIR / "competition.py", "set-docs", comp_dir_of(params)]
    _optional(params, "path", "--path", argv)
    return run_script(argv)


def _db_path_of(comp: Path) -> Path:
    """成就/排行榜共用 workbench-data/leaderboard.db（与比赛同级根下）。"""
    return _core.ROOT / "workbench-data" / "leaderboard.db"


@action("competition.set_mode")
def act_set_mode(params: dict) -> dict:
    comp = comp_dir_of(params)
    mode = _require(params, "mode")
    if mode not in ("individual", "team", "timed"):
        raise ValueError("mode must be individual|team|timed")
    result = run_script([_core.SCRIPTS_DIR / "competition.py", "set-mode", comp, mode])
    result["competition"] = competition_view(comp)
    return result


@action("competition.set_scoring")
def act_set_scoring(params: dict) -> dict:
    comp = comp_dir_of(params)
    argv = [_core.SCRIPTS_DIR / "competition.py", "set-scoring", comp]
    _optional(params, "strategy", "--strategy", argv)
    _optional(params, "decay_type", "--decay-type", argv)
    _float_opt(params, "decay_cap", "--decay-cap", argv)
    _float_opt(params, "decay_step", "--decay-step", argv)
    _float_opt(params, "first_blood_bonus", "--first-blood-bonus", argv)
    if params.get("base_by_difficulty"):
        argv += ["--base-by-difficulty", json.dumps(params["base_by_difficulty"])]
    result = run_script(argv)
    result["competition"] = competition_view(comp)
    return result


@action("competition.add_team")
def act_add_team(params: dict) -> dict:
    comp = comp_dir_of(params)
    argv = [_core.SCRIPTS_DIR / "competition.py", "add-team", comp,
            "--name", _require(params, "name")]
    _optional(params, "team_id", "--team-id", argv)
    _optional(params, "color", "--color", argv)
    return run_script(argv)


@action("competition.update_challenge")
def act_update_challenge(params: dict) -> dict:
    comp = comp_dir_of(params)
    slug = _require(params, "slug")
    argv = [_core.SCRIPTS_DIR / "competition.py", "update-challenge", comp, slug]
    _optional(params, "name", "--name", argv)
    _optional(params, "difficulty", "--difficulty", argv)
    _float_opt(params, "points", "--points", argv)
    _optional(params, "description", "--description", argv)
    if params.get("difficulty_grade") is not None:
        grade = int(params["difficulty_grade"])
        if grade not in (1, 2, 3, 4, 5):
            raise ValueError("difficulty_grade must be 1-5")
        argv += ["--difficulty-grade", str(grade)]
    _optional(params, "team_id", "--team-id", argv)
    result = run_script(argv)
    result["competition"] = competition_view(comp)
    return result


@action("competition.remove_challenge")
def act_remove_challenge(params: dict) -> dict:
    comp = comp_dir_of(params)
    slug = _require(params, "slug")
    result = run_script([_core.SCRIPTS_DIR / "competition.py", "remove-challenge", comp, slug])
    result["competition"] = competition_view(comp)
    return result


@action("case.set_grade")
def act_set_grade(params: dict) -> dict:
    comp, case = case_dir_of(params)
    grade = int(_require(params, "grade"))
    if grade not in (1, 2, 3, 4, 5):
        raise ValueError("grade must be 1-5")
    result = run_script([_core.SCRIPTS_DIR / "case_manager.py", "set-grade", case, str(grade)])
    result["case"] = case_summary(comp, str(case.relative_to(comp)))
    return result


@action("achievement.check")
def act_achievement_check(params: dict) -> dict:
    comp = comp_dir_of(params)
    db = _db_path_of(comp)
    # submissions/teams 由 leaderboard.py 建，achievements 表由 achievements.py 建。
    # 两个 init 都是 CREATE TABLE IF NOT EXISTS（幂等），无条件跑一遍：
    # 否则"只有 achievements 表"的半初始化库会让 check 报 no such table: submissions。
    for script in ("leaderboard.py", "achievements.py"):
        subprocess.run([sys.executable, str(_core.SCRIPTS_DIR / script), "init", str(db)],
                       capture_output=True, text=True, timeout=30)
    return run_script([_core.SCRIPTS_DIR / "achievements.py", "check", db,
                       "--competition", comp.name, "--comp-dir", comp], timeout=30)


@action("team.list")
def act_team_list(params: dict) -> dict:
    comp = comp_dir_of(params)
    return run_script([_core.SCRIPTS_DIR / "competition.py", "list-teams", comp])


@action("docs.write")
def act_docs_write(params: dict) -> dict:
    """R68-DOC1：新建/覆盖比赛级 docs/<name>.md（文件名白名单，路径锁定 docs/ 内）。"""
    import re as _re
    import pathlib as _pl
    name = _require(params, "name")
    if not _re.fullmatch(r"[A-Za-z0-9_一-鿿-]{1,64}\.md", name):
        raise ValueError("文件名不合法（仅字母/数字/中文/下划线/连字符 + .md）")
    comp = comp_dir_of(params)
    docs_dir = comp / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    target = docs_dir / name
    resolved = target.resolve()
    if not str(resolved).startswith(str(docs_dir.resolve())):
        raise ValueError("路径逃逸")
    content = str(params.get("content") or "")
    if len(content) > 256 * 1024:
        raise ValueError("内容超限（256KB）")
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "exit": 0, "file": f"docs/{name}"}


@action("competition.prioritize")
def act_prioritize(params: dict) -> dict:
    return run_script([_core.SCRIPTS_DIR / "competition.py", "prioritize", comp_dir_of(params)])


@action("competition.dashboard")
def act_dashboard(params: dict) -> dict:
    return run_script([_core.SCRIPTS_DIR / "competition.py", "dashboard", comp_dir_of(params)])


@action("competition.export")
def act_competition_export(params: dict) -> dict:
    """R162：一键打包交付——writeup + case 记录 + 复盘报告 → zip（真实 flag 脱敏）。"""
    comp = comp_dir_of(params)
    argv = [_core.SCRIPTS_DIR / "export_package.py", comp]
    if params.get("include_artifacts"):
        argv.append("--include-artifacts")
    if params.get("solved_only"):
        argv.append("--solved-only")
    out = run_script(argv, timeout=180)
    if out.get("exit") == 0 and out.get("stdout"):
        try:
            out["package"] = json.loads(out["stdout"].strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            pass
    return out


@action("competition.inbox_import")
def act_inbox_import(params: dict) -> dict:
    """R173：半接入比赛——inbox/ 附件批量导入：注册题目 + 初始化 case + 附件 sha256 入库。

    场景：平台登录不在自己手里（队友下载/离线复盘赛），只有一批附件。
    约定：比赛/<dir>/inbox/ 顶层一个条目=一道题；<题名>.meta.json 可覆盖
    category/points/description。幂等：已注册 slug 跳过；原件挪入 inbox/.done/ 留档。
    """
    comp = comp_dir_of(params)
    out = run_script([_core.SCRIPTS_DIR / "inbox_import.py", comp], timeout=600)
    if out.get("exit") == 0 and out.get("stdout"):
        try:
            out["import"] = json.loads(out["stdout"].strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            pass
    return out


@action("competition.report")
def act_report(params: dict) -> dict:
    """R4：复盘报告导出（Markdown，flag 自动脱敏）。"""
    return run_script([_core.SCRIPTS_DIR / "competition.py", "report", comp_dir_of(params)])


@action("competition.event")
def act_event(params: dict) -> dict:
    comp = comp_dir_of(params)
    argv = [_core.SCRIPTS_DIR / "competition.py", "event", comp, _require(params, "kind")]
    # competition.py event 的 --detail 只接受 JSON，这里把纯文本包一层
    if params.get("detail"):
        argv += ["--detail", json.dumps({"text": str(params["detail"])}, ensure_ascii=False)]
    return run_script(argv)


@action("case.init", required=["case_dir", "name"])
def act_case_init(params: dict) -> dict:
    comp = comp_dir_of(params)
    case = safe_join(comp, _require(params, "case_dir"))
    if not case:
        raise ValueError("bad case_dir")
    argv = [_core.SCRIPTS_DIR / "case_manager.py", "init", case, "--name", _require(params, "name")]
    _optional(params, "category", "--category", argv)
    _optional(params, "challenge_id", "--challenge-id", argv)
    _optional(params, "description", "--description", argv)
    _float_opt(params, "points", "--points", argv)
    if params.get("force"):
        argv += ["--force"]
    return run_script(argv)


@action("case.status", required=["case_dir", "status"])
def act_case_status(params: dict) -> dict:
    comp, case = case_dir_of(params)
    status = _require(params, "status")
    if status not in _core.CASE_STATUSES:
        raise ValueError(f"invalid status: {status}")
    argv = [_core.SCRIPTS_DIR / "case_manager.py", "status", case, status]
    _optional(params, "reason", "--reason", argv)
    _optional(params, "blocked_on", "--blocked-on", argv)
    for when in params.get("unblock_when") or []:
        argv += ["--unblock-when", str(when)]
    result = run_script(argv)
    result["case"] = case_summary(comp, str(case.relative_to(comp)))
    return result


@action("case.hypothesis", required=["case_dir", "title", "rationale", "expected"])
def act_hypothesis(params: dict) -> dict:
    comp, case = case_dir_of(params)
    argv = [_core.SCRIPTS_DIR / "case_manager.py", "hypothesis", case,
            "--title", _require(params, "title"),
            "--rationale", _require(params, "rationale"),
            "--expected", _require(params, "expected")]
    _optional(params, "stop", "--stop", argv)
    _optional(params, "agent", "--agent", argv)
    _float_opt(params, "minutes", "--minutes", argv)
    _float_opt(params, "priority", "--priority", argv)
    return run_script(argv)


@action("case.finding", required=["case_dir", "claim", "source"])
def act_finding(params: dict) -> dict:
    comp, case = case_dir_of(params)
    argv = [_core.SCRIPTS_DIR / "case_manager.py", "finding", case,
            "--claim", _require(params, "claim"),
            "--source", _require(params, "source")]
    _optional(params, "artifact", "--artifact", argv)
    _optional(params, "agent", "--agent", argv)
    _float_opt(params, "confidence", "--confidence", argv)
    if params.get("kind"):
        argv += ["--kind", str(params["kind"])]
    if params.get("phase"):
        argv += ["--phase", str(params["phase"])]
    return run_script(argv)


@action("case.attempt", required=["case_dir", "hypothesis", "action", "result", "outcome"])
def act_attempt(params: dict) -> dict:
    comp, case = case_dir_of(params)
    argv = [_core.SCRIPTS_DIR / "case_manager.py", "attempt", case,
            "--hypothesis", _require(params, "hypothesis"),
            "--action", _require(params, "action"),
            "--result", _require(params, "result"),
            "--outcome", _require(params, "outcome")]
    _optional(params, "evidence", "--evidence", argv)
    _optional(params, "duration", "--duration", argv)
    _optional(params, "agent", "--agent", argv)
    if params.get("variants"):
        argv += ["--variants", str(int(params["variants"]))]
    if params.get("hypothesis_status"):
        if params["hypothesis_status"] not in _core.HYPOTHESIS_STATUSES:
            raise ValueError("invalid hypothesis_status")
        argv += ["--hypothesis-status", str(params["hypothesis_status"])]
    return run_script(argv)


@action("case.scan_flags", required=["case_dir", "search_root"])
def act_scan_flags(params: dict) -> dict:
    comp, case = case_dir_of(params)
    root = safe_join(comp, _require(params, "search_root"))
    if not root or not root.exists():
        raise ValueError("search_root not found inside competition dir")
    argv = [_core.SCRIPTS_DIR / "case_manager.py", "scan-flags", case, root]
    if params.get("store"):
        argv += ["--store"]
    return run_script(argv, timeout=300)


@action("case.candidate", required=["case_dir", "candidate_id", "candidate_status"])
def act_candidate(params: dict) -> dict:
    comp, case = case_dir_of(params)
    status = _require(params, "candidate_status")
    if status not in _core.CANDIDATE_STATUSES:
        raise ValueError(f"invalid candidate status: {status}")
    argv = [_core.SCRIPTS_DIR / "case_manager.py", "candidate", case,
            _require(params, "candidate_id"), status]
    _optional(params, "note", "--note", argv)
    result = run_script(argv)
    result["case"] = case_summary(comp, str(case.relative_to(comp)))
    return result


@action("case.candidate_add", required=["case_dir", "flag"])
def act_candidate_add(params: dict) -> dict:
    """R183：手动登记 flag 候选（不再依赖 scan-flags 才能进流水线）。"""
    import json as _json
    comp, case = case_dir_of(params)
    case_data = _core.read_json(case / "case.json", {})
    cands = case_data.setdefault("candidates", [])
    nums = [int(c["id"][1:]) for c in cands if str(c.get("id", "")).startswith("C")
            and str(c.get("id", ""))[1:].isdigit()]
    cid = f"C{max(nums, default=0) + 1:04d}"
    cands.append({"id": cid, "value": str(_require(params, "flag")),
                  "status": "unverified",
                  "source": str(params.get("source") or "manual"),
                  "note": str(params.get("note") or ""), "agent": str(params.get("agent") or "")})
    import datetime as _dt
    case_data.setdefault("events", []).append({
        "id": f"EV{len(case_data.get('events', [])) + 1:04d}",
        "time": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": "candidate_added",
        "detail": {"candidate_id": cid, "source": params.get("source") or "manual"}})
    case_data["updated_at"] = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    (case / "case.json").write_text(_json.dumps(case_data, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    return {"exit": 0, "stdout": cid, "stderr": "", "candidate_id": cid}


@action("case.validate")
def act_validate(params: dict) -> dict:
    comp, case = case_dir_of(params)
    result = run_script([_core.SCRIPTS_DIR / "case_manager.py", "validate", case])
    result["case"] = case_summary(comp, str(case.relative_to(comp)))
    return result


@action("case.triage", required=["case_dir", "target"])
def act_triage(params: dict) -> dict:
    comp, case = case_dir_of(params)
    target = safe_join(comp, _require(params, "target"))
    if not target or not target.exists():
        raise ValueError("target not found inside competition dir")
    return run_script([_core.SCRIPTS_DIR / "triage.py", target,
                       "--json-out", case / "triage.json",
                       "--markdown-out", case / "triage.md"], timeout=300)


@action("case.summary")
def act_summary(params: dict) -> dict:
    comp, case = case_dir_of(params)
    return run_script([_core.SCRIPTS_DIR / "case_manager.py", "summary", case,
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
    argv = [_core.SCRIPTS_DIR / "submitter.py", "submit", comp,
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
        lines += [f"| {h.get('id')} | {h.get('title')} | {h.get('status')} | "
                  f"{h.get('expected_signal', h.get('expected', ''))} |"
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
    """异步启动 self_test.py：立即返回，前端轮询 /api/selftest 取进度与结果。

    此前是同步 run_script(timeout=120)，HTTP 请求要挂两分钟，前端只能干等。
    """
    import time

    state = _SELFTEST
    proc = state.get("proc")
    if proc is not None and proc.poll() is None:
        return {"ok": True, "started": True, "running": True, "already": True,
                "elapsed": round(time.time() - state["started"], 1)}
    _HEALTH_CACHE["at"] = 0.0
    log_path = _core.ROOT / "workbench-data" / "selftest.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, str(_core.SCRIPTS_DIR / "self_test.py")],
        stdout=handle, stderr=subprocess.STDOUT, cwd=str(_core.ROOT), text=True,
    )
    state.update({"proc": proc, "started": time.time(), "log": handle, "path": log_path,
                  "code": None})
    return {"ok": True, "started": True, "running": True, "already": False}


def selftest_status() -> dict:
    """自检运行状态（供 /api/selftest 轮询）。"""
    import time

    state = _SELFTEST
    proc = state.get("proc")
    if proc is None:
        return {"started": False, "running": False, "exit": None, "output": ""}
    code = proc.poll()
    if code is not None and state.get("code") is None:
        state["code"] = code
        _HEALTH_CACHE["at"] = 0.0   # R203：自检结果要反映到「系统概况 → 脚本层」
        try:
            state["log"].close()
        except Exception:  # noqa: BLE001
            pass
    output = ""
    path = state.get("path")
    if path and path.exists():
        output = path.read_text(encoding="utf-8", errors="replace")
    return {
        "started": True,
        "running": code is None,
        "exit": code,
        "elapsed": round(time.time() - state["started"], 1),
        "output": output[-8000:],
    }


ACTIONS["case.writeup"] = _writeup_case


