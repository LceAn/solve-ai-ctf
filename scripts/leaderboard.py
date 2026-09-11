#!/usr/bin/env python3
"""SQLite-backed leaderboard with dynamic scoring.

Mirrors submission events from submissions.jsonl into a queryable SQLite cache.
Scoring formula: points = base[grade] * decay(solve_count) + (first_blood ? base[grade] * bonus : 0)
  - base[grade] from competition.json scoring.base_by_difficulty (keys "1".."5")
  - decay(n) for linear: max(cap, 1 - n*step); for log: max(cap, 1/log2(n+2))
  - first_blood: first accepted submission for a challenge across the whole competition

The cache is derived; submissions.jsonl + case.json remain the source of truth.
Idempotent: re-ingesting the same submission does not duplicate rows.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS teams(
  id TEXT PRIMARY KEY,
  name TEXT,
  color TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS submissions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  epoch REAL,
  time TEXT,
  competition TEXT,
  challenge_slug TEXT,
  team_id TEXT,
  operator TEXT,
  flag_sha256 TEXT,
  outcome TEXT,
  dry_run INTEGER,
  source TEXT,
  note TEXT,
  UNIQUE(flag_sha256, time)  -- 幂等：同 flag+time 视为重复
);
CREATE INDEX IF NOT EXISTS idx_sub_comp ON submissions(competition);
CREATE INDEX IF NOT EXISTS idx_sub_slug ON submissions(competition, challenge_slug);
CREATE INDEX IF NOT EXISTS idx_sub_team ON submissions(competition, team_id);
CREATE TABLE IF NOT EXISTS scoring_log(
  competition TEXT,
  challenge_slug TEXT,
  solves INTEGER,
  points REAL,
  updated_at TEXT,
  PRIMARY KEY(competition, challenge_slug)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def cmd_init(args) -> int:
    with connect(args.db) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    print(args.db)
    return 0


def cmd_ingest(args) -> int:
    records = []
    sub_path = args.submissions
    if sub_path and sub_path.exists():
        for line in sub_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    comp_dir = Path(args.comp_dir) if args.comp_dir else None
    with connect(args.db) as conn:
        for r in records:
            conn.execute(
                """INSERT OR IGNORE INTO submissions
                (epoch, time, competition, challenge_slug, team_id, operator,
                 flag_sha256, outcome, dry_run, source, note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (float(r.get("epoch", 0)), r.get("time", ""), args.competition,
                 r.get("challenge_slug", ""), r.get("team_id", ""), r.get("operator", ""),
                 r.get("flag_sha256", ""), r.get("outcome", ""), int(bool(r.get("dry_run", True))),
                 r.get("source", ""), r.get("note", "")))
        conn.commit()
        # 重新计算评分
        _recompute_scoring(conn, args.db, args.competition, comp_dir)
    print(f"ingested {len(records)} records")
    return 0


# === 动态评分（核心） ===

def _load_scoring_config(comp_dir: Path | None) -> dict:
    if not comp_dir or not (comp_dir / "competition.json").exists():
        return {}
    data = json.loads((comp_dir / "competition.json").read_text(encoding="utf-8"))
    return data.get("scoring", {})


def _base_points(scoring: dict, grade: int | None) -> float:
    if not scoring:
        return 0.0
    base_map = scoring.get("base_by_difficulty", {})
    key = str(grade) if grade else "3"  # 默认中等
    return float(base_map.get(key, base_map.get("3", 300)))


def _decay_factor(scoring: dict, solve_count: int) -> float:
    if not scoring:
        return 1.0
    decay = scoring.get("decay", {"type": "linear", "cap": 0.2, "step": 0.1})
    cap = float(decay.get("cap", 0.2))
    dtype = decay.get("type", "linear")
    if dtype == "log":
        return max(cap, 1.0 / math.log2(solve_count + 2)) if solve_count > 0 else 1.0
    step = float(decay.get("step", 0.1))
    return max(cap, 1.0 - solve_count * step)


def _challenge_grade(comp_dir: Path | None, slug: str) -> int | None:
    """从 competition.json challenges[].difficulty_grade 读 grade。"""
    if not comp_dir or not (comp_dir / "competition.json").exists():
        return None
    data = json.loads((comp_dir / "competition.json").read_text(encoding="utf-8"))
    for c in data.get("challenges", []):
        if c.get("slug") == slug:
            return c.get("difficulty_grade")
    return None


