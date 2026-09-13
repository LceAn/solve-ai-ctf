#!/usr/bin/env python3
"""Competition-level control plane: bootstrap an event, register challenges, prioritize, and render a dashboard.

Each challenge gets its own case directory managed by case_manager.py. The competition
state (competition.json) is the machine-readable source of truth for scheduling and the
platform adapter; events append to events.jsonl.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA_VERSION = 1
COMPETITION_FILE = "competition.json"
EVENTS_FILE = "events.jsonl"
ACTIVE_STATUSES = {"new", "triaged", "in_progress", "candidate_found"}
DEFAULT_P_SOLVE = 0.3
DEFAULT_MINUTES = 60.0
# 队伍调色板，循环分配
TEAM_COLORS = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"]

# env 骨架（构建器与 spec 格式见 workbench/docker/COMPETITION_ENV_DESIGN.md）。
# 题目 spec 只写身份字段 → env_builder 视为"无定制"，自动沿用题型层镜像。
ENV_COMP_TEMPLATE = """\
# 比赛级环境声明 —— workbench/env_builder.py 构建 L2 比赛层镜像用。
# 题目级覆盖放 env/challenges/<slug>.yaml；完整字段参考 workbench/docker/envs/*.example.yaml。
api: ctfbox/v1
comp: {comp}
base: ctfbox-misc:0.1.0
mirrors:
  apt: https://mirrors.tuna.tsinghua.edu.cn/debian
  pip: https://pypi.tuna.tsinghua.edu.cn/simple
build:
  apt: []
  pip: []
  pre: |
    :
run:
  network: none
  caps: []
constraints:
  claudemd: ""
  skills: []
