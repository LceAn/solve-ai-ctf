"""本地功能验收：真实启动服务，逐项打接口与写操作（不依赖 pytest，不污染真实比赛）。

用法：
    python workbench/acceptance.py                # 默认端口 8799，临时比赛跑完即删
    python workbench/acceptance.py --port 8801    # 指定端口
    python workbench/acceptance.py --keep         # 保留临时比赛目录便于排查

覆盖：35 个只读路由 + 20 个写操作（competition/challenge/case/docs/submit/task/沙箱配置）。
与 test_workbench.py 的分工：
    test_workbench.py  回归断言（mock 平台、CSP 质量门、页面结构），CI 必跑；
    acceptance.py      端到端冒烟（真起服务、真落盘、真派发），发版或大改后跑。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO if (REPO / "比赛").is_dir() else (
    REPO.parent if (REPO.parent / "比赛").is_dir() else REPO)
results: list[tuple[str, str, str]] = []


def record(kind: str, name: str, detail: str) -> None:
    results.append((kind, name, detail))
    print(f"{'ok  ' if kind == 'ok' else 'FAIL'}  {name:38} {detail[:100]}", flush=True)


def req(base: str, path: str, method: str = "GET", body=None, timeout: int = 30):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method)
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--keep", action="store_true", help="保留临时比赛目录")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    spec = importlib.util.spec_from_file_location(
        "wb_server", REPO / "workbench" / "server.py")
    wb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wb)
    wb.configure(root=ROOT, scripts=REPO / "scripts", static=REPO / "workbench" / "static")
    import wb_actions
    sys.argv = ["server.py", "--port", str(args.port)]
    threading.Thread(target=wb.main, daemon=True).start()

    for _ in range(60):
        if req(base, "/api/help", timeout=2)[0] == 200:
            break
        time.sleep(0.3)
    else:
        print("服务未就绪")
        return 1
    record("ok", "server.boot", f"127.0.0.1:{args.port}")

    def get(name: str, path: str, expect: int = 200) -> str:
        st, raw = req(base, path)
        ok = st == expect
        if ok:
            try:
                json.loads(raw)
            except Exception:  # noqa: BLE001
                ok = False
        record("ok" if ok else "fail", name, f"{st} {raw[:90]}".replace("\n", " "))
        return raw

    def action(name: str, params: dict, expect: int = 200, timeout: int = 30):
        st, raw = req(base, "/api/action", "POST",
                      {"action": name, "params": params}, timeout=timeout)
        record("ok" if st == expect else "fail", f"action:{name}",
               f"{st} {raw[:100]}".replace("\n", " "))
        return raw

    q = urllib.parse.quote
    comps = json.loads(get("api/competitions", "/api/competitions"))
    comp = comps.get("default") or ""
    if not comp:
        print("没有已初始化的比赛，跳过依赖比赛项的检查")
        comp = ""

    get("/api/help", "/api/help")
    if comp:
        get("competition", f"/api/competition?dir={q(comp)}")
        get("board", f"/api/board?dir={q(comp)}")
        get("bootstrap", f"/api/bootstrap?dir={q(comp)}")
        get("events", f"/api/events?dir={q(comp)}")
        get("docs/tree", f"/api/docs/tree?dir={q(comp)}")   # 未配置返回 configured:false
        get("tree", f"/api/tree?dir={q(comp)}")
        get("leaderboard", f"/api/leaderboard?dir={q(comp)}")
        get("achievements", f"/api/achievements?dir={q(comp)}")
        get("scoring", f"/api/scoring?dir={q(comp)}")
        get("submissions", f"/api/submissions?dir={q(comp)}")
        get("teams", f"/api/teams?dir={q(comp)}")
        get("autosubmit", f"/api/autosubmit?dir={q(comp)}")
        get("env/status", f"/api/env/status?dir={q(comp)}")
        get("env/push-history", f"/api/env/push-history?dir={q(comp)}")
    get("tasks", "/api/tasks")
    get("health", "/api/health")
    get("health/detail", "/api/health/detail")
    get("sandbox", "/api/sandbox")
    get("kb", "/api/kb?q=" + q("反序列化") + "&top=3")
    get("kb/stats", "/api/kb/stats")
    get("resources", "/api/resources?q=sql")
    get("presets", "/api/presets")
    get("env/registry", "/api/env/registry")
    get("gateway/usage", "/api/gateway/usage")
    get("agent-gw/directory", "/api/agent-gw/directory")
    get("selftest", "/api/selftest")

    # ---------- 写操作：临时比赛（跑完删除） ----------
    test_comp = f"_acc-{int(time.time())}"
    try:
        action("competition.init", {"name": "验收测试", "dir_name": test_comp})
        action("challenge.register", {"dir": test_comp, "name": "验收题", "category": "web",
                                      "slug": "acc1", "challenge_id": "9001", "points": 100})
        action("case.init", {"dir": test_comp, "case_dir": "cases/acc1",
                             "name": "验收题", "category": "web"})
        action("case.status", {"dir": test_comp, "case_dir": "cases/acc1", "status": "in_progress"})
        action("case.hypothesis", {"dir": test_comp, "case_dir": "cases/acc1",
                                   "title": "疑似 SSTI", "rationale": "输入回显到模板",
                                   "expected": "{{7*7}} 回显 49"})
        action("case.finding", {"dir": test_comp, "case_dir": "cases/acc1",
                                "claim": "模板注入点", "source": "manual"})
        action("case.attempt", {"dir": test_comp, "case_dir": "cases/acc1", "hypothesis": "quick",
                                "action": "试 {{7*7}}", "result": "partial", "outcome": "partial"})
        art = ROOT / "比赛" / test_comp / "cases" / "acc1" / "artifacts"
        art.mkdir(parents=True, exist_ok=True)
        (art / "flag.txt").write_text("flag{acc_flag}", encoding="utf-8")
        action("case.scan_flags", {"dir": test_comp, "case_dir": "cases/acc1",
                                   "search_root": "cases/acc1/artifacts", "store": True})
        case_json = json.loads((ROOT / "比赛" / test_comp / "cases" / "acc1" / "case.json")
                               .read_text(encoding="utf-8"))
        if case_json.get("candidates"):
            action("case.candidate", {"dir": test_comp, "case_dir": "cases/acc1",
                                      "candidate_id": case_json["candidates"][0]["id"],
                                      "candidate_status": "validated"})
        else:
            record("fail", "case.candidate", "扫描未产生候选")
        action("case.summary", {"dir": test_comp, "case_dir": "cases/acc1"})
        action("case.validate", {"dir": test_comp, "case_dir": "cases/acc1"})
        action("docs.write", {"dir": test_comp, "name": "acc.md", "content": "# 验收\n"})
        action("competition.prioritize", {"dir": test_comp})
        action("competition.report", {"dir": test_comp})
        action("achievement.check", {"dir": test_comp})
        action("submit.dryrun", {"dir": test_comp, "challenge": "acc1",
                                 "flag": "flag{acc_flag}"})

        # 沙箱配置保存（先备份，避免覆盖用户设置）
        sb = ROOT / "workbench-data" / "sandbox.json"
        backup = sb.read_bytes() if sb.exists() else None
        st, raw = req(base, "/api/sandbox", "POST", {"max_concurrent": 2})
        record("ok" if st == 200 else "fail", "POST /api/sandbox(save)", f"{st} {raw[:80]}")
        if backup is not None:
            sb.write_bytes(backup)
        elif sb.exists():
            sb.unlink()

        st, raw = req(base, "/api/env/services/down", "POST",
                      {"dir": test_comp, "slug": "acc1"})
        ok = st in (200, 400) and "NameError" not in raw
        record("ok" if ok else "fail", "POST /api/env/services/down", f"{st} {raw[:90]}")

        # 异步自检：启动应立即返回，状态端点可查
        t0 = time.time()
        st, raw = req(base, "/api/action", "POST",
                      {"action": "selftest.run", "params": {}}, timeout=10)
        elapsed = time.time() - t0
        fast = st == 200 and elapsed < 5   # 异步化后应立即返回，而不是挂到自检结束
        record("ok" if fast else "fail", "action:selftest.run(async)",
               f"{st} {elapsed:.2f}s {raw[:70]}")
        st, raw = req(base, "/api/selftest")
        running = st == 200 and '"started": true' in raw
        record("ok" if running else "fail", "GET /api/selftest", f"{st} {raw[:80]}")

        # 任务：演示 Agent
        st, raw = req(base, "/api/task/start", "POST",
                      {"dir": test_comp, "slug": "acc1", "demo": True})
        record("ok" if st == 200 else "fail", "task.start(demo)", f"{st} {raw[:90]}")
        try:
            tid = json.loads(raw).get("task", {}).get("id", "")
        except Exception:  # noqa: BLE001
            tid = ""
        if tid:
            time.sleep(2)
            get("task/tail", f"/api/task/tail?id={tid}")
            st, raw = req(base, "/api/task/stop", "POST", {"id": tid})
            record("ok" if st == 200 else "fail", "task.stop", f"{st} {raw[:80]}")
    finally:
        try:  # 收掉后台自检进程，避免脚本退出后残留
            proc = getattr(wb_actions, "_SELFTEST", {}).get("proc")
            if proc is not None and proc.poll() is None:
                proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        target = ROOT / "比赛" / test_comp
        if target.exists() and not args.keep:
            shutil.rmtree(target, ignore_errors=True)
            record("ok", "cleanup", "临时比赛已删除")
        elif target.exists():
            record("ok", "cleanup", f"保留 {target}")

    fails = [r for r in results if r[0] == "fail"]
    print(f"\n结果：{len(results) - len(fails)} 通过 / {len(fails)} 失败")
    for _, name, detail in fails:
        print(f"  ✗ {name}: {detail[:160]}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
