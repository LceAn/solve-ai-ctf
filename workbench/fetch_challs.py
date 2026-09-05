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
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import ctf_session
from platform_adapters import get_adapter

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
CAT_NORMALIZE = {"pwn": "pwn", "web": "web", "crypto": "crypto", "misc": "misc",
                 "reverse": "reverse", "re": "reverse", "basic": "misc", "real": "misc",
                 "n1book": "misc", "dasbook": "misc",
                 "ai": "ai", "llm": "ai", "model": "ai", "ai-security": "ai"}


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


def authed_get(opener, url: str, token: str, token_prefix: str, timeout: int = 30):
    """带认证的 GET：session opener 优先（BUUCTF 表单登录），否则令牌头。"""
    if opener is not None:
        return opener.open(urllib.request.Request(url, method="GET"), timeout=timeout)
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", (token_prefix + token) if token_prefix else token)
    req.add_header("Accept", "application/json")
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_detail_files(opener, base: str, detail_cfg: dict, cid: str,
                       token: str, token_prefix: str) -> list[str]:
    """按 challenge_detail 配置拉题目详情，返回附件相对路径列表（R1）。"""
    path = str(detail_cfg.get("path", "")).replace("{id}", str(cid))
    if not path:
        return []
    with authed_get(opener, base + path, token, token_prefix) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    files = data
    for key in str(detail_cfg.get("files_field", "data.files")).split("."):
        files = files[key]
    if not isinstance(files, list):
        return []
    return [str(f) for f in files if str(f).strip()]