def cmd_compute_scoring(args) -> int:
    comp_dir = Path(args.comp_dir) if args.comp_dir else None
    with connect(args.db) as conn:
        _recompute_scoring(conn, args.db, args.competition, comp_dir)
    print("scoring recomputed")
    return 0


def _recompute_scoring(conn, db_path, competition, comp_dir=None) -> None:
    """重新计算每题的 solves 计数和当前基础分值（不含首血加成）。

    首血加成在 cmd_query 中 per-team 计算，避免被所有 accepted team 共享。
    scoring_log.points = base[grade] * decay(solve_count - 1)（纯基础分值）
    """
    scoring = _load_scoring_config(comp_dir)
    # 每题的 accepted 提交按时间排序
    rows = conn.execute(
        "SELECT challenge_slug, epoch "
        "FROM submissions WHERE competition=? AND outcome='accepted' AND dry_run=0 "
        "ORDER BY epoch ASC", (competition,)).fetchall()
    solve_count: dict[str, int] = {}
    for row in rows:
        slug = row["challenge_slug"]
        solve_count[slug] = solve_count.get(slug, 0) + 1
    now = utcnow()
    for slug, count in solve_count.items():
        grade = _challenge_grade(comp_dir, slug) if comp_dir else None
        base = _base_points(scoring, grade)
        points = base * _decay_factor(scoring, count - 1)  # 第 N 次解的衰减（纯基础分值）
        conn.execute(
            "INSERT OR REPLACE INTO scoring_log (competition, challenge_slug, solves, points, updated_at) "
            "VALUES (?,?,?,?,?)", (competition, slug, count, points, now))
    conn.commit()


def _first_blood_map(conn, competition: str, mode: str) -> dict[str, str]:
    """每题的首血者（team_id 或 operator），按最早 accepted epoch。"""
    rows = conn.execute(
        "SELECT challenge_slug, team_id, operator, epoch "
        "FROM submissions WHERE competition=? AND outcome='accepted' AND dry_run=0 "
        "ORDER BY epoch ASC", (competition,)).fetchall()
    fb: dict[str, str] = {}
    for row in rows:
        slug = row["challenge_slug"]
        if slug not in fb:
            fb[slug] = row["team_id"] if mode == "team" else (row["operator"] or row["team_id"] or "(anon)")
    return fb


