"""wb_routes —— HTTP 路由方法（RoutesMixin）与鉴权助手（N-06/R25 拆包）。

Mixin 由 wb_http.Handler(RoutesMixin, BaseHTTPRequestHandler) 挂载；
管道方法（_json/_error/_static/_security_headers/_same_origin/_redact）留在 wb_http。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
import threading
import uuid
from pathlib import Path

import env_builder as envb
import wb_env
import wb_gateway
import wb_core as _core
import wb_actions
from wb_actions import ACTIONS, _db_path_of, run_script, selftest_status
from wb_core import (looks_textual, read_json, safe_join, resolve_competition, competition_view,
                     case_summary, file_tree, build_prompt, kb_search, list_competitions,
                     select_default_competition, read_json_line)
from wb_sandbox import (SANDBOX_DEFAULTS, sandbox_status, sandbox_config, gateway_usage,
                        upstream_key, upstream_base, health_detail,
                        sandbox_concurrency_reason, sandbox_running_count)
from wb_tasks import (TASKS, board_data, docker_stop_container, split_cmd_template,
                      _image_exists, _compose_up, _compose_down, _mem_bytes)  # _compose_down: R160 补


API_HELP = {
    "description": "CTF Workbench HTTP API（多 Agent 协作接口；配置 --token 后需带 Authorization: Bearer <token>）",
    "read": {
        "GET /api/competitions": "列出 比赛/ 下所有比赛",
        "GET /api/competition?dir=": "比赛视图（题目/case 摘要/事件/文档/枚举）",
        "GET /api/case?dir=&case_dir=": "case.json 全量 + 工作区文件树",
        "GET /api/events?dir=&limit=": "比赛事件尾部",
        "GET /api/board?dir=&hours=": "AI 看板泳道数据（题目事件 + 任务跨度）",
        "GET /api/tree?dir=&path=": "比赛目录内只读文件树",
        "GET /api/file?dir=&path=": "只读文本文件内容（2MB 上限）",
        "GET /api/kb?q=&category=": "知识库检索",
        "GET /api/prompt?dir=&slug=&style=": "解题提示词（style=continue|fresh|submit|review）",
        "GET /api/tasks 与 /api/task/tail?id=": "任务列表与实时输出",
        "GET /api/health/detail": "执行链路健康",
        "GET /api/env/status?dir=": "比赛环境总览（L0/L1/L2/题目层 spec 与镜像状态、漂移、运行态）",
        "GET /api/env/registry": "读取 Docker 仓库地址（推送用；凭证只在本机 docker login）",
        "GET /api/agent-gw/directory": "Agent 网关名册（AI1/AI2… 编号 + 标签 + 状态 + 认领 + 交接）",
        "GET /api/agent-gw/hello": "零认证发现端点：服务自描述 + 入网方法 + 后续命令清单（AI 自举入口）",
        "GET /api/agent-gw/join-info": "共享接入信息 {exposed, urls[], join_token, brief}（admin）",
        "GET /api/gateway/usage": "模型网关按任务聚合的用量报表（bytes/requests/活跃令牌）",
    },
    "write": {
        "POST /api/action": "白名单动作（competition.init / competition.set_docs / docs.write / challenge.register / case.init / case.status / case.hypothesis / "
                            "case.finding / case.attempt / case.scan_flags / case.candidate /  / case.candidate_add（手动登记 flag 候选）"
                            "case.validate / case.triage / case.writeup / case.summary / "
                            "submit.dryrun / submit.live / competition.prioritize / competition.export / "
                            "competition.set_mode / competition.set_scoring / competition.add_team / competition.update_challenge / competition.remove_challenge / case.set_grade / achievement.check / team.list / competition.dashboard / competition.report / competition.event / selftest.run）",
        "POST /api/task/start": "派发求解任务 {dir, slug, agent?, cmd_template?}；demo=true 可运行内置演示 Agent（只读日志，不提交）",
        "POST /api/task/stop": "停止任务 {id}（沙箱任务连带 compose 服务下线）",
        "POST /api/env/build": "构建比赛/题目层镜像 {dir, slug|comp_image|all, force?}（env_builder 子进程任务）",
        "POST /api/env/verify": "镜像探针矩阵验证 {dir, slug}",
        "POST /api/env/push": "推送已构建镜像到仓库 {dir, slugs?, registry?, no_comp?}（任务）",
        "POST /api/env/registry": "保存 Docker 仓库地址 {registry}（凭证只在本机 docker login）",
        "POST /api/agent-gw/register": "注册协作 agent {name, label?, capabilities[], role?} → {agent_id, tag, agent_key}（key 仅此一次；admin 凭证）",
        "POST /api/agent-gw/join": "自助入网 {name, label?, capabilities[], role?}（X-Join-Token 头；无需 admin 令牌）",
        "POST /api/share": "一键开关局域网共享 {enabled}（admin；免重启热切换绑定，开启时自动落常驻令牌+入网码）",
        "POST /api/share/base-url": "多网卡地址切换 {url}（admin；须为本机网卡地址之一，影响展示与接入指令）",
        "GET /api/inbox/status": "半接入比赛：inbox/ 待导入附件条目（一个条目=一道题）",
        "POST /api/action competition.inbox_import": "批量导入 inbox/ 附件 → 注册题目+case+附件 sha256 入库（幂等）",
        "POST /api/agent-gw/label": "agent 自改标签 {label?, note?, role?, capabilities[]}（X-Agent-Key 头）",
        "POST /api/agent-gw/join-token": "轮换/关闭入网码 {rotate?|disable?}（admin 凭证）",
        "POST /api/agent-gw/heartbeat": "agent 心跳 {status?, current_slug?, note?}（X-Agent-Key 头）",
        "POST /api/agent-gw/claim": "认领题目 {slug}（TTL 45min；已被认领返回 409）",
        "POST /api/agent-gw/release": "释放认领 {slug?}",
        "POST /api/agent-gw/handoff": "交接简报 {slug, summary, findings[]}（自动释放认领；dispatch 时注入下任 prompt）",
        "POST /api/agent-gw/revoke": "吊销 agent {agent_id}（admin 凭证）",
    },
    "agent_workflow": "Agent 协作建议：GET /api/prompt 取题面与上下文 → 用 case.attempt/hypothesis/findings "
                      "登记过程 → flag 用 case.candidate 推进 → 提交必须 submit.dryrun 预览后由人工 submit.live。",
}


# ---------------------------------------------------------------- HTTP


_SESSION_TTL = 900  # 15 分钟
_SESSION_COOKIE = "wb_session"
_LOCAL_ORIGINS_CACHE: list[str] = []
_port = 8787


def _session_secret() -> bytes:
    return hashlib.sha256(_core.RUNTIME.get("auth_token", "").encode("utf-8") + b"wb-session-v1").digest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _issue_session() -> tuple[str, int]:
    payload = {"exp": int(time.time()) + _SESSION_TTL, "rng": uuid.uuid4().hex}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_session_secret(), raw, hashlib.sha256).hexdigest()
    return _b64url(raw) + "." + sig, _SESSION_TTL


def _verify_session(session: str) -> bool:
    try:
        enc, _, sig = session.rpartition(".")
        if not enc or not sig:
            return False
        raw = _b64url_decode(enc)
        expected = hmac.new(_session_secret(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        payload = json.loads(raw)
        return int(payload.get("exp", 0)) >= int(time.time())
    except Exception:  # noqa: BLE001
        return False


_READONLY_API = {
    "/api/competitions", "/api/competition", "/api/bootstrap", "/api/case",
    "/api/events", "/api/board", "/api/tasks", "/api/task/tail",
    "/api/leaderboard", "/api/achievements", "/api/tree", "/api/file",
    "/api/env/container", "/api/sandbox", "/api/kb", "/api/prompt",
    "/api/agent-gw/directory", "/api/agent-gw/events",
    "/api/submissions", "/api/help", "/api/about", "/api/presets",
    # R196：浏览页面加载时会拉的全部状态类端点（防队员端弹令牌框）
    "/api/health/detail", "/api/env/status", "/api/inbox/status",
    "/api/docs/tree", "/api/resources", "/api/agent-gw/join-info",
    "/api/autosubmit", "/api/kb/stats", "/api/selftest", "/api/gateway/usage",
    "/api/docs/file", "/api/connections",
}


def _authorized(headers, qs, path: str = "") -> bool:
    """配置 --token 后所有 /api 请求须凭证：session 或 exchange 路由的裸 token（O-12）。

    R195：只读进度端点放行（队员用自己电脑浏览器直接看板，无需令牌）——
    所有写操作（/api/action、agent-gw 写端点、share 管理）仍需凭证。
    """
    if not _core.RUNTIME.get("auth_token"):
        return True
    if path in _READONLY_API:
        return True
    value = _client_token(headers, qs)
    if not value:
        return False
    if path == "/api/auth/exchange":
        return hmac.compare_digest(value, _core.RUNTIME.get("auth_token", ""))
    if value.startswith(wb_gateway.KEY_PREFIX):  # R104：协作网关 agent key
        return wb_gateway.authenticate(_core.ROOT, value) is not None
    return _verify_session(value)


def _admin_ok(headers, qs=None) -> bool:
    """管理员操作（注册/吊销/入网码）只认人持有的凭证，agent key 不算。

    开放模式（未配 --token，仅回环绑定）返回 True——本机即管理员。
    共享模式下，任何 agent 都不该能给自己发新身份或吊销同伴。
    """
    if not _core.RUNTIME.get("auth_token"):
        return True
    value = _client_token(headers, qs or {})
    if not value or value.startswith(wb_gateway.KEY_PREFIX):
        return False
    if hmac.compare_digest(value, _core.RUNTIME.get("auth_token", "")):
        return True
    return _verify_session(value)


def _client_token(headers, qs) -> str:
    """从 Bearer / Cookie: wb_session= / X-Agent-Key 读取凭证。不接受 ?token= 查询串。"""
    auth = headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    agent_key = headers.get("X-Agent-Key", "")
    if agent_key.startswith(wb_gateway.KEY_PREFIX):
        return agent_key.strip()
    cookie = headers.get("Cookie", "")
    for pair in cookie.split(";"):
        pair = pair.strip()
        if pair.startswith(_SESSION_COOKIE + "="):
            return pair[len(_SESSION_COOKIE) + 1:]
    return ""


def _check_origin(headers) -> bool:
    """--token 模式下的 CSRF 防护：浏览器 Origin 必须在本机源白名单内。

    Agent 请求不带 Origin，自动放行；白名单覆盖 loopback + 全部网卡
    （含局域网/Tailscale），与 local_urls() 同一组地址。
    """
    if not _core.RUNTIME.get("auth_token"):
        return True
    origin = headers.get("Origin", "")
    if not origin:
        return True
    return origin in _local_origins()


def _local_origins() -> list[str]:
    """本机 Origin 白名单：loopback 别名 + 所有本机网卡地址。"""
    if _LOCAL_ORIGINS_CACHE:
        return _LOCAL_ORIGINS_CACHE
    port = _core.RUNTIME.get("port", 8787)
    origins = [f"http://{h}:{port}" for h in ("127.0.0.1", "localhost", "[::1]")]
    for url in _core.local_urls(port):
        origin = url.rstrip("/")
        if origin not in origins:
            origins.append(origin)
    _LOCAL_ORIGINS_CACHE.extend(origins)
    return _LOCAL_ORIGINS_CACHE


class RoutesMixin:
    def do_GET(self):
        self._track_client()
        if _core.RUNTIME.get("verbose"):
            print(f"{self.command} {self._redact(self.path)}", file=sys.stderr, flush=True)
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        try:
            if route == "/" or route.startswith("/static/"):
                if route == "/":
                    return self._static("index.html")
                return self._static(route[len("/static/"):])
            # R178：零认证发现端点必须在全局鉴权之前——共享模式（token 已启用）下
            # 裸地址自举是它存在的意义，放进 authed 区就只剩本机模式可用（实测 401 抓回）
            if route == "/api/agent-gw/hello":
                base = _core.RUNTIME.get("base_url") or \
                    f"http://127.0.0.1:{_core.RUNTIME.get('port', 8787)}/"
                return self._json(wb_gateway.onboarding_payload(base))
            if route.startswith("/api/") and not _authorized(self.headers, qs, route):
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("WWW-Authenticate", "Bearer")
                self._security_headers()
                body = json.dumps({"ok": False, "code": "E_AUTH_REQUIRED",
                                   "error": "需要会话凭证（队员只读无需登录；写操作先 POST /api/auth/exchange）"},
                                  ensure_ascii=False).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if route == "/api/connections":
                import wb_monitor
                # agent 活跃度：从 gateway 名册取（心跳即活跃）
                try:
                    gw = wb_gateway.directory(_core.ROOT)
                    agents_active = [a for a in gw.get("agents", [])
                                     if not a.get("revoked")]
                except Exception:  # noqa: BLE001
                    agents_active = []
                snap = wb_monitor.snapshot()
                snap["agents"] = [{
                    "tag": a.get("tag"), "name": a.get("name"), "label": a.get("label", ""),
                    "status_display": a.get("status_display", a.get("status")),
                    "current_slug": a.get("current_slug", ""),
                    "last_seen_ago": (str(a.get("last_seen_minutes", "?")) + "m 前")
                    if a.get("last_seen_minutes", -1) >= 0 else "?",
                    "online": a.get("last_seen_minutes", 99) < 15,
                } for a in agents_active]
                snap["agents_online"] = sum(1 for a in snap["agents"] if a["online"])
                snap["agents_total"] = len(snap["agents"])
                return self._json(snap)
            if route == "/api/about":
                return self._json(about_payload())
            if route == "/api" or route == "/api/":
                return self._json(API_HELP)
            if route == "/api/help":
                return self._json(API_HELP)
            if route == "/api/competitions":
                competitions = list_competitions()
                return self._json({
                    "competitions": competitions,
                    "default": select_default_competition(competitions, _core._default_competition),
                })
            if route == "/api/competition":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                return self._json(competition_view(comp))
            if route == "/api/case":
                comp = resolve_competition(qs.get("dir", ""))
                case_dir = safe_join(comp or Path(), qs.get("case_dir", ""))
                if not case_dir or not (case_dir / "case.json").exists():
                    return self._error(404, "case.json not found")
                payload = read_json(case_dir / "case.json", {})
                payload["_tree"] = file_tree(case_dir)
                payload["_collab"] = _collab_payload(case_dir.name)
                return self._json(payload)
            if route == "/api/events":
                comp = resolve_competition(qs.get("dir", ""))
                events_path = (comp or Path()) / "events.jsonl"
                events = []
                if events_path.exists():
                    lines = events_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    events = [read_json_line(l) for l in lines[-int(qs.get("limit", _core.EVENTS_TAIL)):]
                              if l.strip()]
                return self._json({"events": events})
            if route == "/api/tree":
                comp = resolve_competition(qs.get("dir", ""))
                base = safe_join(comp or Path(), qs.get("path") or ".")
                if not base or not base.is_dir():
                    return self._error(404, "dir not found")
                return self._json({"tree": file_tree(base)})
            if route == "/api/file":
                return self.api_file(qs)
            if route == "/api/tasks":
                rev = TASKS.revision()
                # R89：rev 未变时轻量返回（前端 1.5s 轮询跳过全量列表与重渲染）
                if qs.get("rev") and qs.get("rev") == rev:
                    return self._json({"rev": rev, "tasks": None,
                                       "agent_cmd": bool(TASKS.agent_cmd),
                                       "demo_agent": True})
                return self._json({"rev": rev,
                                   "tasks": TASKS.list(status=qs.get("status", ""),
                                                       agent=qs.get("agent", ""),
                                                       limit=int(qs.get("limit", 0) or 0)),
                                   "agent_cmd": bool(TASKS.agent_cmd),
                                   # The demo solver is bundled with the workbench and
                                   # never submits a flag.  It keeps a fresh install
                                   # demonstrable while real Agent execution remains
                                   # opt-in through --agent-cmd/WB_AGENT_CMD.
                                   "demo_agent": True})
            if route == "/api/task/tail":
                return self._json(TASKS.tail(qs.get("id", "")))
            if route == "/api/health/detail":
                # R200：?fresh=1 跳过缓存（前端「重新检测」按钮），默认 30s 缓存
                return self._json(health_detail(force=qs.get("fresh") == "1"))
            if route == "/api/events/stream":
                return self.events_stream(qs)
            if route == "/api/presets":
                pdir = Path(__file__).resolve().parent / "presets"
                items = []
                if pdir.is_dir():
                    for f in sorted(pdir.glob("*.json")):
                        meta = read_json(f, {})
                        items.append({"name": f.stem,
                                      "base_url": meta.get("base_url", ""),
                                      "note": meta.get("note", "")})
                return self._json({"presets": items})
            if route == "/api/env/container":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                return self._json({"envs": wb_env.status(_core.ROOT, qs.get("slug", ""))})
            if route == "/api/sandbox":
                return self._json(sandbox_status())
            if route == "/api/gateway/usage":
                return self._json(gateway_usage())
            if route == "/api/env/status":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                return self._json(envb.status_data_cached(comp))
            if route == "/api/file" and qs.get("download") == "1":
                comp = resolve_competition(qs.get("dir", ""))
                target = safe_join(comp or Path(), qs.get("path") or "")
                if not target or not target.is_file():
                    return self._error(404, "file not found")
                data = target.read_bytes()[:_core.MAX_FILE_BYTES * 4]
                fname = target.name
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{fname.encode("ascii", "ignore").decode() or "download.bin"}"; filename*=UTF-8''{urllib.parse.quote(fname)}')
                self.send_header("Content-Length", str(len(data)))
                self._security_headers()
                self.end_headers()
                self.wfile.write(data)
                return
            if route == "/api/inbox/status":
                # R173：半接入比赛——inbox/ 待导入条目（注册页签显示投料口状态）
                comp = resolve_competition(qs.get("dir", ""))
                ib = (comp / "inbox") if comp else None
                items = []
                if ib and ib.is_dir():
                    items = [p.name for p in sorted(ib.iterdir())
                             if not p.name.startswith(".")
                             and not p.name.endswith(".meta.json")]
                return self._json({"exists": bool(ib and ib.is_dir()),
                                   "pending": items})
            if route == "/api/export/download":
                comp = resolve_competition(qs.get("dir", ""))
                target = safe_join((comp or Path()) / "交付", qs.get("name") or "")
                if not comp or not target or not target.is_file() or target.suffix != ".zip":
                    return self._error(404, "package not found")
                data = target.read_bytes()
                fname = target.name
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{fname.encode("ascii", "ignore").decode() or "deliver.zip"}"; filename*=UTF-8\'\'{urllib.parse.quote(fname)}')
                self.send_header("Content-Length", str(len(data)))
                self._security_headers()
                self.end_headers()
                self.wfile.write(data)
                return
            if route == "/api/docs/tree":
                comp = resolve_competition(qs.get("dir", ""))
                docs_base = str((read_json(comp / "competition.json", {})
                                 or {}).get("docs_path") or "") if comp else ""
                if not docs_base or not Path(docs_base).is_dir():
                    # 未配置是正常状态而非错误：返回 200 让调用方可区分"没配"与"路径错了"
                    return self._json({"docs_path": "", "tree": [], "configured": False,
                                       "note": "docs_path not configured"})
                base = Path(docs_base).resolve()
                target = (base / (qs.get("path") or ".")).resolve()
                if not str(target).startswith(str(base)):
                    return self._error(403, "path outside docs_path")
                if not target.is_dir():
                    return self._error(404, "dir not found")
                return self._json({"docs_path": docs_base, "configured": True,
                                   "tree": file_tree(target, limit=800)})
            if route == "/api/docs/file":
                comp = resolve_competition(qs.get("dir", ""))
                docs_base = str((read_json(comp / "competition.json", {})
                                 or {}).get("docs_path") or "") if comp else ""
                if not docs_base:
                    return self._error(404, "docs_path not configured")
                base = Path(docs_base).resolve()
                target = (base / (qs.get("path") or "")).resolve()
                if not str(target).startswith(str(base)) or not target.is_file():
                    return self._error(404, "file not found")
                size = target.stat().st_size
                data = target.read_bytes()[:_core.MAX_FILE_BYTES]
                if not looks_textual(data):
                    return self._json({"path": qs.get("path"), "size": size, "binary": True,
                                       "note": "二进制文件不在浏览器内预览"})
                return self._json({"path": qs.get("path"), "size": size,
                                   "truncated": size > _core.MAX_FILE_BYTES,
                                   "content": data.decode("utf-8", errors="replace")})
            if route == "/api/leaderboard":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                db = _db_path_of(comp)
                if not db.exists():
                    return self._json({"rows": [], "mode": qs.get("mode", "individual")})
                mode = qs.get("mode", "individual")
                if mode not in ("team", "individual"):
                    return self._error(400, "mode must be team|individual")
                result = run_script([_core.SCRIPTS_DIR / "leaderboard.py", "query", db,
                                     "--competition", comp.name, "--mode", mode,
                                     "--comp-dir", comp], timeout=15)
                try:
                    payload = json.loads(result.get("stdout") or "{}")
                except json.JSONDecodeError:
                    payload = {"rows": [], "mode": mode, "error": "bad json"}
                return self._json(payload)
            if route == "/api/achievements":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                db = _db_path_of(comp)
                if not db.exists():
                    return self._json({"competition": comp.name, "achievements": []})
                result = run_script([_core.SCRIPTS_DIR / "achievements.py", "list", db,
                                     "--competition", comp.name], timeout=15)
                try:
                    payload = json.loads(result.get("stdout") or "{}")
                except json.JSONDecodeError:
                    payload = {"competition": comp.name, "achievements": [], "error": "bad json"}
                return self._json(payload)
            if route == "/api/resources":
                q = qs.get("q", "")
                if not q:
                    # 未给关键词是"还没搜"而非错误：返回空结果，前端不必走错误分支
                    return self._json({"query": "", "hits": [], "count": 0,
                                       "note": "missing q"})
                comp = resolve_competition(qs.get("dir", ""))
                argv = [_core.SCRIPTS_DIR / "kb_search.py", "resources", q,
                        "--kind", qs.get("kind", "all"),
                        "--top", str(int(qs.get("top", 20))),
                        "--context", str(int(qs.get("context", 1)))]
                if qs.get("category"):
                    argv += ["--category", qs["category"]]
                if comp and comp.is_dir():
                    argv += ["--comp-dir", comp]
                result = run_script(argv, timeout=15)
                try:
                    payload = json.loads(result.get("stdout") or '{"hits":[],"count":0}')
                except json.JSONDecodeError:
                    payload = {"hits": [], "count": 0, "error": "bad json"}
                return self._json(payload)
            if route == "/api/teams":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                cfg = read_json(comp / "competition.json", {})
                return self._json({"teams": (cfg or {}).get("teams", [])})
            if route == "/api/scoring":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                cfg = read_json(comp / "competition.json", {})
                scoring = (cfg or {}).get("scoring", {})
                slug = qs.get("slug")
                if slug:
                    db = _db_path_of(comp)
                    if db.exists():
                        result = run_script([_core.SCRIPTS_DIR / "leaderboard.py", "compute-scoring",
                                             db, "--competition", comp.name, "--comp-dir", comp],
                                            timeout=10)
                    return self._json({"scoring": scoring, "slug": slug})
                return self._json({"scoring": scoring})
            if route == "/api/bootstrap":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                view = competition_view(comp)
                db = _db_path_of(comp)
                leaderboard = {"rows": [], "mode": "individual"}
                if db.exists():
                    res = run_script([_core.SCRIPTS_DIR / "leaderboard.py", "query", db,
                                      "--competition", comp.name, "--mode", "individual",
                                      "--comp-dir", comp], timeout=15)
                    try:
                        leaderboard = json.loads(res.get("stdout") or "{}")
                    except json.JSONDecodeError:
                        pass
                achievements_count = 0
                if db.exists():
                    res = run_script([_core.SCRIPTS_DIR / "achievements.py", "list", db,
                                      "--competition", comp.name], timeout=15)
                    try:
                        achievements_count = len(json.loads(res.get("stdout") or "{}").get("achievements", []))
                    except json.JSONDecodeError:
                        pass
                resources_stats = {"references": 0, "writeups": 0, "external": 0}
                ref_dir = _core.SCRIPTS_DIR.parent / "references"
                if ref_dir.is_dir():
                    resources_stats["references"] = len(list(ref_dir.glob("*.md")))
                docs_dir = comp / "docs"
                if docs_dir.is_dir():
                    resources_stats["writeups"] = len(list(docs_dir.glob("*.md")))
                links_file = ref_dir / "links.json"
                if links_file.exists():
                    try:
                        resources_stats["external"] = len(json.loads(
                            links_file.read_text(encoding="utf-8")).get("links", []))
                    except json.JSONDecodeError:
                        pass
                case_map = {c.get("slug"): c.get("case") for c in view.get("challenges", [])}
                return self._json({"competition": view, "leaderboard": leaderboard,
                                   "achievements_count": achievements_count,
                                   "case_summary_map": case_map,
                                   "resources_stats": resources_stats})
            if route == "/api/env/push-history":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                hist_path = comp / "env" / "gen" / "push-history.jsonl"
                entries = []
                if hist_path.exists():
                    lines = [l for l in hist_path.read_text(encoding="utf-8",
                            errors="replace").splitlines() if l.strip()]
                    for l in lines[-int(qs.get("limit", 10)):]:
                        try:
                            entries.append(json.loads(l))
                        except json.JSONDecodeError:
                            pass
                return self._json({"entries": list(reversed(entries))})
            if route == "/api/agent-gw/dispatch":
                key = self.headers.get("X-Agent-Key", "") or (
                    self.headers.get("Authorization", "")[7:].strip()
                    if self.headers.get("Authorization", "").lower().startswith("bearer agw_") else "")
                try:
                    comp = resolve_competition(qs.get("dir", ""))
                    if not comp or not comp.is_dir():
                        return self._error(404, "unknown competition")
                    return self._json(wb_gateway.dispatch(_core.ROOT, comp, key,
                                                          category=qs.get("category", ""),
                                                          want_slug=qs.get("slug", ""),
                                                         dry_run=bool(qs.get("dry_run"))))
                except PermissionError as exc:
                    return self._error(401, str(exc), code="E_BAD_AGENT_KEY")
            if route == "/api/agent-gw/join-info":
                return self.agent_gw_join_info()
            if route == "/api/agent-gw/whoami":
                _authz = self.headers.get("Authorization", "")
                key = self.headers.get("X-Agent-Key", "") or (
                    _authz[7:].strip()
                    if _authz.lower().startswith("bearer agw_") else "")
                try:
                    return self._json(wb_gateway.whoami(_core.ROOT, key))
                except PermissionError as exc:
                    msg, code = (exc.args[0] if isinstance(exc.args[0], tuple)
                                 else (str(exc), "E_BAD_AGENT_KEY"))
                    return self._error(401, msg, code=code)
            if route == "/api/agent-gw/contract":
                return self._json(wb_gateway.contract_payload())
            if route == "/api/agent-gw/challenges":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition", code="E_UNKNOWN_COMP")
                return self._json({"challenges": wb_gateway.challenges_readonly(_core.ROOT, comp)})
            if route == "/api/agent-gw/events":
                return self._json(wb_gateway.gw_events(_core.ROOT, int(qs.get("since", 0) or 0)))
            if route == "/api/agent-gw/invite":
                return self.agent_gw_invite()
            if route == "/api/agent-gw/directory":
                result = wb_gateway.directory(_core.ROOT)
                if qs.get("name"):  # R144：按名称过滤（多 agent 时快速定位）
                    needle = qs["name"].lower()
                    result["agents"] = [a for a in result["agents"]
                                        if needle in str(a.get("name", "")).lower()]
                return self._json(result)
            if route == "/api/env/registry":
                reg_path = _core.ROOT / "workbench-data" / "registry.json"
                reg_val = ""
                try:
                    reg_val = str((json.loads(reg_path.read_text(encoding="utf-8"))
                                   or {}).get("registry") or "")
                except (OSError, json.JSONDecodeError):
                    pass
                return self._json({"registry": reg_val})
            if route == "/api/autosubmit":
                # 抢一血场景：自动提交默认开启（限额与 submitter 去重保护仍在）
                cfg = read_json(_core.ROOT / "workbench-data" / "autosubmit.json", {})
                entry = {"enabled": True, "max_live": 3}
                entry.update(cfg.get(qs.get("dir", "")) or {})
                return self._json({"enabled": bool(entry.get("enabled")),
                                   "max_live": int(entry.get("max_live", 3))})
            if route == "/api/submissions":
                comp = resolve_competition(qs.get("dir", ""))
                path = (comp or Path()) / "submissions.jsonl"
                lines = []
                if path.exists():
                    lines = [l for l in path.read_text(encoding="utf-8",
                            errors="replace").splitlines() if l.strip()]
                after = max(0, int(qs.get("after", 0)))
                entries = [read_json_line(l) for l in lines[after:]]
                return self._json({"total": len(lines), "entries": entries})
            if route.startswith("/gw/"):
                return self.gateway(route)
            if route == "/api/board":
                return self._json(board_data(qs))
            if route == "/api/kb/stats":
                # R55-K2：检索命中率与零命中清单（知识库补洞候选）
                result = run_script([_core.SCRIPTS_DIR / "kb_stats.py"], timeout=15)
                try:
                    payload = json.loads(result.get("stdout") or "{}")
                except json.JSONDecodeError:
                    payload = {"total": 0, "error": "bad json"}
                return self._json(payload)
            if route == "/api/kb":
                if not qs.get("q"):
                    return self._error(400, "missing q")
                return self._json(kb_search(qs["q"], qs.get("category"),
                                            int(qs.get("top", 10))))
            if route == "/api/prompt":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                try:
                    prompt = build_prompt(comp, qs.get("slug", ""), qs.get("style") or "continue")
                except ValueError as exc:
                    # slug 不存在等业务错误：返回 404 而不是让异常冒成 500
                    return self._error(404, str(exc))
                return self._json({"prompt": prompt})
            if route == "/api/selftest":
                return self._json(selftest_status())
            if route == "/api/health":
                return self._json({"ok": True, "root": str(_core.ROOT)})
            return self._error(404, "no such route")
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"{type(exc).__name__}: {exc}")

    def task_start(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as exc:
            return self._error(400, f"bad json: {exc}", code="E_BAD_JSON")
        try:
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            slug = body.get("slug", "")
            entry = next((c for c in competition_view(comp)["challenges"]
                          if c.get("slug") == slug), None)
            if not entry:
                raise ValueError("unknown slug")
            case_dir_rel = entry.get("case_dir") or f"cases/{slug}"
            case_dir = safe_join(comp, case_dir_rel)
            prompt = build_prompt(comp, slug, body.get("style") or "continue")
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "scratch").mkdir(exist_ok=True)
            (case_dir / "scratch" / "agent-prompt.txt").write_text(prompt, encoding="utf-8")

            demo = bool(body.get("demo"))
            if demo and body.get("sandbox"):
                raise ValueError("演示 Agent 仅支持宿主直跑，请取消 Docker 沙箱后重试")
            demo_template = None
            if demo:
                # Keep the template explicit and argv-safe at the boundary.  The
                # bundled demo_solver only reads the generated prompt and prints
                # three deterministic phases; it has no submission capability.
                # N-02: split_cmd_template quotes the placeholder paths itself,
                # so {prompt_file} stays bare here.
                demo_template = (f'"{sys.executable}" -u '
                                 f'"{Path(__file__).resolve().parent / "demo_solver.py"}" '
                                 '{prompt_file}')

            if body.get("sandbox"):
                cfg = sandbox_status()
                if not cfg["docker_ok"]:
                    raise ValueError("Docker 引擎不可达（启动 Docker Desktop 后重试）")
                # R2：并发保护——多比赛并行时防止容器数量失控
                reason = sandbox_concurrency_reason(sandbox_running_count(),
                                                    int(cfg.get("max_concurrent_sandbox") or 0))
                if reason:
                    raise ValueError(reason)
                category = str(entry.get("category") or "misc").lower()
                # 镜像选择（COMPETITION_ENV_DESIGN.md §5）：case env.image → env 题目层
                # → spec 钉住 base → L2 比赛层 → 题型层 → 兜底。env 机制只增能力不加豁免：
                # cap 白名单来自 spec 显式声明，资源上限只允许调低。
                sel = envb.resolve_image(comp, slug, category,
                                         default_image=cfg["image"],
                                         category_images=cfg.get("images") or {},
                                         exists=_image_exists)
                for prob in sel.get("mount_problems") or []:
                    raise ValueError(f"env 挂载配置错误：{prob}")
                if not sel["ok"]:
                    if sel.get("explicit_missing") in ("case", "challenge"):
                        # 显式指定的镜像缺失：宁可拒绝也不静默换镜像（pwn 换 glibc 是灾难）
                        hint = (f'python workbench/env_builder.py build "{comp}" --slug {slug}'
                                if sel["explicit_missing"] == "challenge"
                                else "修正 case.json env.image 或恢复该镜像")
                        raise ValueError(f"指定的沙箱镜像 {sel['image']} 不存在（来源 "
                                         f"{sel['explicit_missing']}）：{hint}")
                    image = cfg["image"]
                    if not cfg["image_ok"]:
                        raise ValueError(f"镜像 {cfg['image']} 不存在：在 workbench/docker/ 下执行 "
                                         f"docker build -f misc/Dockerfile -t {cfg['image']} .")
                else:
                    image = sel["image"]
                gateway_on = bool(body.get("gateway") or cfg.get("gateway"))
                if gateway_on and not upstream_key():
                    raise ValueError(f"模型网关已开启但未配置上游密钥（环境变量 "
                                     f"{cfg.get('upstream_key_env')}）或上游地址（sandbox.json upstream_base）")
                container = f"ctfwb-sbx-{uuid.uuid4().hex[:8]}"
                caps_argv = ["--cap-drop", "ALL"]
                if category == "pwn":
                    caps_argv += ["--cap-add", "SYS_PTRACE"]  # gdb/调试需要（沿用 BTFly 策略）
                for cap in sel.get("caps") or []:
                    if cap and cap not in caps_argv:  # spec 显式白名单，记入任务日志
                        caps_argv += ["--cap-add", str(cap)]
                # 资源上限：spec 只允许在 sandbox 默认之上收紧
                mem, cpus, pids = cfg["memory"], cfg["cpus"], cfg["pids"]
                res = sel.get("resources") or {}
                if res.get("memory") and _mem_bytes(res["memory"]):
                    mem = min([m for m in (mem, str(res["memory"]))
                               if _mem_bytes(m)] or [mem], key=_mem_bytes)
                if res.get("cpus"):
                    try:
                        cpus = str(min(float(cpus), float(res["cpus"])))
                    except (TypeError, ValueError):
                        pass
                if res.get("pids"):
                    try:
                        pids = min(int(pids), int(res["pids"]))
                    except (TypeError, ValueError):
                        pass
                # 多服务题目：先拉起 compose（internal 网络），solver 加入同网络；
                # 网关回程需要默认桥（N-02：网络参数一律走 argv，不再拼字符串）
                compose_meta = None
                if sel.get("services"):
                    compose_meta = _compose_up(comp / sel["compose_file"], sel["project"])
                nets: list[str] = []
                if compose_meta:
                    nets.append(compose_meta.get("network") or sel.get("network") or "")
                if gateway_on:
                    nets.append("bridge")
                nets = [n for n in nets if n] or [cfg["network"]]
                # 模型网关：一次性令牌在 docker run 时注入 env，上游 API key 不下容器
                gw_token = uuid.uuid4().hex[:24] if gateway_on else ""
                gw_argv = (["-e", f"OPENAI_API_KEY={gw_token}",
                            "-e", f"OPENAI_BASE_URL=http://host.docker.internal:{_core.RUNTIME['port']}/gw/{gw_token}/v1",
                            "-e", f"OPENAI_API_BASE=http://host.docker.internal:{_core.RUNTIME['port']}/gw/{gw_token}/v1"]
                           if gateway_on else [])
                cmd_inside = (cfg["cmd"]
                              .replace("{prompt_file}", "/workspace/scratch/agent-prompt.txt")
                              .replace("{case_dir}", "/workspace")
                              .replace("{solver_dir}", "/solver"))
                sandbox_argv = [
                    *(envb.docker_prefix() or ["docker"]), "run", "--rm",
                    "--name", container, *caps_argv,
                    "--security-opt", "no-new-privileges",
                    "--memory", str(mem), "--cpus", str(cpus), "--pids-limit", str(pids),
                ]
                for net in nets:
                    sandbox_argv += ["--network", net]
                sandbox_argv += ["--add-host", "host.docker.internal:host-gateway", *gw_argv,
                                 "-v", f"{envb.docker_path(case_dir)}:/workspace",
                                 "-v", f"{envb.docker_path(Path(__file__).resolve().parent)}:/solver:ro"]
                for m in sel.get("mounts") or []:
                    sandbox_argv += ["-v", f"{envb.docker_path(m['host'])}:{m['container']}:ro"]
                sandbox_argv += ["-w", "/workspace", image, *split_cmd_template(cmd_inside)]
                task = TASKS.run_custom(comp.name, slug, body.get("agent") or "sandbox",
                                        sandbox_argv, cwd=case_dir, container=container,
                                        compose=compose_meta)
                if gw_token:
                    TASKS.register_token(gw_token, task["id"])
                    task = dict(task, gateway_base=f"http://host.docker.internal:{_core.RUNTIME['port']}/gw/{gw_token}/v1")
                return self._json({"ok": True, "task": task, "sandbox": True,
                                   "image": image,
                                   "image_source": sel["source"] if sel["ok"] else "fallback",
                                   "category": category, "services": bool(sel.get("services")),
                                   "gateway": bool(gateway_on)})

            task = TASKS.start(comp, slug, case_dir_rel, prompt,
                               demo_template or body.get("cmd_template"),
                               ("demo-agent" if demo else (body.get("agent") or "")),
                               demo=demo)
            return self._json({"ok": True, "task": task, "demo": demo})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def task_stop(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            return self._json(TASKS.stop(body.get("id", "")))
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)

    def env_build(self):
        """构建/预热比赛环境：env_builder 以子进程任务跑，输出进任务日志。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            mode = ("preheat" if body.get("preheat")
                    else "base_rebuild" if body.get("base_rebuild")
                    else "clean" if body.get("clean") else "build")
            # R45：多 slug 批量（env_builder 原生支持重复 --slug + --jobs 并行）
            slugs = [str(s) for s in (body.get("slugs") or [])]
            for s in slugs:
                if not envb.SLUG_RE.match(s) or ".." in s:
                    raise ValueError(f"slug 不合法：{s}")
            slug = str(body.get("slug") or "")
            if slug and (not envb.SLUG_RE.match(slug) or ".." in slug):
                raise ValueError(f"slug 不合法：{slug}")
            if mode == "build" and not slug and not slugs and not body.get("comp_image") and not body.get("all"):
                raise ValueError("需要 slug、slugs、comp_image 或 all 之一")
            argv = [sys.executable, str(Path(__file__).resolve().parent / "env_builder.py"),
                    mode, str(comp)]
            if mode == "build":
                for s in slugs:
                    argv += ["--slug", s]
                if slug and slug not in slugs:
                    argv += ["--slug", slug]
                if body.get("comp_image"):
                    argv += ["--comp-image"]
                if body.get("all"):
                    argv += ["--all"]
                if body.get("force"):
                    argv += ["--force"]
                if body.get("jobs"):
                    argv += ["--jobs", str(int(body["jobs"]))]
            elif mode == "clean":
                argv += ["--keep-days", str(int(body.get("keep_days", 7)))]
                if body.get("dry_run"):
                    argv += ["--dry-run"]
            elif body.get("categories"):
                argv += ["--categories", str(body["categories"])]
            task = TASKS.run_custom(comp.name, f"env-{mode}:{slug or 'comp'}", "env-builder",
                                    argv, cwd=comp)
            return self._json({"ok": True, "task": task})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def env_verify(self):
        """对已构建镜像跑探针矩阵（工具存在性 + 版本断言），输出进任务日志。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            slug = str(body.get("slug") or "")
            if not slug or not envb.SLUG_RE.match(slug) or ".." in slug:
                raise ValueError(f"slug 不合法：{slug}")
            argv = [sys.executable, str(Path(__file__).resolve().parent / "env_builder.py"),
                    "verify", str(comp), "--slug", slug]
            task = TASKS.run_custom(comp.name, f"env-verify:{slug}", "env-verify",
                                    argv, cwd=comp)
            return self._json({"ok": True, "task": task})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def env_registry_save(self):
        """R42：保存 Docker 仓库地址（只存地址；凭证只在本机 docker login）。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            reg = str(body.get("registry") or "").strip().rstrip("/")
            if reg and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:\-]*", reg):
                raise ValueError("仓库地址格式不合法（域名[:端口][/路径]）")
            path = _core.ROOT / "workbench-data" / "registry.json"
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps({"registry": reg}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
            return self._json({"ok": True, "registry": reg})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def env_push(self):
        """R42：推送已构建镜像到仓库（env_builder 子进程任务）。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            argv = [sys.executable, str(Path(__file__).resolve().parent / "env_builder.py"),
                    "push", str(comp)]
            for slug in body.get("slugs") or []:
                slug = str(slug)
                if not envb.SLUG_RE.match(slug) or ".." in slug:
                    raise ValueError(f"slug 不合法：{slug}")
                argv += ["--slug", slug]
            registry = str(body.get("registry") or "").strip().rstrip("/")
            if not registry:  # 未显式指定时用已保存的地址（来自本 ROOT 的 registry.json）
                registry = str((read_json(_core.ROOT / "workbench-data" / "registry.json", {})
                                or {}).get("registry") or "")
            if registry:
                argv += ["--registry", registry]
            if body.get("no_comp"):
                argv += ["--no-comp"]
            task = TASKS.run_custom(comp.name, "env-push", "env-push", argv, cwd=comp)
            return self._json({"ok": True, "task": task})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def env_services_down(self):
        """R46-E5：手动停止题目服务（compose down -v），不必等任务结束。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            slug = str(body.get("slug") or "")
            if not slug or not envb.SLUG_RE.match(slug) or ".." in slug:
                raise ValueError(f"slug 不合法：{slug}")
            built = envb.read_built(comp)
            rec = (built.get("images") or {}).get(slug) or {}
            if not rec.get("project"):
                raise ValueError(f"{slug} 未配置 services（无 compose 工程可停止）")
            compose_file = str(comp / rec["compose_file"]) if rec.get("compose_file") else ""
            _compose_down(rec["project"], compose_file)
            stopped = [c["name"] for c in envb.docker_runtime().get("containers", [])
                       if rec["project"] in c["name"]]
            return self._json({"ok": True, "project": rec["project"],
                               "stopped": not stopped})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def sandbox_save(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as exc:
            return self._error(400, f"bad json: {exc}", code="E_BAD_JSON")
        cfg_path = _core.ROOT / "workbench-data" / "sandbox.json"
        cfg_path.parent.mkdir(exist_ok=True)
        merged = {**sandbox_config(),
                  **{k: body[k] for k in SANDBOX_DEFAULTS if k in body}}
        cfg_path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        return self._json({"ok": True, **sandbox_status()})

    def agent_start(self):
        """派发开赛自动化代理：kind=platform（对接平台写提交脚本）| fetch（自动抓题注册）。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as exc:
            return self._error(400, f"bad json: {exc}", code="E_BAD_JSON")
        try:
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            kind = body.get("kind", "")
            spec = {"platform": ("platform-agent", "platform_agent.py", "plat"),
                    "fetch": ("chall-agent", "fetch_challs.py", "fetch"),
                    "buuctf": ("platform-agent", "platform_agent.py", "buuctf")}.get(kind)
            if not spec:
                raise ValueError("kind 必须是 platform / fetch / buuctf")
            agent, script, label = spec
            solver_dir = Path(__file__).resolve().parent
            argv = [sys.executable, "-u", str(solver_dir / script), str(comp)]
            if kind == "buuctf":
                argv += ["--preset", "buuctf"]
            if kind == "fetch":
                if body.get("limit"):
                    argv += ["--limit", str(int(body["limit"]))]
            if body.get("categories"):
                # N-01 白名单：请求体直接进 argv 之前先收紧字符集（纵深防御）
                cats = str(body["categories"]).strip()
                if not re.fullmatch(r"[A-Za-z0-9_\- ]{1,20}(,[A-Za-z0-9_\- ]{1,20})*", cats):
                    raise ValueError("categories 只允许字母/数字/连字符/下划线，逗号分隔")
                argv += ["--categories", cats]
            if body.get("reconcile"):
                argv += ["--reconcile"]  # R21：对账模式（platform.solved 配置）
            task = TASKS.run_custom(comp.name, label, agent, argv, cwd=comp)
            return self._json({"ok": True, "task": task})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def hunter_start(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as exc:
            return self._error(400, f"bad json: {exc}", code="E_BAD_JSON")
        try:
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            solver_dir = Path(__file__).resolve().parent
            cfg_path = _core.ROOT / "workbench-data" / "autosubmit.json"
            max_live = 3
            cfg_all = read_json(cfg_path, {})
            if isinstance(cfg_all.get(comp.name), dict):
                max_live = int(cfg_all[comp.name].get("max_live", 3))
            argv = [sys.executable, "-u", str(solver_dir / "flag_hunter.py"), str(comp),
                    "--autosubmit-config", str(cfg_path), "--max-live", str(max_live)]
            task = TASKS.run_custom(comp.name, "flag-hunt", "flag-agent", argv, cwd=comp)
            return self._json({"ok": True, "task": task})
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def autosubmit_save(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            comp = resolve_competition(body.get("dir", ""))
            if not comp or not comp.is_dir():
                raise ValueError("unknown competition")
            cfg_path = _core.ROOT / "workbench-data" / "autosubmit.json"
            cfg_path.parent.mkdir(exist_ok=True)
            cfg_all = read_json(cfg_path, {})
            cfg_all[comp.name] = {"enabled": bool(body.get("enabled")),
                                  "max_live": max(1, min(int(body.get("max_live", 3)), 10))}
            cfg_path.write_text(json.dumps(cfg_all, ensure_ascii=False, indent=1), encoding="utf-8")
            return self._json({"ok": True, **cfg_all[comp.name]})
        except (ValueError, TypeError) as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)

    def events_stream(self, qs: dict):
        """SSE：推送比赛事件流增量与任务状态变化，断开由客户端触发。"""
        comp = resolve_competition(qs.get("dir", ""))
        if not comp or not comp.is_dir():
            return self._error(404, "unknown competition")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "close")   # AG-15：流式响应退出 keep-alive
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        events_path = comp / "events.jsonl"
        # R90：追加读——记录字节偏移与 mtime，仅当 mtime 变化时 seek 读新增字节
        # （此前每秒全量 read_text + splitlines，大事件流 × N 连接是隐形 CPU 大户）
        offset = events_path.stat().st_size if events_path.exists() else 0
        try:
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            idle = 0
            last_mtime = events_path.stat().st_mtime if events_path.exists() else 0
            while idle < 600:  # 单连接最长 ~10 分钟，前端 EventSource 自动重连
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                if events_path.exists():
                    st = events_path.stat()
                    if st.st_mtime != last_mtime:
                        last_mtime = st.st_mtime
                        if st.st_size < offset:  # 轮换/清空：从头重读
                            offset = 0
                        if st.st_size > offset:
                            with events_path.open("rb") as ef:
                                ef.seek(offset)
                                chunk = ef.read(st.st_size - offset).decode(
                                    "utf-8", errors="replace")
                                offset = st.st_size
                            for line in chunk.splitlines():
                                if line.strip():
                                    payload = json.dumps(read_json_line(line),
                                                         ensure_ascii=False)
                                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(1.0)
                idle += 1
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def api_file(self, qs: dict):
        comp = resolve_competition(qs.get("dir", ""))
        target = safe_join(comp or Path(), qs.get("path", ""))
        if not target or not target.is_file():
            return self._error(404, "file not found")
        size = target.stat().st_size
        data = target.read_bytes()[:_core.MAX_FILE_BYTES]
        if not looks_textual(data):
            return self._json({"path": qs.get("path"), "size": size, "binary": True,
                               "note": "二进制文件不在浏览器内预览，请用本机工具查看"})
        return self._json({"path": qs.get("path"), "size": size,
                           "truncated": size > _core.MAX_FILE_BYTES,
                           "content": data.decode("utf-8", errors="replace")})

    # -- 模型网关（参考 BTFly modelgateway：上游 key 只在宿主，容器持一次性令牌）
    def gateway(self, route: str):
        try:
            return self._gateway(route)
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as exc:  # noqa: BLE001
            try:
                return self._error(500, f"gateway: {type(exc).__name__}: {exc}")
            except Exception:  # noqa: BLE001
                pass

    def _gateway(self, route: str):
        parts = route.split("/")  # /gw/<token>/v1/...
        if len(parts) < 3:
            return self._error(404, "bad gateway path")
        token = parts[2]
        with TASKS._lock:
            info = TASKS._gateway_tokens.get(token)
        if info is None:
            return self._error(401, "无效或已撤销的网关令牌")
        # R33：每令牌限速——失控的 Agent 循环不能无限烧上游
        rate_cap = int(sandbox_config().get("gateway_rate_per_min") or 30)
        now_ts = time.time()
        with TASKS._lock:  # R85：限速窗口读改写全程持锁（并发下丢 hit 会放行超限请求）
            info = TASKS._gateway_tokens.get(token)
            if info is None:
                return self._error(401, "无效或已撤销的网关令牌")  # 竞态 revoke
            hits = [ts for ts in info.setdefault("hits", []) if now_ts - ts < 60]
            if rate_cap > 0 and len(hits) >= rate_cap:
                return self._json({"error": f"gateway rate limit: {rate_cap}/min per token"}, 429)
            hits.append(now_ts)
            info["hits"] = hits
        rest = "/" + "/".join(parts[3:])  # /v1/...
        base, key = upstream_base(), upstream_key()
        if not base or not key:
            return self._error(503, "网关未配置上游（sandbox.json upstream_base + 环境变量密钥）")
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(base + rest, data=body, method=self.command)
        for h in ("Content-Type", "Accept"):
            if self.headers.get(h):
                req.add_header(h, self.headers[h])
        req.add_header("Authorization", "Bearer " + key)
        try:
            up = urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            return self._json({"error": "upstream error"}, e.code)
        except Exception as exc:  # noqa: BLE001
            return self._error(502, f"upstream failed: {exc}")
        self.send_response(up.status)
        self.send_header("Content-Type", up.headers.get("Content-Type", "application/json"))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")   # AG-15：流式转发退出 keep-alive
        self._security_headers()
        self.end_headers()
        total = 0
        try:
            while True:
                chunk = up.read(8192)
                if not chunk:
                    break
                total += len(chunk)
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with TASKS._lock:
                # R85：计费写回加锁——并发请求下读改写会丢计数
                with TASKS._lock:
                    info_after = TASKS._gateway_tokens.get(token)
                    if info_after is not None:
                        info_after["bytes"] = info_after.get("bytes", 0) + total
                        info_after["requests"] = info_after.get("requests", 0) + 1

    # -- POST
    def auth_exchange(self, qs: dict) -> None:
        """POST /api/auth/exchange：用裸 token 换取 15 分钟签名 session。

        body: {"token": "..."} 或 ?token=...（兼容老 Agent）
        返回: {"session": "...", "expires_in": 900}
        同时 Set-Cookie: wb_session=<session>; HttpOnly; SameSite=Strict; Max-Age=900; Path=/
        """
        if not _core.RUNTIME.get("auth_token"):
            return self._error(400, "未配置 --token，无需 exchange",
                               code="E_NO_TOKEN_CONFIGURED")
        token = (qs.get("token") or "").strip()
        if not token:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if 0 < length <= _core.MAX_BODY_BYTES:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    token = (body.get("token") or "").strip()
            except Exception:  # noqa: BLE001
                pass
        if not token or not hmac.compare_digest(token, _core.RUNTIME.get("auth_token", "")):
            return self._error(401, "令牌无效", code="E_BAD_TOKEN",
                               hint="检查 --token / WB_TOKEN 是否匹配")
        session, expires_in = _issue_session()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie",
                         f"{_SESSION_COOKIE}={session}; HttpOnly; SameSite=Strict; "
                         f"Max-Age={expires_in}; Path=/")
        self._security_headers()
        payload = json.dumps({"session": session, "expires_in": expires_in}).encode("utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _is_agent_key_call(self) -> bool:
        """R104：识别 agent key 调用——注册/吊销等管理端点仅限 admin 凭证。"""
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer ") and auth[7:].strip().startswith(wb_gateway.KEY_PREFIX):
            return True
        return self.headers.get("X-Agent-Key", "").startswith(wb_gateway.KEY_PREFIX)

    def _agent_key(self) -> str:
        key = self.headers.get("X-Agent-Key", "")
        if key:
            return key.strip()
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer agw_"):
            return auth[7:].strip()
        return ""

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"请求体不是合法 JSON：{exc}") from exc
        return data if isinstance(data, dict) else {}

    def agent_gw_register(self):
        try:
            if self._is_agent_key_call():
                return self._error(403, "agent key 不能注册新 agent（需 admin 凭证）",
                                   code="E_ADMIN_ONLY")
            if not _check_origin(self.headers):  # cookie 鉴权下的 CSRF 防护
                return self._error(403, "跨来源请求被拒绝", code="E_BAD_ORIGIN")
            if not _admin_ok(self.headers):
                return self._error(401, "注册 agent 需要管理员令牌（--token 或浏览器 session）",
                                   code="E_ADMIN_REQUIRED")
            body = self._body()
            role = str(body.get("role") or "")
            result = wb_gateway.register(_core.ROOT, body.get("name", ""),
                                         body.get("capabilities") or [], role=role,
                                         label=str(body.get("label") or ""),
                                         note=str(body.get("note") or ""))
            return self._json(result)
        except ValueError as exc:
            return self._error(400, str(exc))

    def agent_gw_join(self):
        """自助入网：只认入网码，不需要管理员令牌（共享模式的主入口）。"""
        try:
            body = self._body()
            token = self.headers.get("X-Join-Token", "") or str(body.get("join_token") or "")
            base = _core.RUNTIME.get("base_url") or \
                f"http://127.0.0.1:{_core.RUNTIME.get('port', 8787)}/"
            result = wb_gateway.join(_core.ROOT, token,
                                     name=str(body.get("name") or ""),
                                     label=str(body.get("label") or ""),
                                     capabilities=body.get("capabilities") or [],
                                     role=str(body.get("role") or "solver"),
                                     base_url=base)
            result["brief"] = wb_gateway.join_brief(
                base, wb_gateway.read_join_token(_core.ROOT),
                name=str(result["agent"].get("name") or ""),
                dir_name=str(_core.RUNTIME.get("default_dir") or ""))
            return self._json(result)
        except PermissionError as exc:
            return self._error(403, str(exc), code="E_BAD_JOIN_TOKEN")
        except ValueError as exc:
            if isinstance(exc.args[0], tuple):   # AG-07：label/note 超长等 400 类
                return self._json({"ok": False, "error": exc.args[0][0],
                                   "code": exc.args[0][1]}, 400)
            return self._error(409, str(exc), code="E_NAME_TAKEN")

    def agent_gw_label(self):
        try:
            body = self._body()
            kwargs = {}
            for key in ("label", "note", "role", "capabilities"):
                if key in body:
                    kwargs[key] = body.get(key)
            return self._json(wb_gateway.label(_core.ROOT, self._agent_key(), **kwargs))
        except PermissionError as exc:
            return self._error(401, str(exc), code="E_BAD_AGENT_KEY")
        except LookupError as exc:
            _m, _c = (exc.args[0] if isinstance(exc.args[0], tuple)
                      else (str(exc), "E_UNKNOWN_SLUG"))
            return self._error(404, _m, code=_c)
        except ValueError as exc:
            if isinstance(exc.args[0], tuple):
                _t = exc.args[0]
                return self._json({"ok": False, "error": _t[0], "code": _t[1],
                                   **({"allowed": _t[2]} if len(_t) > 2 else {})}, 400)
            return self._error(400, str(exc), code="E_INVALID")
        except ValueError as exc:
            return self._error(400, str(exc))

    def agent_gw_join_token(self):
        try:
            if self._is_agent_key_call():
                return self._error(403, "agent key 不能改入网码", code="E_ADMIN_ONLY")
            if not _check_origin(self.headers):
                return self._error(403, "跨来源请求被拒绝", code="E_BAD_ORIGIN")
            if not _admin_ok(self.headers):
                return self._error(401, "需要管理员令牌", code="E_ADMIN_REQUIRED")
            body = self._body()
            if body.get("disable"):
                wb_gateway.disable_join(_core.ROOT)
                return self._json({"ok": True, "join_token": "", "enabled": False})
            token = wb_gateway.rotate_join_token(_core.ROOT)
            return self._json({"ok": True, "join_token": token, "enabled": True})
        except ValueError as exc:
            return self._error(400, str(exc))

    def agent_gw_join_info(self):
        if not _admin_ok(self.headers):
            return self._error(403, "仅管理员可查看入网码", code="E_ADMIN_REQUIRED")
        port = _core.RUNTIME.get("port", 8787)
        exposed = bool(_core.RUNTIME.get("exposed"))
        urls = list(_core.local_urls(port)) if exposed else [f"http://127.0.0.1:{port}/"]
        base = _core.effective_base_url(urls, _core.ROOT) if exposed \
            else f"http://127.0.0.1:{port}/"
        token = wb_gateway.read_join_token(_core.ROOT)
        return self._json({
            "exposed": exposed,
            "urls": urls,
            "base_url": base,
            "join_token": token,
            "join_enabled": bool(token),
            "default_dir": str(_core.RUNTIME.get("default_dir") or ""),
            "brief": wb_gateway.join_brief(base, token or "<未开启>",
                                           dir_name=str(_core.RUNTIME.get("default_dir") or "")),
        })

    def share_toggle(self, qs: dict):
        """R170：AI 看板一键开关局域网共享（免重启进程）。

        仅管理员（_admin_ok 拒 agent key）。开启前先落常驻令牌与入网码，
        新生成的令牌随响应返回（浏览器存 localStorage 供会话过期静默续期）。
        切换经 0.25s timer 执行——先应答再关旧监听，worker 线程内同步切换会自等待死锁。
        """
        if not _admin_ok(self.headers, qs):
            return self._error(403, "仅管理员可切换共享模式", code="E_ADMIN_REQUIRED")
        try:
            body = self._body()
        except Exception:  # noqa: BLE001
            body = {}
        enabled = bool(body.get("enabled"))
        fn = _core.RUNTIME.get("share_switch")
        if fn is None:
            return self._error(503, "共享切换不可用（服务器未就绪）")
        new_token = ""
        if enabled:
            if not _core.RUNTIME.get("auth_token"):
                new_token = _core.lan_token(_core.ROOT)
                _core.RUNTIME["auth_token"] = new_token
            wb_gateway.ensure_join_token(_core.ROOT)
        threading.Timer(0.25, lambda: fn(enabled)).start()
        return self._json({"ok": True, "switching": True, "enabled": enabled,
                           "token": new_token})

    def share_base_url(self):
        """R177：多网卡地址切换——选定对外展示/接入指令使用的地址（admin）。

        校验：必须是本机当前网卡地址之一（拒绝任意 URL 注入 brief）。
        """
        if not _admin_ok(self.headers):
            return self._error(403, "仅管理员可切换地址", code="E_ADMIN_REQUIRED")
        try:
            body = self._body()
        except Exception:  # noqa: BLE001
            body = {}
        url = str(body.get("url") or "").strip()
        port = _core.RUNTIME.get("port", 8787)
        urls = [f"http://127.0.0.1:{port}/"] if not _core.RUNTIME.get("exposed") \
            else _core.local_urls(port)
        if url not in urls or url.startswith("http://127.0.0.1"):
            return self._error(400, "地址必须是本机当前网卡地址之一", code="E_BAD_URL")
        _core.set_lan_url_pref(_core.ROOT, url)
        return self._json({"ok": True, "base_url": url, "urls": urls})

    def agent_gw_heartbeat(self):
        try:
            body = self._body()
            kwargs = {}
            if "note" in body:
                kwargs["note"] = body.get("note")
            # AG-05：current_slug 三态——缺省 None=不变；null/""=清空；值=设置
            cs = body["current_slug"] if "current_slug" in body else None
            return self._json(wb_gateway.heartbeat(
                _core.ROOT, self._agent_key(),
                str(body.get("status") or ""), cs, **kwargs))
        except PermissionError as exc:
            return self._error(401, str(exc), code="E_BAD_AGENT_KEY")
        except LookupError as exc:
            _m, _c = (exc.args[0] if isinstance(exc.args[0], tuple)
                      else (str(exc), "E_UNKNOWN_SLUG"))
            return self._error(404, _m, code=_c)
        except ValueError as exc:
            if isinstance(exc.args[0], tuple):
                _t = exc.args[0]
                return self._json({"ok": False, "error": _t[0], "code": _t[1],
                                   **({"allowed": _t[2]} if len(_t) > 2 else {})}, 400)
            return self._error(400, str(exc), code="E_INVALID")

    def agent_gw_env(self):
        """R192：题目容器环境——协作 AI 在统一环境里解题（不再自行装环境）。

        POST {slug, action: open|exec|renew|close|status, cmd?, workdir?}
        鉴权：X-Agent-Key；exec/renew/close 需该题在认领名单中（或本地管理员）。
        """
        try:
            body = self._body()
            key = self._agent_key()
            agent = wb_gateway.authenticate(_core.ROOT, key)
            if agent is None:
                return self._error(401, "需要 agent key", code="E_BAD_AGENT_KEY")
            slug = str(body.get("slug") or "").strip()
            action = str(body.get("action") or "").strip()
            if not slug or not action:
                return self._error(400, "slug 与 action 必填", code="E_INVALID")
            comp = _core.resolve_competition(str(body.get("dir") or "")) if body.get("dir") else None
            if comp is None:
                comp = _core.resolve_competition(_core.RUNTIME.get("competition", ""))                     or _core.list_competitions()[0]["dir"] if _core.list_competitions() else None
            if comp is None or not comp.is_dir():
                return self._error(404, "unknown competition", code="E_UNKNOWN_COMP")
            view = _core.competition_view(comp)
            entry = next((c for c in view.get("challenges", []) if c.get("slug") == slug), None)
            if entry is None:
                return self._error(404, f"unknown slug: {slug}", code="E_UNKNOWN_SLUG")

            # 写操作校验认领（open/status 放宽：看题不占题原则）
            if action in ("exec", "renew", "close"):
                claims = [c for c in wb_gateway.active_claims(_core.ROOT)
                          if c.get("slug") == slug]
                mine = any(c.get("agent_id") == agent.get("id") for c in claims)
                if not mine and agent.get("role") != "observer":
                    # 未认领：自动代领（与写 case 同语义）——共解时代领不抢他人
                    if not claims:
                        wb_gateway.claim(_core.ROOT, key, slug)
                    else:
                        return self._error(403, f"该题正由 {[c.get('agent_tag') for c in claims]} 认领，"
                                       "共解请先 claim co:true", code="E_NOT_CLAIMED")

            case_rel = entry.get("case_dir") or f"cases/{slug}"
            case_dir = _core.safe_join(comp, case_rel)
            if action == "open":
                r = wb_env.open_env(_core.ROOT, comp, case_dir, slug,
                                    str(entry.get("category") or "misc"))
            elif action == "exec":
                r = wb_env.exec_cmd(_core.ROOT, slug, str(body.get("cmd") or ""),
                                    str(body.get("workdir") or "/workspace"))
            elif action == "renew":
                r = wb_env.renew(_core.ROOT, slug, int(body.get("seconds") or 0))
            elif action == "close":
                r = wb_env.close(_core.ROOT, slug)
            elif action == "status":
                r = {"ok": True, "env": wb_env.status(_core.ROOT, slug).get(slug)}
            else:
                return self._error(400, f"action 必须是 open/exec/renew/close/status",
                                   code="E_INVALID")
            return self._json(r)
        except PermissionError as exc:
            return self._error(401, str(exc), code="E_BAD_AGENT_KEY")
        except ValueError as exc:
            return self._error(400, str(exc), code="E_INVALID")
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"env: {type(exc).__name__}: {exc}")

    def agent_gw_invite(self):
        """R183：邀请 AI 提示词——真实地址/入网码/当前比赛自动填充，可直接复制给任何 AI。"""
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query).items()}
        urls = _core.local_urls(_core.RUNTIME.get("port", 8787)) or ["http://127.0.0.1:8787/"]
        base = urls[0].rstrip("/")
        token = wb_gateway.read_join_token(_core.ROOT) or "<入网已关闭：POST /api/agent-gw/join-token {\"rotate\":true} 先开启>"
        comp_dir = (qs.get("dir") or "").strip() or "<比赛目录名>"
        q = "'"
        lines = [
            "你是 CTF 工作台的协作 agent。网关地址（任选一个能通的）：",
            *[f"  {u}" for u in urls],
            "",
            "■ 1. 入网（拿你自己的 agw_ 密钥，只显示一次）",
            f'curl -s -X POST {base}/api/agent-gw/join -H "Content-Type: application/json" -H "X-Join-Token: {token}" -d {q}{{"name":"你的名字","label":"你的专长"}}{q}',
            '→ 返回 {"agent_key":"agw_...","agent":{"tag":"AI2",...}}',
            '之后所有请求都带 -H "X-Agent-Key: agw_..."',
            "",
            "■ 2. 打标签 / 心跳（每 5 分钟）",
            f'curl -s -X POST {base}/api/agent-gw/label -H "X-Agent-Key: agw_..." -H "Content-Type: application/json" -d {q}{{"label":"主攻 Web","note":"当前思路一句话","capabilities":["web"]}}{q}',
            f'curl -s -X POST {base}/api/agent-gw/heartbeat -H "X-Agent-Key: agw_..." -H "Content-Type: application/json" -d {q}{{"status":"working","current_slug":"<slug>"}}{q}',
            "（中文请用 UTF-8 文件方式发，别从 GBK 终端直接敲）",
            "",
            "■ 2.5 自检（key 是否有效 / 我的认领与剩余时间）",
            f'curl -s {base}/api/agent-gw/whoami -H "X-Agent-Key: agw_..."',
            "",
            "■ 3. 领题（按优先级自动分配 + 认领，TTL 45 分钟）",
            "先看有什么题（只读，绝不占题）：",
            f'curl -s "{base}/api/agent-gw/challenges?dir={comp_dir}" -H "X-Agent-Key: agw_..."',
            "试分配（不认领）：dispatch 加 &dry_run=1；协作事件流：GET /api/agent-gw/events?since=0",
            f'curl -s "{base}/api/agent-gw/dispatch?dir={comp_dir}" -H "X-Agent-Key: agw_..."',
            "→ assignment.prompt = 题面 + 上下文 + 前任交接简报",
            f'同题共解（多 AI 各走各的方向）：curl -s -X POST {base}/api/agent-gw/claim -H "X-Agent-Key: agw_..." -d {q}{{"slug":"<slug>","co":true}}{q}',
            "",
            "■ 4. 写解题过程（身份自动归属，题目子看板按你分列、思维导图按你分支）",
            f'curl -s -X POST {base}/api/action -H "X-Agent-Key: agw_..." -H "Content-Type: application/json" -d {q}{{"action":"case.attempt","params":{{"dir":"{comp_dir}","case_dir":"cases/<slug>","hypothesis":"quick","action":"做了什么","result":"结果如何","outcome":"success|partial|failure|error"}}}}{q}',
            "同级动作：case.hypothesis（登记解题方向）/ case.finding（证据）/ case.candidate_add（flag 候选登记）",
            "",
            "■ 3.5 题目容器环境（推荐：在统一环境里解题，勿自行 pip/apt 装环境）",
            f'开环境：curl -s -X POST {base}/api/agent-gw/env -H "X-Agent-Key: agw_..." -d {q}{{"slug":"<slug>","action":"open"}}{q}',
            f'执行：… -d {q}{{"slug":"<slug>","action":"exec","cmd":"python3 solve.py"}}{q}（工作目录 /workspace=case，产物落 /workspace/work/）',
            "续期/关闭：action renew / close；状态：GET /api/env/status?dir=<比赛>",
            "",
            "■ 5. 交接 / 换题",
            f'curl -s -X POST {base}/api/agent-gw/handoff -H "X-Agent-Key: agw_..." -H "Content-Type: application/json" -d {q}{{"slug":"<slug>","summary":"阶段结论","findings":["关键线索"]}}{q}',
            "",
            "■ 规则",
            "- 同题可多人共解（claim 带 co:true）：只写自己路线的记录，从别人的结论上接力而不是推翻",
            "- 密钥别贴进聊天；名册 GET /api/agent-gw/directory；全量 API 见 GET /api/help",
        ]
        body = ("\n".join(lines)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def agent_gw_claim(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            key = self.headers.get("X-Agent-Key", "") or (
                self.headers.get("Authorization", "")[7:].strip()
                if self.headers.get("Authorization", "").lower().startswith("bearer agw_") else "")
            return self._json(wb_gateway.claim(_core.ROOT, key, str(body.get("slug") or ""),
                                                bool(body.get("co"))))
        except PermissionError as exc:
            return self._error(401, str(exc), code="E_BAD_AGENT_KEY")
        except LookupError as exc:
            msg, code = (exc.args[0] if isinstance(exc.args[0], tuple)
                         else (str(exc), "E_UNKNOWN_SLUG"))
            return self._error(404, msg, code=code)
        except ValueError as exc:
            if isinstance(exc.args[0], tuple):
                msg, code = exc.args[0][0], exc.args[0][1]
            else:
                msg, code = str(exc), "E_ALREADY_CLAIMED"
            return self._error(409 if code == "E_ALREADY_CLAIMED" else 400, msg, code=code)

    def agent_gw_handoff(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            key = self.headers.get("X-Agent-Key", "") or (
                self.headers.get("Authorization", "")[7:].strip()
                if self.headers.get("Authorization", "").lower().startswith("bearer agw_") else "")
            return self._json(wb_gateway.handoff(_core.ROOT, key,
                                                 str(body.get("slug") or ""),
                                                 str(body.get("summary") or ""),
                                                 body.get("findings") or []))
        except PermissionError as exc:
            return self._error(401, str(exc), code="E_BAD_AGENT_KEY")
        except LookupError as exc:
            _m, _c = (exc.args[0] if isinstance(exc.args[0], tuple)
                      else (str(exc), "E_UNKNOWN_SLUG"))
            return self._error(404, _m, code=_c)
        except ValueError as exc:
            if isinstance(exc.args[0], tuple):
                _t = exc.args[0]
                return self._json({"ok": False, "error": _t[0], "code": _t[1],
                                   **({"allowed": _t[2]} if len(_t) > 2 else {})}, 400)
            return self._error(400, str(exc), code="E_INVALID")
        except ValueError as exc:
            return self._error(400, str(exc))

    def agent_gw_release(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            key = self.headers.get("X-Agent-Key", "") or (
                self.headers.get("Authorization", "")[7:].strip()
                if self.headers.get("Authorization", "").lower().startswith("bearer agw_") else "")
            return self._json(wb_gateway.release(_core.ROOT, key, str(body.get("slug") or "")))
        except PermissionError as exc:
            return self._error(401, str(exc), code="E_BAD_AGENT_KEY")

    def agent_gw_revoke(self):
        try:
            if self._is_agent_key_call():
                return self._error(403, "agent key 不能吊销其他 agent（需 admin 凭证）",
                                   code="E_ADMIN_ONLY")
            if not _check_origin(self.headers):
                return self._error(403, "跨来源请求被拒绝", code="E_BAD_ORIGIN")
            if not _admin_ok(self.headers):
                return self._error(401, "吊销 agent 需要管理员令牌", code="E_ADMIN_REQUIRED")
            body = self._body()
            return self._json(wb_gateway.revoke(_core.ROOT, str(body.get("agent_id") or "")))
        except ValueError as exc:
            return self._error(404, str(exc))

    def do_POST(self):
        self._track_client()
        if _core.RUNTIME.get("verbose"):
            print(f"{self.command} {self._redact(self.path)}", file=sys.stderr, flush=True)
        parsed = urllib.parse.urlparse(self.path)
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if parsed.path.startswith("/gw/"):
            return self.gateway(parsed.path)
        # /api/auth/exchange：必须在 _authorized 与 Origin 检查之前（该路由只接受裸 token）
        if parsed.path == "/api/auth/exchange":
            return self.auth_exchange(qs)
        if parsed.path == "/api/agent-gw/register":
            return self.agent_gw_register()
        if parsed.path == "/api/agent-gw/join":
            return self.agent_gw_join()
        if parsed.path == "/api/agent-gw/label":
            return self.agent_gw_label()
        if parsed.path == "/api/agent-gw/join-token":
            return self.agent_gw_join_token()
        if parsed.path == "/api/agent-gw/heartbeat":
            return self.agent_gw_heartbeat()
        if parsed.path == "/api/agent-gw/invite":
            return self.agent_gw_invite()
        if parsed.path == "/api/agent-gw/env":
            return self.agent_gw_env()
        if parsed.path == "/api/agent-gw/claim":
            return self.agent_gw_claim()
        if parsed.path == "/api/agent-gw/release":
            return self.agent_gw_release()
        if parsed.path == "/api/agent-gw/handoff":
            return self.agent_gw_handoff()
        if parsed.path == "/api/agent-gw/revoke":
            return self.agent_gw_revoke()
        if parsed.path == "/api/share":
            return self.share_toggle(qs)
        if parsed.path == "/api/share/base-url":
            return self.share_base_url()
        if not _check_origin(self.headers):
            return self._error(403, "跨来源请求被拒绝（Origin 不在本机白名单）",
                               code="E_BAD_ORIGIN",
                               hint=f"浏览器请求 Origin 必须是本机源：{', '.join(_local_origins())}")
        if parsed.path.startswith("/api/") and not _authorized(self.headers, qs, parsed.path):
            return self._error(401, "需要会话凭证；先 POST /api/auth/exchange 换 session（或浏览器打开页面登录）",
                               code="E_AUTH_REQUIRED",
                               hint="Authorization: Bearer <session> 或 Cookie: wb_session=<session>")
        if not _check_origin(self.headers):
            return self._error(403, "跨来源请求被拒绝（Origin 不在本机白名单）")

        if parsed.path == "/api/task/start":
            return self.task_start()
        if parsed.path == "/api/task/stop":
            return self.task_stop()
        if parsed.path == "/api/hunter/start":
            return self.hunter_start()
        if parsed.path == "/api/agent/start":
            return self.agent_start()
        if parsed.path == "/api/autosubmit":
            return self.autosubmit_save()
        if parsed.path == "/api/sandbox":
            return self.sandbox_save()
        if parsed.path == "/api/auth/exchange":
            return self.auth_exchange(qs)
        if parsed.path == "/api/env/build":
            return self.env_build()
        if parsed.path == "/api/env/registry":
            return self.env_registry_save()
        if parsed.path == "/api/env/push":
            return self.env_push()
        if parsed.path == "/api/env/services/down":
            return self.env_services_down()
        if parsed.path == "/api/env/verify":
            return self.env_verify()
        if parsed.path != "/api/action":
            return self._error(404, "no such route")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > _core.MAX_BODY_BYTES:
                return self._error(400, "bad body size")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            return self._error(400, f"bad json: {exc}", code="E_BAD_JSON")
        name = body.get("action")
        fn = ACTIONS.get(name)
        if fn is None:
            return self._json({"ok": False, "code": "E_UNKNOWN_ACTION",
                               "error": f"unknown action: {name}",
                               "hint": "GET /api/help 查看 action 清单"}, 400)
        # AG-02：按动作声明的必填参数一次报全（不再逐个 missing param）
        required = getattr(fn, "wb_required", None)
        if required:
            missing = [k for k in required
                       if not str((body.get("params") or {}).get(k, "") or "").strip()]
            if missing:
                return self._json({"ok": False, "code": "E_MISSING_PARAMS",
                                   "error": "missing params: " + ", ".join(missing),
                                   "missing": missing}, 400)
        # R112-L4：agent key 调 case.* 写动作时校验认领（observer 拒写；solver 限本认领题）
        agent_key_hdr = self.headers.get("X-Agent-Key", "")
        if (agent_key_hdr.startswith(wb_gateway.KEY_PREFIX)
                and name.startswith("case.")):
            agent = wb_gateway.authenticate(_core.ROOT, agent_key_hdr)
            if agent is None:
                return self._error(401, "无效的 agent key", code="E_BAD_AGENT_KEY")
            if agent.get("role") == "observer":
                return self._error(403, "observer 角色只读", code="E_READONLY_ROLE")
            params = body.get("params") or {}
            slug_for_check = (str(params.get("slug") or "")
                              or (str(params.get("case_dir") or "").split("/")[-1]))
            if slug_for_check:
                ok, reason = wb_gateway.can_write_case(_core.ROOT, agent_key_hdr,
                                                       slug_for_check)
                if not ok:
                    return self._error(403, reason, code="E_NOT_CLAIMED")
            # R182：agent key 写 case.* 时把身份落档（题目子看板按此分列）
            params = body.get("params") or {}
            params.setdefault("agent", agent.get("tag") or agent.get("name") or "")
            body["params"] = params
        if fn is None:
            return self._error(400, f"unknown action: {name}")
        params = body.get("params") or {}
        try:
            result = fn(params)
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
        result.update({"ok": result.get("exit") == 0, "action": name})
        # 写动作可能改变 case 目录内容（writeup/triage/scan 等），主动失效视图缓存
        target_dir = str(params.get("dir") or "")
        for key in [k for k in _core._VIEW_CACHE if k.endswith(target_dir)]:
            _core._VIEW_CACHE.pop(key, None)
        return self._json(result)


def about_payload() -> dict:
    """R189：关于页数据——版本/功能总览/更新迭代记录（读 CHANGELOG.md）。"""
    # R200：版本号从 git tag 推导——最后一个 tag + 之后 commit 数（无 git 环境回落内置）
    version = "v0.5.0"
    try:
        import subprocess as _sp
        describe = _sp.run(["git", "describe", "--tags", "--abbrev=0"],
                           capture_output=True, text=True, timeout=5,
                           cwd=str(Path(__file__).resolve().parents[1]))
        if describe.returncode == 0:
            tag = describe.stdout.strip()
            count = _sp.run(["git", "rev-list", tag + "..HEAD", "--count"],
                            capture_output=True, text=True, timeout=5,
                            cwd=str(Path(__file__).resolve().parents[1]))
            n = int(count.stdout.strip() or 0) if count.returncode == 0 else 0
            version = tag if n == 0 else f"{tag}+{n} commits"
    except Exception:  # noqa: BLE001  无 git 环境 / tag 缺失 → 内置版本
        pass
    changelog = ""
    for cand in (_core.ROOT / "solve-ai-ctf" / "CHANGELOG.md",
                 _core.ROOT / "CHANGELOG.md"):
        try:
            changelog = cand.read_text(encoding="utf-8")[:60000]
            break
        except OSError:
            continue
    features = [
        {"group": "🧭 工作台", "items": [
            "题目总览：分类看板 / 状态流 / 搜索 / 首清与参与数统计",
            "题目工作区：概览（FLAG 常显）· 协作看板（分列 + 思维导图）· 假设阶梯 · 尝试（筛选/变体数）· 证据 · 排除 · Flag 历史 · 提示词 · 守则",
            "AI 看板：泳道时间线 / agent 名册与离线衰减 / 交接链 / 协作快照",
            "时间线（SSE 实时）/ 文件浏览 / 文档渲染 / 知识库检索与提示词生成",
            "排行榜（个人/队伍）· 成就 · 资源库 · 环境页 · 系统概况"]},
        {"group": "🤖 多 AI 协作", "items": [
            "自助入网（join-token）/ 固定编号 AI1..N / 自标签 / whoami 自检",
            "认领与同题共解（claim co:true）/ 交接简报注入下任 prompt / TTL 可见",
            "写过程身份自动归属：子看板按 AI 分列，思维导图按 AI 分枝",
            "介入提示词一键生成（真实地址/入网码自动填充）",
            "协作事件流（events?since=）与错误码体系（E_* ）"]},
        {"group": "🚀 开赛自动化", "items": [
            "平台对接代理（探测 API → 写提交配置，BUUCTF 预设开箱即用）",
            "抓题代理（限额/类别过滤批量注册）+ inbox 半接入投料口",
            "Flag 猎手：自主扫描校验 → 抢一血式自动提交 → 全局 toast 报喜",
            "提示词自动注入知识库命中（类别 playbook + 题面关键词）"]},
        {"group": "📦 沙箱与执行", "items": [
            "Docker 沙箱：按题型选镜像（7 层）· cap-drop/断网/限额/超时强停",
            "模型网关：一次性令牌调上游，API key 不下容器，按令牌记账",
            "任务系统：实时输出 / 失败重派 / 深链接 / 环境探活断路器"]},
        {"group": "🛡 安全", "items": [
            "提交默认 dry-run，--live 人工确认；限速与 flag 哈希去重",
            "CSP/nosniff/no-store 安全响应头 · mdRender scheme 白名单",
            "名册 note 自动打码 flag · 路径防穿越 · 共享模式令牌鉴权"]},
    ]
    return {"version": version, "features": features,
            "changelog_md": changelog or "（CHANGELOG.md 未找到）",
            "repo": "https://github.com/LceAn/solve-ai-ctf",
            "stack": "Python 标准库（零依赖）+ 原生 JS (petite-vue) + Docker"}


def _collab_payload(slug: str) -> dict:
    """R182：题目协作聚合——当前认领者 / 该题交接史 / 名册（子看板数据源）。"""
    import time as _time
    try:
        data = wb_gateway._load(_core.ROOT)
    except Exception:  # noqa: BLE001
        return {"claim": None, "handoffs": [], "agents": []}
    now = _time.time()

    def _ts(value):
        try:
            import datetime as _dt
            return _dt.datetime.fromisoformat(str(value)).timestamp()
        except Exception:  # noqa: BLE001
            return 0.0

    claims = [{"agent_tag": cl.get("agent_tag"), "agent_name": cl.get("agent_name"),
               "claimed_at": cl.get("claimed_at"), "expires_at": cl.get("expires_at")}
              for cl in data.get("claims", [])
              if cl.get("slug") == slug and _ts(cl.get("expires_at")) > now]
    claim = claims[0] if claims else None   # 兼容单字段；共解取全量用 claims
    handoffs = [{"agent_tag": h.get("agent_tag"), "agent_name": h.get("agent_name"),
                 "time": h.get("time"), "summary": h.get("summary", ""),
                 "findings": len(h.get("findings") or [])}
                for h in data.get("handoffs", []) if h.get("slug") == slug]
    handoffs.reverse()
    agents = [{"tag": a.get("tag"), "name": a.get("name"), "label": a.get("label", ""),
               "status": a.get("status", ""), "role": a.get("role", ""),
               "revoked": bool(a.get("revoked"))}
              for a in data.get("agents", [])]
    return {"claim": claim, "claims": claims, "handoffs": handoffs, "agents": agents}
