#!/usr/bin/env python3
"""平台对接代理 —— 自主探测比赛平台的 API 形态，产出提交脚本所需的 platform 配置。

自主流程：
  1. 从 competition.json 取门户线索（login_url/origin）与令牌环境变量
  2. 依序探测常见平台 API 形态（CTFd 系优先），校验挑战列表端点
  3. 探测成功 → 写入 competition.json 的 platform 段（base_url/auth/challenges/submit）
  4. 无法识别的形态 → 明确告知缺什么，留人工确认

进度全部走 stdout（任务系统实时可见），以 PLATFORM DONE configured=… 收尾。
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
from urllib.parse import urlsplit

import ctf_session

HERE = Path(__file__).resolve().parent


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


def save(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def http_json(opener, url: str, token: str = "", token_prefix: str = "", timeout: int = 12):
    if opener is not None:
        return ctf_session.get_json(opener, url, token, token_prefix, timeout)
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", (token_prefix + token) if token_prefix else token)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))


def probe_ctfd(opener, base: str, token: str = "", prefix: str = ""):
    """CTFd 系：/api/v1/challenges（token 直连）或 /api/v1/challenges.cache（BUUCTF 等会话形态）"""
    for path, shape in (("/api/v1/challenges", "token-api"),
                        ("/api/v1/challenges.cache", "session-cache")):
        try:
            status, data = http_json(opener, base + path, token, prefix)
        except (urllib.error.HTTPError, urllib.error.URLError):
            continue
        items = data.get("data") if isinstance(data, dict) else None
        if status == 200 and isinstance(items, list) and items:
            return {
                "challenges": {"method": "GET", "path": path,
                               "items_field": "data",
                               "map": {"id": "id", "name": "name", "category": "category",
                                       "points": "value"}},
                "submit": {"method": "POST",
                           "path": "/api/v1/challenges/{challenge_id}/attempt",
                           "content_type": "application/json",
                           "body_template": '{"challenge_id": "{challenge_id}", "submission": "{flag}"}',
                           "success": {"field": "data.status", "equals": "correct"},
                           "timeout_seconds": 15},
                "shape": shape,
                "sample": items[:3],
            }
    return None


def apply_preset(comp: Path, preset_name: str) -> None:
    preset = load(HERE / "presets" / f"{preset_name}.json", None)
    if not isinstance(preset, dict):
        raise ValueError(f"预设不存在：{preset_name}")
    cfg_path = comp / "competition.json"
    cfg = load(cfg_path, {})
    platform = dict(cfg.get("platform") or {})
    for key, value in preset.items():
        if key == "base_url" and platform.get(key):
            continue
        platform[key] = value
    cfg["platform"] = platform
    save(cfg_path, cfg)
    log(f"[platform-agent] 已套用预设 {preset_name}（登录/门户/提交形态）")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("comp_dir", type=Path)
    ap.add_argument("--preset", help="套用平台预设（如 buuctf）后再探测")
    args = ap.parse_args()
    comp = args.comp_dir.resolve()
    cfg_path = comp / "competition.json"
    cfg = load(cfg_path, None)
    if not isinstance(cfg, dict):
        log("[platform-agent] ✗ competition.json 不存在或不可读——请先 competition.py init")
        print("PLATFORM DONE configured=0 reason=no-config")
        return 1
    if args.preset:
        try:
            apply_preset(comp, args.preset)
        except ValueError as exc:
            log(f"[platform-agent] ✗ {exc}")
            print("PLATFORM DONE configured=0 reason=preset-failed")
            return 1
        cfg = load(cfg_path, cfg)  # 套用预设后刷新内存态

    platform = dict(cfg.get("platform") or {})
    portal = platform.get("portal") or {}
    auth = platform.get("auth") or {}
    token_env = auth.get("value_env") or "CTF_TOKEN"
    token = os.environ.get(token_env, "")
    login_cfg = platform.get("login") or {}
    if not token and not login_cfg.get("path"):
        log(f"[platform-agent] ✗ 无可用认证：未设置令牌 {token_env}，也没有 login 配置")
        print("PLATFORM DONE configured=0 reason=no-auth")
        return 1

    # base_url 候选：已有配置 > 门户 login_url 的 origin
    base = (platform.get("base_url") or "").rstrip("/")
    if not base:
        login_url = portal.get("login_url") or ""
        if login_url.startswith("http"):
            base = login_url.split("/", 3)[0] + "//" + login_url.split("/", 3)[2]
    if not base:
        log("[platform-agent] ✗ 无 base_url 线索：请在 platform 配置里填 base_url 或 portal.login_url")
        print("PLATFORM DONE configured=0 reason=no-base-url")
        return 1
    log(f"[platform-agent] 平台基址：{base}（令牌来自 {token_env}）")

    opener = None
    if login_cfg.get("path"):
        opener = ctf_session.build_opener()
        try:
            ctf_session.login(opener, base, login_cfg)
            log("[platform-agent] ✓ 表单登录成功（session 已建立）")
        except ValueError as exc:
            log(f"[platform-agent] ✗ {exc}")
            print("PLATFORM DONE configured=0 reason=login-failed")
            return 1

    token_prefix = auth.get("value_prefix") or "Token "
    started = time.time()
    for name, fn in (("CTFd 系（含 .cache 会话形态）", probe_ctfd),):
        try:
            log(f"[platform-agent] 探测 {name} …")
            found = fn(opener, base, token, token_prefix)
        except urllib.error.HTTPError as e:
            log(f"[platform-agent]   {name}：HTTP {e.code}，继续下一形态")
            found = None
        except Exception as exc:  # noqa: BLE001
            log(f"[platform-agent]   {name}：{type(exc).__name__}，继续下一形态")
            found = None
        if found:
            platform["base_url"] = base
            platform["auth"] = {"header": "Authorization", "value_prefix": token_prefix,
                                "value_env": token_env}
            platform["challenges"] = found["challenges"]
            platform["submit"] = found["submit"]
            platform["status"] = "auto-configured"
            platform["shape"] = found.get("shape", "")
            platform["note"] = (f"由 platform-agent 于 {time.strftime('%Y-%m-%dT%H:%M:%S')} "
                                f"自动探测（{found.get('shape', name)} 形态），提交端点建议先 dry-run 验证")
            cfg["platform"] = platform
            save(cfg_path, cfg)
            log(f"[platform-agent] ✓ 已写入 platform 配置（{name}），示例题目："
                f"{json.dumps(found['sample'], ensure_ascii=False)[:200]}")
            log("[platform-agent] 提醒：提交端点先用 submitter dry-run 验证一次再放行 --live")
            print(f"PLATFORM DONE configured=1 elapsed={time.time() - started:.1f}s")
            return 0

    log("[platform-agent] ✗ 常见形态均未命中：需要人工确认列表端点后填入 platform.challenges"
        "（可对照 config/platform.template.json 的字段）")
    print("PLATFORM DONE configured=0 reason=unknown-shape")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