"""

ENV_CHALL_TEMPLATE = """\
# 题目环境声明（骨架）——按需定制后用 workbench/env_builder.py build --slug {slug} 构建。
# 可定制：build.apt/pip、assets[]（带 sha256）、files[]、services{{}}（web 本地复现）、run.caps。
# 示例：workbench/docker/envs/challenge.pwn-glibc235.example.yaml、challenge.web-lamp.example.yaml
api: ctfbox/v1
slug: {slug}
category: {category}
base: ctfbox-{category}:0.1.0
"""


def init_env_skeleton(comp_dir: Path, name: str) -> None:
    """competition.py init 时创建 env/ 骨架（幂等：已存在的文件不覆盖）。"""
    env_dir = comp_dir / "env"
    (env_dir / "challenges").mkdir(parents=True, exist_ok=True)
    (env_dir / "assets").mkdir(exist_ok=True)
    (env_dir / ".gitignore").write_text("gen/\n", encoding="utf-8")
    comp_yaml = env_dir / "comp.yaml"
    if not comp_yaml.exists():
        comp_yaml.write_text(ENV_COMP_TEMPLATE.format(comp=name), encoding="utf-8")


def write_challenge_spec_skeleton(comp_dir: Path, slug: str, category: str) -> bool:
    """注册题目时补一份题目 spec 骨架（幂等）。返回是否新写。"""
    env_ch = comp_dir / "env" / "challenges"
    if not env_ch.parent.is_dir():
        return False
    spec_path = env_ch / f"{slug}.yaml"
    if spec_path.exists():
        return False
    spec_path.write_text(ENV_CHALL_TEMPLATE.format(slug=slug, category=category),
                         encoding="utf-8")
    return True


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def comp_path(comp_dir: Path) -> Path:
    return comp_dir / COMPETITION_FILE


def events_path(comp_dir: Path) -> Path:
    return comp_dir / EVENTS_FILE


def load_comp(comp_dir: Path) -> dict[str, Any]:
    path = comp_path(comp_dir)
    if not path.exists():
        raise FileNotFoundError(f"competition file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_comp(comp_dir: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = utcnow()
    comp_path(comp_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def append_event(comp_dir: Path, kind: str, detail: dict[str, Any]) -> None:
    record = {"time": utcnow(), "kind": kind, "detail": detail}
    with events_path(comp_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def slugify(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return value or "challenge"


def find_case_dirs(comp_dir: Path) -> list[Path]:
    cases_root = comp_dir / "cases"
    if not cases_root.is_dir():
        return []
    return sorted(cases_root.iterdir(), key=lambda path: str(path).lower())


def read_case(comp_dir: Path, slug: str) -> dict[str, Any] | None:
    case_dir = comp_dir / "cases" / slug
    path = case_dir / "case.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_challenge_entries(comp_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    data = load_comp(comp_dir)
    return [(item["slug"], item) for item in data.get("challenges", [])]


def cmd_init(args: argparse.Namespace) -> int:
    path = comp_path(args.comp_dir)
    if path.exists() and not args.force:
        print(f"refusing to overwrite existing {path}; use --force", file=sys.stderr)
        return 2
    args.comp_dir.mkdir(parents=True, exist_ok=True)
    (args.comp_dir / "cases").mkdir(exist_ok=True)
    (args.comp_dir / "artifacts").mkdir(exist_ok=True)
    platform: dict[str, Any] = {}
    if args.platform_config:
        platform = json.loads(args.platform_config.read_text(encoding="utf-8"))
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "name": args.name,
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "scope": args.scope,
        "competition_id": args.competition_id or "",
        "platform": platform,
        "rate_limit": args.rate_limit,
        "challenges": [],
        # additive 顶层字段（向后兼容；旧 competition.json 缺这些字段时按默认值工作）
        "mode": "individual",  # individual|team|timed
        "teams": [],  # [{"id","name","color","created_at"}]
        "scoring": {  # 评分策略
            "strategy": "static",  # static|dynamic
            "decay": {"type": "linear", "cap": 0.2, "step": 0.1},  # 或 {"type":"log"}
            "first_blood_bonus": 0.1,
            # base_by_difficulty 的 key 为字符串（JSON object key 皆为字符串），leaderboard.py 读取时转 int
            "base_by_difficulty": {"1": 100, "2": 200, "3": 300, "4": 400, "5": 500},
        },
    }
    save_comp(args.comp_dir, data)
    events_path(args.comp_dir).touch()
    append_event(args.comp_dir, "competition_initialized", {"name": args.name})
    init_env_skeleton(args.comp_dir, args.name)
    readme = args.comp_dir / "README.md"
    readme.write_text(
        "# {name}\n\n"
        "## 目录\n\n"
        "- `competition.json` 比赛状态与平台适配器配置（机器可读，唯一真源）\n"
        "- `events.jsonl` 追加式事件流，用于复盘与重建看板\n"
        "- `cases/<slug>/` 每道题的独立 case（由 case_manager.py 维护）\n"
        "- `artifacts/` 附件原件的不可变存储（先哈希再移动，勿直接执行）\n"
        "- `env/` 比赛环境声明（comp.yaml + challenges/，`workbench/env_builder.py` 构建；gen/ 为产物勿手改）\n"
        "- `warroom.html` 由 `competition.py dashboard` 生成\n\n"
        "## 凭证\n\n"
        "平台 Token/密码一律放环境变量（如 `CTF_TOKEN`），绝不写入本目录任何文件。\n".format(name=args.name),
        encoding="utf-8",
    )
    print(path)
    return 0


def cmd_add_challenge(args: argparse.Namespace) -> int:
    data = load_comp(args.comp_dir)
    # Platform IDs are the stable identity when a caller does not provide a
    # human slug; this keeps API/CLI registrations aligned with fetch_challs.
    slug = args.slug or (f"c{args.challenge_id}" if args.challenge_id else slugify(args.name))
    if any(item["slug"] == slug for item in data["challenges"]) and not args.force:
        print(f"challenge slug already registered: {slug}", file=sys.stderr)
        return 2
    case_dir = args.comp_dir / "cases" / slug
    cmd = [
        sys.executable, str(HERE / "case_manager.py"), "init", str(case_dir),
        "--name", args.name,
        "--category", args.category,
        "--scope", args.scope or data.get("scope", ""),
        "--description", args.description,
    ]
    if args.challenge_id:
        cmd += ["--challenge-id", args.challenge_id]
    if args.difficulty:
        cmd += ["--difficulty", args.difficulty]
    if args.points is not None:
        cmd += ["--points", str(args.points)]
    for pattern in args.flag_pattern or []:
        cmd += ["--flag-pattern", pattern]
    if case_dir.exists() and not args.force:
        print(f"case directory already exists: {case_dir}", file=sys.stderr)
        return 2
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        return result.returncode or 1
    entry = {
        "slug": slug,
        "name": args.name,
        "platform_id": args.challenge_id or "",
        "category": args.category,
        "difficulty": args.difficulty or "",
        "description": args.description or "",
        "points": args.points,
        "p_solve": args.p_solve,
        "expected_minutes": args.expected_minutes,
        "case_dir": f"cases/{slug}",
    }
    # additive 可选字段：难度分级（1-5）与归属队伍
    if args.difficulty_grade is not None:
        entry["difficulty_grade"] = args.difficulty_grade
    if args.team_id:
        entry["team_id"] = args.team_id
    data.setdefault("challenges", []).append(entry)
    save_comp(args.comp_dir, data)
    append_event(args.comp_dir, "challenge_registered", {"slug": slug, "name": args.name})
    write_challenge_spec_skeleton(args.comp_dir, slug, args.category)
    print(slug)
    return 0


def urgency(status: str) -> float:
    if status in {"candidate_found", "submitted"}:
        return 3.0
    if status in ACTIVE_STATUSES:
        return 1.0
    return 0.0


def priority_of(entry: dict[str, Any], case: dict[str, Any] | None) -> float:
    status = case.get("status", "new") if case else "new"
    if status in {"solved", "submitted", "closed", "abandoned", "invalid", "blocked"}:
        return 0.0
    p_solve = float(entry.get("p_solve", DEFAULT_P_SOLVE))
    points = float(entry.get("points") or 0.0)
    minutes = max(float(entry.get("expected_minutes") or DEFAULT_MINUTES), 1.0)
    return p_solve * points * urgency(status) / minutes


def cmd_prioritize(args: argparse.Namespace) -> int:
    data = load_comp(args.comp_dir)
    rows = []
    for entry in data.get("challenges", []):
        case = read_case(args.comp_dir, entry["slug"])
        rows.append((priority_of(entry, case), entry, case))
    rows.sort(key=lambda row: (-row[0], row[1]["slug"]))
    limit = args.top or len(rows)
    for score, entry, case in rows[:limit]:
        status = case.get("status", "new") if case else "new"
        print(f"{score:8.2f}  [{status:<16}] {entry['name']} ({entry['category']}, {entry.get('points', '?')}pt)")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    data = load_comp(args.comp_dir)
    for entry in data.get("challenges", []):
        case = read_case(args.comp_dir, entry["slug"])
        status = case.get("status", "new") if case else "new"
        hypotheses = len(case.get("hypotheses", [])) if case else 0
        attempts = len(case.get("attempts", [])) if case else 0
        print(
            f"{entry['slug']:<24} [{status:<16}] {entry['category']:<10} "
            f"{str(entry.get('points', '?')):>5}pt  H:{hypotheses} A:{attempts}"
        )
    if not data.get("challenges"):
        print("no challenges registered; use `competition.py add-challenge`")
    return 0


def html_escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def cmd_dashboard(args: argparse.Namespace) -> int:
    data = load_comp(args.comp_dir)
    out = args.output or args.comp_dir / "warroom.html"
    rows = []
    totals = {"solved": 0, "active": 0, "blocked": 0, "points": 0.0}
    env_rows: list[str] = []
    built_path = args.comp_dir / "env" / "gen" / ".built.json"
    if built_path.exists():
        try:
            built = json.loads(built_path.read_text(encoding="utf-8"))
            for slug, rec in sorted((built.get("images") or {}).items()):
                if rec.get("image"):
                    env_rows.append(f"<li><code>{html_escape(rec['image'])}</code></li>")
        except json.JSONDecodeError:
            pass
    env_html = ""
    if env_rows:
        env_html = ('<h2 style="font-size:14px;margin-top:18px">题目环境镜像</h2><ul style="font-size:11px">'
                    + "".join(env_rows) + "</ul>")
    for entry in data.get("challenges", []):
        case = read_case(args.comp_dir, entry["slug"])
        status = case.get("status", "new") if case else "new"
        if status in {"solved", "submitted", "closed"}:
            totals["solved"] += 1
        elif status == "blocked":
            totals["blocked"] += 1
        elif status in ACTIVE_STATUSES:
            totals["active"] += 1
        if status in {"solved", "submitted", "closed"}:
            totals["points"] += float(entry.get("points") or 0.0)
        hypotheses = case.get("hypotheses", []) if case else []
        attempts = case.get("attempts", []) if case else []
        top = sorted(hypotheses, key=lambda item: (-item.get("priority", 0), item["id"]))[:3]
        hyp_html = "".join(
            f"<li>[{html_escape(h['status'])}] {html_escape(h['title'])}</li>" for h in top
        ) or "<li>-</li>"
        last = attempts[-1]["action"] if attempts else "-"
        candidates = case.get("candidates", []) if case else []
        accepted = sum(1 for c in candidates if c.get("status") in ("submitted", "accepted"))
        cand_note = f"{accepted}/{len(candidates)} 接受" if candidates else "-"
        rows.append(
            "<tr>"
            f"<td>{html_escape(entry['name'])}</td>"
            f"<td>{html_escape(entry['category'])}</td>"
            f"<td>{html_escape(entry.get('points', '?'))}</td>"
            f"<td>{html_escape(status)}</td>"
            f"<td>{html_escape(last)}</td>"
            f"<td><ul>{hyp_html}</ul></td>"
            f"<td>{html_escape(cand_note)}</td>"
            "</tr>"
        )
    page = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{name} War Room</title>
<style>
body{{background:#0d1117;color:#e6edf3;font-family:Menlo,monospace;margin:24px}}
h1{{font-size:18px}} table{{border-collapse:collapse;width:100%;margin-top:16px;font-size:12px}}
th,td{{border:1px solid #30363d;padding:6px 10px;text-align:left;vertical-align:top}}
th{{background:#161b22;color:#8b949e}} ul{{margin:0;padding-left:18px}}
.solved{{color:#3fb950}}.blocked{{color:#f85149}}.active{{color:#d29922}}
.stats{{color:#8b949e;font-size:11px}}
</style></head><body>
<h1>{name} <span class="stats">solved {solved} · active {active} · blocked {blocked} · raw points {points:.0f}</span></h1>
<table><tr><th>Challenge</th><th>Category</th><th>Points</th><th>Status</th><th>Last attempt</th><th>Top hypotheses</th><th>Flags</th></tr>
{rows}</table><p class="stats">generated {time}</p>{env_html}</body></html>
""".format(
        name=html_escape(data.get("name", "CTF")),
        solved=totals["solved"], active=totals["active"], blocked=totals["blocked"],
        points=totals["points"], rows="".join(rows), time=utcnow(),
        env_html=env_html,
    )
    out.write_text(page, encoding="utf-8")
    print(out)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """R4：复盘报告导出——Markdown（总览/事件统计/逐题假设与尝试/脱敏候选/环境镜像）。

    SKILL.md 红线第 8 条：真实 flag 不进报告，统一脱敏为「sha256 前 8 位」关联标识。
    """
    data = load_comp(args.comp_dir)
    flag_re = re.compile(r"(?i)(?:flag|hkcert|ctf)\{[^}]+\}")

    def redact(text: Any) -> str:
        def _sub(m: re.Match) -> str:
            v = m.group(0)
            return (v.split("{", 1)[0] + "{…脱敏·sha256:"
                    + hashlib.sha256(v.encode("utf-8")).hexdigest()[:8] + "}")
        return flag_re.sub(_sub, str(text))

    out = args.output or (args.comp_dir / "report.md")
    statuses: dict[str, dict[str, Any]] = {}
    solved = accepted = points = 0.0
    attempts_total = hypotheses_total = 0
    outcome_counter: Counter[str] = Counter()
    for entry in data.get("challenges", []):
        case = read_case(args.comp_dir, entry["slug"]) or {}
        status = case.get("status", "new")
        statuses[entry["slug"]] = case
        if status in {"solved", "submitted", "closed"}:
            solved += 1
        accepted += sum(1 for c in case.get("candidates", [])
                        if c.get("status") in {"submitted", "accepted"})
        points += float(entry.get("points") or 0.0) if status in {"solved", "submitted", "closed"} else 0.0
        attempts_total += len(case.get("attempts", []))
        hypotheses_total += len(case.get("hypotheses", []))
        outcome_counter.update(a.get("outcome", "?") for a in case.get("attempts", []))

    lines: list[str] = [
        f"# {data.get('name', 'CTF')} 复盘报告", "",
        f"> 生成时间 {utcnow()} · 范围 {data.get('scope') or 'authorized'}", "",
        "## 总览", "",
        f"- 题目 {len(data.get('challenges', []))} · 解出/提交 {int(solved)} · 候选提交接受 {accepted} · 原始分 {points:.0f}",
        f"- 假设 {hypotheses_total} 条 · 有界尝试 {attempts_total} 次"
        + (f"（" + "，".join(f"{k} {v}" for k, v in outcome_counter.most_common()) + "）" if outcome_counter else ""),
        "",
    ]
    ev_path = events_path(args.comp_dir)
    if ev_path.exists():
        kinds: Counter[str] = Counter()
        for line in ev_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                kinds += Counter([json.loads(line).get("kind", "?")])
        if kinds:
            lines += ["## 事件流概览", "", "，".join(f"`{k}`×{v}" for k, v in kinds.most_common(10)), ""]
    built = args.comp_dir / "env" / "gen" / ".built.json"
    if built.exists():
        try:
            images = json.loads(built.read_text(encoding="utf-8")).get("images") or {}
            rows = [f"- `{slug}` → `{rec.get('image')}`（base {rec.get('base')}）"
                    for slug, rec in sorted(images.items()) if rec.get("image")]
            if rows:
                lines += ["## 题目环境镜像", ""] + rows + [""]
        except json.JSONDecodeError:
            pass
    lines += ["## 逐题复盘", ""]
    for entry in data.get("challenges", []):
        slug = entry["slug"]
        case = statuses.get(slug) or {}
        ch = case.get("challenge", {}) or {}
        lines.append(f"### {slug} · {ch.get('name') or entry.get('name', slug)}"
                     f"（{ch.get('category') or entry.get('category', '?')}，"
                     f"{entry.get('points') or '?'} 分）")
        lines.append("")
        lines.append(f"- 状态 **{case.get('status', 'new')}** · case `{entry.get('case_dir')}`")
        hyps = sorted(case.get("hypotheses", []),
                      key=lambda h: (-float(h.get("priority") or 0), h.get("id", "")))[:3]
        for h in hyps:
            lines.append(f"- 假设 `{h['id']}` [{h.get('status')}] {h.get('title')}")
        for a in case.get("attempts", []):
            lines.append(f"- 尝试 `{a['id']}` [{a.get('outcome')}] {a.get('action')}")
        for c in case.get("candidates", []):
            lines.append(f"- 候选 `{c['id']}` [{c.get('status')}] {redact(c.get('value', ''))}")
        for ev in case.get("evidence", [])[:3]:
            lines.append(f"- 证据 `{ev['id']}` ({float(ev.get('confidence') or 0):.1f}) {redact(ev.get('claim', ''))}")
        writeup = args.comp_dir / str(entry.get("case_dir") or f"cases/{slug}") / "WRITEUP.md"
        if writeup.exists():
            lines.append(f"- Writeup：`{writeup.relative_to(args.comp_dir)}`")
        lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    data = load_comp(args.comp_dir)
    registered = {entry["slug"] for entry in data.get("challenges", [])}
    orphans = []
    for case_dir in find_case_dirs(args.comp_dir):
        slug = case_dir.name
        if slug not in registered and (case_dir / "case.json").exists():
            orphans.append(slug)
    for slug in orphans:
        case = json.loads((args.comp_dir / "cases" / slug / "case.json").read_text(encoding="utf-8"))
        challenge = case.get("challenge", {})
        data.setdefault("challenges", []).append({
            "slug": slug,
            "name": challenge.get("name", slug),
            "platform_id": challenge.get("id", ""),
            "category": challenge.get("category", "auto"),
            "difficulty": challenge.get("difficulty", ""),
            "points": challenge.get("points"),
            "p_solve": DEFAULT_P_SOLVE,
            "expected_minutes": DEFAULT_MINUTES,
            "case_dir": f"cases/{slug}",
        })
        print(f"registered orphan case: {slug}")
    if orphans:
        save_comp(args.comp_dir, data)
        append_event(args.comp_dir, "cases_synced", {"orphans": orphans})
    else:
        print("no orphan cases found")
    return 0


