"""wb_health —— 系统概况：功能在线矩阵（R203）。

原来的「系统概况」是能力清单：写着"执行链路""脚本层"，但无论功能是否可用
都显示同一个绿点。用户看完仍然不知道**现在**能干什么。

这里改成实测：
- 每个子系统独立判定 online / degraded / off 三态，附实时指标；
- 所有结论都来自真实探测（读文件、编译脚本、查库、读内存计数），
  不做"文件存在就算在线"这种含糊判断；
- off ≠ 故障：未配置的能力单独计数，避免和"坏了"混在一起吓人。

性能：本模块自己缓存 10s，Docker 探测复用 wb_sandbox 的 30s 缓存，
整页响应控制在百毫秒级（不跑 subprocess、不打网络）。
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path

import wb_core as _core
from wb_core import list_competitions, read_json
from wb_tasks import TASKS

GROUPS = ["核心运行时", "求解环境", "协作接入", "数据与交付"]

# 运行时长基准：main() 在 serve 前写入 RUNTIME["started_at"]；
# 本模块是延迟导入的，不能拿模块导入时间当启动时间（那永远显示 0s）。
_BOOT_AT = time.time()

_CACHE: dict = {"at": 0.0, "data": {}}
_CACHE_TTL = 10.0
_SCAN_CACHE: dict = {"at": 0.0, "data": {}}
_SCAN_TTL = 60.0


# ------------------------------------------------------------------ 工具

def _now_text() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _ago(seconds: float) -> str:
    """秒 → 人话（0s / 12m / 3h / 2d）。"""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return (f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}")
        n /= 1024.0
    return f"{n:.1f} GB"


def _mtime_text(p: Path) -> str:
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(p.stat().st_mtime))
    except OSError:
        return "—"


def _mod(key: str, name: str, group: str, state: str, detail: str,
         metrics: list | None = None, probe: str = "", hint: str = "",
         link: str = "") -> dict:
    return {"key": key, "name": name, "group": group, "state": state,
            "detail": detail, "metrics": metrics or [], "probe": probe,
            "hint": hint, "link": link}


# ------------------------------------------------------------------ 扫描（60s 缓存）
#
# 比赛目录可能很大（几十个 case、上千条事件）。这几个函数只做文件系统读，
# 但页面上 10s 一刷也没必要重扫，单独加一层缓存。

def _scan(force: bool = False) -> dict:
    now = time.time()
    if not force and now - _SCAN_CACHE["at"] < _SCAN_TTL and _SCAN_CACHE["data"]:
        return _SCAN_CACHE["data"]

    comps = list_competitions()
    challenges = 0
    cases_total = 0
    bad_status: list[str] = []
    status_counts: Counter = Counter()
    events_total = 0
    events_latest: tuple[float, str] = (0.0, "")
    docs_total = 0
    docs_comps = 0
    writeups = 0
    exports: list[dict] = []
    inbox_pending = 0
    submissions = 0
    valid = set(_core.CASE_STATUSES)

    for comp in comps:
        # list_competitions 只给相对目录名（comp["dir"]），没有绝对路径字段。
        # 注意别写成 Path("")——那是 Path(".")，会把当前工作目录当成比赛目录。
        raw_dir = str(comp.get("dir_path") or comp.get("path") or comp.get("dir") or "").strip()
        if not raw_dir:
            continue
        comp_dir = Path(raw_dir)
        if not comp_dir.is_absolute():
            comp_dir = _core.ROOT / "比赛" / raw_dir
        if not comp_dir.is_dir():
            continue
        challenges += int(comp.get("challenges") or 0)

        # case.json：题目数 + 状态合法性
        for cj in sorted((comp_dir / "cases").glob("*/case.json")):
            cases_total += 1
            try:
                data = json.loads(cj.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                bad_status.append(f"{comp_dir.name}/{cj.parent.name}: 不可解析")
                continue
            st = str(data.get("status") or "").strip()
            status_counts[st or "(空)"] += 1
            if valid and st not in valid:
                bad_status.append(f"{comp_dir.name}/{cj.parent.name}: {st or '(空)'}")

        # 事件流
        ev = comp_dir / "events.jsonl"
        if ev.is_file():
            try:
                raw = ev.read_text(encoding="utf-8", errors="replace")
                lines = [ln for ln in raw.splitlines() if ln.strip()]
                events_total += len(lines)
                mt = ev.stat().st_mtime
                if mt > events_latest[0]:
                    events_latest = (mt, _ago(time.time() - mt))
            except OSError:
                pass

        # 文档
        comp_docs = list((comp_dir / "docs").glob("*.md")) if (comp_dir / "docs").is_dir() else []
        if comp_docs:
            docs_comps += 1
            docs_total += len(comp_docs)
        writeups += len(list((comp_dir / "cases").glob("*/WRITEUP*.md")))

        # 交付包
        for z in (comp_dir / "交付").glob("*.zip") if (comp_dir / "交付").is_dir() else []:
            try:
                stt = z.stat()
                exports.append({"path": z, "mtime": stt.st_mtime, "size": stt.st_size})
            except OSError:
                pass

        # inbox 待导入
        inbox = comp_dir / "inbox"
        if inbox.is_dir():
            inbox_pending += sum(1 for p in inbox.iterdir()
                                 if not p.name.startswith(".") and p.name != "README.md")

        # 提交记录
        sub = comp_dir / "submissions.jsonl"
        if sub.is_file():
            try:
                submissions += sum(1 for ln in sub.read_text(
                    encoding="utf-8", errors="replace").splitlines() if ln.strip())
            except OSError:
                pass

    exports.sort(key=lambda x: -x["mtime"])
    references = 0
    try:
        references = len(list((_core.ROOT / "solve-ai-ctf" / "references").glob("**/*.md")))
    except OSError:
        pass

    data = {
        "comps": comps,
        "challenges": challenges,
        "cases": cases_total,
        "bad_status": bad_status,
        "status_counts": status_counts,
        "events_total": events_total,
        "events_latest": events_latest,
        "docs_total": docs_total,
        "docs_comps": docs_comps,
        "writeups": writeups,
        "exports": exports,
        "inbox_pending": inbox_pending,
        "submissions": submissions,
        "references": references,
    }
    _SCAN_CACHE.update({"at": now, "data": data})
    return data


def _kb_stats() -> dict:
    """直接读检索日志，不 import kb_search（避免把检索器的副作用带进健康页）。

    注意日志落在 solve-ai-ctf/workbench-data/（kb_search.py 的 parents[1]），
    不是仓库根的 workbench-data/。
    """
    candidates = [_core.ROOT / "solve-ai-ctf" / "workbench-data" / "kb_queries.jsonl",
                  _core.ROOT / "workbench-data" / "kb_queries.jsonl"]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return {"total": 0, "hit": 0, "zero": 0, "rate": 0}
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.strip()][-500:]
    except OSError:
        return {"total": 0, "hit": 0, "zero": 0, "rate": 0}
    total = hit = 0
    for ln in lines:
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        total += 1
        if int(rec.get("hits") or 0) > 0:
            hit += 1
    return {"total": total, "hit": hit, "zero": total - hit,
            "rate": round(hit * 100 / max(total, 1))}


def _db_counts() -> dict:
    path = _core.ROOT / "workbench-data" / "leaderboard.db"
    out = {"ok": False, "teams": 0, "submissions": 0, "achievements": 0, "error": ""}
    if not path.is_file():
        out["error"] = "库未创建"
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        try:
            for table, key in (("teams", "teams"), ("submissions", "submissions"),
                               ("achievements", "achievements")):
                try:
                    out[key] = con.execute(f"select count(*) from {table}").fetchone()[0]
                except sqlite3.Error:
                    pass
            out["ok"] = True
        finally:
            con.close()
    except sqlite3.Error as exc:
        out["error"] = str(exc)[:80]
    return out


def _scripts_check() -> tuple[int, list[str]]:
    """逐个 compile()：抓语法错误，不执行、不导入。"""
    files = sorted(_core.SCRIPTS_DIR.glob("*.py"))
    bad = []
    for f in files:
        try:
            compile(f.read_text(encoding="utf-8", errors="replace"), str(f), "exec")
        except (SyntaxError, ValueError) as exc:
            bad.append(f"{f.name}: {type(exc).__name__}")
    return len(files), bad


# ------------------------------------------------------------------ 各模块判定

def _boot_at() -> float:
    try:
        return float(_core.RUNTIME.get("started_at") or _BOOT_AT)
    except (TypeError, ValueError):
        return _BOOT_AT


def _uptime_seconds() -> int:
    return max(0, int(time.time() - _boot_at()))


def _m_http(scan: dict) -> dict:
    port = _core.RUNTIME.get("port", 8787)
    exposed = bool(_core.RUNTIME.get("exposed"))
    host = _core.RUNTIME.get("host") or ("0.0.0.0" if exposed else "127.0.0.1")
    up = _uptime_seconds()
    devices_online = _core.RUNTIME.get("_devices_online")
    if devices_online is None:
        try:
            import wb_monitor
            devices_online = wb_monitor.snapshot().get("online_now", 0)
        except Exception:  # noqa: BLE001
            devices_online = 0
    return _mod(
        "http", "HTTP 服务", GROUPS[0], "online",
        f"{host}:{port}" + ("（局域网共享）" if exposed else "（仅本机）"),
        [{"label": "运行时长", "value": _ago(up)},
         {"label": "在线设备", "value": str(devices_online)}],
        probe="本进程（能渲染本页即在线）",
    )


def _m_scripts() -> dict:
    try:
        total, bad = _scripts_check()
    except OSError as exc:
        return _mod("scripts", "脚本层", GROUPS[0], "degraded",
                    f"脚本目录不可读：{exc}", probe="读取 scripts/*.py")
    # 自检结果闭环：跑过 self_test 且失败，脚本层就该显示注意（延迟导入避免循环）
    selftest_code = None
    try:
        import wb_actions
        selftest_code = wb_actions._SELFTEST.get("code")
    except Exception:  # noqa: BLE001
        pass
    extra = [{"label": "自检", "value": "未运行" if selftest_code is None
              else ("通过" if selftest_code == 0 else f"失败 {selftest_code}")}]
    if bad:
        return _mod("scripts", "脚本层", GROUPS[0], "degraded",
                    f"{len(bad)}/{total} 个脚本语法错误",
                    [{"label": "脚本", "value": str(total)},
                     {"label": "异常", "value": str(len(bad))}] + extra,
                    probe="逐个 compile() 语法校验",
                    hint="异常脚本：" + "、".join(bad[:3]))
    if selftest_code not in (None, 0):
        return _mod("scripts", "脚本层", GROUPS[0], "degraded",
                    f"{total} 个脚本可加载，但 self_test 失败（exit {selftest_code}）",
                    [{"label": "脚本", "value": str(total)},
                     {"label": "语法", "value": "通过"}] + extra,
                    probe="逐个 compile() + 最近一次 self_test 结果",
                    hint="点右上「运行自检」查看失败详情")
    return _mod("scripts", "脚本层", GROUPS[0], "online",
                f"{total} 个脚本全部可加载",
                [{"label": "脚本", "value": str(total)},
                 {"label": "语法", "value": "通过"}] + extra,
                probe="逐个 compile() 语法校验")


def _m_data(scan: dict) -> dict:
    comps = scan["comps"]
    bad = scan["bad_status"]
    if not comps:
        return _mod("data", "比赛数据", GROUPS[0], "off", "还没有初始化任何比赛",
                    probe="扫描 比赛/*/competition.json",
                    hint="到「比赛管理」新建，或把赛题包放进 inbox/ 半接入")
    if bad:
        return _mod("data", "比赛数据", GROUPS[0], "degraded",
                    f"{len(bad)} 个 case 状态异常",
                    [{"label": "比赛", "value": str(len(comps))},
                     {"label": "题目", "value": str(scan["challenges"])},
                     {"label": "异常", "value": str(len(bad))}],
                    probe="解析 cases/*/case.json 并校验状态白名单",
                    hint="、".join(bad[:3]))
    return _mod("data", "比赛数据", GROUPS[0], "online",
                f"{len(comps)} 场比赛 · {scan['challenges']} 题 · {scan['cases']} 个 case",
                [{"label": "比赛", "value": str(len(comps))},
                 {"label": "题目", "value": str(scan["challenges"])},
                 {"label": "case", "value": str(scan["cases"])}],
                probe="解析 cases/*/case.json 并校验状态白名单")


def _m_events(scan: dict) -> dict:
    if not scan["events_total"]:
        return _mod("events", "事件流", GROUPS[3], "off", "还没有事件记录",
                    probe="读取 比赛/*/events.jsonl",
                    hint="任何一次状态推进都会写入审计事件")
    mt, ago = scan["events_latest"]
    return _mod("events", "事件流", GROUPS[3], "online",
                f"最后事件 {ago} 前 · 共 {scan['events_total']} 条",
                [{"label": "事件", "value": str(scan["events_total"])},
                 {"label": "最后", "value": f"{ago} 前"}],
                probe="读取 比赛/*/events.jsonl（时间线同源）")


def _m_tasks() -> dict:
    ts = TASKS.list()
    running = sum(1 for t in ts if t.get("status") == "running")
    # 只把「最近的」异常算作需要关注：服务重启会让在跑的任务变 lost，
    # 那是历史噪声，不该让「系统概况」永远挂一个黄灯。
    cutoff = time.time() - 86400
    bad = []
    for t in ts:
        if t.get("status") not in ("failed", "lost", "error"):
            continue
        try:
            started = time.mktime(time.strptime(str(t.get("started"))[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            started = 0
        if started >= cutoff:
            bad.append(t)
    cmd = TASKS.agent_cmd
    detail = f"运行中 {running} · 累计 {len(ts)}" + (f" · 24h 内异常 {len(bad)}" if bad else "")
    metrics = [{"label": "运行中", "value": str(running)},
               {"label": "累计", "value": str(len(ts))},
               {"label": "24h 异常", "value": str(len(bad))}]
    if bad:
        return _mod("tasks", "任务执行器", GROUPS[1], "degraded", detail, metrics,
                    probe="读取 workbench-data/tasks.json",
                    hint=f"最近异常：{bad[-1].get('id')} {bad[-1].get('status')}（{bad[-1].get('slug', '?')}）")
    if not cmd:
        return _mod("tasks", "任务执行器", GROUPS[1], "off",
                    "未配置求解命令模板，仅演示 Agent 可用", metrics,
                    probe="读取 --agent-cmd / WB_AGENT_CMD",
                    hint="启动时加 --agent-cmd \"<你的 Agent 命令>\" 才能派发真实任务")
    return _mod("tasks", "任务执行器", GROUPS[1], "online", detail, metrics,
                probe="读取 workbench-data/tasks.json")


def _m_docker(docker: dict | None, sandbox: dict | None) -> dict:
    sb = sandbox or {}
    enabled = bool(sb.get("enabled"))
    images = sb.get("images") or {}
    running = sum(1 for t in TASKS.list()
                  if t.get("status") == "running" and t.get("sandbox"))
    if docker is None:
        return _mod("docker", "Docker 与沙箱", GROUPS[1], "degraded",
                    "尚未探测", probe="docker version")
    if docker.get("ok") is None:
        return _mod("docker", "Docker 与沙箱", GROUPS[1], "degraded",
                    docker.get("detail") or "Docker 探测预热中",
                    [{"label": "沙箱", "value": "开" if enabled else "关"}],
                    probe="docker version（复用 env_builder 的 WSL 前缀发现）",
                    hint="WSL 冷启动需要 1–3 分钟，稍后自动恢复")
    if not docker.get("ok"):
        return _mod("docker", "Docker 与沙箱", GROUPS[1], "degraded",
                    docker.get("detail") or "Docker 不可达",
                    [{"label": "沙箱", "value": "开" if enabled else "关"}],
                    probe="docker version",
                    hint="检查 Docker Desktop / WSL 是否启动")
    ver = docker.get("detail") or ""
    detail = f"引擎 {ver} · " + (f"沙箱开启（{len(images)} 类镜像）" if enabled
                                 else "沙箱关闭（宿主直跑）")
    return _mod("docker", "Docker 与沙箱", GROUPS[1],
                "online" if (enabled or not images) else "online",
                detail,
                [{"label": "引擎", "value": ver.split()[0] if ver else "—"},
                 {"label": "沙箱", "value": "开" if enabled else "关"},
                 {"label": "容器", "value": str(running)}],
                probe="docker version + workbench-data/sandbox.json")


def _m_submitter(scan: dict) -> dict:
    subs = scan["submissions"]
    autosubmit = _core.ROOT / "workbench-data" / "autosubmit.json"
    enabled = True
    try:
        cfg = read_json(autosubmit, {})
        if cfg:
            enabled = any(bool(v.get("enabled", True)) for v in cfg.values()
                          if isinstance(v, dict))
    except Exception:  # noqa: BLE001
        pass
    state = "online" if subs else "off"
    if subs:
        detail = f"已提交 {subs} 次 · 自动提交{'开' if enabled else '关'}"
    else:
        detail = "还没有提交记录（dry-run 与 live 均可用）"
    return _mod("submitter", "提交器", GROUPS[1], state, detail,
                [{"label": "提交", "value": str(subs)},
                 {"label": "自动", "value": "开" if enabled else "关"}],
                probe="读取 submissions.jsonl 与 autosubmit.json",
                hint="" if subs else "首次提交建议先 submit.dryrun 预览")


def _m_gateway(scan: dict) -> dict:
    exposed = bool(_core.RUNTIME.get("exposed"))
    try:
        import wb_gateway
        token = wb_gateway.read_join_token(_core.ROOT)
        gw = wb_gateway.directory(_core.ROOT)
        agents = [a for a in gw.get("agents", []) if not a.get("revoked")]
        online = [a for a in agents if 0 <= int(a.get("last_seen_minutes", 999)) < 15]
        claims = len(gw.get("claims") or [])
        handoffs = len(gw.get("handoffs") or [])
    except Exception as exc:  # noqa: BLE001
        return _mod("gateway", "协作网关", GROUPS[2], "degraded",
                    f"名册读取失败：{type(exc).__name__}", probe="读取 agent-gateway.json")
    metrics = [{"label": "在线 AI", "value": f"{len(online)}/{len(agents)}"},
               {"label": "认领", "value": str(claims)},
               {"label": "交接", "value": str(handoffs)}]
    if not exposed:
        return _mod("gateway", "协作网关", GROUPS[2], "off",
                    "本机模式，其他 AI 无法接入", metrics,
                    probe="RUNTIME.exposed + 心跳名册",
                    hint="AI 看板 →「让其他 AI 接入」一键开启局域网共享")
    if not token:
        return _mod("gateway", "协作网关", GROUPS[2], "degraded",
                    "已共享，但入网码未生成", metrics,
                    probe="RUNTIME.exposed + join-token.txt",
                    hint="在接入面板点「生成入网码」")
    if not online:
        return _mod("gateway", "协作网关", GROUPS[2], "degraded",
                    "已共享，暂无 AI 在线", metrics,
                    probe="RUNTIME.exposed + 心跳名册",
                    hint="把接入指令发给同伴；心跳有效期 15 分钟")
    return _mod("gateway", "协作网关", GROUPS[2], "online",
                f"共享开启 · {len(online)} 个 AI 在线", metrics,
                probe="RUNTIME.exposed + 心跳名册", link="?tab=board2")


def _m_netdev() -> dict:
    try:
        import wb_monitor
        snap = wb_monitor.snapshot()
    except Exception:  # noqa: BLE001
        return _mod("netdev", "接入设备", GROUPS[2], "degraded", "监控模块不可用",
                    probe="wb_monitor 内存计数")
    devices = snap.get("devices") or []
    hits = sum(int(d.get("hits") or 0) for d in devices)
    return _mod("netdev", "接入设备", GROUPS[2], "online",
                f"{snap.get('online_now', 0)} 台在线 · 累计 {hits} 次请求",
                [{"label": "在线", "value": str(snap.get("online_now", 0))},
                 {"label": "跟踪 IP", "value": str(snap.get("total_tracked", 0))},
                 {"label": "请求", "value": str(hits)}],
                probe="Handler 每请求记账（2 分钟窗口）", link="?tab=connections")


def _m_model_gw(usage: dict | None) -> dict:
    u = usage or {}
    tokens = int(u.get("active_tokens") or 0)
    reqs = int(u.get("total_requests") or 0)
    byts = int(u.get("total_bytes") or 0)
    metrics = [{"label": "令牌", "value": str(tokens)},
               {"label": "请求", "value": str(reqs)},
               {"label": "流量", "value": _human_size(byts)}]
    if not tokens:
        return _mod("model_gw", "模型网关", GROUPS[2], "off",
                    "无活跃令牌（沙箱任务才会签发）", metrics,
                    probe="TASKS._gateway_tokens 内存表",
                    hint="派发沙箱任务后自动生效，用于转发模型请求并记账")
    return _mod("model_gw", "模型网关", GROUPS[2], "online",
                f"{tokens} 个令牌在用 · {reqs} 次请求", metrics,
                probe="TASKS._gateway_tokens 内存表")


def _m_kb(scan: dict) -> dict:
    stats = _kb_stats()
    refs = scan["references"]
    metrics = [{"label": "查询", "value": str(stats["total"])},
               {"label": "命中率", "value": f"{stats['rate']}%"},
               {"label": "参考", "value": str(refs)}]
    if not refs and not stats["total"]:
        return _mod("kb", "知识库", GROUPS[3], "off", "还没有参考条目与检索记录",
                    metrics, probe="references/ 与 kb_queries.jsonl",
                    hint="把题解 md 放进 references/ 即可被检索到")
    if stats["total"] >= 20 and stats["rate"] < 60:
        return _mod("kb", "知识库", GROUPS[3], "degraded",
                    f"检索命中率偏低（{stats['rate']}%，{stats['zero']} 次零命中）",
                    metrics, probe="统计最近 500 次检索的 hits",
                    hint="零命中最多的关键词就是补洞候选（知识库页可看清单）")
    return _mod("kb", "知识库", GROUPS[3], "online",
                f"{refs} 篇参考 · 命中率 {stats['rate']}%", metrics,
                probe="references/ 与 kb_queries.jsonl")


def _m_docs(scan: dict) -> dict:
    total = scan["docs_total"]
    metrics = [{"label": "文档", "value": str(total)},
               {"label": "题解", "value": str(scan["writeups"])},
               {"label": "覆盖", "value": f"{scan['docs_comps']} 场"}]
    if not total and not scan["writeups"]:
        return _mod("docs", "文档与题解", GROUPS[3], "off", "还没有比赛文档",
                    metrics, probe="扫描 比赛/*/docs/*.md 与 cases/*/WRITEUP*.md",
                    hint="解题完成后 case.writeup 会自动落一篇")
    return _mod("docs", "文档与题解", GROUPS[3], "online",
                f"{total} 篇文档 · {scan['writeups']} 篇题解", metrics,
                probe="扫描 比赛/*/docs/*.md 与 cases/*/WRITEUP*.md", link="?tab=docs")


def _m_export(scan: dict) -> dict:
    exports = scan["exports"]
    if not exports:
        return _mod("export", "交付打包", GROUPS[3], "off", "还没有生成交付包",
                    [{"label": "包", "value": "0"}],
                    probe="扫描 比赛/*/交付/*.zip",
                    hint="文档页右侧「打包交付」一键生成（含复盘报告与题解）")
    latest = exports[0]
    total_size = sum(e["size"] for e in exports)
    return _mod("export", "交付打包", GROUPS[3], "online",
                f"最近 {_mtime_text(latest['path'])} · {_human_size(latest['size'])}",
                [{"label": "包", "value": str(len(exports))},
                 {"label": "占用", "value": _human_size(total_size)}],
                probe="扫描 比赛/*/交付/*.zip", link="?tab=docs")


def _m_board(scan: dict) -> dict:
    db = _db_counts()
    metrics = [{"label": "队伍", "value": str(db["teams"])},
               {"label": "提交", "value": str(db["submissions"])},
               {"label": "成就", "value": str(db["achievements"])}]
    if not db["ok"]:
        return _mod("board", "积分与成就", GROUPS[3], "degraded",
                    f"排行榜库不可用：{db['error']}", metrics,
                    probe="只读打开 leaderboard.db",
                    hint="调用一次 achievement.check 会自动建表")
    return _mod("board", "积分与成就", GROUPS[3], "online",
                f"{db['teams']} 支队伍 · {db['achievements']} 个成就解锁", metrics,
                probe="只读打开 leaderboard.db", link="?tab=leaderboard")


def _m_inbox(scan: dict) -> dict:
    pending = scan["inbox_pending"]
    if pending:
        return _mod("inbox", "半接入 inbox", GROUPS[3], "degraded",
                    f"{pending} 个附件待导入",
                    [{"label": "待导入", "value": str(pending)}],
                    probe="统计 比赛/*/inbox/ 条目",
                    hint="到「比赛管理 → 半接入」批量导入为一题")
    return _mod("inbox", "半接入 inbox", GROUPS[3], "online", "无待导入条目",
                [{"label": "待导入", "value": "0"}],
                probe="统计 比赛/*/inbox/ 条目")


# ------------------------------------------------------------------ 汇总

def modules_snapshot(*, force: bool = False, docker: dict | None = None,
                     sandbox: dict | None = None, usage: dict | None = None) -> dict:
    now = time.time()
    if not force and now - _CACHE["at"] < _CACHE_TTL and _CACHE["data"]:
        return _CACHE["data"]

    scan = _scan(force=force)
    modules = [
        _m_http(scan), _m_scripts(), _m_data(scan), _m_events(scan), _m_tasks(),
        _m_docker(docker, sandbox), _m_submitter(scan),
        _m_gateway(scan), _m_netdev(), _m_model_gw(usage),
        _m_kb(scan), _m_docs(scan), _m_export(scan), _m_board(scan), _m_inbox(scan),
    ]
    online = sum(1 for m in modules if m["state"] == "online")
    degraded = sum(1 for m in modules if m["state"] == "degraded")
    off = sum(1 for m in modules if m["state"] == "off")
    if degraded:
        headline = f"{degraded} 项需要关注"
        overall = "warn"
    elif off:
        headline = f"全部正常 · {off} 项未启用"
        overall = "ok"
    else:
        headline = "全部功能在线"
        overall = "ok"

    result = {
        "modules": modules,
        "groups": GROUPS,
        "summary": {"online": online, "degraded": degraded, "off": off,
                    "total": len(modules), "headline": headline, "state": overall},
        "attention": [{"key": m["key"], "name": m["name"], "state": m["state"],
                       "hint": m["hint"] or m["detail"]}
                      for m in modules if m["state"] != "online"],
        "overview": {
            "port": _core.RUNTIME.get("port", 8787),
            "host": _core.RUNTIME.get("host", "127.0.0.1"),
            "exposed": bool(_core.RUNTIME.get("exposed")),
            "base_url": _core.RUNTIME.get("base_url", ""),
            "uptime": _ago(_uptime_seconds()),
            "uptime_seconds": _uptime_seconds(),
            "server_time": _now_text(),
        },
    }
    _CACHE.update({"at": now, "data": result})
    return result
