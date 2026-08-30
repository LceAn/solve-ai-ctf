#!/usr/bin/env python3
"""Workbench 冒烟测试：临时目录起真实服务，覆盖全部 API 与关键动作。

用法：python solve-ai-ctf/workbench/test_workbench.py
不触碰 比赛/ 下的真实数据。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

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


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="wb_test_"))
    (tmp / "比赛").mkdir()
    comp = tmp / "比赛" / "wbtest"
    try:
        print("== 准备临时比赛 ==")
        for argv in (
            [SCRIPTS / "competition.py", "init", comp, "--name", "WB Test CTF", "--scope", "test-only"],
            [SCRIPTS / "competition.py", "add-challenge", comp, "--name", "Test Chall",
             "--category", "crypto", "--slug", "testc", "--points", "100",
             "--description", "冒烟测试题目"],
        ):
            r = subprocess.run([sys.executable, *map(str, argv)], capture_output=True, text=True)
            check(f"script {argv[1]}", r.returncode == 0, r.stderr[-300:])

        art = comp / "artifacts"
        art.mkdir(exist_ok=True)
        (art / "note.txt").write_text("ignored flag{wb_test_flag_001} tail", encoding="utf-8")
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

        st, comp_view = http_get(port, "/api/competition?dir=wbtest")
        check("competition 200", st == 200)
        check("challenge listed", any(c["slug"] == "testc" for c in comp_view.get("challenges", [])))
        testc = next((c for c in comp_view["challenges"] if c["slug"] == "testc"), {})
        check("case summary exists", testc.get("case", {}).get("exists") is True)
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
        case_dir_abs = comp / "cases" / "testc"
        check("task log written", any(case_dir_abs.glob("scratch/T*-agent-run.log")))

        st, r = http_post_json(port, "/api/action", {
            "action": "case.writeup", "params": {"dir": "wbtest", "case_dir": "cases/testc"}})
        check("writeup generated", st == 200 and r.get("ok") is True, str(r)[:200])
        check("writeup file exists", (case_dir_abs / "WRITEUP.md").exists())

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
        st, _ = http_get(port, "/api/competitions")
        check("401 without token", st == 401)
        st, _ = http_get(port, "/api/competitions?token=sekrit")
        check("200 with query token", st == 200)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/competitions",
                                     headers={"Authorization": "Bearer sekrit"})
        st = urllib.request.urlopen(req, timeout=10).status
        check("200 with bearer token", st == 200)
        wb._auth_token = ""

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
              cfg["platform"]["submit"]["path"].endswith("/submit"),
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
        st, comp_view2 = http_get(port, "/api/competition?dir=wbtest")
        check("challenges auto-registered",
              {c["slug"] for c in comp_view2["challenges"]} >= {"c101", "c102"},
              str([c["slug"] for c in comp_view2["challenges"]]))
        mock.shutdown()

        st, _ = http_get(port, "/")
        check("index served", st == 200)
        st, _ = http_get(port, "/static/app.js")
        check("static served", st == 200)

        httpd.shutdown()
        print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