def cmd_set_docs(args: argparse.Namespace) -> int:
    """R43：设置比赛本地文档路径（外部目录，只读浏览；空串清除）。"""
    data = load_comp(args.comp_dir)
    path = str(args.path or "").strip()
    if path:
        p = Path(path).expanduser()
        if not p.is_dir():
            print(f"path is not a directory: {p}", file=sys.stderr)
            return 2
        path = str(p.resolve())
    data["docs_path"] = path
    save_comp(args.comp_dir, data)
    append_event(args.comp_dir, "docs_path_set", {"path": path})
    print(path or "(cleared)")
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    detail = json.loads(args.detail) if args.detail else {}
    append_event(args.comp_dir, args.kind, detail)
    return 0


def cmd_set_mode(args: argparse.Namespace) -> int:
    """设置比赛模式：individual|team|timed。"""
    if args.mode not in {"individual", "team", "timed"}:
        print(f"invalid mode: {args.mode}", file=sys.stderr)
        return 2
    data = load_comp(args.comp_dir)
    data["mode"] = args.mode
    save_comp(args.comp_dir, data)
    append_event(args.comp_dir, "mode_changed", {"mode": args.mode})
    print(args.mode)
    return 0


def cmd_add_team(args: argparse.Namespace) -> int:
    """新增队伍；team_id 缺省时按 teams 列表长度生成 t01..t99。"""
    data = load_comp(args.comp_dir)
    teams = data.setdefault("teams", [])
    team_id = args.team_id or f"t{len(teams) + 1:02d}"
    if any(t.get("id") == team_id for t in teams):
        print(f"team id already exists: {team_id}", file=sys.stderr)
        return 2
    color = args.color or TEAM_COLORS[len(teams) % len(TEAM_COLORS)]
    team = {"id": team_id, "name": args.name, "color": color, "created_at": utcnow()}
    teams.append(team)
    save_comp(args.comp_dir, data)
    append_event(args.comp_dir, "team_added", {"team_id": team_id, "name": args.name})
    print(team_id)
    return 0


