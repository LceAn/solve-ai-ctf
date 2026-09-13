#!/usr/bin/env python3
"""Workbench 冒烟测试：临时目录起真实服务，覆盖全部 API 与关键动作。

用法：python solve-ai-ctf/workbench/test_workbench.py
不触碰 比赛/ 下的真实数据。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Windows consoles may use a legacy code page; keep failure diagnostics
# printable even when a solver emits Chinese/emoji output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="backslashreplace")

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
ROOT = HERE.parents[1]

import importlib.util
import sys as _sys

spec = importlib.util.spec_from_file_location("platform_adapters", HERE / "platform_adapters.py")
padapters = importlib.util.module_from_spec(spec)
spec.loader.exec_module(padapters)
spec = importlib.util.spec_from_file_location("wb_server", HERE / "server.py")
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail}")


def http_get(port: int, path: str) -> tuple[int, dict | bytes]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=15) as r:
            body = r.read()
            if r.headers.get("Content-Type", "").startswith("application/json"):
                return r.status, json.loads(body)
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def http_post_json(port: int, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def http_headers(port: int, path: str) -> dict:
    """取响应头（用于断言安全响应头确实下发）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=15) as r:
            r.read()
            return {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return {k.lower(): v for k, v in e.headers.items()}


def strip_js_comments(src: str) -> str:
    """剔除 /* */ 与 // 注释后再判断关键字，避免把注释里的说明文字当成代码。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    return re.sub(r"(?m)\s//\s[^\n]*$", "", src)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="wb_test_"))
    (tmp / "比赛").mkdir()
    (tmp / "比赛" / "aaa-empty").mkdir()
    comp = tmp / "比赛" / "wbtest"
    try:
        print("== 静态检查 ==")
        # 1) 前端不得引入 CSP 不允许的动态代码：静态 JS 去注释后不得出现 new Function( / eval(
        #    （CSP 为 script-src 'self'，无 'unsafe-eval'；这条断言就是它的守卫）
        offenders = []
        for js in sorted((HERE / "static").rglob("*.js")):
            code = strip_js_comments(js.read_text(encoding="utf-8", errors="replace"))
            for pat in ("new Function(", "eval("):
                if pat in code:
                    offenders.append(f"{js.relative_to(HERE)}:{pat}")
        check("static js is CSP-safe (no eval/new Function)", not offenders, "; ".join(offenders))

        # 2) 技能树内不得残留合并冲突标记
        #    只认三个无歧义的标记（<<<<<<< / >>>>>>> / |||||||）；裸 ======= 会误伤
        #    markdown 标题下划线。范围限定技能树，避免扫到 tools/ 与第三方 .venv。
        markers = []
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "vendor"}
        for ext in ("*.md", "*.py", "*.js", "*.json", "*.yml", "*.yaml", "*.html", "*.css"):
            for f in sorted((HERE.parent).rglob(ext)):
                if any(p in skip_dirs for p in f.parts):
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if line.startswith(("<<<<<<<", ">>>>>>>", "|||||||")):
                        markers.append(f"{f.relative_to(HERE.parent)}:{i}")
        check("no VCS conflict markers", not markers, "; ".join(markers[:5]))

        # 3) Origin 白名单必须覆盖本机全部访问地址：否则 --host 0.0.0.0 --token 共享模式下，
        #    用局域网/Tailscale 地址打开工作台的浏览器所有写操作都会被 403（能看不能点）
        wb._LOCAL_ORIGINS_CACHE.clear()
        probe = wb._port or 8787
        want = {f"http://{h}:{probe}" for h in ("127.0.0.1", "localhost", "[::1]")}
        want |= {u.rstrip("/") for u in wb.local_urls(probe)}
        missing = sorted(want - set(wb._local_origins()))
        check("origin whitelist covers all local addresses", not missing, "; ".join(missing))
        wb._LOCAL_ORIGINS_CACHE.clear()

        # 4) 知识库：无孤儿文档 + 分类白名单确实收录新专题
        #    （2026-09-11 实际出过：新增 15 份专题文档未登记进 CATEGORY_FILES，
        #     带分类检索时静默搜不到，只有"全部"能命中）
        kb_spec = importlib.util.spec_from_file_location("kb_search_t", SCRIPTS / "kb_search.py")
        kb = importlib.util.module_from_spec(kb_spec)
        # 必须先注册进 sys.modules：kb_search 用了 @dataclass，
        # dataclass 装饰器要经 sys.modules[cls.__module__] 解析类型注解
        sys.modules["kb_search_t"] = kb
        kb_spec.loader.exec_module(kb)
        registered = set(kb.COMMON_FILES) | set(kb.EXCLUDED_FROM_SEARCH)
        for files in kb.CATEGORY_FILES.values():
            registered |= set(files)
        on_disk = {p.name for p in (SCRIPTS.parent / "references").glob("*.md")}
        orphan = sorted(on_disk - registered)
        check("no orphan reference docs", not orphan,
              "未登记进任何分类/通用/排除清单: " + "; ".join(orphan))
        for cat, name in (("web", "PHP反序列化漏洞总结.md"), ("web", "SQL.md"),
                          ("forensics", "图片隐写.md"), ("misc", "压缩包总结.md")):
            check(f"category {cat} includes {name}",
                  name in (kb.allowed_files(cat) or set()), f"{name} 未被 {cat} 收录")
        check("index files excluded from search",
              not kb.searchable(SCRIPTS.parent / "references" / "AI-SEARCH-INDEX.md"),
              "AI-SEARCH-INDEX.md 仍会参与内容检索并霸榜")

        print("== 准备临时比赛 ==")
        for argv in (
            [SCRIPTS / "competition.py", "init", comp, "--name", "WB Test CTF", "--scope", "test-only"],
            [SCRIPTS / "competition.py", "add-challenge", comp, "--name", "Test Chall",
             "--category", "crypto", "--slug", "testc", "--points", "100",
             "--description", "冒烟测试题目"],
            [SCRIPTS / "competition.py", "add-challenge", comp, "--name", "ID Chall",
             "--category", "crypto", "--challenge-id", "241",
             "--description", "平台 ID slug 回归测试"],
        ):
            r = subprocess.run([sys.executable, *map(str, argv)], capture_output=True, text=True)
            check(f"script {argv[1]}", r.returncode == 0, r.stderr[-300:])
        cfg = json.loads((comp / "competition.json").read_text(encoding="utf-8"))
        check("platform ID slug defaults to c<ID>",
              any(c.get("slug") == "c241" and c.get("platform_id") == "241"
                  for c in cfg.get("challenges", [])), str(cfg.get("challenges")))

        art = comp / "artifacts"
        art.mkdir(exist_ok=True)
        (art / "note.txt").write_text("ignored flag{wb_test_flag_001} tail", encoding="utf-8")
        case_art = comp / "cases" / "testc" / "artifacts"
        case_art.mkdir(parents=True, exist_ok=True)
        (case_art / "challenge.txt").write_text("case artifact", encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "case_manager.py"), "scan-flags",
             str(comp / "cases" / "testc"), str(art), "--store"],
            capture_output=True, text=True)
        check("scan-flags --store", r.returncode == 0, r.stderr[-300:])

        print("== 启动服务 ==")
        wb.configure(root=tmp, scripts=SCRIPTS, static=HERE / "static")
        httpd = wb.ThreadingHTTPServer(("127.0.0.1", 0), wb.Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        print("== 只读 API ==")
        st, body = http_get(port, "/api/health")
        check("health", st == 200 and body.get("ok") is True)

        st, body = http_get(port, "/api/competitions")
        names = [c["dir"] for c in body.get("competitions", [])]
        check("competitions contains wbtest", "wbtest" in names, str(names))
        check("default prefers initialized competition", body.get("default") == "wbtest",
              str(body.get("default")))
        check("explicit default accepts competition path",
              wb.select_default_competition(body["competitions"], "比赛/wbtest") == "wbtest")

        st, comp_view = http_get(port, "/api/competition?dir=wbtest")
        check("competition 200", st == 200)
        check("challenge listed", any(c["slug"] == "testc" for c in comp_view.get("challenges", [])))
        testc = next((c for c in comp_view["challenges"] if c["slug"] == "testc"), {})
        check("challenge description exposed", testc.get("description") == "冒烟测试题目",
              str(testc.get("description")))
        check("case summary exists", testc.get("case", {}).get("exists") is True)
        check("case artifact count exposed", testc.get("case", {}).get("artifacts_count") == 1,
              str(testc.get("case", {})))
        check("scan stored candidate",
              any(c["status"] == "unverified" for c in testc.get("case", {}).get("candidates", [])),
              str(testc.get("case", {}).get("candidates")))
        check("enums present", set(comp_view.get("enums", {})) >= {"statuses", "candidate_statuses"})

        st, case = http_get(port, "/api/case?dir=wbtest&case_dir=cases/testc")
        check("case 200", st == 200 and case.get("challenge", {}).get("name") == "Test Chall")
        check("case tree", any(f["path"] == "case.json" for f in case.get("_tree", [])))

        st, pr = http_get(port, "/api/prompt?dir=wbtest&slug=testc")
        check("prompt has slug", st == 200 and "testc" in pr.get("prompt", ""))

        st, kb = http_get(port, "/api/kb?q=triage")
        check("kb search runs", st == 200 and "hits" in kb)

        st, fdata = http_get(port, "/api/file?dir=wbtest&path=artifacts/note.txt")
        check("file read", st == 200 and "flag{wb_test_flag_001}" in fdata.get("content", ""))

        st, _ = http_get(port, "/api/file?dir=wbtest&path=../../etc/passwd")
        check("path traversal blocked", st == 404)
        st, _ = http_get(port, "/api/competition?dir=%2e%2e%5c%2e%2e")
        check("competition traversal blocked", st == 404)

        print("== 动作 API ==")
        st, r = http_post_json(port, "/api/action", {
            "action": "case.status",
            "params": {"dir": "wbtest", "case_dir": "cases/testc", "status": "in_progress",
                       "reason": "wb test"}})
        check("case.status ok", st == 200 and r.get("ok") is True, str(r)[:300])
        check("status reflected", r.get("case", {}).get("status") == "in_progress")

        st, r = http_post_json(port, "/api/action", {
            "action": "case.candidate",
            "params": {"dir": "wbtest", "case_dir": "cases/testc",
                       "candidate_id": "C0001", "candidate_status": "validated",
                       "note": "wb test"}})
        check("candidate validate", st == 200 and r.get("ok") is True, str(r)[:300])

        st, r = http_post_json(port, "/api/action", {
            "action": "case.hypothesis",
            "params": {"dir": "wbtest", "case_dir": "cases/testc", "title": "T",
                       "rationale": "R", "expected": "E", "minutes": 10}})
        check("hypothesis ok", st == 200 and r.get("ok") is True, str(r)[:300])

        st, r = http_post_json(port, "/api/action", {
            "action": "submit.dryrun",
            "params": {"dir": "wbtest", "challenge": "testc", "flag": "flag{wb_test_flag_001}"}})
        check("submit dryrun responds", st in (200, 400) and "exit" in r, str(r)[:300])

        st, r = http_post_json(port, "/api/action", {
            "action": "submit.live",
            "params": {"dir": "wbtest", "challenge": "testc", "flag": "x"}})
        check("live without confirm rejected", st == 400, str(r)[:200])

        st, r = http_post_json(port, "/api/action", {"action": "nope", "params": {}})
        check("unknown action 400", st == 400)

        st, r = http_post_json(port, "/api/action", {
            "action": "case.status", "params": {"dir": "wbtest", "case_dir": "cases/testc",
                                                "status": "hacker"}})
        check("invalid enum rejected", st == 400)

        print("== 任务 / 概况 / WP ==")
        st, r = http_post_json(port, "/api/task/start", {
            "dir": "wbtest", "slug": "testc",
            "cmd_template": '{python} -u -c "import time; print(\':start\'); time.sleep(3)"'.format(
                python=sys.executable)})
        check("task start", st == 200 and r.get("ok") is True, str(r)[:200])
        tid = r.get("task", {}).get("id", "")
        time.sleep(2.0)  # 等子进程冷启动并写出首行
        st, r = http_get(port, f"/api/task/tail?id={tid}")
        check("task tail has output", st == 200 and ":start" in r.get("output", ""), str(r)[:200])
        st, r = http_post_json(port, "/api/task/stop", {"id": tid})
        check("task stop", st == 200 and r.get("stopped") is True, str(r)[:200])
        st, r = http_get(port, "/api/tasks")
        check("tasks list", st == 200 and any(t["id"] == tid for t in r.get("tasks", [])))
        # R8：服务端过滤与截断
        st, r = http_get(port, "/api/tasks?status=running&limit=1")
        check("tasks filter+limit", st == 200
              and all(t["status"] == "running" for t in r.get("tasks", []))
              and len(r.get("tasks", [])) <= 1, str(r)[:150])
        check("demo agent advertised", st == 200 and r.get("demo_agent") is True)
        case_dir_abs = comp / "cases" / "testc"
        check("task log written", any(case_dir_abs.glob("scratch/T*-agent-run.log")))

        print("== 网关链路（mock 上游，R9）==")
        from http.server import BaseHTTPRequestHandler as _BH, HTTPServer as _HS

        class MockUpstream(_BH):
            def log_message(self, *a): pass
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0") or 0)
                self.rfile.read(length)
                body = json.dumps({"choices": [{"message": {"content": "mock-ok"}}],
                                   "usage": {"total_tokens": 7}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        upstream = _HS(("127.0.0.1", 0), MockUpstream)
        upstream_port = upstream.server_address[1]
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        sbx_path = wb.ROOT / "workbench-data" / "sandbox.json"
        sbx_path.parent.mkdir(exist_ok=True)
        sbx_path.write_text(json.dumps({
            "upstream_base": f"http://127.0.0.1:{upstream_port}",
            "upstream_key_env": "WB_TEST_UPSTREAM_KEY"}), encoding="utf-8")
        os.environ["WB_TEST_UPSTREAM_KEY"] = "sk-mock-upstream"
        st, r = http_post_json(port, "/gw/bad-token/v1/chat/completions", {"ping": 1})
        check("gateway bad token 401", st == 401, str(r)[:120])
        wb.TASKS.register_token("r9gw-token", "T0000")
        gw_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/gw/r9gw-token/v1/chat/completions",
            data=json.dumps({"model": "mock", "messages": []}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(gw_req, timeout=15) as resp:
                gw_status, gw_body = resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            gw_status, gw_body = e.code, {}
        check("gateway forwards to upstream", gw_status == 200
              and gw_body.get("choices", [{}])[0].get("message", {}).get("content") == "mock-ok",
              f"{gw_status} {str(gw_body)[:150]}")
        gw_info = wb.TASKS._gateway_tokens.get("r9gw-token") or {}
        check("gateway accounting bytes/requests", gw_info.get("bytes", 0) > 0
              and gw_info.get("requests", 0) == 1, str(gw_info))
        # R33：每令牌限速（把上限临时调成 1/min，第二次请求 429）
        sbx = json.loads(sbx_path.read_text(encoding="utf-8"))
        sbx["gateway_rate_per_min"] = 1
        sbx_path.write_text(json.dumps(sbx), encoding="utf-8")
        wb.TASKS.register_token("r33-rate-token", "T0000")
        codes = []
        for _ in range(2):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/gw/r33-rate-token/v1/chat/completions",
                data=json.dumps({"model": "mock", "messages": []}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    codes.append(resp.status)
            except urllib.error.HTTPError as e:
                codes.append(e.code)
        check("gateway per-token rate limit (R33)", codes == [200, 429], str(codes))
        wb.TASKS._gateway_tokens.pop("r33-rate-token", None)
        sbx["gateway_rate_per_min"] = 30
        sbx_path.write_text(json.dumps(sbx), encoding="utf-8")
        wb.TASKS._gateway_tokens.pop("r9gw-token", None)
        upstream.shutdown()

        # Fresh installs have no real Agent command yet.  The bundled demo
        # Agent must still exercise the same prompt → task → tail lifecycle,
        # while remaining explicitly non-submitting.
        st, r = http_post_json(port, "/api/task/start", {
            "dir": "wbtest", "slug": "testc", "demo": True, "agent": "custom-label"})
        check("demo task start without agent command", st == 200 and r.get("ok") is True
              and r.get("demo") is True, str(r)[:200])
        demo_tid = r.get("task", {}).get("id", "")
        demo_tail = {}
        for _ in range(20):
            time.sleep(0.5)
            st, demo_tail = http_get(port, f"/api/task/tail?id={demo_tid}")
            if demo_tail.get("task", {}).get("status") in {"done", "failed"}:
                break
        check("demo task finished", demo_tail.get("task", {}).get("status") == "done",
              str(demo_tail.get("task", {})))
        check("demo task output", "[solver]" in (demo_tail.get("output") or "")
              and "flag" in (demo_tail.get("output") or ""),
              (demo_tail.get("output") or "")[-180:])
        st, tasks_payload = http_get(port, "/api/tasks")
        demo_item = next((t for t in tasks_payload.get("tasks", []) if t.get("id") == demo_tid), {})
        check("demo task is labelled", demo_item.get("mode") == "demo"
              and demo_item.get("agent") == "demo-agent", str(demo_item))

        st, r = http_post_json(port, "/api/action", {
            "action": "case.writeup", "params": {"dir": "wbtest", "case_dir": "cases/testc"}})
        check("writeup generated", st == 200 and r.get("ok") is True, str(r)[:200])
        check("writeup file exists", (case_dir_abs / "WRITEUP.md").exists())
        st, comp_after_writeup = http_get(port, "/api/competition?dir=wbtest")
        testc_after_writeup = next((c for c in comp_after_writeup.get("challenges", [])
                                    if c.get("slug") == "testc"), {})
        check("case doc count exposed", testc_after_writeup.get("case", {}).get("docs_count", 0) >= 1,
              str(testc_after_writeup.get("case", {})))

        st, h = http_get(port, "/api/health/detail")
        check("health detail", st == 200 and "stats" in h and "docker" in h)

        print("== 看板 / 提示词模板 / help ==")
        st, b = http_get(port, "/api/board?dir=wbtest&hours=24")
        check("board data", st == 200 and "lanes" in b, str(b)[:200])
        st, p1 = http_get(port, "/api/prompt?dir=wbtest&slug=testc&style=submit")
        st2, p2 = http_get(port, "/api/prompt?dir=wbtest&slug=testc&style=review")
        check("prompt styles differ",
              st == 200 and st2 == 200 and p1["prompt"] != p2["prompt"])
        st, h = http_get(port, "/api/help")
        check("api help", st == 200 and "agent_workflow" in h)

        print("== 令牌鉴权 ==")
        _sys.modules["wb_core"].RUNTIME["auth_token"] = "sekrit"  # N-06 拆包后令牌在 wb_http
        st, _ = http_get(port, "/api/competitions")
        check("401 without token", st == 401)
        # O-12: ?token= 查询串已废弃
        st, _ = http_get(port, "/api/competitions?token=sekrit")
        check("401 reject query token on api", st == 401)
        # 裸 Bearer token 在非 exchange 路由已不再接受
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/competitions",
                                     headers={"Authorization": "Bearer sekrit"})
        try:
            urllib.request.urlopen(req, timeout=10)
            check("401 reject raw bearer on non-exchange", False)
        except urllib.error.HTTPError as e:
            check("401 reject raw bearer on non-exchange", e.code == 401)
        # exchange：错误 token 401
        st, r = http_post_json(port, "/api/auth/exchange", {"token": "wrong"})
        check("401 exchange wrong token", st == 401 and r.get("code") == "E_BAD_TOKEN", str(r)[:200])
        # exchange：正确 token 200 + session
        st, r = http_post_json(port, "/api/auth/exchange", {"token": "sekrit"})
        check("200 exchange issues session", st == 200 and "session" in r
              and r.get("expires_in") == 900, str(r)[:200])
        session = r.get("session", "")
        check("session is base64url.sig format",
              "." in session and len(session.split(".")[1]) == 64, session[:80])
        # Authorization: Bearer <session> 200
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/competitions",
                                     headers={"Authorization": f"Bearer {session}"})
        st = urllib.request.urlopen(req, timeout=10).status
        check("200 with bearer token", st == 200)
        st, r = http_post_json(port, "/api/autosubmit?token=sekrit",
                               {"dir": "wbtest", "enabled": False, "max_live": 2})
        check("POST accepts query token", st == 200 and r.get("ok") is True, str(r)[:200])
        _sys.modules["wb_core"].RUNTIME["auth_token"] = ""

        print("== Flag 猎手 / 自动提交配置 ==")
        st, r = http_get(port, "/api/autosubmit?dir=unset-comp")
        check("autosubmit default enabled", st == 200 and r.get("enabled") is True,
              str(r))
        case_art = comp / "cases" / "testc" / "artifacts"
        case_art.mkdir(exist_ok=True)
        (case_art / "more.txt").write_text("second flag{wb_test_flag_002} tail", encoding="utf-8")
        st, r = http_post_json(port, "/api/autosubmit",
                               {"dir": "wbtest", "enabled": False, "max_live": 2})
        check("autosubmit save", st == 200 and r.get("ok") is True and r.get("max_live") == 2)
        st, r = http_get(port, "/api/autosubmit?dir=wbtest")
        check("autosubmit read", st == 200 and r.get("enabled") is False and r.get("max_live") == 2)

        st, r = http_post_json(port, "/api/hunter/start", {"dir": "wbtest"})
        check("hunter start", st == 200 and r.get("ok") is True, str(r)[:200])
        hid = r.get("task", {}).get("id", "")
        for _ in range(30):
            time.sleep(1)
            st, r = http_get(port, f"/api/task/tail?id={hid}")
            if "HUNTER DONE" in (r.get("output") or ""):
                break
        check("hunter finished", "HUNTER DONE" in (r.get("output") or ""), (r.get("output") or "")[-200:])
        check("hunter agent label", r.get("task", {}).get("agent") == "flag-agent")
        st, case = http_get(port, "/api/case?dir=wbtest&case_dir=cases/testc")
        vals = {c["value"]: c["status"] for c in case.get("candidates", [])}
        check("hunter auto-validated C0002", vals.get("flag{wb_test_flag_002}") == "validated", str(vals))

        (comp / "submissions.jsonl").write_text(
            json.dumps({"time": "2026-08-30T00:00:00+00:00", "challenge_slug": "testc", "flag_sha256": "x", "dry_run": False, "outcome": "accepted"}) + '\n' +
            json.dumps({"time": "2026-08-30T00:01:00+00:00", "challenge_slug": "testc", "flag_sha256": "y", "dry_run": True, "outcome": "dry_run"}) + '\n',
            encoding="utf-8")
        st, r = http_get(port, "/api/submissions?dir=wbtest&after=0")
        check("submissions all", st == 200 and r.get("total") == 2 and len(r.get("entries")) == 2)
        st, r = http_get(port, "/api/submissions?dir=wbtest&after=2")
        check("submissions after", r.get("total") == 2 and r.get("entries") == [])

        print("== 开赛自动化代理（对接 + 抓题，mock CTFd）==")
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class MockCTFD(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.path == "/api/v1/challenges":
                    body = json.dumps({"success": True, "data": [
                        {"id": "101", "name": "MockWeb", "category": "web", "value": 200},
                        {"id": "102", "name": "MockPwn", "category": "pwn", "value": 300},
                    ]}).encode()
                    ctype = "application/json"
                elif self.path == "/api/v1/challenges/101":
                    # R1：附件自动下载 —— 详情返回文件清单
                    body = json.dumps({"success": True,
                                       "data": {"files": ["/files/101/mock_art.txt"]}}).encode()
                    ctype = "application/json"
                elif self.path.startswith("/files/101/mock_art.txt"):
                    body = b"mock artifact bytes flag{mock_art_001}\n"
                    ctype = "application/octet-stream"
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        mock = HTTPServer(("127.0.0.1", 0), MockCTFD)
        mock_port = mock.server_address[1]
        threading.Thread(target=mock.serve_forever, daemon=True).start()

        # 给临时比赛写入门户线索 + 启用环境变量令牌
        cfg_path = comp / "competition.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["platform"]["base_url"] = f"http://127.0.0.1:{mock_port}"
        cfg["platform"]["auth"] = {"header": "Authorization", "value_prefix": "Token ",
                                   "value_env": "WB_TEST_TOKEN"}
        cfg["platform"]["portal"] = {"login_url": f"http://127.0.0.1:{mock_port}/login"}
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        os.environ["WB_TEST_TOKEN"] = "mock-token-abc"

        st, r = http_post_json(port, "/api/agent/start", {"dir": "wbtest", "kind": "platform"})
        check("platform agent start", st == 200 and r.get("ok") is True, str(r)[:200])
        pid_ = r["task"]["id"]
        for _ in range(20):
            time.sleep(0.5)
            st, r = http_get(port, f"/api/task/tail?id={pid_}")
            if "PLATFORM DONE" in (r.get("output") or ""):
                break
        check("platform agent done", "PLATFORM DONE configured=1" in (r.get("output") or ""),
              (r.get("output") or "")[-200:])
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        check("platform submit written",
              cfg["platform"]["submit"]["path"].endswith("/attempt"),
              json.dumps(cfg["platform"].get("submit", {}))[:120])

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        # R7：走适配器缺省——不写显式 challenge_detail，由 platform_adapters 提供
        cfg["platform"]["adapter"] = "ctfd"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        check("adapter defaults applied",
              padapters.CTFdAdapter().apply_defaults({"base_url": "x"})["challenge_detail"]
              .get("path") == "/api/v1/challenges/{id}"
              and padapters.get_adapter({"adapter": "buuctf"}) is not None
              and padapters.get_adapter({"adapter": "nope"}) is None)
        st, r = http_post_json(port, "/api/agent/start", {"dir": "wbtest", "kind": "fetch"})
        check("fetch agent start", st == 200 and r.get("ok") is True, str(r)[:200])
        fid = r["task"]["id"]
        for _ in range(20):
            time.sleep(0.5)
            st, r = http_get(port, f"/api/task/tail?id={fid}")
            if "FETCH DONE" in (r.get("output") or ""):
                break
        check("fetch agent done", "FETCH DONE registered=2" in (r.get("output") or ""),
              (r.get("output") or "")[-200:])
        # categories 白名单：注入载荷必须被拒（该参数会拼进 shell 命令串）
        st, r = http_post_json(port, "/api/agent/start",
                               {"dir": "wbtest", "kind": "fetch", "categories": "web & calc & "})
        check("categories injection rejected", st == 400 and r.get("ok") is False, str(r)[:200])
        st, r = http_post_json(port, "/api/agent/start",
                               {"dir": "wbtest", "kind": "fetch", "categories": "web,crypto"})
        check("categories whitelist accepted", st == 200 and r.get("ok") is True, str(r)[:200])
        st, comp_view2 = http_get(port, "/api/competition?dir=wbtest")
        check("challenges auto-registered",
              {c["slug"] for c in comp_view2["challenges"]} >= {"c101", "c102"},
              str([c["slug"] for c in comp_view2["challenges"]]))
        check("fetch agent downloaded artifacts", "artifacts=1" in (r.get("output") or ""),
              (r.get("output") or "")[-200:])
        import hashlib
        art = comp / "cases" / "c101" / "artifacts" / "mock_art.txt"
        check("artifact file stored", art.is_file()
              and b"flag{mock_art_001}" in art.read_bytes())
        case_data = json.loads((comp / "cases" / "c101" / "case.json").read_text(encoding="utf-8"))
        check("artifact registered with sha256",
              any(a.get("name") == "mock_art.txt"
                  and a.get("sha256") == hashlib.sha256(art.read_bytes()).hexdigest()
                  for a in case_data.get("artifacts", [])),
              str(case_data.get("artifacts"))[:200])

        # 抓题幂等：再跑一次必须全部跳过（按平台 ID / 名称去重），不得重复注册。
        # 原实现只在循环外快照 slug 集合且只按 slug 比对，列表里无平台 ID 时
        # 会用位置计数生成 slug（chall-1/2…），第二次运行必然全部"已存在"或被误建。
        st, r = http_post_json(port, "/api/agent/start", {"dir": "wbtest", "kind": "fetch"})
        check("fetch re-run accepted", st == 200 and r.get("ok") is True, str(r)[:200])
        fid2 = r["task"]["id"]
        for _ in range(20):
            time.sleep(0.5)
            st, r = http_get(port, f"/api/task/tail?id={fid2}")
            if "FETCH DONE" in (r.get("output") or ""):
                break
        check("fetch is idempotent (registered=0)",
              "FETCH DONE registered=0" in (r.get("output") or ""),
              (r.get("output") or "")[-200:])
        st, comp_view3 = http_get(port, "/api/competition?dir=wbtest")
        check("no duplicate challenges after re-run",
              len(comp_view3["challenges"]) == len(comp_view2["challenges"]),
              f'{len(comp_view2["challenges"])} -> {len(comp_view3["challenges"])}')
        mock.shutdown()

        print("== R16：平台已解状态对账（mock 已解列表）==")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["platform"]["solved"] = {"path": "/api/v1/users/me/solves",
                                     "items_field": "data",
                                     "map": {"challenge_id": "challenge_id"}}
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        # mock：用户已解 101（MockWeb），本地 case 未结算 → 应写事件
        # 直接改 mock 类源码不可行（已实例化）——改用独立 mock 服务做对账
        class MockSolved(_BH):
            def log_message(self, *a): pass
            def do_GET(self):
                body = json.dumps({"success": True, "data": [
                    {"challenge_id": 101, "solved": True}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        solved_mock = _HS(("127.0.0.1", 0), MockSolved)
        solved_port = solved_mock.server_address[1]
        threading.Thread(target=solved_mock.serve_forever, daemon=True).start()
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["platform"]["base_url"] = f"http://127.0.0.1:{solved_port}"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        r = subprocess.run([sys.executable, str(HERE / "fetch_challs.py"), str(comp), "--reconcile"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        check("reconcile runs", "RECONCILE DONE solved=1 fresh=1" in (r.stdout or ""),
              (r.stdout or r.stderr)[-200:])
        events = (comp / "events.jsonl").read_text(encoding="utf-8")
        check("platform_solved_detected event written", "platform_solved_detected" in events)
        check("challenges_new event written (R32)", "challenges_new" in events)
        solved_mock.shutdown()

        print("== case.init（手工目录补救入口）==")
        (comp / "cases" / "manual").mkdir(exist_ok=True)
        st, r = http_post_json(port, "/api/action", {
            "action": "case.init", "params": {"dir": "wbtest", "case_dir": "cases/manual",
                                              "name": "手工题", "category": "misc"}})
        check("case.init ok", st == 200 and r.get("ok") is True, str(r)[:200])
        check("case.json created", (comp / "cases" / "manual" / "case.json").exists())
        st, r = http_post_json(port, "/api/action", {
            "action": "case.init", "params": {"dir": "wbtest", "case_dir": "cases/manual",
                                              "name": "x", "force": True}})
        check("case.init force re-init", st == 200 and r.get("ok") is True, str(r)[:200])

        print("== R10：沙箱 smoke（Docker 可用才执行，CI 自动跳过）==")
        if wb.envb.docker_available():
            st, r = http_post_json(port, "/api/task/start",
                                   {"dir": "wbtest", "slug": "testc", "sandbox": True})
            check("sandbox dispatch", st == 200 and r.get("ok") is True, str(r)[:200])
            smoke_status, smoke_out = "", ""
            for _ in range(90):
                time.sleep(1)
                st, td = http_get(port, f"/api/task/tail?id={r['task']['id']}")
                smoke_status = td.get("task", {}).get("status", "")
                smoke_out = td.get("output", "")
                if smoke_status in ("done", "failed"):
                    break
            check("sandbox demo run in container", smoke_status == "done"
                  and "[solver] 完成" in smoke_out, f"{smoke_status} {smoke_out[-200:]}")
        else:
            check("sandbox smoke skipped (no docker)", True)

        print("== 比赛环境（env spec / 四层镜像矩阵）==")
        espec = importlib.util.spec_from_file_location("env_builder", HERE / "env_builder.py")
        envb = importlib.util.module_from_spec(espec)
        espec.loader.exec_module(envb)
        try:
            import yaml as pyyaml
        except ImportError:
            pyyaml = None
        ex_dir = HERE / "docker" / "envs"
        # env 骨架：init 建 comp.yaml，add-challenge 补题目 spec
        check("init created env/comp.yaml", (comp / "env" / "comp.yaml").exists())
        check("add-challenge wrote challenge spec",
              (comp / "env" / "challenges" / "testc.yaml").exists())
        # 双解析器一致性回归：示例 spec 与骨架 spec，mini ↔ PyYAML 必须等价
        yaml_inputs = [ex_dir / "comp.example.yaml",
                       ex_dir / "challenge.pwn-glibc235.example.yaml",
                       ex_dir / "challenge.web-lamp.example.yaml",
                       comp / "env" / "comp.yaml",
                       comp / "env" / "challenges" / "testc.yaml"]
        for y in yaml_inputs:
            if not y.exists():
                continue
            text = y.read_text(encoding="utf-8")
            mini = envb.parse_yaml_text(text)
            check(f"mini parse {y.name}",
                  isinstance(mini, dict) and mini.get("api") == "ctfbox/v1", str(mini)[:120])
            if pyyaml is not None:
                check(f"mini==pyyaml {y.name}", mini == pyyaml.safe_load(text),
                      f"mini={json.dumps(mini, ensure_ascii=False, default=str)[:200]}")
        # 合并语义：题目覆盖比赛、None 不覆盖
        mbase = {"run": {"network": "none", "caps": ["A"]}, "build": {"apt": ["x"]}}
        mres = envb.deep_merge(mbase, {"run": {"caps": ["B"]}, "build": None})
        check("deep_merge override", mres["run"]["caps"] == ["B"]
              and mres["run"]["network"] == "none" and mres["build"] == {"apt": ["x"]}, str(mres))
        # base_for：无显式 base 时题目跟题型层/L2，不继承 comp.yaml 的 base（防 web 题落到 misc 底座）
        check("base_for follows category then L2",
              envb.base_for("t", "x", "web", {}) == "ctfbox-web:0.1.0"
              and envb.base_for("t", "x", "web", {}, {"comp": {"image": "ctf-t:1"}}) == "ctf-t:1"
              and envb.base_for("t", "x", "web", {"base": "custom:1"}, {}) == "custom:1",
              f"{envb.base_for('t', 'x', 'web', {})}")
        # sync-solver：幂等生成 + skill 包 frontmatter + 约束层双写 + ai 层映射 + FLAG 占位校验
        envb.sync_solver_assets()
        sync2 = envb.sync_solver_assets()
        check("sync-solver idempotent", sync2["changed"] == [], str(sync2["changed"]))
        pwn_skill = HERE / "docker" / "base" / "skills" / "pwn" / "SKILL.md"
        check("skill pack generated", pwn_skill.is_file()
              and pwn_skill.read_text(encoding="utf-8").startswith("---\nname: ctf-pwn"),
              pwn_skill.read_text(encoding="utf-8")[:80] if pwn_skill.exists() else "missing")
        check("solver constraints 双写",
              (HERE / "docker" / "base" / "CLAUDE.md").is_file()
              and (HERE / "docker" / "base" / "AGENTS.md").is_file())
        check("ai 题型层映射", envb.CATEGORY_IMAGES.get("ai") == "ctfbox-ai:0.1.0"
              and bool(envb.PROBES.get("ai"))
              and envb.base_for("t", "x", "ai", {}) == "ctfbox-ai:0.1.0")
        bad = envb.compose_dict("t", "x", {"services": {"s": {
            "image": "busybox", "env": {"FLAG": "flag{real_flag_value}"}}}})
        check("FLAG 真值被拒绝", bool(bad[1]) and "占位" in bad[1][0], str(bad[1]))
        good = envb.compose_dict("t", "x", {"services": {"s": {
            "image": "busybox", "env": {"FLAG": "flag{placeholder-x}"}}}})
        check("FLAG 占位通过", not good[1], str(good[1]))
        # tag 规范：中文/空格/下划线归一化
        tag = envb.image_tag("HK 去吧 CTF", "Pwn_EasyHeap", "a" * 64)
        check("image_tag normalized", tag.startswith("ctf-hk-ctf-pwn-easyheap:2"), tag)
        # assets 路径逃逸必须被拒绝
        pwn_spec = envb.parse_yaml_text(
            (ex_dir / "challenge.pwn-glibc235.example.yaml").read_text(encoding="utf-8"))
        evil = dict(pwn_spec)
        evil["assets"] = [dict(pwn_spec["assets"][0], src="../../../etc/shadow")]
        problems = envb.validate_spec(comp, "wbtest", "pwn-easyheap", evil, True)
        check("asset escape rejected", any("逃逸" in p for p in problems), str(problems))
        # 渲染：FROM / USER ctf / heredoc / COPY
        comp_spec = envb.parse_yaml_text((ex_dir / "comp.example.yaml").read_text(encoding="utf-8"))
        merged_pwn = envb.deep_merge(comp_spec, pwn_spec)
        df = envb.render_dockerfile("t", "pwn-easyheap", merged_pwn, "ctfbox-pwn:0.1.0",
                                    merged_pwn.get("mirrors"))
        check("dockerfile rendered", "FROM ctfbox-pwn:0.1.0" in df and "USER ctf" in df
              and "CTFBOX_PRE" in df and "COPY --chmod=755 context/libc" in df, df[:200])
        # compose：internal 网络 + 占位 flag + 双向可解析
        web_spec = envb.parse_yaml_text(
            (ex_dir / "challenge.web-lamp.example.yaml").read_text(encoding="utf-8"))
        cdoc, cprobs = envb.compose_dict("t", "web-blog", web_spec)
        check("compose rendered", not cprobs and cdoc["name"] == "ctf-t-web-blog"
              and cdoc["networks"]["challnet"]["internal"] is True
              and str(cdoc["services"]["web"]["environment"]["FLAG"]).startswith("flag{placeholder"),
              str(cdoc)[:200])
        yml = envb.yaml_dump(cdoc)
        if pyyaml is not None:
            check("yaml_dump roundtrip", pyyaml.safe_load(yml) == cdoc, yml[:200])
        # 镜像选择优先级：.built.json 题目层 > 兜底；显式指定缺失硬失败；files 挂载进结果
        envb.save_built(comp, {"images": {"testc": {"image": "ctf-wbtest-testc:x"}}})
        sel = envb.resolve_image(comp, "testc", "crypto", default_image="default:x",
                                 category_images={}, exists=lambda t: t == "ctf-wbtest-testc:x")
        check("resolve prefers built challenge layer",
              sel["ok"] and sel["source"] == "challenge" and sel["image"] == "ctf-wbtest-testc:x",
              str(sel))
        sel4 = envb.resolve_image(comp, "testc", "crypto", default_image="default:x",
                                  category_images={}, exists=lambda t: False)
        check("explicit missing hard-fails (no silent fallback)",
              not sel4["ok"] and sel4["explicit_missing"] == "challenge"
              and sel4["image"] == "ctf-wbtest-testc:x", str(sel4))
        # files 挂载回归：用独立临时 spec，不污染 testc（后面 API 测试依赖其"空骨架"）
        (comp / "env" / "assets" / "mountcheck").mkdir(parents=True, exist_ok=True)
        (comp / "env" / "assets" / "mountcheck" / "hint.txt").write_text("x", encoding="utf-8")
        (comp / "env" / "challenges" / "mountcheck.yaml").write_text(
            "api: ctfbox/v1\nslug: mountcheck\ncategory: crypto\nbase: ctfbox-crypto:0.1.0\n"
            "files:\n  - src: hint.txt\n    dst: hint.txt\n", encoding="utf-8")
        sel3 = envb.resolve_image(comp, "mountcheck", "crypto", default_image="default:x",
                                  category_images={}, exists=lambda t: True)
        check("resolve_image carries files mounts",
              any(m["container"] == "/workspace/hint.txt" for m in sel3["mounts"]),
              str(sel3.get("mounts")))
        (comp / "env" / "challenges" / "mountcheck.yaml").unlink()
        envb.save_built(comp, {"images": {}})
        sel2 = envb.resolve_image(comp, "testc", "crypto", default_image="default:x",
                                  category_images={}, exists=lambda t: False)
        check("resolve falls back when nothing explicit",
              not sel2["ok"] and sel2["source"] == "fallback" and sel2["image"] == "default:x"
              and sel2["explicit_missing"] == "", str(sel2))
        # API：env/status
        st, body = http_get(port, "/api/env/status?dir=wbtest")
        check("env/status 200", st == 200 and body.get("has_env") is True, str(body)[:200])
        check("env/status lists challenge",
              any(c["slug"] == "testc" for c in body.get("challenges", [])),
              str(body.get("challenges"))[:200])
        # API：env/build —— 空 spec 跳过（不依赖 Docker）；非法输入 400
        st, r = http_post_json(port, "/api/env/build", {"dir": "wbtest", "slug": "testc"})
        check("env/build dispatched", st == 200 and r.get("ok") is True, str(r)[:200])
        task_state, tail_out = "", ""
        deadline = time.time() + 20
        while time.time() < deadline:
            st, td = http_get(port, f"/api/task/tail?id={r['task']['id']}")
            task_state = td.get("task", {}).get("status", "")
            tail_out = td.get("output", "")
            if task_state in ("done", "failed"):
                break
            time.sleep(0.5)
        check("env build skips empty spec", task_state == "done" and "skipped-empty" in tail_out,
              f"status={task_state} out={tail_out[-200:]}")
        st, r = http_post_json(port, "/api/env/build", {"dir": "wbtest"})
        check("env/build without target rejected", st == 400, str(r)[:150])
        st, r = http_post_json(port, "/api/env/build", {"dir": "wbtest", "slug": "bad/../slug"})
        check("env/build bad slug rejected", st == 400, str(r)[:150])

        print("== 安全加固（N-01/N-02/N-03/N-12 回归）==")
        # split_cmd_template：argv 词法（含空格路径、引号、占位符、token 内嵌路径）
        split_cases = [
            ('python -u "C:/Program Files/x/demo.py" --prompt {prompt_file} --tag "a b"',
             {"prompt_file": "C:/tmp/a b/prompt.txt"},
             ["python", "-u", "C:/Program Files/x/demo.py", "--prompt",
              "C:/tmp/a b/prompt.txt", "--tag", "a b"]),
            ('python {solver_dir}/solver.py {prompt_file}',
             {"solver_dir": "C:/sp ace/wb", "prompt_file": "C:/tmp/p.txt"},
             ["python", "C:/sp ace/wb/solver.py", "C:/tmp/p.txt"]),
        ]
        check("split_cmd_template argv lexing",
              all(wb.split_cmd_template(t, **kv) == want for t, kv, want in split_cases),
              str([wb.split_cmd_template(t, **kv) for t, kv, _ in split_cases]))
        # N-03：非回环绑定无令牌必须拒绝（--allow-insecure 才可豁免）
        check("bind security gate",
              wb.validate_bind_security("0.0.0.0", "", False) is not None
              and wb.validate_bind_security("0.0.0.0", "tok", False) is None
              and wb.validate_bind_security("0.0.0.0", "", True) is None
              and wb.validate_bind_security("127.0.0.1", "", False) is None)
        # N-01 回归：categories 注入载荷拒绝，合法值放行
        st, r = http_post_json(port, "/api/agent/start",
                               {"dir": "wbtest", "kind": "fetch", "categories": "web & calc & "})
        check("agent categories injection rejected", st == 400, str(r)[:200])
        st, r = http_post_json(port, "/api/agent/start",
                               {"dir": "wbtest", "kind": "fetch", "categories": "web,crypto"})
        check("agent categories valid dispatched", st == 200 and r.get("ok") is True,
              str(r)[:200])
        # N-12：浏览器跨站 Origin 与 Host 不一致 → 403（非浏览器无 Origin 不受影响）
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/action",
            data=json.dumps({"action": "competition.prioritize",
                             "params": {"dir": "wbtest"}}).encode(),
            headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                origin_code = resp.status
        except urllib.error.HTTPError as e:
            origin_code = e.code
        check("cross-origin POST rejected", origin_code == 403, str(origin_code))
        # R2：沙箱并发上限
        check("sandbox concurrency gate",
              wb.sandbox_concurrency_reason(3, 4) is None
              and wb.sandbox_concurrency_reason(4, 4) is not None
              and wb.sandbox_concurrency_reason(9, 0) is None
              and "max_concurrent_sandbox" in wb.sandbox_concurrency_reason(4, 4))
        st, r = http_post_json(port, "/api/action",
                               {"action": "competition.prioritize", "params": {"dir": "wbtest"}})
        check("same-origin POST unaffected", st == 200 and r.get("ok") is True, str(r)[:150])

        # R3：网关用量报表（按任务聚合）
        wb.TASKS._gateway_tokens.update({
            "t1": {"task": "T9001", "bytes": 100, "requests": 2, "issued": 1.0},
            "t2": {"task": "T9001", "bytes": 50, "requests": 1, "issued": 2.0},
            "t3": {"task": "T9002", "bytes": 7, "requests": 1, "issued": 3.0}})
        usage = wb.gateway_usage()
        check("gateway usage aggregation", usage["total_bytes"] == 157
              and usage["total_requests"] == 4 and usage["tasks"][0]["task"] == "T9001"
              and usage["tasks"][0]["tokens"] == 2, str(usage))
        for k in ("t1", "t2", "t3"):
            wb.TASKS._gateway_tokens.pop(k, None)
        st, u = http_get(port, "/api/gateway/usage")
        check("gateway usage endpoint", st == 200 and u.get("total_bytes") == 0, str(u)[:150])

        # R4：复盘报告导出（flag 必须脱敏——SKILL.md 红线第 8 条）
        st, r = http_post_json(port, "/api/action", {
            "action": "competition.report", "params": {"dir": "wbtest"}})
        check("report action ok", st == 200 and r.get("ok") is True, str(r)[:200])
        report = comp / "report.md"
        check("report written", report.is_file()
              and "复盘报告" in report.read_text(encoding="utf-8"))
        report_text = report.read_text(encoding="utf-8")
        check("report redacts real flags", "flag{wb_test_flag_001}" not in report_text
              and "sha256:" in report_text, report_text[:200])

        # R5：triage 签名扩充（容器/固件/文件系统/数据库盲区）
        import tempfile as _tmod
        with _tmod.TemporaryDirectory(prefix="triage_r5_") as td:
            tdir = Path(td)
            (tdir / "rootfs.squashfs").write_bytes(b"hsqs" + b"\x00" * 64)
            (tdir / "data.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 32)
            fw = bytearray(64)
            fw[40:44] = b"_FVH"
            (tdir / "bios.rom").write_bytes(bytes(fw))
            tar = bytearray(512)
            tar[257:262] = b"ustar"
            (tdir / "bundle.tar").write_bytes(bytes(tar))
            tri_json = tdir / "triage.json"
            r = subprocess.run([sys.executable, str(SCRIPTS / "triage.py"), str(tdir),
                                "--json-out", str(tri_json)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            tri = json.loads(tri_json.read_text(encoding="utf-8")) if tri_json.exists() else {}
            magics = " ".join(i.get("magic", "") for i in tri.get("files", []))
            check("triage squashfs/sqlite/uefi/tar magics",
                  all(k in magics for k in ("SquashFS", "SQLite database",
                                            "UEFI firmware volume", "TAR archive")), magics[:160])
            check("triage routes firmware to forensics",
                  (tri.get("classification") or {}).get("primary") == "forensics",
                  str((tri.get("classification") or {}).get("scores"))[:120])

        # R34：并行构建（真实 docker；三个独立 misc 题层并发）
        if wb.envb.docker_available():
            for slug in ("par-a", "par-b", "par-c"):
                (comp / "env" / "challenges" / (slug + ".yaml")).write_text(
                    f"api: ctfbox/v1\nslug: {slug}\ncategory: misc\nbuild:\n  apt: [jq]\n",
                    encoding="utf-8")
            r2 = subprocess.run([sys.executable, str(HERE / "env_builder.py"), "build",
                                 str(comp), "--slug", "par-a", "--slug", "par-b",
                                 "--slug", "par-c", "--jobs", "3"],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace")
            built2 = wb.envb.read_built(comp)
            ok_count = sum(1 for s in ("par-a", "par-b", "par-c")
                           if (built2.get("images") or {}).get(s, {}).get("status") == "built")
            check("parallel build 3 layers", r2.returncode == 0 and ok_count == 3,
                  (r2.stderr or r2.stdout)[-200:] + " ok={}".format(ok_count))
            for slug in ("par-a", "par-b", "par-c"):
                tag = (built2.get("images") or {}).get(slug, {}).get("image")
                if tag:
                    subprocess.run([*wb.envb.docker_prefix(), "rmi", "-f", tag],
                                   capture_output=True, timeout=120)
                    built2.get("images", {}).pop(slug, None)
            wb.envb.save_built(comp, built2)

        # R12：任务日志轮转（隔离目录，避免真实任务日志干扰 mtime 排序）
        rot_comp = comp.parent / "rotcheck"
        log_dir = rot_comp / "scratch"
        log_dir.mkdir(parents=True, exist_ok=True)
        for i in range(5):
            lp = log_dir / f"rot-{i}.log"
            lp.write_text("x", encoding="utf-8")
            os.utime(lp, (time.time() - (10 - i) * 60, time.time() - (10 - i) * 60))
        removed = wb.prune_task_logs(rot_comp, keep=2)
        remaining = sorted(p.name for p in log_dir.glob("rot-*.log"))
        check("task log rotation keeps newest", removed == 3
              and remaining == ["rot-3.log", "rot-4.log"], f"removed={removed} {remaining}")
        shutil.rmtree(rot_comp, ignore_errors=True)

        # R18：文档一致性——动作白名单 ⊆ /api/help 文档
        help_doc = json.dumps(wb.API_HELP, ensure_ascii=False)
        missing = [name for name in wb.ACTIONS if name not in help_doc]
        check("API help covers all actions", not missing, f"missing: {missing}")
        # R42：registry 配置读写
        st, r = http_post_json(port, "/api/env/registry",
                               {"registry": "registry.example.com/team"})
        check("registry save", st == 200 and r.get("ok") is True, str(r)[:150])
        st, r = http_get(port, "/api/env/registry")
        check("registry read back", st == 200
              and r.get("registry") == "registry.example.com/team", str(r)[:150])
        st, r = http_post_json(port, "/api/env/registry", {"registry": "bad reg!!"})
        check("registry format rejected", st == 400, str(r)[:150])
        import pathlib as _pl
        reg_path = wb.ROOT / "workbench-data" / "registry.json"
        reg_path.unlink(missing_ok=True)

        st, _ = http_get(port, "/")
        check("index served", st == 200)
        h = http_headers(port, "/")
        csp = h.get("content-security-policy", "")
        check("CSP header present with script-src 'self'",
              "script-src 'self'" in csp and "unsafe-eval" not in csp, csp[:160])
        check("security headers on static",
              h.get("x-content-type-options") == "nosniff" and "referrer-policy" in h,
              str({k: h.get(k) for k in ("x-content-type-options", "referrer-policy")}))
        st, _ = http_get(port, "/static/app.js")
        check("static served", st == 200)
        # F.5 G4 烟测：vendor petite-vue.es.js 200 + app.js module
        st, vendor_body = http_get(port, "/static/vendor/petite-vue.es.js")
        check("vendor petite-vue served", st == 200, str(st))
        check("vendor is ES module",
              isinstance(vendor_body, bytes) and b"export" in vendor_body,
              str(vendor_body)[:120] if isinstance(vendor_body, bytes) else "")
        # index.html 含 type="module" 且无内联 <script> 内容
        st, idx_body = http_get(port, "/")
        idx_html = idx_body.decode("utf-8") if isinstance(idx_body, bytes) else ""
        check("index uses module script", 'type="module" src="/static/app.js"' in idx_html)
        check("index no inline script",
              idx_html.count("<script") == 1 and "type=\"module\"" in idx_html,
              f"<script count={idx_html.count('<script')}")

        # F.12 主题切换：index.html 默认 data-theme="dark"；style.css 含 dark+light 两块
        check("index has data-theme default",
              'data-theme="dark"' in idx_html,
              "missing data-theme default on <html>")
        st, css_body = http_get(port, "/static/style.css")
        css_text = css_body.decode("utf-8") if isinstance(css_body, bytes) else ""
        check("style has dark theme block", '[data-theme="dark"]' in css_text)
        check("style has light theme block", '[data-theme="light"]' in css_text)
        check("style has prefers-reduced-motion",
              "prefers-reduced-motion" in css_text)
        # F.13 a11y 烟测：modal role=dialog / aria-modal / skip-link / icon-btn aria-label
        check("index has skip-link", 'class="skip-link"' in idx_html)
        check("index modal has dialog role",
              'role="dialog"' in idx_html and 'aria-modal="true"' in idx_html)
        check("index icon buttons have aria-label",
              idx_html.count('aria-label=') >= 6,
              f"aria-label count={idx_html.count('aria-label=')}")
        check("index sidebar has nav groups",
              'nav-group-label' in idx_html and '解题' in idx_html and '监控' in idx_html)
        # 新视图 sections 都已注入
        for tab in ("leaderboard", "achievements", "resources"):
            check(f"index has view-{tab}", f'id="view-{tab}"' in idx_html)

        print("== 托管层：模式/评分/队伍/难度/排行榜/成就/资源 ==")
        # set_mode team
        st, r = http_post_json(port, "/api/action", {
            "action": "competition.set_mode", "params": {"dir": "wbtest", "mode": "team"}})
        check("set_mode team", st == 200 and r.get("ok") is True
              and r.get("competition", {}).get("config", {}).get("mode") == "team", str(r)[:200])
        # add_team
        st, r = http_post_json(port, "/api/action", {
            "action": "competition.add_team", "params": {"dir": "wbtest", "name": "Alpha", "team_id": "t01"}})
        check("add_team", st == 200 and r.get("ok") is True, str(r)[:200])
        # team.list
        st, r = http_post_json(port, "/api/action", {
            "action": "team.list", "params": {"dir": "wbtest"}})
        check("team.list has Alpha", st == 200 and any(
            t.get("id") == "t01" and t.get("name") == "Alpha"
            for t in json.loads(r.get("stdout", "[]"))), str(r)[:200])
        # /api/teams
        st, r = http_get(port, "/api/teams?dir=wbtest")
        check("GET /api/teams", st == 200 and any(t.get("id") == "t01" for t in r.get("teams", [])),
              str(r)[:200])
        # set_scoring dynamic
        st, r = http_post_json(port, "/api/action", {
            "action": "competition.set_scoring",
            "params": {"dir": "wbtest", "strategy": "dynamic", "decay_type": "linear",
                       "decay_cap": 0.2, "decay_step": 0.1, "first_blood_bonus": 0.1}})
        check("set_scoring dynamic", st == 200 and r.get("ok") is True, str(r)[:200])
        # /api/scoring
        st, r = http_get(port, "/api/scoring?dir=wbtest")
        check("GET /api/scoring", st == 200 and r.get("scoring", {}).get("strategy") == "dynamic",
              str(r)[:200])
        # update_challenge difficulty_grade
        st, r = http_post_json(port, "/api/action", {
            "action": "competition.update_challenge",
            "params": {"dir": "wbtest", "slug": "testc", "difficulty_grade": 4}})
        check("update_challenge grade", st == 200 and r.get("ok") is True, str(r)[:200])
        # case.set_grade
        st, r = http_post_json(port, "/api/action", {
            "action": "case.set_grade", "params": {"dir": "wbtest", "case_dir": "cases/testc", "grade": 5}})
        check("case.set_grade", st == 200 and r.get("ok") is True, str(r)[:200])
        # grade=6 rejected
        st, r = http_post_json(port, "/api/action", {
            "action": "case.set_grade", "params": {"dir": "wbtest", "case_dir": "cases/testc", "grade": 6}})
        check("grade=6 rejected", st == 400, str(r)[:200])
        # /api/leaderboard (无 db 时空)
        st, r = http_get(port, "/api/leaderboard?dir=wbtest&mode=team")
        check("GET /api/leaderboard empty", st == 200 and r.get("rows") == [], str(r)[:200])
        # /api/achievements (无 db 时空)
        st, r = http_get(port, "/api/achievements?dir=wbtest")
        check("GET /api/achievements empty", st == 200 and r.get("achievements") == [], str(r)[:200])
        # /api/resources
        st, r = http_get(port, "/api/resources?q=triage&dir=wbtest")
        check("GET /api/resources", st == 200 and r.get("count", 0) > 0, str(r)[:200])
        # /api/bootstrap
        st, r = http_get(port, "/api/bootstrap?dir=wbtest")
        check("GET /api/bootstrap", st == 200 and "competition" in r
              and "case_summary_map" in r and "resources_stats" in r, str(r)[:200])
        # remove_challenge：先注册一个临时题再移除
        st, r = http_post_json(port, "/api/action", {
            "action": "challenge.register",
            "params": {"dir": "wbtest", "name": "Temp Remove", "category": "misc", "slug": "temprem"}})
        check("register temp for remove", st == 200 and r.get("ok") is True, str(r)[:200])
        st, r = http_post_json(port, "/api/action", {
            "action": "competition.remove_challenge", "params": {"dir": "wbtest", "slug": "temprem"}})
        check("remove_challenge", st == 200 and r.get("ok") is True, str(r)[:200])

        # 新视图模块可被静态服务（app.js 通过 import 引用）
        for view in ("leaderboard", "achievements", "resources", "ops"):
            st, _ = http_get(port, f"/static/views/{view}.js")
            check(f"/static/views/{view}.js served", st == 200,
                  f"status={st}")
        # achievements.meta.json 可被服务
        st, meta_body = http_get(port, "/static/achievements.meta.json")
        check("achievements.meta.json served", st == 200 and b"first_blood" in (meta_body or b""),
              f"status={st}")
        # 训练系统定位内容断言（不依赖运行时数据，仅校验静态文件文案）
        st, lb_body = http_get(port, "/static/views/leaderboard.js")
        check("leaderboard.js 含 progress 字段引用",
              st == 200 and b"progress" in (lb_body or b""),
              f"status={st}")
        st, ops_body = http_get(port, "/static/views/ops.js")
        check("ops.js 含 自由练习 / 模拟赛 / 复盘 三档训练模式",
              st == 200 and all(kw.encode("utf-8") in (ops_body or b"") for kw in
                                ("自由练习", "模拟赛", "复盘")),
              f"status={st}")
        check("achievements.meta.json 含训练激励文案（首次突破 / 连续通关）",
              all(kw.encode("utf-8") in (meta_body or b"") for kw in
                  ("首次突破", "连续通关")),
              "missing training-incentive copy")

        # external_kb 外部知识库接入断言
        # 1. 未配置 KB_EXTERNAL_DIR 时优雅降级（httpd 启动时未设该环境变量）
        st, r = http_get(port, "/api/resources?q=test&kind=external_kb&dir=wbtest")
        check("external_kb 未配置时降级（200 + count==0）",
              st == 200 and r.get("count", -1) == 0, str(r)[:200])
        # 2. 配置 KB_EXTERNAL_DIR 后可检索 + .idx.md 被跳过（直接调 CLI，不走 HTTP）
        kb_tmp = tmp / "external_kb_test"
        kb_tmp.mkdir()
        (kb_tmp / "test_kb.md").write_text("# SQL注入 test\n这是 external_kb 测试内容", encoding="utf-8")
        (kb_tmp / "test_kb.idx.md").write_text("# SQL注入 idx\n这是 idx 索引文件应被跳过", encoding="utf-8")
        env = {**os.environ, "KB_EXTERNAL_DIR": str(kb_tmp)}
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "kb_search.py"), "resources", "SQL注入",
             "--kind", "external_kb", "--top", "20"],
            capture_output=True, text=True, env=env)
        check("external_kb CLI 可检索 + idx 跳过",
              r.returncode == 0 and "test_kb.md" in r.stdout and "test_kb.idx.md" not in r.stdout,
              r.stderr[-300:] if r.stderr else "")
        # 3. 新复制的专题被 reference 类检索（用纯 ASCII 查询词避免 URL 编码问题）
        st, r = http_get(port, "/api/resources?q=SQL&kind=reference&dir=wbtest")
        check("reference 类检索到新复制的专题（SQL.md）",
              st == 200 and r.get("count", 0) > 0, str(r)[:200])

        # 4. 中文名文档必须能通过 /api/kb 返回（KB_LINE 曾用 ASCII-only 字符类，
        #    把 references/ 下 9 份中文名文档的命中全部静默丢弃：
        #    CLI 搜得到、知识库页空白）
        st, r = http_get(port, "/api/kb?q=lsb&top=10")
        files = {h.get("file") for h in (r or {}).get("hits", [])}
        check("KB 接口返回中文名文档命中",
              st == 200 and "图片隐写.md" in files, f"files={sorted(files)}")
        # 5. 索引类文件不得出现在 KB 结果里（会把每篇文档标题复制一份霸榜）
        st, r = http_get(port, "/api/kb?q=" + urllib.parse.quote("反序列化")
                         + "&top=10&category=web")
        files = {h.get("file") for h in (r or {}).get("hits", [])}
        check("KB 结果不含索引文件且含专题正文",
              "AI-SEARCH-INDEX.md" not in files and "PHP反序列化漏洞总结.md" in files,
              f"files={sorted(files)}")

        # F.14 性能预算（轻量回归守护）：/api/bootstrap 响应 < 800ms（50 题预算 250ms，
        # 测试样本仅几题，放宽到 800ms 作为退化告警；本地冷启动 SQLite 也在内）
        t0 = time.time()
        st, _ = http_get(port, "/api/bootstrap?dir=wbtest")
        elapsed_ms = (time.time() - t0) * 1000
        check("bootstrap perf < 800ms",
              st == 200 and elapsed_ms < 800,
              f"elapsed={int(elapsed_ms)}ms status={st}")

        httpd.shutdown()
        print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
