#!/usr/bin/env python3
"""平台会话模块：支持「令牌直连」与「表单登录 + session」两种形态。

登录配置（platform.login）示例——BUUCTF（改版 CTFd，nonce 表单登录）：
    {
      "method": "POST", "path": "/login",
      "content_type": "application/x-www-form-urlencoded",
      "fields": {"name": "{username}", "password": "{password}"},
      "csrf": {"field": "nonce", "from_path": "/login",
               "pattern": "name=\\\"nonce\\\"[^>]*value=\\\"([^\\\"]+)\\\""},
      "credentials_env": "CTF_CREDENTIALS_JSON"
    }
credentials_env 指向的环境变量应为 JSON：{"username": "...", "password": "..."}
凭证只存环境变量，绝不写文件、不进日志。
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ctfwb-agent/1.0"


def build_opener() -> urllib.request.OpenerDirector:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", UA), ("Accept", "application/json, text/html;q=0.9")]
    return opener


def load_credentials(login_cfg: dict) -> dict:
    env = login_cfg.get("credentials_env") or "CTF_CREDENTIALS_JSON"
    raw = os.environ.get(env, "")
    if not raw:
        raise ValueError(f"未设置登录凭据环境变量 {env}（JSON：{{\"username\":..,\"password\":..}}）")
    try:
        creds = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{env} 不是合法 JSON：{exc}")
    if not isinstance(creds, dict) or not creds.get("username") or not creds.get("password"):
        raise ValueError(f"{env} 需包含 username 与 password")
    return creds


def csrf_from(opener, base: str, csrf_cfg: dict) -> str:
    path = csrf_cfg.get("from_path", "/login")
    pattern = csrf_cfg.get("pattern") or r'name="nonce"[^>]*value="([^"]+)"'
    html = opener.open(base + path, timeout=20).read().decode("utf-8", errors="replace")
    m = re.search(pattern, html)
    if not m:
        raise ValueError(f"登录页未匹配到 CSRF 字段（{csrf_cfg.get('field')}），页面结构可能变化")
    return m.group(1)


def login(opener, base: str, login_cfg: dict) -> None:
    creds = load_credentials(login_cfg)
    data = {}
    for key, tpl in (login_cfg.get("fields") or {}).items():
        data[key] = (tpl or "{username}"
                     ).replace("{username}", creds["username"]).replace("{password}", creds["password"])
    csrf_cfg = login_cfg.get("csrf")
    if csrf_cfg and csrf_cfg.get("field"):
        data[csrf_cfg["field"]] = csrf_from(opener, base, csrf_cfg)
    method = login_cfg.get("method", "POST")
    path = login_cfg.get("path", "/login")
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(base + path, data=body, method=method)
    req.add_header("Content-Type", login_cfg.get("content_type", "application/x-www-form-urlencoded"))
    try:
        resp = opener.open(req, timeout=25)
        landed = resp.geturl()
    except urllib.error.HTTPError as exc:
        raise ValueError(f"登录 HTTP {exc.code}：检查凭据或登录配置")
    want = login_cfg.get("success_redirect")
    if want and want not in landed:
        raise ValueError(f"登录后未跳转到 {want}（当前 {landed[:80]}），凭据或配置可能有误")


def get_json(opener, url: str, token: str = "", token_prefix: str = "", timeout: int = 25):
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", (token_prefix + token) if token_prefix else token)
    with opener.open(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8", errors="replace"))
