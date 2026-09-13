"""wb_http —— HTTP Handler、路由与 main 入口（N-06 拆包；server.py 是本模块的 facade）。"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import env_builder as envb
import wb_core as _core
import wb_tasks
import wb_actions
import wb_sandbox
from wb_core import (read_json, safe_join, resolve_competition, competition_view,
                     case_summary, file_tree, build_prompt, kb_search, list_competitions,
                     select_default_competition, read_json_line, prune_task_logs)
from wb_tasks import (TASKS, split_cmd_template, validate_bind_security, board_data,
                      docker_stop_container, _image_exists, _compose_up, _compose_down, _mem_bytes)
from wb_core import looks_textual
from wb_sandbox import (sandbox_status, sandbox_config, gateway_usage, upstream_key,
                        health_detail,
                        upstream_base, sandbox_concurrency_reason, sandbox_running_count)
from wb_actions import ACTIONS

from wb_routes import RoutesMixin, API_HELP  # noqa: F401  （API_HELP 经 facade 暴露）


class Handler(RoutesMixin, BaseHTTPRequestHandler):
    server_version = "CTFWorkbench/1.0"

    # -- plumbing
    def log_message(self, fmt, *args):  # 静默默认日志，避免刷屏
        pass

    @staticmethod
    def _redact(path: str) -> str:
        """N-12：verbose 请求日志里对 ?token= 脱敏，令牌不落日志。"""
        return re.sub(r"([?&]token=)[^&\s]+", r"\1***", path)


    def _security_headers(self):
        # script-src 'self'：前端无内联 <script>、无内联事件处理器、无 eval（已审计），
        # 该约束可直接落地，是 XSS 的兜底防线。style-src 需 'unsafe-inline'：
        # 前端大量使用 style="" 内联属性。img-src data: 用于 favicon 的 data: URI。
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "connect-src 'self'; object-src 'none'; base-uri 'none'; "
                         "frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload, status: int = 200):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _error(self, status: int, message: str, *, code: str = "", hint: str = ""):
        body: dict = {"error": message}
        if code:
            body["code"] = code
        if hint:
            body["hint"] = hint
        self._json(body, status)
        self._json({"error": message}, status)

    def _static(self, rel: str) -> None:
        target = safe_join(_core.STATIC_DIR, rel)
        if not target or not target.is_file():
            self._error(404, "not found")
            return
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon"}.get(target.suffix.lower(),
                                                                  "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    # -- GET


def watchdog_loop() -> None:
    """沙箱任务超时看门狗（BTFly 没有的部分）。"""
    while True:
        time.sleep(30)
        try:
            TASKS.enforce_timeouts(sandbox_config()["timeout_min"])
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1",
                        help="绑定地址：127.0.0.1（默认）| 0.0.0.0（局域网/Tailscale 共享）| 指定 IP")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--token", default=os.environ.get("WB_TOKEN", ""),
                        help="访问令牌；非回环绑定时强烈建议配置（亦可用环境变量 WB_TOKEN）")
    parser.add_argument("--competition", default="", help="默认选中的比赛目录名（比赛/ 之下）")
    parser.add_argument("--agent-cmd", default=os.environ.get("WB_AGENT_CMD", ""),
                        help="求解命令模板，占位符 {prompt_file} {case_dir} {solver_dir}；"
                             "按 argv 词法解析（不支持 && | > 与环境变量展开），"
                             "例：'python solver.py --prompt {prompt_file}'")
    parser.add_argument("--allow-insecure", action="store_true",
                        help="非回环绑定且未配置令牌时，显式豁免强制鉴权（N-03，危险）")
    parser.add_argument("--verbose", action="store_true", help="打印请求日志到 stderr（token 自动脱敏）")
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()
    _port = args.port
    _core.RUNTIME["port"] = _port
    _core.RUNTIME["auth_token"] = args.token
    reason = validate_bind_security(args.host, args.token, args.allow_insecure)
    if reason:
        print(f"✗ 拒绝启动：{reason}", file=sys.stderr)
        return 2
    _core.RUNTIME["verbose"] = args.verbose
    _core._default_competition = args.competition
    TASKS.agent_cmd = args.agent_cmd

    ThreadingHTTPServer.request_queue_size = 16
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    threading.Thread(target=watchdog_loop, daemon=True).start()
    if _core.COMPETITIONS_DIR.is_dir():  # R12：启动时轮转任务日志，防止 scratch 无限膨胀
        for comp_dir in _core.COMPETITIONS_DIR.iterdir():
            if comp_dir.is_dir():
                prune_task_logs(comp_dir)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::', '') else args.host}:{args.port}/"
    print(f"CTF Workbench → {url}   (root={_core.ROOT})", flush=True)
    if args.host in ("0.0.0.0", "::", ""):
        for u in local_urls(args.port):
            print(f"  共享地址: {u}", flush=True)
        if _core.RUNTIME.get("auth_token"):
            print("  已启用令牌鉴权：Agent 请求请带 'Authorization: Bearer <token>'；浏览器首次打开会提示输入一次。",
                  flush=True)
        else:
            print("  ⚠ 对局域网开放且未设令牌（--token）：同网段可读取本机比赛数据。建议配置令牌。",
                  flush=True)
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