def download_artifacts(opener, base: str, detail_cfg: dict, cid: str, slug: str,
                       case_dir: Path, token: str, token_prefix: str, scripts: Path) -> tuple[int, int]:
    """下载题目附件 → case_manager artifact-add 落库（sha256 + 不可变存储）。返回 (成功数, 失败数)。"""
    ok = fail = 0
    try:
        files = fetch_detail_files(opener, base, detail_cfg, cid, token, token_prefix)
    except Exception as exc:  # noqa: BLE001
        log(f"[chall-agent]   · {slug}: 附件清单获取失败 {type(exc).__name__}（不影响注册）")
        return 0, 1
    if not files:
        return 0, 0
    max_files = int(detail_cfg.get("max_files", 10))
    tmp_root = Path(tempfile.mkdtemp(prefix="ctfwb-art-"))
    try:
        for i, fpath in enumerate(files[:max_files]):
            fpath = fpath.strip()
            url = base + (fpath if fpath.startswith("/") else "/" + fpath)
            name = fpath.rstrip("/").split("?")[0].split("/")[-1] or f"artifact-{i + 1}"
            tmp = tmp_root / f"{i:02d}-{name}"
            try:
                with authed_get(opener, url, token, token_prefix, timeout=120) as resp:
                    tmp.write_bytes(resp.read())
                argv = [sys.executable, str(scripts / "case_manager.py"), "artifact-add",
                        str(case_dir), "--file", str(tmp), "--name", name, "--source", "platform"]
                r = subprocess.run(argv, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
                if r.returncode == 0:
                    ok += 1
                    log(f"[chall-agent]   ✓ {slug} 附件 {name}（{tmp.stat().st_size} bytes → artifacts/）")
                else:
                    fail += 1
                    log(f"[chall-agent]   ✗ {slug} 附件 {name} 登记失败：{(r.stderr or '').strip()[-100]}")
            except Exception as exc:  # noqa: BLE001
                fail += 1
                log(f"[chall-agent]   ✗ {slug} 附件 {name} 下载失败 {type(exc).__name__}")
        if len(files) > max_files:
            log(f"[chall-agent]   · {slug}: 附件超过 max_files={max_files}，已截断（共 {len(files)}）")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return ok, fail


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


def reconcile(opener, base: str, platform: dict, token: str, token_prefix: str,
              comp: Path, cfg: dict) -> int:
    """R16（N-13②）：平台已解列表 → 本地 case 状态对账。

    配置 platform.solved = {"path": "/api/v1/users/me/solves", "items_field": "data",
    "map": {"challenge_id": "challenge_id"}}；每个平台已解且本地 case 未标记
    solved/submitted 的题目，写一条 platform_solved_detected 事件（审计流），
    不自动改状态——是否采信由人确认。
    """
    solved_cfg = platform.get("solved") or {}
    if not solved_cfg.get("path"):
        log("[chall-agent] ✗ 对账需要 platform.solved 配置（path/items_field/map）")
        print("RECONCILE DONE solved=0 fresh=0 reason=no-config")
        return 1
    path = str(solved_cfg["path"])
    with authed_get(opener, base + path, token, token_prefix) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    items = data
    for key in str(solved_cfg.get("items_field", "data")).split("."):
        items = items[key]
    id_key = ((solved_cfg.get("map") or {}).get("challenge_id") or "challenge_id")
    solved_ids = {str(item.get(id_key)) for item in items if isinstance(item, dict)}
    local = {str(c.get("platform_id")): c for c in cfg.get("challenges", [])
             if c.get("platform_id")}
    fresh = []
    for pid in sorted(solved_ids):
        entry = local.get(pid)
        if not entry:
            continue  # 平台已解但本地未注册：跳过（对账只对已注册题）
        slug = entry["slug"]
        case_path = comp / "cases" / slug / "case.json"
        try:
            case = json.loads(case_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if case.get("status") in ("solved", "submitted", "closed"):
            continue
        fresh.append(slug)
        argv = [sys.executable, str(SCRIPTS / "competition.py"), "event", str(comp),
                "platform_solved_detected", "--detail",
                json.dumps({"slug": slug, "platform_id": pid}, ensure_ascii=False)]
        subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
        log(f"[chall-agent] ⚑ 平台已解但本地未结算：{slug}（platform_id {pid}）→ 事件已写")
    print(f"RECONCILE DONE solved={len(solved_ids)} fresh={len(fresh)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("comp_dir", type=Path)
    ap.add_argument("--limit", type=int, default=0, help="最多注册 N 题（0=不限）")
    ap.add_argument("--categories", default="", help="逗号分隔的类别过滤（如 web,crypto）")
    ap.add_argument("--reconcile", action="store_true",
                    help="对账模式：拉平台已解列表，与本地 case 状态比对并写事件流（R16）")
    args = ap.parse_args()
    comp = args.comp_dir.resolve()
    cfg = load(comp / "competition.json", None)
    if not isinstance(cfg, dict):
        log("[chall-agent] ✗ competition.json 不存在")
        print("FETCH DONE registered=0 skipped=0 reason=no-config")
        return 1

    platform = cfg.get("platform") or {}
    adapter = get_adapter(platform)
    if adapter is not None:  # N-07：适配器缺省补齐（显式配置优先），探测失败也能抓题
        platform = adapter.apply_defaults(platform)
        log(f"[chall-agent] 适配器 {adapter.name}：challenge_detail="
            f"{(platform.get('challenge_detail') or {}).get('path', '无')}")
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
    if args.reconcile:  # R16：对账模式——不抓题、不注册
        return reconcile(opener, base, platform, token, prefix, comp, cfg)
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
    detail_cfg = platform.get("challenge_detail") or {}
    if detail_cfg.get("path"):
        log(f"[chall-agent] 附件自动下载已启用：{detail_cfg['path']}"
            f"（files_field={detail_cfg.get('files_field', 'data.files')}）")
    log(f"[chall-agent] 列表含 {len(items)} 题，开始逐题注册…")
    registered = skipped = 0
    artifacts_ok = artifacts_fail = 0
    existing = {c.get("slug") for c in cfg.get("challenges", [])}
    for it in items:
        name = str(field(it, m.get("name", "name")) or f"chall-{field(it, m.get('id', 'id'))}")
        cid = str(field(it, m.get("id", "id")))
        raw_cat = str(field(it, m.get("category", "category")) or "misc").lower()
        category = CAT_NORMALIZE.get(raw_cat, raw_cat)
        if category not in ("crypto", "pwn", "reverse", "web", "misc", "forensics", "ai"):
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
            if detail_cfg.get("path"):
                case_dir = comp / "cases" / slug
                ok_n, fail_n = download_artifacts(opener, base, detail_cfg, cid, slug,
                                                  case_dir, token, prefix, SCRIPTS)
                artifacts_ok += ok_n
                artifacts_fail += fail_n
        else:
            skipped += 1
            log(f"[chall-agent]   注册失败 {name}：{(r.stderr or r.stdout).strip()[-120]}")

    if detail_cfg.get("path"):
        log("[chall-agent] 附件已自动下载进各 case 的 artifacts/（挂载为容器 /workspace）")
    else:
        log("[chall-agent] 提醒：附件需手动放置（artifacts/）；配置 platform.challenge_detail "
            "{path, files_field} 可自动下载")
    print(f"FETCH DONE registered={registered} skipped={skipped} "
          f"artifacts={artifacts_ok} artifacts_failed={artifacts_fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
