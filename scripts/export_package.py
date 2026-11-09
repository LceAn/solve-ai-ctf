#!/usr/bin/env python3
"""比赛交付打包：writeup + case 记录 + 复盘报告 → 单个 zip（真实 flag 一律脱敏）。

用法：
    python export_package.py 比赛/xxx                      # 输出到 比赛/xxx/交付/
    python export_package.py 比赛/xxx --include-artifacts  # 连附件一起打
    python export_package.py 比赛/xxx --out /tmp/deliver

stdout 输出一行 JSON：{zip, files, bytes, redacted, out_dir}
退出码 0 成功；非 0 时 stderr 给出原因。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
# 与 competition.py 报告口径一致：常见赛制前缀 + 任意大小写
FLAG_RE = re.compile(r"(?i)(?:flag|hkcert|ctf|nssctf|buu|n1ctf|dasctf|hgame)\{[^}\n]{4,200}\}")
SKIP_DIRS = {"__pycache__", ".git", "交付", "workbench-data", ".venv"}
MAX_ARTIFACT = 20 * 1024 * 1024


class Redactor:
    """把任何形似 flag 的字符串替换为 sha256 前 8 位关联标识。"""

    def __init__(self) -> None:
        self.count = 0

    def text(self, value: str) -> str:
        def _sub(m: re.Match) -> str:
            self.count += 1
            raw = m.group(0)
            return (raw.split("{", 1)[0] + "{…脱敏·sha256:"
                    + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8] + "}")

        return FLAG_RE.sub(_sub, str(value))

    def obj(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.obj(v) for v in value]
        if isinstance(value, dict):
            return {k: self.obj(v) for k, v in value.items()}
        return value


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("comp_dir", type=Path)
    ap.add_argument("--out", type=Path, help="输出目录（默认 比赛/<name>/交付）")
    ap.add_argument("--include-artifacts", action="store_true", help="把题目附件一并打包")
    ap.add_argument("--solved-only", action="store_true",
                    help="只打包已解/已交题目（正式交付常用）")
    args = ap.parse_args()

    comp = args.comp_dir.resolve()
    if not comp.is_dir():
        print(f"比赛目录不存在：{comp}", file=sys.stderr)
        return 2
    data = load_json(comp / "competition.json", {})
    name = str(data.get("name") or comp.name)
    out_dir = (args.out or (comp / "交付")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name).strip("-")[:40] or "competition"
    zip_path = out_dir / f"{safe}-{stamp}.zip"
    root = f"{safe}-交付"
    red = Redactor()
    files = 0

    challenges = data.get("challenges") or []
    cases: list[tuple[str, dict]] = []
    for case_json in sorted((comp / "cases").glob("*/case.json")):
        slug = case_json.parent.name
        payload = load_json(case_json, {})
        cases.append((slug, payload))
    if args.solved_only:
        done = {"solved", "submitted", "closed"}
        cases = [(s, p) for s, p in cases if str(p.get("status")) in done]
        keep = {s for s, _ in cases}
        challenges = [c for c in challenges if str(c.get("slug")) in keep]

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) 复盘报告（复用 competition.py report，输出到临时目录避免污染比赛目录）
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "report.md"
            try:
                subprocess.run(
                    [sys.executable, str(SCRIPTS / "competition.py"), "report",
                     str(comp), "--output", str(tmp)],
                    capture_output=True, text=True, timeout=90, check=False,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"warn: report 生成失败：{exc}", file=sys.stderr)
            if tmp.exists():
                zf.writestr(f"{root}/复盘报告.md", red.text(tmp.read_text(encoding="utf-8")))
                files += 1

        # 2a) 比赛级 docs/*.md（通常就是 writeup）
        docs_dir = comp / "docs"
        if docs_dir.is_dir():
            for doc in sorted(docs_dir.glob("*.md")):
                zf.writestr(f"{root}/writeups/{doc.name}",
                            red.text(doc.read_text(encoding="utf-8", errors="replace")))
                files += 1

        # 2b) 逐题 case + writeup + 小结（summary.md 是工作区生成的题目小结，含解题叙述）
        for slug, payload in cases:
            zf.writestr(f"{root}/cases/{slug}.json",
                        json.dumps(red.obj(payload), ensure_ascii=False, indent=1))
            files += 1
            case_dir = comp / "cases" / slug
            for wp in sorted(case_dir.glob("[Ww][Rr][Ii][Tt][Ee][Uu][Pp]*.md")):
                zf.writestr(f"{root}/writeups/{slug}-{wp.name}",
                            red.text(wp.read_text(encoding="utf-8", errors="replace")))
                files += 1
            sm = case_dir / "summary.md"
            if sm.exists():
                zf.writestr(f"{root}/writeups/{slug}-summary.md",
                            red.text(sm.read_text(encoding="utf-8", errors="replace")))
                files += 1
            if args.include_artifacts:
                art = case_dir / "artifacts"
                if art.is_dir():
                    for f in sorted(art.rglob("*")):
                        if not f.is_file() or any(p in SKIP_DIRS for p in f.parts):
                            continue
                        if f.stat().st_size > MAX_ARTIFACT:
                            print(f"warn: 跳过超大附件 {f.name}", file=sys.stderr)
                            continue
                        zf.write(f, f"{root}/artifacts/{slug}/{f.relative_to(art)}")
                        files += 1

        # 3) 事件流（脱敏）
        events = comp / "events.jsonl"
        if events.exists():
            zf.writestr(f"{root}/events.jsonl",
                        red.text(events.read_text(encoding="utf-8", errors="replace")))
            files += 1

        # 4) 交付说明（索引 + 脱敏声明）
        solved = sum(1 for _, c in cases
                     if str(c.get("status")) in {"solved", "submitted", "closed"})
        wp_count = (len(list((comp / "docs").glob("*.md"))) if (comp / "docs").is_dir() else 0) + \
            sum(len(list((comp / "cases" / s).glob("WRITEUP*.md"))) for s, _ in cases)
        lines = [
            f"# {name} · 交付包",
            "",
            f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 题目：{len(challenges)} 题（case 记录 {len(cases)} 份，已解/已交 {solved}）"
            + ("　**范围：仅已解题目**" if args.solved_only else ""),
            f"- writeup：{wp_count} 份"
            + ("（比赛级 docs 为全部文档，不随题目过滤）" if args.solved_only else ""),
            f"- 附件：{'已包含' if args.include_artifacts else '未包含（需要时用 --include-artifacts 重新打包）'}",
            f"- 平台：{data.get('platform', {}).get('base_url') or '未配置'}"
            if isinstance(data.get("platform"), dict) else "- 平台：未配置",
            "",
            "## 目录结构",
            "",
            "| 路径 | 内容 |",
            "| --- | --- |",
            "| `复盘报告.md` | 总览、事件统计、逐题假设与尝试、环境镜像 |",
            "| `writeups/` | 每题 writeup（`<slug>-WRITEUP.md`） |",
            "| `cases/` | 结构化解题记录（状态/假设/尝试/证据/候选） |",
            "| `events.jsonl` | 比赛事件流 |",
            "| `artifacts/` | 题目附件（仅 `--include-artifacts` 时包含） |",
            "",
            "## 脱敏说明",
            "",
            "所有真实 flag 已替换为 `flag{…脱敏·sha256:xxxxxxxx}`，可凭 sha256 前 8 位与平台记录对照；",
            "case 记录中的假设、尝试、证据文本同样经过脱敏。附件（如启用）为原始比赛材料，未做改写。",
            "",
            "## 题目清单",
            "",
            "| 题目 | 状态 | 分数 | writeup |",
            "| --- | --- | --- | --- |",
        ]
        for ch in challenges:
            slug = str(ch.get("slug") or "")
            c = next((p for s, p in cases if s == slug), {})
            has_wp = "✓" if slug and list((comp / "cases" / slug).glob("WRITEUP*.md")) else "—"
            lines.append(f"| {ch.get('name') or slug} | {c.get('status') or 'new'} | "
                         f"{ch.get('points') if ch.get('points') is not None else '—'} | {has_wp} |")
        zf.writestr(f"{root}/交付说明.md", "\n".join(lines) + "\n")
        files += 1

    # 只保留最近 5 个交付包（每次点击都会生成新包，避免无限堆积）
    for stale in sorted(out_dir.glob("*.zip"), key=lambda x: x.stat().st_mtime,
                        reverse=True)[5:]:
        try:
            stale.unlink()
        except OSError:
            pass

    size = zip_path.stat().st_size
    print(json.dumps({
        "ok": True, "zip": str(zip_path), "name": zip_path.name,
        "files": files, "bytes": size, "redacted": red.count, "out_dir": str(out_dir),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
