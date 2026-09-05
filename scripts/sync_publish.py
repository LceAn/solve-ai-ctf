#!/usr/bin/env python3
"""N-04：主目录 → 发布副本的单向同步，结束后 diff 断言零差异。

用法：
    python scripts/sync_publish.py                        # 默认同步到 ../_publish/<repo名>/
    python scripts/sync_publish.py --target D:/copy/ctf   # 指定目标

排除构建产物与本地数据（__pycache__ / .git / workbench-data / 比赛 / *.log 等），
目标侧多出的文件会被删除，保证与源目录严格一致；任何差异导致非零退出。
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

EXCLUDE_DIRS = {"__pycache__", ".git", "workbench-data", "比赛", ".warroom", "node_modules", "scratch"}
EXCLUDE_PATTERNS = ("*.pyc", "*.log", "*.tar", "*.tar.gz")


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.is_dir():
            continue
        if any(p.match(pat) for pat in EXCLUDE_PATTERNS):
            continue
        yield rel, p


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=repo,
                    help="源目录（默认仓库根）")
    ap.add_argument("--target", type=Path,
                    default=repo.parent / "_publish" / repo.name,
                    help="发布副本目录（默认 ../_publish/<repo名>）")
    args = ap.parse_args()
    src, dst = args.source.resolve(), args.target.resolve()
    if not (src / "workbench" / "server.py").is_file():
        print(f"✗ 源目录不像仓库根（缺 workbench/server.py）：{src}", file=sys.stderr)
        return 2

    src_files = dict(iter_files(src))
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for rel, sp in src_files.items():
        dp = dst / rel
        if not dp.exists() or not filecmp.cmp(sp, dp, shallow=False):
            dp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sp, dp)
            copied += 1
    removed = 0
    for rel, dp in list(iter_files(dst)):
        if rel not in src_files:
            dp.unlink()
            removed += 1

    # diff 断言：双向一致
    diffs = [str(rel) for rel, sp in src_files.items()
             if not (dst / rel).is_file() or not filecmp.cmp(sp, dst / rel, shallow=False)]
    extras = [str(rel) for rel, _ in iter_files(dst) if rel not in src_files]
    print(f"同步 {src} → {dst}：复制 {copied}，删除多余 {removed}")
    for d in diffs:
        print(f"  ✗ 差异：{d}")
    for e in extras:
        print(f"  ✗ 多余：{e}")
    if diffs or extras:
        print(f"SYNC FAILED diffs={len(diffs)} extras={len(extras)}")
        return 1
    print(f"SYNC OK files={len(src_files)}（diff 断言零差异）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