def cmd_list_teams(args: argparse.Namespace) -> int:
    """以 JSON 数组形式列出 teams，便于 server.py 转发。"""
    data = load_comp(args.comp_dir)
    print(json.dumps(data.get("teams", []), ensure_ascii=False, indent=2))
    return 0


def cmd_set_scoring(args: argparse.Namespace) -> int:
    """更新评分策略；只更新传入的字段，其它保持不变。"""
    data = load_comp(args.comp_dir)
    scoring = data.setdefault("scoring", {
        "strategy": "static",
        "decay": {"type": "linear", "cap": 0.2, "step": 0.1},
        "first_blood_bonus": 0.1,
        "base_by_difficulty": {"1": 100, "2": 200, "3": 300, "4": 400, "5": 500},
    })
    if args.strategy:
        scoring["strategy"] = args.strategy
    if args.decay_type or args.decay_cap is not None or args.decay_step is not None:
        decay = scoring.setdefault("decay", {"type": "linear", "cap": 0.2, "step": 0.1})
        if args.decay_type:
            decay["type"] = args.decay_type
        if args.decay_cap is not None:
            decay["cap"] = args.decay_cap
        if args.decay_step is not None:
            decay["step"] = args.decay_step
    if args.first_blood_bonus is not None:
        scoring["first_blood_bonus"] = args.first_blood_bonus
    if args.base_by_difficulty:
        scoring["base_by_difficulty"] = json.loads(args.base_by_difficulty)
    save_comp(args.comp_dir, data)
    append_event(args.comp_dir, "scoring_updated", {"strategy": scoring.get("strategy")})
    print(json.dumps(scoring, ensure_ascii=False))
    return 0


