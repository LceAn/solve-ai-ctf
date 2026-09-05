#!/usr/bin/env python3
"""E2E 环境验证 —— 从建比赛到沙箱求解的全链路真实检查（依赖 Docker）。

覆盖：env 骨架生成 → API 状态 → preheat → build（含漂移检测）→ verify 探针
→ 沙箱派发（镜像选择优先级 / cap 白名单 / files 挂载）→ compose 服务编排
（solver 按服务名访问）→ 任务停止 → 看门狗超时连带 compose down → export。

用法：
    python solve-ai-ctf/workbench/e2e_env_check.py            # 跑完自动清理
    python solve-ai-ctf/workbench/e2e_env_check.py --keep     # 保留比赛目录与镜像

Docker 不可达时直接跳过（exit 3）；幂等：启动前先清理上一轮残留。
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
COMP_NAME = "e2e-demo"
COMP = REPO / "比赛" / COMP_NAME

spec = importlib.util.spec_from_file_location("wb_server", HERE / "server.py")
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)
envb = wb.envb

PASS = 0
FAIL = 0
KEEP = "--keep" in sys.argv


def check(name: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail[:300]}")
    return bool(cond)


def http_get(port: int, path: str, timeout: int = 120):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            body = r.read()
            if r.headers.get("Content-Type", "").startswith("application/json"):
                return r.status, json.loads(body)
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def http_post(port: int, path: str, payload: dict, timeout: int = 240):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait_task(port: int, tid: str, timeout: int = 420):
    """轮询任务到 done/failed，返回 (status, output)。"""
    deadline = time.time() + timeout
    status, output = "running", ""
    while time.time() < deadline:
        st, td = http_get(port, f"/api/task/tail?id={tid}")
        status = td.get("task", {}).get("status", "")
        output = td.get("output", "")
        if status in ("done", "failed", "lost"):
            return status, output
        time.sleep(1.0)
    return status, output


def docker(argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    prefix = envb.docker_prefix() or []
    return subprocess.run([*prefix, *argv], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def network_exists(name: str) -> bool:
    r = docker(["network", "ls", "--format", "{{.Name}}"])
    return name in (r.stdout or "").split()


def containers_named(pattern: str) -> list[str]:
    r = docker(["ps", "-a", "--format", "{{.Names}}"])
    return [n for n in (r.stdout or "").splitlines() if pattern in n]


def compose_project_of(comp: Path, slug: str) -> str:
    doc = envb.parse_yaml_text((comp / "env" / "gen" / slug / "compose.yaml").read_text(encoding="utf-8"))
    return str(doc["name"])


# ---------------------------------------------------------------- specs

MISC_SPEC = """\
api: ctfbox/v1
slug: misc-echo
category: misc
build:
  apt: [jq]
  pip: ["six==1.16.0"]
"""

WEB_SPEC = """\
api: ctfbox/v1
slug: web-blog
category: web
services:
  web:
    image: busybox:1.36
    command: ["httpd", "-f", "-p", "80", "-h", "/www"]
    mount: src/ -> /www
    env:
      FLAG: "flag{placeholder-do-not-submit}"
run:
  network: services
"""

PWN_SPEC = """\
api: ctfbox/v1
slug: pwn-heap
category: pwn
base: ctfbox-misc:0.1.0
build:
  apt: [socat]
files:
  - src: flag.txt
    dst: flag.txt
run:
  caps: [SYS_PTRACE]
