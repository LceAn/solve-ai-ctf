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
import uuid
from pathlib import Path

import env_builder as envb
import wb_core as _core
import wb_actions
from wb_actions import ACTIONS, _db_path_of, run_script
from wb_core import (looks_textual, read_json, safe_join, resolve_competition, competition_view,
                     case_summary, file_tree, build_prompt, kb_search, list_competitions,
                     select_default_competition, read_json_line)
from wb_sandbox import (sandbox_status, sandbox_config, gateway_usage, upstream_key,
                        upstream_base, health_detail, sandbox_concurrency_reason,
                        sandbox_running_count)
from wb_tasks import (TASKS, board_data, docker_stop_container, split_cmd_template,
                      _image_exists, _compose_up, _mem_bytes)


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
        "GET /api/gateway/usage": "模型网关按任务聚合的用量报表（bytes/requests/活跃令牌）",
    },
    "write": {
        "POST /api/action": "白名单动作（competition.init / competition.set_docs / challenge.register / case.init / case.status / case.hypothesis / "
                            "case.finding / case.attempt / case.scan_flags / case.candidate / "
                            "case.validate / case.triage / case.writeup / case.summary / "
                            "submit.dryrun / submit.live / competition.prioritize / "
                            "competition.set_mode / competition.set_scoring / competition.add_team / competition.update_challenge / competition.remove_challenge / case.set_grade / achievement.check / team.list / competition.dashboard / competition.report / competition.event / selftest.run）",
        "POST /api/task/start": "派发求解任务 {dir, slug, agent?, cmd_template?}；demo=true 可运行内置演示 Agent（只读日志，不提交）",
        "POST /api/task/stop": "停止任务 {id}（沙箱任务连带 compose 服务下线）",
        "POST /api/env/build": "构建比赛/题目层镜像 {dir, slug|comp_image|all, force?}（env_builder 子进程任务）",
        "POST /api/env/verify": "镜像探针矩阵验证 {dir, slug}",
        "POST /api/env/push": "推送已构建镜像到仓库 {dir, slugs?, registry?, no_comp?}（任务）",
        "POST /api/env/registry": "保存 Docker 仓库地址 {registry}（凭证只在本机 docker login）",
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


def _authorized(headers, qs, path: str = "") -> bool:
    """配置 --token 后所有 /api 请求须凭证：session 或 exchange 路由的裸 token（O-12）。"""
    if not _core.RUNTIME.get("auth_token"):
        return True
    value = _client_token(headers, qs)
    if not value:
        return False
    if path == "/api/auth/exchange":
        return hmac.compare_digest(value, _core.RUNTIME.get("auth_token", ""))
    return _verify_session(value)


def _client_token(headers, qs) -> str:
    """从 Bearer 或 Cookie: wb_session= 读取凭证。不再接受 ?token= 查询串。"""
    auth = headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
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
            if route.startswith("/api/") and not _authorized(self.headers, qs, route):
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("WWW-Authenticate", "Bearer")
                self._security_headers()
                body = json.dumps({"error": "需要访问令牌（--token）"}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
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
                return self._json({"tasks": TASKS.list(status=qs.get("status", ""),
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
                return self._json(health_detail())
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
            if route == "/api/sandbox":
                return self._json(sandbox_status())
            if route == "/api/gateway/usage":
                return self._json(gateway_usage())
            if route == "/api/env/status":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                return self._json(envb.status_data(comp))
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
            if route == "/api/docs/tree":
                comp = resolve_competition(qs.get("dir", ""))
                docs_base = str((read_json(comp / "competition.json", {})
                                 or {}).get("docs_path") or "") if comp else ""
                if not docs_base or not Path(docs_base).is_dir():
                    return self._error(404, "docs_path not configured")
                base = Path(docs_base).resolve()
                target = (base / (qs.get("path") or ".")).resolve()
                if not str(target).startswith(str(base)):
                    return self._error(403, "path outside docs_path")
                if not target.is_dir():
                    return self._error(404, "dir not found")
                return self._json({"docs_path": docs_base,
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
                    return self._error(400, "missing q")
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
            if route == "/api/kb":
                if not qs.get("q"):
                    return self._error(400, "missing q")
                return self._json(kb_search(qs["q"], qs.get("category"),
                                            int(qs.get("top", 10))))
            if route == "/api/prompt":
                comp = resolve_competition(qs.get("dir", ""))
                if not comp or not comp.is_dir():
                    return self._error(404, "unknown competition")
                return self._json({"prompt": build_prompt(comp, qs.get("slug", ""),
                                                          qs.get("style") or "continue")})
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
            return self._error(400, f"bad json: {exc}")
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
                registry = str((read_json(ROOT / "workbench-data" / "registry.json", {})
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
            return self._error(400, f"bad json: {exc}")
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
            return self._error(400, f"bad json: {exc}")
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
            return self._error(400, f"bad json: {exc}")
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
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        events_path = comp / "events.jsonl"
        seen = 0
        try:
            if events_path.exists():
                seen = len(events_path.read_text(encoding="utf-8",
                                                 errors="replace").splitlines())
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            idle = 0
            while idle < 600:  # 单连接最长 ~10 分钟，前端 EventSource 自动重连
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                if events_path.exists():
                    total = len(events_path.read_text(encoding="utf-8",
                                                      errors="replace").splitlines())
                    while seen < total:
                        line = events_path.read_text(
                            encoding="utf-8", errors="replace").splitlines()[seen]
                        seen += 1
                        if line.strip():
                            payload = json.dumps(read_json_line(line), ensure_ascii=False)
                            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    if total < seen:  # 文件被轮换/清空
                        seen = total
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
                if token in TASKS._gateway_tokens:
                    TASKS._gateway_tokens[token]["bytes"] = TASKS._gateway_tokens[token].get("bytes", 0) + total
                    TASKS._gateway_tokens[token]["requests"] = TASKS._gateway_tokens[token].get("requests", 0) + 1

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

    def do_POST(self):
        if _core.RUNTIME.get("verbose"):
            print(f"{self.command} {self._redact(self.path)}", file=sys.stderr, flush=True)
        parsed = urllib.parse.urlparse(self.path)
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if parsed.path.startswith("/gw/"):
            return self.gateway(parsed.path)
        # /api/auth/exchange：必须在 _authorized 与 Origin 检查之前（该路由只接受裸 token）
        if parsed.path == "/api/auth/exchange":
            return self.auth_exchange(qs)
        if not _check_origin(self.headers):
            return self._error(403, "跨来源请求被拒绝（Origin 不在本机白名单）",
                               code="E_BAD_ORIGIN",
                               hint=f"浏览器请求 Origin 必须是本机源：{', '.join(_local_origins())}")
        if parsed.path.startswith("/api/") and not _authorized(self.headers, qs, parsed.path):
            return self._error(401, "需要访问令牌（--token）；先 POST /api/auth/exchange 换 session",
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
            return self._error(400, f"bad json: {exc}")
        name = body.get("action")
        fn = ACTIONS.get(name)
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


