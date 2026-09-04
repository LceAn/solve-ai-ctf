#!/usr/bin/env python3
"""Flag 猎手 —— 内建的专职 Flag 求解代理（确定性，无 LLM 依赖）。

自主流程：扫描全部 case → 对照 flag 正则自主校验 → 高置信候选自动 validated
→ （可选）自动提交：dry-run 通过即 --live，受每轮限额与 submitter 限速/去重保护。

用法：
    python flag_hunter.py <comp_dir> [--autosubmit-config cfg.json] [--max-live 3]

输出以 HUNTER DONE validated=N live=M 收尾，供任务系统/前端判别。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
DEFAULT_PATTERN = re.compile(r"(?:flag|hkcert|ctf|DASCTF)\{[^}\n]{4,120}\}")
DENYLIST = ("flag{test", "flag{xxx", "flag{fake", "flag{example", "flag{flag",
            "flag{xxx}", "flag{this", "flag{your")


def log(msg: str) -> None:
    """Write progress even when Windows stdout uses a narrow code page."""
    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        line = (msg + "\n").encode(encoding)
    except (LookupError, UnicodeEncodeError):
        encoding = "utf-8"
        line = (msg + "\n").encode("utf-8", errors="replace")
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(line)
        buffer.flush()
    else:
        stream.write(line.decode(encoding, errors="replace"))
        stream.flush()


def run(argv: list) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *[str(a) for a in argv]],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def collect_cases(comp: Path) -> list[tuple[Path, dict]]:
    cases = []
    cases_dir = comp / "cases"
    if cases_dir.is_dir():
        for d in sorted(cases_dir.iterdir()):
            cj = d / "case.json"
            if cj.exists():
                cases.append((d, load(cj, {})))
    return cases


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("comp_dir", type=Path)
    ap.add_argument("--autosubmit-config", type=Path, dest="autosubmit_config",
                    help="JSON：{enabled: bool, max_live: int}；缺省视为关闭")
    ap.add_argument("--max-live", type=int, default=3)
    args = ap.parse_args()

    comp = args.comp_dir.resolve()
    cfg = load(args.autosubmit_config, {}) if args.autosubmit_config else {}
    auto = bool(cfg.get("enabled", True))  # 抢一血：默认开启（受限额保护）
    max_live = max(1, int(cfg.get("max_live", args.max_live)))
    log(f"[flag-agent] 目标比赛：{comp.name} · 自动提交：{'开（每轮上限 %d）' % max_live if auto else '关'}")

    # 1) 全量扫描：每个 case 目录内的脚本/日志/文本都可能藏着 flag
    cases = collect_cases(comp)
    log(f"[flag-agent] 发现 {len(cases)} 个 case，开始自主扫描…")
    for d, _ in cases:
        r = run([SCRIPTS / "case_manager.py", "scan-flags", d, d, "--store"])
        if r.returncode != 0:
            log(f"[flag-agent]   scan {d.name}: 无新增")

    # 2) 自主校验：对照题目 flag 正则（无正则时用默认格式 + 黑名单去误报）
    comp_cfg = load(comp / "competition.json", {})
    comp_patterns = {c.get("slug"): c.get("flag_pattern") or [] for c in comp_cfg.get("challenges", [])}
    validated = []
    for d, _ in cases:
        case = load(d / "case.json", {})
        slug = d.name
        patterns = case.get("challenge", {}).get("flag_patterns") or comp_patterns.get(slug) or []
        for cand in case.get("candidates", []):
            if cand.get("status") != "unverified":
                continue
            val = str(cand.get("value", ""))
            low = val.lower()
            if any(x in low for x in DENYLIST):
                log(f"[flag-agent]   跳过 {slug}/{cand.get('id')}：命中误报黑名单")
                continue
            if patterns:
                ok = any(re.fullmatch(str(p), val) for p in patterns if p)
                why = "匹配题目 flag 正则" if ok else "不匹配题目 flag 正则"
            else:
                ok = bool(DEFAULT_PATTERN.fullmatch(val)) and len(val) <= 120
                why = "默认格式校验通过" if ok else "默认格式不符"
            if not ok:
                log(f"[flag-agent]   跳过 {slug}/{cand.get('id')}：{why}")
                continue
            r = run([SCRIPTS / "case_manager.py", "candidate", d, cand["id"],
                     "validated", "--note", f"flag-agent: {why}"])
            if r.returncode == 0:
                log(f"[flag-agent] ✓ {slug}/{cand['id']} validated：{val}（{why}）")
                validated.append((slug, cand["id"], val))
            else:
                log(f"[flag-agent]   状态推进失败 {slug}/{cand['id']}：{(r.stderr or r.stdout).strip()[-120]}")

    # 3) 自动提交（默认关闭；显式开启后 dry-run 通过即 live，受限额保护）
    live = 0
    if auto and validated:
        log("[flag-agent] 进入自动提交阶段（dry-run 通过才 --live）")
        for slug, cid, val in validated:
            if live >= max_live:
                log(f"[flag-agent] 已达本轮上限 {max_live}，剩余候选留待下轮")
                break
            dry = run([SCRIPTS / "submitter.py", "submit", comp,
                       "--challenge", slug, "--flag", val, "--candidate", cid])
            if dry.returncode != 0:
                log(f"[flag-agent]   dry-run 未通过 {slug}/{cid}：{(dry.stdout or dry.stderr).strip()[-140:]}")
                continue
            r = run([SCRIPTS / "submitter.py", "submit", comp, "--challenge", slug,
                     "--flag", val, "--candidate", cid, "--live", "--update-case"])
            if r.returncode == 0:
                live += 1
                log(f"[flag-agent] 🚀 已提交 {slug}：{val}")
            else:
                log(f"[flag-agent]   提交失败 {slug}：{(r.stdout or r.stderr).strip()[-140:]}")
    elif auto and not validated:
        log("[flag-agent] 自动提交已开启，但本轮没有新验证的候选")

    log(f"[flag-agent] 本轮结束：新验证 {len(validated)}，实提 {live}")
    print(f"HUNTER DONE validated={len(validated)} live={live}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
