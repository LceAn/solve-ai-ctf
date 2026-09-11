#!/usr/bin/env python3
"""Ranked lexical search over the solve-ai-ctf reference files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
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

# references/links.json：外部学习资源 registry（脱敏，无 token/credential/flag）
LINKS_FILE = Path(__file__).resolve().parent.parent / "references" / "links.json"


@dataclass
class Hit:
    score: float
    path: Path
    line_no: int
    line: str
    context: list[str]
    kind: str = "reference"  # reference|writeup|external
    source: str = ""  # 文件名或 URL


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
    """原 search 行为：仅索引 references/*.md。Hit.kind="reference"，source=path.name。"""
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
            hits.append(Hit(value, path, index + 1, line, lines[start:end],
                            kind="reference", source=path.name))
    return sorted(hits, key=lambda hit: (-hit.score, hit.path.name, hit.line_no))


def search_resources(query: str, category: str | None, kind: str,
                     comp_dir: Path | None, context_lines: int) -> list[Hit]:
    """资源库搜索：reference + writeup + external 三类。

    kind: "all" | "reference" | "writeup" | "external"
    comp_dir: 比赛目录（用于 docs/*.md writeup 索引），可选
    """
    words = tokens(query)
    if not words:
        return []
    hits: list[Hit] = []

    # 1. references/*.md
    if kind in ("all", "reference"):
        reference_dir = Path(__file__).resolve().parent.parent / "references"
        allowed = CATEGORY_FILES.get(category, None) if category else None
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
                hits.append(Hit(value, path, index + 1, line, lines[start:end],
                                kind="reference", source=path.name))

    # 2. docs/*.md（writeup）
    if kind in ("all", "writeup") and comp_dir is not None:
        docs_dir = comp_dir / "docs"
        if docs_dir.is_dir():
            for path in sorted(docs_dir.glob("*.md")):
                lines = path.read_text(encoding="utf-8").splitlines()
                for index, line in enumerate(lines):
                    value = score_line(line, words, line.lstrip().startswith("#"))
                    if value <= 0:
                        continue
                    start = max(0, index - context_lines)
                    end = min(len(lines), index + context_lines + 1)
                    hits.append(Hit(value, path, index + 1, line, lines[start:end],
                                    kind="writeup", source=path.name))

    # 3. links.json（external）
    if kind in ("all", "external") and LINKS_FILE.exists():
        try:
            links = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
            if isinstance(links, dict):
                links = links.get("links", [])
            for link in links:
                title = link.get("title", "")
                note = link.get("note", "")
                link_category = link.get("category", "")
                if category and link_category != category:
                    continue
                # 用 score_line 评 title+note 拼接
                combined = f"{title} {note}"
                value = score_line(combined, words, False)
                if value <= 0:
                    continue
                hits.append(Hit(value, LINKS_FILE, 0, title, [note] if note else [],
                                kind="external", source=link.get("url", "")))
        except Exception:
            pass

    return sorted(hits, key=lambda hit: (-hit.score, hit.kind, hit.source, hit.line_no))


def cmd_search(args) -> int:
    hits = search(args.query, args.category, max(0, args.context))[: max(1, args.top)]
    if not hits:
        print("No matches")
        return 1
    for hit in hits:
        print(f"{hit.path.name}:{hit.line_no} score={hit.score:.1f}")
        for line in hit.context:
            print(f"  {line}")
        print()
    return 0


def cmd_resources(args) -> int:
    hits = search_resources(args.query, args.category, args.kind, args.comp_dir,
                            max(0, args.context))[: max(1, args.top)]
    if not hits:
        print("No matches")
        return 1
    # JSON 输出便于 server.py 转发
    out = [{
        "score": hit.score, "path": str(hit.path), "line_no": hit.line_no,
        "line": hit.line, "context": hit.context,
        "kind": hit.kind, "source": hit.source,
    } for hit in hits]
    print(json.dumps({"hits": out, "count": len(out)}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    # 向后兼容：argv[1] 不是已知子命令时，走原 positional query 模式
    known_commands = {"search", "resources"}
    if len(sys.argv) <= 1 or sys.argv[1] not in known_commands:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("query")
        parser.add_argument("--category", choices=sorted(CATEGORY_FILES))
        parser.add_argument("--top", type=int, default=10)
        parser.add_argument("--context", type=int, default=1)
        args = parser.parse_args()
        return cmd_search(args)

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")

    search_cmd = sub.add_parser("search")
    search_cmd.add_argument("query")
    search_cmd.add_argument("--category", choices=sorted(CATEGORY_FILES))
    search_cmd.add_argument("--top", type=int, default=10)
    search_cmd.add_argument("--context", type=int, default=1)
    search_cmd.set_defaults(func=cmd_search)

    resources_cmd = sub.add_parser("resources")
    resources_cmd.add_argument("query")
    resources_cmd.add_argument("--category", choices=sorted(CATEGORY_FILES))
    resources_cmd.add_argument("--kind",
                              choices=["all", "reference", "writeup", "external"],
                              default="all")
    resources_cmd.add_argument("--comp-dir", type=Path)
    resources_cmd.add_argument("--top", type=int, default=20)
    resources_cmd.add_argument("--context", type=int, default=1)
    resources_cmd.set_defaults(func=cmd_resources)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
