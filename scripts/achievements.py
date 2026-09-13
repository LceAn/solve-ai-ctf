#!/usr/bin/env python3
"""Achievement rule engine backed by SQLite + JSON mirror.

Rules evaluated on each check:
  - first_blood: first accepted submission for a challenge across the competition
  - full_category_clear: team/operator has accepted on every challenge in a category
  - speedrun: time from case_initialized event to accepted < expected_minutes
  - zero_false_positive: >=5 candidates promoted to validated with zero live rejections
  - streak: N consecutive accepted submissions

Unlocked achievements append to events.jsonl as kind:"achievement_unlocked".
A JSON mirror at workbench-data/achievements.json aids audit/grep.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ACHIEVEMENTS_MIRROR = HERE.parent.parent / "workbench-data" / "achievements.json"
SCHEMA_VERSION = 1
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS achievements(
  id TEXT PRIMARY KEY,
  rule TEXT,
  competition TEXT,
  team_id TEXT,
  operator TEXT,
  challenge_slug TEXT,
  category TEXT,
  unlocked_at TEXT,
  meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_ach_comp ON achievements(competition);
CREATE INDEX IF NOT EXISTS idx_ach_rule ON achievements(rule, competition);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _gen_id(rule: str, competition: str, scope: str, slug: str = "") -> str:
    import hashlib
    raw = f"{rule}:{competition}:{scope}:{slug}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def cmd_init(args) -> int:
    with connect(args.db) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    print(args.db)
    return 0


def cmd_check(args) -> int:
    """评估所有规则，新解锁的写入 DB + 镜像 + events.jsonl。"""
    comp_dir = Path(args.comp_dir)
    competition = args.competition
    team_filter = args.team
    operator_filter = args.operator
    events_file = comp_dir / "events.jsonl"
    mirror_path = ACHIEVEMENTS_MIRROR
    mirror_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(args.db) as conn:
        # 读 submissions（从 leaderboard 同 db）
        subs = conn.execute(
            "SELECT * FROM submissions WHERE competition=? ORDER BY epoch",
            (competition,)).fetchall()
        new_unlocks: list[dict] = []

        # Rule 1: first_blood per challenge
        seen_first: set[str] = set()
        for s in subs:
            if s["outcome"] != "accepted" or s["dry_run"]:
                continue
            slug = s["challenge_slug"]
            if slug in seen_first:
                continue
            seen_first.add(slug)
            scope = s["team_id"] or s["operator"] or "(anon)"
            aid = _gen_id("first_blood", competition, scope, slug)
            exists = conn.execute("SELECT 1 FROM achievements WHERE id=?", (aid,)).fetchone()
            if not exists:
                new_unlocks.append({
                    "id": aid, "rule": "first_blood", "competition": competition,
                    "team_id": s["team_id"] or "", "operator": s["operator"] or "",
                    "challenge_slug": slug, "category": "",
                    "unlocked_at": utcnow(),
                    "meta": json.dumps({"challenge_slug": slug, "epoch": s["epoch"]}),
                })

        # Rule 2: full_category_clear
        # 读 competition.json 取每 category 的题目集合
        comp_data = json.loads((comp_dir / "competition.json").read_text(encoding="utf-8"))
        cat_challs: dict[str, set] = {}
        for c in comp_data.get("challenges", []):
            cat_challs.setdefault(c.get("category", ""), set()).add(c["slug"])
        # 按 team/operator 收集 accepted 题集合
        accepted_by_scope: dict[str, set] = {}
        for s in subs:
            if s["outcome"] != "accepted" or s["dry_run"]:
                continue
            scope = s["team_id"] or s["operator"] or "(anon)"
            accepted_by_scope.setdefault(scope, set()).add(s["challenge_slug"])
        for scope, accepted_set in accepted_by_scope.items():
            for cat, challs in cat_challs.items():
                if challs and challs.issubset(accepted_set):
                    aid = _gen_id("full_category_clear", competition, scope, cat)
                    exists = conn.execute("SELECT 1 FROM achievements WHERE id=?", (aid,)).fetchone()
                    if not exists:
                        team_id = scope if scope.startswith("t") else ""
                        operator = scope if not team_id else ""
                        new_unlocks.append({
                            "id": aid, "rule": "full_category_clear", "competition": competition,
                            "team_id": team_id, "operator": operator,
                            "challenge_slug": "", "category": cat,
                            "unlocked_at": utcnow(),
                            "meta": json.dumps({"category": cat, "count": len(challs)}),
                        })

        # Rule 3: speedrun — 从 case_initialized 事件到 accepted < expected_minutes
        # 读 events.jsonl + case.json
        if events_file.exists():
            init_events: dict[str, float] = {}  # slug -> earliest init epoch
            for line in events_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("kind") == "case_initialized":
                    slug = ev.get("detail", {}).get("slug", "")
                    if slug:
                        try:
                            epoch = datetime.fromisoformat(ev["time"].replace("Z", "+00:00")).timestamp()
                            if slug not in init_events or epoch < init_events[slug]:
                                init_events[slug] = epoch
                        except Exception:
                            pass
            # 也从每个 case.json 读 case_initialized 事件（更可靠）
            cases_root = comp_dir / "cases"
            if cases_root.is_dir():
                for case_json_path in cases_root.glob("*/case.json"):
                    try:
                        case_data = json.loads(case_json_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    slug = case_data.get("challenge", {}).get("slug") or case_json_path.parent.name
                    for ev in case_data.get("events", []):
                        if ev.get("kind") == "case_initialized":
                            try:
                                epoch = datetime.fromisoformat(ev["time"].replace("Z", "+00:00")).timestamp()
                                if slug not in init_events or epoch < init_events[slug]:
                                    init_events[slug] = epoch
                            except Exception:
                                pass
            # expected_minutes per challenge
            expected = {c["slug"]: float(c.get("expected_minutes", 60))
                        for c in comp_data.get("challenges", []) if "slug" in c}
            for s in subs:
                if s["outcome"] != "accepted" or s["dry_run"]:
                    continue
                slug = s["challenge_slug"]
                if slug not in init_events:
                    continue
                elapsed_min = (s["epoch"] - init_events[slug]) / 60.0
                if elapsed_min < expected.get(slug, 60):
                    scope = s["team_id"] or s["operator"] or "(anon)"
                    aid = _gen_id("speedrun", competition, scope, slug)
                    exists = conn.execute("SELECT 1 FROM achievements WHERE id=?", (aid,)).fetchone()
                    if not exists:
                        team_id = scope if scope.startswith("t") else ""
                        operator = scope if not team_id else ""
                        new_unlocks.append({
                            "id": aid, "rule": "speedrun", "competition": competition,
                            "team_id": team_id, "operator": operator,
                            "challenge_slug": slug, "category": "",
                            "unlocked_at": utcnow(),
                            "meta": json.dumps({"minutes": round(elapsed_min, 2),
                                                "expected": expected.get(slug, 60)}),
                        })

        # Rule 4: zero_false_positive — 每个 case.json 中 >=5 validated 候选 且 0 live rejected
        cases_root = comp_dir / "cases"
        if cases_root.is_dir():
            for case_json_path in cases_root.glob("*/case.json"):
                try:
                    case_data = json.loads(case_json_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                slug = case_data.get("challenge", {}).get("slug") or case_json_path.parent.name
                candidates = case_data.get("candidates", [])
                validated = [c for c in candidates if c.get("status") == "validated"]
                if len(validated) < 5:
                    continue
                # 查该 slug 的 live rejected 数
                rejected = [s for s in subs
                            if s["challenge_slug"] == slug and s["outcome"] == "rejected" and not s["dry_run"]]
                if not rejected:
                    scope = "(competition)"  # 全比赛级
                    aid = _gen_id("zero_false_positive", competition, scope, slug)
                    exists = conn.execute("SELECT 1 FROM achievements WHERE id=?", (aid,)).fetchone()
                    if not exists:
                        new_unlocks.append({
                            "id": aid, "rule": "zero_false_positive", "competition": competition,
                            "team_id": "", "operator": "",
                            "challenge_slug": slug, "category": "",
                            "unlocked_at": utcnow(),
                            "meta": json.dumps({"validated_count": len(validated)}),
                        })

        # Rule 5: streak — N 连续 accepted（N>=3）
        STREAK_MIN = 3
        # 按 operator 收集时序 accepted
        by_op: dict[str, list] = {}
        for s in subs:
            if s["outcome"] != "accepted" or s["dry_run"]:
                continue
            op = s["operator"] or s["team_id"] or "(anon)"
            by_op.setdefault(op, []).append(s)
        for op, op_subs in by_op.items():
            op_subs.sort(key=lambda r: r["epoch"])
            current_streak = 1
            best_streak = 1
            best_end_slug = op_subs[0]["challenge_slug"]
            for i in range(1, len(op_subs)):
                if op_subs[i]["epoch"] > op_subs[i-1]["epoch"]:
                    current_streak += 1
                    if current_streak > best_streak:
                        best_streak = current_streak
                        best_end_slug = op_subs[i]["challenge_slug"]
                else:
                    current_streak = 1
            if best_streak >= STREAK_MIN:
                aid = _gen_id("streak", competition, op, f"n{best_streak}")
                exists = conn.execute("SELECT 1 FROM achievements WHERE id=?", (aid,)).fetchone()
                if not exists:
                    team_id = op if op.startswith("t") else ""
                    operator = op if not team_id else ""
                    new_unlocks.append({
                        "id": aid, "rule": "streak", "competition": competition,
                        "team_id": team_id, "operator": operator,
                        "challenge_slug": best_end_slug, "category": "",
                        "unlocked_at": utcnow(),
                        "meta": json.dumps({"streak": best_streak}),
                    })

        # 写入 DB + events.jsonl + 镜像
        for ach in new_unlocks:
            conn.execute(
                "INSERT OR IGNORE INTO achievements "
                "(id, rule, competition, team_id, operator, challenge_slug, category, unlocked_at, meta) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ach["id"], ach["rule"], competition, ach["team_id"], ach["operator"],
                 ach["challenge_slug"], ach["category"], ach["unlocked_at"], ach["meta"]))
            # append to events.jsonl
            with events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "time": utcnow(), "kind": "achievement_unlocked",
                    "detail": {"rule": ach["rule"], "challenge_slug": ach["challenge_slug"],
                               "team_id": ach["team_id"], "operator": ach["operator"],
                               "category": ach["category"]}
                }, ensure_ascii=False) + "\n")
        conn.commit()

        # 写镜像
        all_achs = [dict(r) for r in conn.execute(
            "SELECT * FROM achievements WHERE competition=? ORDER BY unlocked_at",
            (competition,)).fetchall()]
        mirror_path.write_text(
            json.dumps({"competition": competition, "achievements": all_achs},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"new_unlocks": len(new_unlocks),
                      "rules": [a["rule"] for a in new_unlocks]}, ensure_ascii=False))
    return 0


def cmd_list(args) -> int:
    with connect(args.db) as conn:
        rows = conn.execute(
            "SELECT * FROM achievements WHERE competition=? ORDER BY unlocked_at",
            (args.competition,)).fetchall()
    print(json.dumps({"competition": args.competition,
                      "achievements": [dict(r) for r in rows]}, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("db", type=Path)
    init.set_defaults(func=cmd_init)

    check = sub.add_parser("check")
    check.add_argument("db", type=Path)
    check.add_argument("--competition", required=True)
    check.add_argument("--comp-dir", type=Path, required=True)
    check.add_argument("--team")
    check.add_argument("--operator")
    check.set_defaults(func=cmd_check)

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("db", type=Path)
    list_cmd.add_argument("--competition", required=True)
    list_cmd.set_defaults(func=cmd_list)

    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