"""


def write_specs(comp: Path) -> None:
    env = comp / "env"
    (env / "challenges" / "misc-echo.yaml").write_text(MISC_SPEC, encoding="utf-8")
    (env / "challenges" / "web-blog.yaml").write_text(WEB_SPEC, encoding="utf-8")
    (env / "challenges" / "pwn-heap.yaml").write_text(PWN_SPEC, encoding="utf-8")
    src = env / "assets" / "web-blog" / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "index.html").write_text(
        "<html><body>blog home. flag{placeholder-do-not-submit}</body></html>", encoding="utf-8")
    fdir = env / "assets" / "pwn-heap"
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / "flag.txt").write_text("flag{placeholder-do-not-submit}\n", encoding="utf-8")


def register(comp: Path) -> None:
    for argv in (
        [HERE / ".." / "scripts" / "competition.py", "init", comp,
         "--name", "E2E Demo CTF", "--scope", "e2e-test"],
        [HERE / ".." / "scripts" / "competition.py", "add-challenge", comp,
         "--name", "Echo Chall", "--category", "misc", "--slug", "misc-echo"],
        [HERE / ".." / "scripts" / "competition.py", "add-challenge", comp,
         "--name", "Blog Chall", "--category", "web", "--slug", "web-blog"],
        [HERE / ".." / "scripts" / "competition.py", "add-challenge", comp,
         "--name", "Heap Chall", "--category", "pwn", "--slug", "pwn-heap"],
    ):
        r = subprocess.run([sys.executable, *map(str, argv)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"注册失败：{argv[1]} {r.stderr[-200:]}")


def cleanup(comp: Path) -> None:
    """清掉本轮/上轮的比赛目录、镜像、compose 工程（幂等）。"""
    built_path = comp / "env" / "gen" / ".built.json"
    tags: list[str] = []
    projects: list[str] = []
    if built_path.exists():
        try:
            built = json.loads(built_path.read_text(encoding="utf-8"))
            recs = list((built.get("images") or {}).values())
            tags = [str(r["image"]) for r in recs if r.get("image")]
            if (built.get("comp") or {}).get("image"):
                tags.append(str(built["comp"]["image"]))
        except Exception:  # noqa: BLE001
            pass
    if comp.is_dir():
        for cf in (comp / "env" / "gen").glob("*/compose.yaml"):
            try:
                doc = envb.parse_yaml_text(cf.read_text(encoding="utf-8"))
                if doc.get("name"):
                    projects.append(str(doc["name"]))
            except Exception:  # noqa: BLE001
                pass
    for proj in projects:
        subprocess.run([*(envb.docker_prefix() or []), "compose", "-p", proj,
                        "down", "-v", "--remove-orphans"],
                       capture_output=True, timeout=120)
    for tag in tags:
        subprocess.run([*(envb.docker_prefix() or []), "rmi", "-f", tag],
                       capture_output=True, timeout=120)
    shutil.rmtree(comp, ignore_errors=True)


def main() -> int:
    print("== E2E 环境验证（真实 Docker 全链路）==")
    if not envb.docker_available():
        print("Docker 不可达：本检查需要真实 Docker（Docker Desktop 或 WSL docker）。")
        return 3
    cleanup(COMP)  # 幂等：清上一轮
    print("== A. 准备：建比赛 + 三道题（CLI）==")
    register(COMP)
    write_specs(COMP)
    check("init 创建 env 骨架", (COMP / "env" / "comp.yaml").is_file())
    check("三道题的 spec 就位",
          all((COMP / "env" / "challenges" / f"{s}.yaml").is_file()
              for s in ("misc-echo", "web-blog", "pwn-heap")))

    print("== B. 起服务 + env/status（骨架态）==")
    wb.configure(root=REPO, scripts=REPO / "scripts", static=HERE / "static")
    httpd = wb.ThreadingHTTPServer(("127.0.0.1", 0), wb.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        st, health = http_get(port, "/api/health")
        check("server 起来", st == 200 and health.get("ok") is True)
        st, sbx = http_get(port, "/api/sandbox")
        check("sandbox docker 可达", st == 200 and sbx.get("docker_ok") is True,
              json.dumps(sbx, ensure_ascii=False)[:200])
        st, stat = http_get(port, "/api/env/status?dir=e2e-demo", timeout=120)
        check("env/status 骨架态", st == 200 and stat.get("has_env") is True
              and len(stat.get("challenges", [])) == 3,
              json.dumps(stat, ensure_ascii=False)[:300])
        check("env/status 标记未构建",
              all(not (c.get("built") or {}) for c in stat.get("challenges", [])))

        print("== C. preheat（misc+web 题型层）==")
        st, r = http_post(port, "/api/env/build",
                          {"dir": COMP_NAME, "preheat": True, "categories": "misc,web"})
        check("preheat 派发", st == 200 and r.get("ok") is True, str(r)[:200])
        status, out = wait_task(port, r["task"]["id"], timeout=420)
        check("preheat 完成", status == "done" and "PREHEAT DONE" in out, out[-200:])
        check("L1 misc/web 就绪",
              envb.docker_image_exists("ctfbox-misc:0.1.0")
              and envb.docker_image_exists("ctfbox-web:0.1.0"))
        # 约束层随 L0 烤入：CLAUDE.md/AGENTS.md 双写 + 七类 skill 包
        r = docker(["run", "--rm", "--network", "none", "ctfbox-base:0.1.0", "sh", "-c",
                    "head -1 /workspace/CLAUDE.md; head -1 /workspace/AGENTS.md; "
                    "ls /workspace/.claude/skills | tr '\\n' ' '"])
        check("L0 烤入约束层与 skill 包",
              r.returncode == 0 and r.stdout.count("CTF 解题沙箱工作约束") == 2
              and "pwn" in r.stdout and "ai" in r.stdout,
              (r.stderr or r.stdout)[-250:])

        print("== D. build --all（L2 比赛层 + 三个题目层）==")
        st, r = http_post(port, "/api/env/build", {"dir": COMP_NAME, "all": True})
        status, out = wait_task(port, r["task"]["id"], timeout=420)
        check("build 完成", status == "done" and "BUILD DONE failed=0" in out, out[-300:])
        built = envb.read_built(COMP)
        check("四条构建记录（L2+3 题）",
              (built.get("comp") or {}).get("status") == "built"
              and len(built.get("images") or {}) == 3,
              json.dumps(built, ensure_ascii=False)[:300])
        st, stat = http_get(port, "/api/env/status?dir=e2e-demo", timeout=120)
        stat_by = {c["slug"]: c for c in stat.get("challenges", [])}
        check("status 显示已构建且无漂移",
              all((stat_by[s].get("built") or {}).get("image") and not stat_by[s].get("stale")
                  for s in ("misc-echo", "web-blog", "pwn-heap")),
              json.dumps(stat_by, ensure_ascii=False)[:400])

        print("== E. 漂移检测：改 spec → stale → 重建 → 消失 ==")
        misc_spec_path = COMP / "env" / "challenges" / "misc-echo.yaml"
        # 真实字段变更（注释不影响解析结果，不算漂移）
        misc_spec_path.write_text(
            misc_spec_path.read_text(encoding="utf-8")
            .replace('pip: ["six==1.16.0"]', 'pip: ["six==1.16.0", "packaging"]'),
            encoding="utf-8")
        st, stat = http_get(port, "/api/env/status?dir=e2e-demo", timeout=120)
        misc_row = next(c for c in stat["challenges"] if c["slug"] == "misc-echo")
        check("改 spec 后标记 stale", misc_row.get("stale") is True, str(misc_row)[:200])
        st, r = http_post(port, "/api/env/build", {"dir": COMP_NAME, "slug": "misc-echo"})
        status, out = wait_task(port, r["task"]["id"], timeout=300)
        st, stat = http_get(port, "/api/env/status?dir=e2e-demo", timeout=120)
        misc_row = next(c for c in stat["challenges"] if c["slug"] == "misc-echo")
        check("重建后 stale 消失", status == "done" and not misc_row.get("stale"), out[-200:])

        print("== F. verify 探针（misc-echo 镜像内）==")
        st, r = http_post(port, "/api/env/verify", {"dir": COMP_NAME, "slug": "misc-echo"})
        status, out = wait_task(port, r["task"]["id"], timeout=300)
        check("verify 探针全过", status == "done" and "VERIFY DONE failed=0" in out, out[-300:])

        print("== G. 沙箱派发：misc-echo（镜像选择 → 容器内求解）==")
        built = envb.read_built(COMP)
        misc_image = built["images"]["misc-echo"]["image"]
        st, r = http_post(port, "/api/task/start",
                          {"dir": COMP_NAME, "slug": "misc-echo", "sandbox": True})
        check("派发接受", st == 200 and r.get("ok") is True and r.get("sandbox") is True,
              str(r)[:300])
        check("选中题目层镜像", r.get("image") == misc_image and r.get("image_source") == "challenge",
              f"{r.get('image')} / {r.get('image_source')}")
        status, out = wait_task(port, r["task"]["id"], timeout=300)
        check("容器内 demo solver 跑完三阶段", status == "done" and "[solver] 完成" in out,
              f"status={status} {out[-300:]}")
        task_cmd = http_get(port, f"/api/task/tail?id={r['task']['id']}")[1]["task"]["command"]
        check("运行参数齐全（cap-drop/断网/限额/双挂载）",
              "--cap-drop ALL" in task_cmd and "--network none" in task_cmd
              and "--memory 2g" in task_cmd
              and ":/workspace" in task_cmd and ":/solver:ro" in task_cmd, task_cmd[:300])

        print("== H. 多服务题目：web-blog（compose 编排 + solver 进网）==")
        proj = compose_project_of(COMP, "web-blog")
        net = proj + "_challnet"
        st, r = http_post(port, "/api/task/start",
                          {"dir": COMP_NAME, "slug": "web-blog", "sandbox": True})
        check("派发接受且带 compose 元数据", st == 200 and r.get("ok") is True
              and r.get("services") is True, str(r)[:300])
        check("命令加入服务网络", net in http_get(port, f"/api/task/tail?id={r['task']['id']}")[1]["task"]["command"])
        check("服务容器拉起", wait_net_up(net), f"network {net} 未出现")
        # 用题目层镜像当 solver：按服务名抓首页，验证网络互通与占位 flag
        fetch = docker(["run", "--rm", "--network", net,
                        built["images"]["web-blog"]["image"], "python", "-c",
                        "import urllib.request;print(urllib.request.urlopen("
                        "'http://web/',timeout=10).read().decode())"], timeout=180)
        check("solver 按服务名取到题目页（占位 flag）",
              fetch.returncode == 0 and "flag{placeholder-do-not-submit}" in fetch.stdout,
              (fetch.stderr or fetch.stdout)[-200:])
        status, out = wait_task(port, r["task"]["id"], timeout=300)
        check("任务正常结束", status == "done", f"status={status} {out[-200:]}")
        check("任务结束后 compose 自动 down（网络消失）", wait_net_gone(net))
        check("无遗留容器", not containers_named(proj))

        print("== I. 镜像选择优先级：case env.image 覆盖 / 缺失硬报错 ==")
        case_json = COMP / "cases" / "misc-echo" / "case.json"
        case = json.loads(case_json.read_text(encoding="utf-8"))
        case.setdefault("env", {})["image"] = "ctfbox-misc:0.1.0"
        case_json.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
        st, r = http_post(port, "/api/task/start",
                          {"dir": COMP_NAME, "slug": "misc-echo", "sandbox": True})
        check("case 指定镜像优先生效", st == 200 and r.get("image") == "ctfbox-misc:0.1.0"
              and r.get("image_source") == "case", f"{r.get('image')}/{r.get('image_source')}")
        wait_task(port, r["task"]["id"], timeout=300)
        case["env"]["image"] = "nope:missing-e2e"
        case_json.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
        st, r = http_post(port, "/api/task/start",
                          {"dir": COMP_NAME, "slug": "misc-echo", "sandbox": True})
        check("指定镜像缺失 → 400 硬报错", st == 400 and "不存在" in str(r.get("error", "")),
              str(r)[:200])
        case["env"].pop("image")
        case_json.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")

        print("== J. pwn-heap：cap 白名单 + files 挂载 ==")
        st, r = http_post(port, "/api/task/start",
                          {"dir": COMP_NAME, "slug": "pwn-heap", "sandbox": True})
        check("pwn 派发接受", st == 200 and r.get("ok") is True, str(r)[:300])
        pwn_cmd = http_get(port, f"/api/task/tail?id={r['task']['id']}")[1]["task"]["command"]
        check("SYS_PTRACE 白名单（spec 声明 + pwn 类目缺省去重）",
              pwn_cmd.count("--cap-add SYS_PTRACE") == 1, pwn_cmd[:250])
        check("files 预置挂载进 /workspace", "flag.txt:ro" in pwn_cmd, pwn_cmd[:250])
        status, out = wait_task(port, r["task"]["id"], timeout=300)
        check("pwn 任务完成", status == "done" and "[solver] 完成" in out, out[-200:])

        print("== K. 手动停止：连带 compose down ==")
        st, r = http_post(port, "/api/task/start",
                          {"dir": COMP_NAME, "slug": "web-blog", "sandbox": True})
        check("再次派发接受", st == 200 and r.get("ok") is True)
        check("服务网络再次拉起", wait_net_up(net))
        time.sleep(3)
        st, r = http_post(port, "/api/task/stop", {"id": r["task"]["id"]})
        check("stop 成功", st == 200 and r.get("stopped") is True, str(r)[:200])
        check("stop 后 compose down（网络消失）", wait_net_gone(net))

        print("== L. 看门狗超时：强停 + 连带 compose down ==")
        wb._compose_up(COMP / "env" / "gen" / "web-blog" / "compose.yaml", proj)
        check("看门狗前置：服务网络在", wait_net_up(net))
        task = wb.TASKS.run_custom(COMP_NAME, "watchdog-e2e", "e2e",
                                   "python -c \"import time;time.sleep(120)\"",
                                   cwd=COMP, container="ctfwb-e2e-fake",
                                   compose={"project": proj,
                                            "compose_file": str(COMP / "env" / "gen" / "web-blog" / "compose.yaml")})
        tasks = wb.TASKS._load()
        tasks[task["id"]]["started"] = "2026-01-01T00:00:00"  # 回拨，触发超时
        wb.TASKS._save(tasks)
        wb.TASKS.enforce_timeouts(1)
        wd_task = wb.TASKS.get(task["id"])
        check("超时任务标记失败", wd_task.get("status") == "failed"
              and "timeout" in str(wd_task.get("error", "")), str(wd_task)[:200])
        check("看门狗连带 compose down", wait_net_gone(net))

        print("== M. export 导出镜像 ==")
        out_tar = REPO / "workbench-data" / "e2e-export.tar"
        result = envb.export_images(COMP, ["misc-echo"], out_tar, with_spec=True)
        ok_export = Path(result["out"]).is_file() and Path(result["out"]).stat().st_size > 0
        check("docker save 产物存在", ok_export, str(result))
        check("spec 归档存在", bool(result.get("spec_archive"))
              and Path(result["spec_archive"]).is_file())
        Path(result["out"]).unlink(missing_ok=True)
        if result.get("spec_archive"):
            Path(result["spec_archive"]).unlink(missing_ok=True)

        print("== N. 前端资产 ==")
        st, body = http_get(port, "/")
        check("index 可用", st == 200)
        st, js = http_get(port, "/static/app.js")
        check("app.js 含环境面板", st == 200 and b"opsEnv" in js)
    finally:
        if not KEEP:
            print("== 清理（--keep 可保留）==")
            cleanup(COMP)
            print("清理完成：比赛目录与 e2e 镜像已删除（L0/L1 题型层保留）")
        else:
            print(f"--keep：保留 {COMP} 与已构建镜像")
        httpd.shutdown()

    print(f"\nE2E 结果：{PASS} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


def wait_net_up(net: str, timeout: int = 120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if network_exists(net):
            return True
        time.sleep(1)
    return False


def wait_net_gone(net: str, timeout: int = 120) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not network_exists(net):
            return True
        time.sleep(1)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
