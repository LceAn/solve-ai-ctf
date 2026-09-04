#!/usr/bin/env python3
"""Competition-level control plane: bootstrap an event, register challenges, prioritize, and render a dashboard.

Each challenge gets its own case directory managed by case_manager.py. The competition
state (competition.json) is the machine-readable source of truth for scheduling and the
platform adapter; events append to events.jsonl.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
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
    }
    save_comp(args.comp_dir, data)
    events_path(args.comp_dir).touch()
    append_event(args.comp_dir, "competition_initialized", {"name": args.name})
    readme = args.comp_dir / "README.md"
    readme.write_text(
        "# {name}\n\n"
        "## 目录\n\n"
        "- `competition.json` 比赛状态与平台适配器配置（机器可读，唯一真源）\n"
        "- `events.jsonl` 追加式事件流，用于复盘与重建看板\n"
        "- `cases/<slug>/` 每道题的独立 case（由 case_manager.py 维护）\n"
        "- `artifacts/` 附件原件的不可变存储（先哈希再移动，勿直接执行）\n"
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
    data.setdefault("challenges", []).append(entry)
    save_comp(args.comp_dir, data)
    append_event(args.comp_dir, "challenge_registered", {"slug": slug, "name": args.name})
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
        rows.append(
            "<tr>"
            f"<td>{html_escape(entry['name'])}</td>"
            f"<td>{html_escape(entry['category'])}</td>"
            f"<td>{html_escape(entry.get('points', '?'))}</td>"
            f"<td>{html_escape(status)}</td>"
            f"<td>{html_escape(last)}</td>"
            f"<td><ul>{hyp_html}</ul></td>"
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
<table><tr><th>Challenge</th><th>Category</th><th>Points</th><th>Status</th><th>Last attempt</th><th>Top hypotheses</th></tr>
{rows}</table><p class="stats">generated {time}</p></body></html>
""".format(
        name=html_escape(data.get("name", "CTF")),
        solved=totals["solved"], active=totals["active"], blocked=totals["blocked"],
        points=totals["points"], rows="".join(rows), time=utcnow(),
    )
    out.write_text(page, encoding="utf-8")
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


def cmd_event(args: argparse.Namespace) -> int:
    detail = json.loads(args.detail) if args.detail else {}
    append_event(args.comp_dir, args.kind, detail)
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

    sync = sub.add_parser("sync")
    sync.add_argument("comp_dir", type=Path)
    sync.set_defaults(func=cmd_sync)

    event_cmd = sub.add_parser("event")
    event_cmd.add_argument("comp_dir", type=Path)
    event_cmd.add_argument("kind")
    event_cmd.add_argument("--detail")
    event_cmd.set_defaults(func=cmd_event)

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
