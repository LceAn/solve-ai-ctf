#!/usr/bin/env python3
"""一键启动本地工作台（ROOT 固定为本仓库，比赛数据在 比赛/ 下）。

用法：
    python 启动工作台.py                    # 自动选第一个已初始化的比赛（比赛/*/competition.json）
    python 启动工作台.py "比赛/xxx"          # 位置参数指定比赛
    python 启动工作台.py --lan               # 局域网共享：其他 AI 可用入网码自助接入
    python 启动工作台.py --competition "比赛/xxx" --agent-cmd "..."   # 服务端旗标原样透传
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
HERE = REPO / "workbench"
# 数据根兼容两种布局：
#   ① 仓库内置数据：solve-ai-ctf/比赛/
#   ② 工作区布局：CTF/比赛/ + CTF/solve-ai-ctf/（当前机器）
DATA_ROOT = REPO
if not (REPO / "比赛").is_dir() and (REPO.parent / "比赛").is_dir():
    DATA_ROOT = REPO.parent
spec = importlib.util.spec_from_file_location("wb_server", HERE / "server.py")
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)
wb.configure(root=DATA_ROOT, scripts=REPO / "scripts", static=HERE / "static")

user = sys.argv[1:]
argv = ["server.py", "--port", "8787", "--open"]
if user and not user[0].startswith("--"):          # 旧用法：首个位置参数 = 比赛目录
    argv += ["--competition", user[0]]
    user = user[1:]
if "--competition" not in argv and "--competition" not in user:
    # 不再硬编码 demo-env（多数环境没有该目录，一启动就 unknown competition）：
    # 自动挑第一个已初始化的比赛，保持"双击即用"。
    comps_dir = DATA_ROOT / "比赛"
    pick = ""
    if comps_dir.is_dir():
        for d in sorted(comps_dir.iterdir(), key=lambda p: p.name):
            if d.is_dir() and (d / "competition.json").is_file():
                pick = d.name
                break
    if pick:
        argv += ["--competition", pick]
sys.argv = argv + user                              # wb_http.main() 直接解析 sys.argv
raise SystemExit(wb.main())