def _compute_progress(conn, competition: str, comp_dir: Path | None) -> dict:
    """训练进度聚合：按 operator / 类别 / 覆盖率 / 近 7 天活跃。

    返回结构：
      {
        "by_operator":   [{id, solves, categories, first_clears, points, accepted_epochs}],
        "by_category":   [{category, total, solved, coverage, operators}],
        "coverage":       {solved_challenges, total_challenges, ratio},
        "recent_activity": [{day, count}],  # 近 7 天
        "skill_axes":     ["crypto","pwn","web","reverse","misc","forensics"],
        "operator_skill": {operator: {axis: count, ...}}
      }
    六维技能雷达固定为 crypto/pwn/web/reverse/misc/forensics。
    """
    SIX_AXES = ["crypto", "pwn", "web", "reverse", "misc", "forensics"]
    challenges = []
    if comp_dir and (comp_dir / "competition.json").exists():
        data = json.loads((comp_dir / "competition.json").read_text(encoding="utf-8"))
        challenges = data.get("challenges", [])
    slug_to_cat = {c.get("slug"): c.get("category", "misc") for c in challenges}
    cat_totals: dict[str, int] = {}
    for c in challenges:
        cat = c.get("category", "misc")
        cat_totals[cat] = cat_totals.get(cat, 0) + 1

    acc_rows = conn.execute(
        "SELECT operator, team_id, challenge_slug, epoch "
        "FROM submissions WHERE competition=? AND outcome='accepted' AND dry_run=0 "
        "ORDER BY epoch ASC", (competition,)).fetchall()

    by_operator: dict[str, dict] = {}
    cat_solvers: dict[str, set] = {cat: set() for cat in SIX_AXES}
    solved_slugs_by_cat: dict[str, set] = {cat: set() for cat in SIX_AXES}
    recent_days: dict[str, int] = {}
    for r in acc_rows:
        op = r["operator"] or r["team_id"] or "(anon)"
        slug = r["challenge_slug"]
        cat = slug_to_cat.get(slug, "misc")
        if cat not in SIX_AXES:
            continue  # 仅统计六轴类别
        d = by_operator.setdefault(op, {
            "id": op, "solves": 0, "categories": {}, "first_clears": 0,
            "points": 0.0, "accepted_epochs": [],
        })
        d["solves"] += 1
        d["categories"][cat] = d["categories"].get(cat, 0) + 1
        d["accepted_epochs"].append(r["epoch"])
        cat_solvers[cat].add(op)
        solved_slugs_by_cat[cat].add(slug)
        try:
            day = datetime.fromtimestamp(r["epoch"], tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            day = ""
        if day:
            recent_days[day] = recent_days.get(day, 0) + 1

    # first_clears：每题首血者按 operator 聚合
    fb_map = _first_blood_map(conn, competition, "individual")
    for op, d in by_operator.items():
        d["first_clears"] = sum(1 for v in fb_map.values() if v == op)

    # points：每 operator accepted 题的 scoring_log 基础分值累加
    scores_by_slug: dict[str, float] = {}
    for r in conn.execute(
        "SELECT challenge_slug, points FROM scoring_log WHERE competition=?",
        (competition,)).fetchall():
        scores_by_slug[r["challenge_slug"]] = r["points"]
    for r in acc_rows:
        op = r["operator"] or r["team_id"] or "(anon)"
        if op in by_operator:
            by_operator[op]["points"] = round(
                by_operator[op]["points"] + scores_by_slug.get(r["challenge_slug"], 0), 2)

    operator_skill = {op: {ax: d["categories"].get(ax, 0) for ax in SIX_AXES}
                      for op, d in by_operator.items()}

    by_category = []
    for cat in SIX_AXES:
        total = cat_totals.get(cat, 0)
        solved_count = len(solved_slugs_by_cat.get(cat, set()))
        by_category.append({
            "category": cat, "total": total, "solved": solved_count,
            "coverage": round(solved_count / total, 3) if total else 0.0,
            "operators": sorted(cat_solvers.get(cat, set())),
        })

    total_challenges = len(challenges)
    solved_challenges = len({r["challenge_slug"] for r in acc_rows})
    coverage = {
        "solved_challenges": solved_challenges,
        "total_challenges": total_challenges,
        "ratio": round(solved_challenges / total_challenges, 3) if total_challenges else 0.0,
    }

    today = datetime.now(timezone.utc)
    recent_activity = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        recent_activity.append({"day": ds, "count": recent_days.get(ds, 0)})

    return {
        "by_operator": list(by_operator.values()),
        "by_category": by_category,
        "coverage": coverage,
        "recent_activity": recent_activity,
        "skill_axes": SIX_AXES,
        "operator_skill": operator_skill,
    }


def cmd_query(args) -> int:
    comp_dir = Path(args.comp_dir) if args.comp_dir else None
    scoring = _load_scoring_config(comp_dir)
    bonus = float(scoring.get("first_blood_bonus", 0.1)) if scoring else 0.1
    progress: dict = {}
    with connect(args.db) as conn:
        if args.mode == "team":
            sql = (
                "SELECT team_id AS id, "
                "  COUNT(DISTINCT challenge_slug) AS solves, "
                "  SUM(CASE WHEN outcome='accepted' AND dry_run=0 THEN 1 ELSE 0 END) AS accepted, "
                "  COUNT(*) AS total "
                "FROM submissions WHERE competition=? "
                "GROUP BY team_id ORDER BY accepted DESC, total ASC")
            rows = conn.execute(sql, (args.competition,)).fetchall()
        else:  # individual by operator
            sql = (
                "SELECT operator AS id, "
                "  COUNT(DISTINCT challenge_slug) AS solves, "
                "  SUM(CASE WHEN outcome='accepted' AND dry_run=0 THEN 1 ELSE 0 END) AS accepted, "
                "  COUNT(*) AS total "
                "FROM submissions WHERE competition=? AND operator != '' "
                "GROUP BY operator ORDER BY accepted DESC, total ASC")
            rows = conn.execute(sql, (args.competition,)).fetchall()
        # 取 scoring_log 的基础分值（不含首血加成）
        scores: dict[str, float] = {}
        for r in conn.execute(
            "SELECT challenge_slug, points FROM scoring_log WHERE competition=?",
            (args.competition,)).fetchall():
            scores[r["challenge_slug"]] = r["points"]
        # 每题首血者
        fb_map = _first_blood_map(conn, args.competition, args.mode)
        # 每队/人的首血数
        first_blood_count: dict[str, int] = {}
        for fb_id in fb_map.values():
            first_blood_count[fb_id] = first_blood_count.get(fb_id, 0) + 1
        # 计算每队/人的总分：sum(accepted 题基础分值) + sum(首血题的 base*bonus)
        result_rows = []
        for i, row in enumerate(rows):
            id_val = row["id"] or "(unassigned)"
            if args.mode == "team":
                accepted_slugs = [r["challenge_slug"] for r in conn.execute(
                    "SELECT DISTINCT challenge_slug FROM submissions WHERE competition=? AND team_id=? "
                    "AND outcome='accepted' AND dry_run=0",
                    (args.competition, id_val)).fetchall()]
            else:
                accepted_slugs = [r["challenge_slug"] for r in conn.execute(
                    "SELECT DISTINCT challenge_slug FROM submissions WHERE competition=? AND operator=? "
                    "AND outcome='accepted' AND dry_run=0",
                    (args.competition, id_val)).fetchall()]
            base_points_total = sum(scores.get(s, 0) for s in accepted_slugs)
            # 首血加成：只给该 id 首血的题目加 base*bonus
            fb_bonus_total = 0.0
            for slug in accepted_slugs:
                if fb_map.get(slug) == id_val:
                    grade = _challenge_grade(comp_dir, slug) if comp_dir else None
                    fb_bonus_total += _base_points(scoring, grade) * bonus
            total_points = base_points_total + fb_bonus_total
            result_rows.append({
                "rank": i + 1,
                "id": id_val,
                "name": id_val,
                "solves": row["accepted"],
                "points": round(total_points, 2),
                "first_bloods": first_blood_count.get(id_val, 0),
            })
        # 训练进度聚合（与 rows 并存：rows 兼容旧调用，progress 为训练仪表盘主结构）
        progress = _compute_progress(conn, args.competition, comp_dir)
    print(json.dumps({"rows": result_rows, "mode": args.mode,
                      "progress": progress}, ensure_ascii=False))
    return 0


def cmd_on_submission(args) -> int:
    record = json.loads(args.record)
    comp_dir = Path(args.comp_dir) if args.comp_dir else None
    with connect(args.db) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO submissions "
            "(epoch, time, competition, challenge_slug, team_id, operator, "
            " flag_sha256, outcome, dry_run, source, note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (float(record.get("epoch", 0)), record.get("time", ""), args.competition,
             record.get("challenge_slug", ""), record.get("team_id", ""),
             record.get("operator", ""), record.get("flag_sha256", ""),
             record.get("outcome", ""), int(bool(record.get("dry_run", True))),
             record.get("source", ""), record.get("note", "")))
        conn.commit()
        _recompute_scoring(conn, args.db, args.competition, comp_dir)
    print("ok")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("db", type=Path)
    init.set_defaults(func=cmd_init)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("db", type=Path)
    ingest.add_argument("--submissions", type=Path)
    ingest.add_argument("--events", type=Path)
    ingest.add_argument("--competition", required=True)
    ingest.add_argument("--comp-dir", type=Path)
    ingest.set_defaults(func=cmd_ingest)

    query = sub.add_parser("query")
    query.add_argument("db", type=Path)
    query.add_argument("--competition", required=True)
    query.add_argument("--mode", choices=["team", "individual"], default="individual")
    query.add_argument("--comp-dir", type=Path)
    query.set_defaults(func=cmd_query)

    compute = sub.add_parser("compute-scoring")
    compute.add_argument("db", type=Path)
    compute.add_argument("--competition", required=True)
    compute.add_argument("--comp-dir", type=Path)
    compute.set_defaults(func=cmd_compute_scoring)

    on_sub = sub.add_parser("on-submission")
    on_sub.add_argument("db", type=Path)
    on_sub.add_argument("--competition", required=True)
    on_sub.add_argument("--record", required=True)
    on_sub.add_argument("--comp-dir", type=Path)
    on_sub.set_defaults(func=cmd_on_submission)

    return root


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
