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
        check("demo agent advertised", st == 200 and r.get("demo_agent") is True)
        case_dir_abs = comp / "cases" / "testc"
        check("task log written", any(case_dir_abs.glob("scratch/T*-agent-run.log")))

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
        wb._auth_token = "sekrit"
        wb._LOCAL_ORIGINS_CACHE = [f"http://127.0.0.1:{port}",
                                   f"http://localhost:{port}",
                                   f"http://[::1]:{port}"]
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
        check("200 with bearer session", st == 200)
        # Cookie: wb_session=<session> 200
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/competitions",
                                     headers={"Cookie": f"wb_session={session}"})
        st = urllib.request.urlopen(req, timeout=10).status
        check("200 with cookie session", st == 200)
        # 篡改 session 签名 401
        bad = session[:-4] + "0000"
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/competitions",
                                     headers={"Authorization": f"Bearer {bad}"})
        try:
            urllib.request.urlopen(req, timeout=10)
            check("401 on tampered session sig", False)
        except urllib.error.HTTPError as e:
            check("401 on tampered session sig", e.code == 401)
        # POST /api/action 用 session
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/action",
            data=json.dumps({"action": "submit.dryrun",
                             "params": {"dir": "wbtest", "challenge": "testc",
                                        "flag": "x"}}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {session}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r2:
                st, r = r2.status, json.loads(r2.read())
        except urllib.error.HTTPError as e:
            st, r = e.code, json.loads(e.read() or b"{}")
        check("POST accepts bearer session", st in (200, 400) and "exit" in r, str(r)[:200])
        wb._auth_token = ""
        wb._LOCAL_ORIGINS_CACHE = []

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
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404); self.end_headers()

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
        mock.shutdown()

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