def cmd_update_challenge(args: argparse.Namespace) -> int:
    """更新题目字段；--difficulty-grade 同步 patch case.json challenge.difficulty_grade。"""
    data = load_comp(args.comp_dir)
    entry = next((c for c in data.get("challenges", []) if c["slug"] == args.slug), None)
    if entry is None:
        print(f"challenge not found: {args.slug}", file=sys.stderr)
        return 2
    if args.difficulty_grade is not None and args.difficulty_grade not in {1, 2, 3, 4, 5}:
        print("difficulty_grade must be 1-5", file=sys.stderr)
        return 2
    updates: dict[str, Any] = {}
    for field in ("name", "difficulty", "description"):
        val = getattr(args, field, None)
        if val is not None:
            entry[field] = val
            updates[field] = val
    if args.points is not None:
        entry["points"] = args.points
        updates["points"] = args.points
    if args.difficulty_grade is not None:
        entry["difficulty_grade"] = args.difficulty_grade
        updates["difficulty_grade"] = args.difficulty_grade
        # 同步 patch case.json challenge.difficulty_grade
        case_dir = args.comp_dir / "cases" / args.slug
        case_json = case_dir / "case.json"
        if case_json.exists():
            subprocess.run(
                [sys.executable, str(HERE / "case_manager.py"), "set-grade",
                 str(case_dir), str(args.difficulty_grade)],
                capture_output=True, text=True,
            )
    if args.team_id is not None:
        entry["team_id"] = args.team_id
        updates["team_id"] = args.team_id
    save_comp(args.comp_dir, data)
    append_event(args.comp_dir, "challenge_updated", {"slug": args.slug, "updates": updates})
    print(args.slug)
    return 0


