#!/usr/bin/env python3
"""Ranked lexical search over the solve-ai-ctf reference files."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CATEGORY_FILES = {
    "web": {"playbooks-web-ai.md", "triage-routing.md", "case-corpus.md"},
    "ai": {"playbooks-web-ai.md", "triage-routing.md", "environment.md"},
    "pwn": {"playbooks-pwn.md", "triage-routing.md", "case-corpus.md"},
    "crypto": {"playbooks-crypto-reverse.md", "triage-routing.md", "case-corpus.md"},
    "reverse": {"playbooks-crypto-reverse.md", "triage-routing.md", "case-corpus.md"},
    "forensics": {"playbooks-forensics-misc.md", "triage-routing.md", "case-corpus.md"},
    "misc": {"playbooks-forensics-misc.md", "triage-routing.md", "case-corpus.md"},
    "architecture": {"architecture-operations.md", "evaluation-governance.md", "environment.md"},
}


@dataclass
class Hit:
    score: float
    path: Path
    line_no: int
    line: str
    context: list[str]


def tokens(query: str) -> list[str]:
    found = re.findall(r"[A-Za-z0-9_+.-]+|[\u4e00-\u9fff]{2,}", query.lower())
    return list(dict.fromkeys(token for token in found if len(token) > 1))


def score_line(line: str, words: list[str], heading: bool) -> float:
    lowered = line.lower()
    score = 0.0
    for word in words:
        count = lowered.count(word)
        if count:
            score += 2.0 + min(count, 3)
            if heading:
                score += 2.0
    if words and all(word in lowered for word in words):
        score += 5.0
    return score


def search(query: str, category: str | None, context_lines: int) -> list[Hit]:
    reference_dir = Path(__file__).resolve().parent.parent / "references"
    allowed = CATEGORY_FILES.get(category, None) if category else None
    words = tokens(query)
    if not words:
        return []
    hits: list[Hit] = []
    for path in sorted(reference_dir.glob("*.md")):
        if allowed is not None and path.name not in allowed:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            value = score_line(line, words, line.lstrip().startswith("#"))
            if value <= 0:
                continue
            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)
            hits.append(Hit(value, path, index + 1, line, lines[start:end]))
    return sorted(hits, key=lambda hit: (-hit.score, hit.path.name, hit.line_no))


def _log_path() -> Path:
    return Path(__file__).resolve().parents[1] / "workbench-data" / "kb_queries.jsonl"


def log_query(query: str, category: str | None, top: int, hits: int) -> None:
    """R6（N-09③）：检索日志——命中数随查询落盘，供 --stats 反哺知识库补洞。"""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"time": datetime.now(timezone.utc).isoformat(),
                  "query": query, "category": category, "top": top, "hits": len(hits)}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 统计是尽力而为，绝不能影响检索本身


def stats(last: int = 500) -> int:
    path = _log_path()
    if not path.exists():
        print("No queries logged yet（检索会自动记录到 workbench-data/kb_queries.jsonl）")
        return 0
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip()][-last:]
    records = [json.loads(line) for line in lines]
    zero = [r for r in records if r["hits"] == 0]
    hit_count = len(records) - len(zero)
    print(f"检索 {len(records)} 次：有命中 {hit_count}（{hit_count * 100 // max(len(records), 1)}%）· 零命中 {len(zero)}")
    if zero:
        print("\n零命中查询（知识库补洞候选，按出现频次）：")
        counter = Counter(r["query"].strip().lower() for r in zero)
        for query, count in counter.most_common(15):
            print(f"  ×{count}  {query}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="", help="检索词；--stats 时忽略")
    parser.add_argument("--category", choices=sorted(CATEGORY_FILES))
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--context", type=int, default=1)
    parser.add_argument("--stats", action="store_true",
                        help="查看检索命中率统计与零命中查询清单（N-09③）")
    args = parser.parse_args()
    if args.stats or not args.query:
        return stats()
    hits = search(args.query, args.category, max(0, args.context))[: max(1, args.top)]
    log_query(args.query, args.category, args.top, hits)
    if not hits:
        print("No matches")
        return 1
    for hit in hits:
        print(f"{hit.path.name}:{hit.line_no} score={hit.score:.1f}")
        for line in hit.context:
            print(f"  {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
