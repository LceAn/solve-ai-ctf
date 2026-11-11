"""wb_http —— HTTP Handler、路由与 main 入口（N-06 拆包；server.py 是本模块的 facade）。"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import secrets
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
import wb_gateway
import wb_tasks
import wb_actions
import wb_sandbox
from wb_banner import print_banner
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
    # AG-15：HTTP/1.1 keep-alive（高频轮询不再每次新建 TCP）。
    # 流式端点（SSE / 模型网关转发）必须自报 Connection: close——无 Content-Length
    # 的响应在 1.1 下会挂住连接。
    protocol_version = "HTTP/1.1"
    server_version = "CTFWorkbench/1.0"

    # -- plumbing
    def log_message(self, fmt, *args):  # 静默默认日志，避免刷屏
        pass

    def _track_client(self):
        """R199：连接监控——记录本请求的 IP / 凭证类型 / 路径。"""
        try:
            import wb_monitor
            wb_monitor.track(self)
        except Exception:  # noqa: BLE001
            pass
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
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:
            # R169：Windows 防火墙/客户端提前断开抛 ConnectionAbortedError(10053)，
            # 连接已死，静默放弃本次响应（避免 500-while-error 级联与日志刷屏）
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

    def _static(self, rel: str) -> None:
        target = safe_join(_core.STATIC_DIR, rel)
        if not target or not target.is_file():
            self._error(404, "not found")
            return
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon"}.get(target.suffix.lower(),
                                                                  "application/octet-stream")
        # R94：ETag/304——mtime+size 弱校验，模块文件重复加载零字节传输
        st = target.stat()
        etag = f'W/"{int(st.st_mtime)}-{st.st_size}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self._security_headers()
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")  # 协商缓存：每次校验、变了才拉
        body = target.read_bytes()
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    # -- GET


def _docker_warmup_loop() -> None:
    """R57：每 5 分钟触碰一次 docker（WSL VM 保热 + images 列表缓存刷新），
    消除用户首次打开环境页时的冷启动等待（实测冷探可达 100s+）。"""
    while True:
        time.sleep(300)
        try:
            envb.docker_images_meta(max_age=0)  # 强制刷新
        except Exception:  # noqa: BLE001
            pass


def _log_rotate_loop() -> None:
    """R97：每 30 分钟轮转任务日志（此前仅启动时一次，长跑会话 scratch 仍会膨胀）。"""
    while True:
        time.sleep(1800)
        try:
            if _core.COMPETITIONS_DIR.is_dir():
                for comp_dir in _core.COMPETITIONS_DIR.iterdir():
                    if comp_dir.is_dir():
                        prune_task_logs(comp_dir)
        except Exception:  # noqa: BLE001
            pass


def watchdog_loop() -> None:
    """沙箱任务超时看门狗（BTFly 没有的部分）。"""
    while True:
        time.sleep(30)
        try:
            TASKS.enforce_timeouts(sandbox_config()["timeout_min"])
        except Exception:  # noqa: BLE001
            pass

    # R192：题目环境 TTL 回收
    try:
        import wb_env as _we
        dead = _we.reap_expired(_core.ROOT)
        if dead:
            print(f"[env] TTL 回收: {dead}", file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass

def _lan_token(root: Path) -> str:
    """共享模式的常驻管理员令牌：重启不换，浏览器只需粘贴一次。

    与 --token 临时值不同，它落在 workbench-data/lan-token.txt，
    同一台机器下次 --lan 启动直接复用（否则每次重启所有浏览器会话失效）。
    R170：实现移至 wb_core.lan_token（wb_routes 的 /api/share 也要用，
    本模块保留薄委托避免循环依赖）。
    """
    return _core.lan_token(root)


def switch_share_mode(enabled: bool) -> dict:
    """R170：运行时切换局域网共享（AI 看板一键开关，免重启进程）。

    由 /api/share 经 0.25s timer 调度（先应答再切换——切换会关闭当前监听，
    在 worker 线程里同步做会自等待死锁）。旧监听 daemon 化后关闭，
    SSE 长连接不阻塞关停（客户端 EventSource 自动重连到新监听）。
    """
    server = _core.RUNTIME.get("server")
    port = _core.RUNTIME.get("port", 8787)
    if server is None:
        return {"ok": False, "error": "服务器未就绪"}
    want_host = "0.0.0.0" if enabled else "127.0.0.1"
    fallback_err = ""
    _core.RUNTIME["server_switching"] = True  # main 服务循环据此等待新监听就位
    try:
        try:
            server.shutdown()
            server.daemon_threads = True
            server.block_on_close = False
            server.server_close()
        except Exception:  # noqa: BLE001  旧监听已死也继续重绑
            pass
        try:
            new = ThreadingHTTPServer((want_host, port), Handler)
        except OSError as exc:
            fallback_err = f"对外绑定失败（防火墙/端口被占？）：{exc}；已回绑本机"
            enabled = False
            new = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        _core.RUNTIME["server"] = new
    finally:
        _core.RUNTIME["server_switching"] = False
    _core.RUNTIME["host"] = "0.0.0.0" if enabled else "127.0.0.1"
    _core.RUNTIME["exposed"] = bool(enabled)
    lan = list(_core.local_urls(port)) if enabled else []
    _core.RUNTIME["lan_urls"] = lan
    _core.RUNTIME["base_url"] = _core.preferred_url(
        lan, f"http://127.0.0.1:{port}/")
    try:  # Origin 白名单覆盖全部本机地址，绑定变化后缓存必须失效
        import wb_routes as _wr
        _wr._LOCAL_ORIGINS_CACHE.clear()
    except Exception:  # noqa: BLE001
        pass
    # 不另起 serve 线程：main 的服务循环检测到 RUNTIME["server"] 换新后自行续跑
    print(f"[share] {'已开启局域网共享' if enabled else '已停止共享，回到仅本机'}"
          f" → http://{'0.0.0.0' if enabled else '127.0.0.1'}:{port}/"
          + (f" · 地址：{'、'.join(lan[:3])}" if lan else "")
          + (f" · {fallback_err}" if fallback_err else ""), flush=True)
    return {"ok": not fallback_err, "exposed": bool(enabled),
            "urls": lan or [f"http://127.0.0.1:{port}/"], "error": fallback_err}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1",
                        help="绑定地址：127.0.0.1（默认）| 0.0.0.0（局域网/Tailscale 共享）| 指定 IP")
    parser.add_argument("--lan", "--share", dest="lan", action="store_true",
                        help="局域网共享模式：绑定 0.0.0.0 + 常驻访问令牌 + 开启其他 AI 自助入网")
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
    if args.lan:
        args.host = "0.0.0.0"
        if not args.token:
            args.token = _lan_token(_core.ROOT)
        wb_gateway.ensure_join_token(_core.ROOT)
    _port = args.port
    _core.RUNTIME["port"] = _port
    _core.RUNTIME["auth_token"] = args.token
    _core.RUNTIME["host"] = args.host
    _core.RUNTIME["exposed"] = args.host in ("0.0.0.0", "::", "")
    _core.RUNTIME["default_dir"] = args.competition
    reason = validate_bind_security(args.host, args.token, args.allow_insecure)
    if reason:
        print(f"✗ 拒绝启动：{reason}", file=sys.stderr)
        return 2
    _core.RUNTIME["verbose"] = args.verbose
    _core._default_competition = args.competition
    TASKS.agent_cmd = args.agent_cmd

    ThreadingHTTPServer.request_queue_size = 16
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    _core.RUNTIME["server"] = server            # R170：共享热切换要关旧监听重绑
    _core.RUNTIME["share_switch"] = switch_share_mode
    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=_docker_warmup_loop, daemon=True).start()
    threading.Thread(target=_log_rotate_loop, daemon=True).start()
    if _core.COMPETITIONS_DIR.is_dir():  # R12：启动时轮转任务日志，防止 scratch 无限膨胀
        for comp_dir in _core.COMPETITIONS_DIR.iterdir():
            if comp_dir.is_dir():
                prune_task_logs(comp_dir)
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::', '') else args.host}:{args.port}/"
    exposed = args.host in ("0.0.0.0", "::", "")
    lan_urls = list(_core.local_urls(args.port)) if exposed else []
    # 其他 AI 该用哪个地址接进来：优先第一条非回环地址（局域网/Tailscale）
    base_url = _core.preferred_url(lan_urls, url)
    _core.RUNTIME["lan_urls"] = lan_urls
    _core.RUNTIME["base_url"] = base_url
    join_token = wb_gateway.read_join_token(_core.ROOT) if exposed else ""
    token_on = bool(_core.RUNTIME.get("auth_token"))
    try:
        sandbox_on = bool(sandbox_config().get("enabled"))
    except Exception:  # noqa: BLE001
        sandbox_on = False
    print_banner(
        url=url,
        root=_core.ROOT,
        comps=list_competitions(),
        default=_core._default_competition,
        sandbox_enabled=sandbox_on,
        token=token_on,
        admin_token=str(_core.RUNTIME.get("auth_token") or ""),
        agent_cmd=bool(TASKS.agent_cmd),
        exposed=exposed and not token_on,
        shared=exposed,
        lan_urls=lan_urls,
        join_token=join_token,
    )
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        # R170：服务循环——共享热切换会 shutdown 旧监听并换 RUNTIME["server"]，
        # main 必须接着 serve 新对象（此前单次 serve_forever 返回即进程退出，
        # 首次实测一键开启共享直接把整个服务打死）。
        while True:
            cur = _core.RUNTIME["server"]
            cur.serve_forever()
            # 切换中：等新监听就位（最多 5s）；无切换且对象未变 = 正常退出
            for _ in range(250):
                if _core.RUNTIME["server"] is not cur or not _core.RUNTIME.get("server_switching"):
                    break
                time.sleep(0.02)
            if _core.RUNTIME["server"] is cur and not _core.RUNTIME.get("server_switching"):
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            _core.RUNTIME["server"].server_close()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