def cmd_remove_challenge(args: argparse.Namespace) -> int:
    """仅从 challenges 列表移除，不删除 case_dir。"""
    data = load_comp(args.comp_dir)
    before = len(data.get("challenges", []))
    data["challenges"] = [c for c in data.get("challenges", []) if c["slug"] != args.slug]
    if len(data["challenges"]) == before:
        print(f"challenge not found: {args.slug}", file=sys.stderr)
        return 2
    save_comp(args.comp_dir, data)
    append_event(args.comp_dir, "challenge_removed", {"slug": args.slug})
    print(args.slug)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("comp_dir", type=Path)
    init.add_argument("--name", required=True)
    init.add_argument("--scope", default="")
    init.add_argument("--competition-id", default="")
    init.add_argument("--platform-config", type=Path)
    init.add_argument("--rate-limit", default="min_interval_seconds=2,max_per_window=20,window_seconds=300")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    add = sub.add_parser("add-challenge")
    add.add_argument("comp_dir", type=Path)
    add.add_argument("--name", required=True)
    add.add_argument("--category", required=True)
    add.add_argument("--slug")
    add.add_argument("--challenge-id")
    add.add_argument("--difficulty")
    add.add_argument("--points", type=float)
    add.add_argument("--description", default="")
    add.add_argument("--p-solve", type=float, default=DEFAULT_P_SOLVE)
    add.add_argument("--expected-minutes", type=float, default=DEFAULT_MINUTES)
    add.add_argument("--flag-pattern", action="append")
    add.add_argument("--scope")
    add.add_argument("--difficulty-grade", type=int, choices=[1, 2, 3, 4, 5])
    add.add_argument("--team-id")
    add.add_argument("--force", action="store_true")
    add.set_defaults(func=cmd_add_challenge)

    prioritize = sub.add_parser("prioritize")
    prioritize.add_argument("comp_dir", type=Path)
    prioritize.add_argument("--top", type=int)
    prioritize.set_defaults(func=cmd_prioritize)

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("comp_dir", type=Path)
    list_cmd.set_defaults(func=cmd_list)

    dashboard = sub.add_parser("dashboard")
    dashboard.add_argument("comp_dir", type=Path)
    dashboard.add_argument("--output", type=Path)
    dashboard.set_defaults(func=cmd_dashboard)

    report = sub.add_parser("report")
    report.add_argument("comp_dir", type=Path)
    report.add_argument("--output", type=Path)
    report.set_defaults(func=cmd_report)

    sync = sub.add_parser("sync")
    sync.add_argument("comp_dir", type=Path)
    sync.set_defaults(func=cmd_sync)

    set_docs = sub.add_parser("set-docs")
    set_docs.add_argument("comp_dir", type=Path)
    set_docs.add_argument("--path", default="", help="本地文档目录（空串清除）")
    set_docs.set_defaults(func=cmd_set_docs)

    event_cmd = sub.add_parser("event")
    event_cmd.add_argument("comp_dir", type=Path)
    event_cmd.add_argument("kind")
    event_cmd.add_argument("--detail")
    event_cmd.set_defaults(func=cmd_event)

    set_mode = sub.add_parser("set-mode")
    set_mode.add_argument("comp_dir", type=Path)
    set_mode.add_argument("mode", choices=["individual", "team", "timed"])
    set_mode.set_defaults(func=cmd_set_mode)

    add_team = sub.add_parser("add-team")
    add_team.add_argument("comp_dir", type=Path)
    add_team.add_argument("--name", required=True)
    add_team.add_argument("--team-id")
    add_team.add_argument("--color")
    add_team.set_defaults(func=cmd_add_team)

    list_teams = sub.add_parser("list-teams")
    list_teams.add_argument("comp_dir", type=Path)
    list_teams.set_defaults(func=cmd_list_teams)

    set_scoring = sub.add_parser("set-scoring")
    set_scoring.add_argument("comp_dir", type=Path)
    set_scoring.add_argument("--strategy", choices=["static", "dynamic"])
    set_scoring.add_argument("--decay-type", choices=["linear", "log"])
    set_scoring.add_argument("--decay-cap", type=float)
    set_scoring.add_argument("--decay-step", type=float)
    set_scoring.add_argument("--first-blood-bonus", type=float)
    set_scoring.add_argument("--base-by-difficulty")
    set_scoring.set_defaults(func=cmd_set_scoring)

    update_chal = sub.add_parser("update-challenge")
    update_chal.add_argument("comp_dir", type=Path)
    update_chal.add_argument("slug")
    update_chal.add_argument("--name")
    update_chal.add_argument("--difficulty")
    update_chal.add_argument("--points", type=float)
    update_chal.add_argument("--description")
    update_chal.add_argument("--difficulty-grade", type=int, choices=[1, 2, 3, 4, 5])
    update_chal.add_argument("--team-id")
    update_chal.set_defaults(func=cmd_update_challenge)

    remove_chal = sub.add_parser("remove-challenge")
    remove_chal.add_argument("comp_dir", type=Path)
    remove_chal.add_argument("slug")
    remove_chal.add_argument("--force", action="store_true")
    remove_chal.set_defaults(func=cmd_remove_challenge)

    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except (OSError, json.JSONDecodeError, FileNotFoundError, KeyError) as exc:
        print(f"competition error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
