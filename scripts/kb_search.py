#!/usr/bin/env python3
"""Ranked lexical search over the solve-ai-ctf reference files."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CATEGORY_FILES = {
    "web": {"playbooks-web-ai.md",
            "SQL.md", "SSTI.md", "SSRF漏洞.md", "JWT.md", "命令执行.md",
            "文件上传漏洞.md", "文件包含.md", "文件包含漏洞.md",
            "PHP反序列化漏洞总结.md", "php代码审计.md"},
    "ai": {"playbooks-web-ai.md", "environment.md"},
    "pwn": {"playbooks-pwn.md"},
    "crypto": {"playbooks-crypto-reverse.md"},
    "reverse": {"playbooks-crypto-reverse.md"},
    "forensics": {"playbooks-forensics-misc.md",
                  "图片隐写.md", "音频隐写.md", "压缩包总结.md"},
    "misc": {"playbooks-forensics-misc.md",
             "压缩包总结.md", "图片隐写.md"},
    "architecture": {"architecture-operations.md", "evaluation-governance.md", "environment.md"},
}

# 所有方向都该检索到的通用文档（分诊路由、案例语料、payload 速查）
COMMON_FILES = {"triage-routing.md", "case-corpus.md", "PAYLOAD-CHEATSHEET.md"}

# 不参与内容检索：索引与署名类文件会把每篇文档的标题都复制一份，
# 一搜就高分霸榜，把真正的正文挤下去（外部库路径用 IDX_SUFFIX 挡同类噪声）。
EXCLUDED_FROM_SEARCH = {"AI-SEARCH-INDEX.md", "KB-ATTRIBUTION.md",
                        "case-corpus-template.md"}  # R35：回填模板非检索语料

# references/links.json：外部学习资源 registry（脱敏，无 token/credential/flag）
LINKS_FILE = Path(__file__).resolve().parent.parent / "references" / "links.json"

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "references"

# 外部知识库目录（用户通过 KB_EXTERNAL_DIR 环境变量指向本地 clone 的知识库）
EXTERNAL_KB_DIR = os.environ.get("KB_EXTERNAL_DIR")
MAX_EXTERNAL_FILES = 200        # 单次扫描文件数上限（防 1156 WP 全扫描拖慢）
MAX_LINES_PER_FILE = 5000       # 单文件行数上限（防 6959 行大文件拖慢）
IDX_SUFFIX = ".idx.md"          # 仓库的 idx 索引文件，跳过避免噪声命中


def allowed_files(category: str | None) -> set[str] | None:
    """按方向返回可检索文档集；未指定方向返回 None（代表全部）。

    注意：这是硬编码白名单，新增 references/*.md 若忘了登记就会被静默排除——
    `test_workbench.py` 有一条"无孤儿文档"断言守着这一点。
    """
    if not category:
        return None
    return CATEGORY_FILES.get(category, set()) | COMMON_FILES


def searchable(path: Path) -> bool:
    """索引/署名类文件不进内容检索。"""
    return path.name not in EXCLUDED_FROM_SEARCH


@dataclass
class Hit:
    score: float
    path: Path
    line_no: int
    line: str
    context: list[str]
    kind: str = "reference"  # reference|writeup|external|external_kb
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
    allowed = allowed_files(category)
    words = tokens(query)
    if not words:
        return []
    hits: list[Hit] = []
    for path in sorted(REFERENCE_DIR.glob("*.md")):
        if not searchable(path):
            continue
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
        allowed = allowed_files(category)
        for path in sorted(REFERENCE_DIR.glob("*.md")):
            if not searchable(path):
                continue
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

    # 4. 外部知识库目录（KB_EXTERNAL_DIR 指向用户本地 clone 的 Markdown 知识库）
    if kind in ("all", "external_kb") and EXTERNAL_KB_DIR and Path(EXTERNAL_KB_DIR).is_dir():
        kb_root = Path(EXTERNAL_KB_DIR)
        file_count = 0
        for path in sorted(kb_root.rglob("*.md")):
            if path.name.endswith(IDX_SUFFIX):
                continue  # 跳过仓库的 idx 索引文件（避免噪声命中）
            if file_count >= MAX_EXTERNAL_FILES:
                break  # 单次扫描文件数上限，防 1156 WP 全扫描拖慢
            file_count += 1
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            if len(lines) > MAX_LINES_PER_FILE:
                lines = lines[:MAX_LINES_PER_FILE]  # 大文件截断（如 6959 行 PHP 反序列化）
            for index, line in enumerate(lines):
                value = score_line(line, words, line.lstrip().startswith("#"))
                if value <= 0:
                    continue
                start = max(0, index - context_lines)
                end = min(len(lines), index + context_lines + 1)
                hits.append(Hit(value, path, index + 1, line, lines[start:end],
                                kind="external_kb", source=path.name))

    return sorted(hits, key=lambda hit: (-hit.score, hit.kind, hit.source, hit.line_no))


def cmd_search(args) -> int:
    hits = search(args.query, args.category, max(0, args.context))[: max(1, args.top)]
    log_query(args.query, args.category, args.top, hits)  # R6：检索记账
    if not hits:
        print("No matches")
        return 1
    for hit in hits:
        print(f"{hit.path.name}:{hit.line_no} score={hit.score:.1f}")
        for line in hit.context:
            print(f"  {line}")
        print()
    return 0

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
    known_commands = {"search", "resources", "stats"}
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        return stats()
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
                              choices=["all", "reference", "writeup", "external", "external_kb"],
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
