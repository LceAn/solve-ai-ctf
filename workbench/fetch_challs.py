#!/usr/bin/env python3
"""抓题代理 —— 从平台拉取题目列表，批量注册进工作台（每题一个 case）。

前提：platform.challenges 已配置（platform_agent 探测成功或人工填写）+ 平台令牌环境变量。
流程：GET 列表 → 按 map 取字段 → 逐题 add-challenge 注册 → 打印进度。
进度全部走 stdout，以 FETCH DONE registered=N skipped=M 收尾。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import ctf_session

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
CAT_NORMALIZE = {"pwn": "pwn", "web": "web", "crypto": "crypto", "misc": "misc",
                 "reverse": "reverse", "re": "reverse", "basic": "misc", "real": "misc",
                 "n1book": "misc", "dasbook": "misc"}


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


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def fetch_items(opener, base: str, ch_cfg: dict, token: str, token_prefix: str):
    url = base + str(ch_cfg.get("path", ""))
    method = ch_cfg.get("method", "GET")
    if opener is not None:
        _, data = ctf_session.get_json(opener, url, timeout=30)
    else:
        req = urllib.request.Request(url, method=method)
        if token:
            req.add_header("Authorization", (token_prefix + token) if token_prefix else token)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    items_field = ch_cfg.get("items_field", "data")
    items = data
    for key in items_field.split("."):
        items = items[key]
    return items


def field(item: dict, key: str):
    v = item.get(key)
    return v if v is not None else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("comp_dir", type=Path)
    ap.add_argument("--limit", type=int, default=0, help="最多注册 N 题（0=不限）")
    ap.add_argument("--categories", default="", help="逗号分隔的类别过滤（如 web,crypto）")
    args = ap.parse_args()
    comp = args.comp_dir.resolve()
    cfg = load(comp / "competition.json", None)
    if not isinstance(cfg, dict):
        log("[chall-agent] ✗ competition.json 不存在")
        print("FETCH DONE registered=0 skipped=0 reason=no-config")
        return 1

    platform = cfg.get("platform") or {}
    ch_cfg = platform.get("challenges") or {}
    if not ch_cfg.get("path"):
        log("[chall-agent] ✗ platform.challenges 未配置：先运行「自动对接平台」或人工填写")
        print("FETCH DONE registered=0 skipped=0 reason=no-challenges-config")
        return 1

    token_env = (platform.get("auth") or {}).get("value_env") or "CTF_TOKEN"
    token = os.environ.get(token_env, "")
    login_cfg = platform.get("login") or {}
    if not token and not login_cfg.get("path"):
        log(f"[chall-agent] ✗ 无可用认证：未设置令牌 {token_env}，也没有 login 配置")
        print("FETCH DONE registered=0 skipped=0 reason=no-auth")
        return 1

    base = (platform.get("base_url") or "").rstrip("/")
    prefix = (platform.get("auth") or {}).get("value_prefix") or "Token "
    opener = None
    login_cfg = platform.get("login") or {}
    if login_cfg.get("path"):
        opener = ctf_session.build_opener()
        try:
            ctf_session.login(opener, base, login_cfg)
            log("[chall-agent] ✓ 平台登录成功（session）")
        except ValueError as exc:
            log(f"[chall-agent] ✗ {exc}")
            print("FETCH DONE registered=0 skipped=0 reason=login-failed")
            return 1
    cat_filter = {c.strip().lower() for c in args.categories.split(",") if c.strip()}
    log(f"[chall-agent] 拉取题目列表：{base}{ch_cfg.get('path')}"
        + (f"（过滤 {','.join(cat_filter)}，上限 {args.limit or '∞'}）" if (cat_filter or args.limit) else ""))
    try:
        items = fetch_items(opener, base, ch_cfg, token, prefix)
    except Exception as exc:  # noqa: BLE001
        log(f"[chall-agent] ✗ 拉取失败：{type(exc).__name__} {exc}")
        print("FETCH DONE registered=0 skipped=0 reason=fetch-failed")
        return 1
    if cat_filter:
        cat_key = (ch_cfg.get("map") or {}).get("category", "category")
        items = [it for it in items if str(field(it, cat_key)).lower() in cat_filter]

    m = ch_cfg.get("map") or {}
    log(f"[chall-agent] 列表含 {len(items)} 题，开始逐题注册…")
    registered = skipped = 0
    existing = {c.get("slug") for c in cfg.get("challenges", [])}
    for it in items:
        name = str(field(it, m.get("name", "name")) or f"chall-{field(it, m.get('id', 'id'))}")
        cid = str(field(it, m.get("id", "id")))
        raw_cat = str(field(it, m.get("category", "category")) or "misc").lower()
        category = CAT_NORMALIZE.get(raw_cat, raw_cat)
        if category not in ("crypto", "pwn", "reverse", "web", "misc", "forensics"):
            category = "misc"
        if args.limit and registered >= args.limit:
            log(f"[chall-agent] 已达 --limit {args.limit}，停止注册")
            break
        points = field(it, m.get("points", "points"))
        try:
            points = float(points) if points != "" else None
        except (TypeError, ValueError):
            points = None
        slug = f"c{cid}" if cid else f"chall-{registered + skipped + 1}"
        if slug in existing:
            log(f"[chall-agent] · 跳过 {name}（slug 已存在）")
            skipped += 1
            continue
        argv = [SCRIPTS / "competition.py", "add-challenge", comp,
                "--name", name, "--category", category, "--slug", slug,
                "--challenge-id", cid]
        if points:
            argv += ["--points", str(points)]
        r = subprocess.run([sys.executable, *map(str, argv)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            registered += 1
            log(f"[chall-agent] ✓ {name}（{category} · {points or '?'} 分 · 平台ID {cid}）")
        else:
            skipped += 1
            log(f"[chall-agent]   注册失败 {name}：{(r.stderr or r.stdout).strip()[-120]}")

    log(f"[chall-agent] 提醒：附件需在题目工作区手动放置（artifacts/），容器沙箱会挂载为 /workspace")
    print(f"FETCH DONE registered={registered} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
