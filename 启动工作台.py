#!/usr/bin/env python3
"""一键启动本地工作台（ROOT 固定为本仓库，比赛数据在 比赛/ 下）。

用法：
    python 启动工作台.py                    # 默认加载 demo-env 演示比赛
    python 启动工作台.py "比赛/xxx"          # 位置参数指定比赛
    python 启动工作台.py --competition "比赛/xxx" --agent-cmd "..."   # 服务端旗标原样透传
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
HERE = REPO / "workbench"
spec = importlib.util.spec_from_file_location("wb_server", HERE / "server.py")
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)
wb.configure(root=REPO, scripts=REPO / "scripts", static=HERE / "static")

user = sys.argv[1:]
argv = ["server.py", "--port", "8787", "--open"]
if user and not user[0].startswith("--"):          # 旧用法：首个位置参数 = 比赛目录
    argv += ["--competition", user[0]]
    user = user[1:]
if "--competition" not in argv and "--competition" not in user:
    argv += ["--competition", "demo-env"]
sys.argv = argv + user                              # wb_http.main() 直接解析 sys.argv
raise SystemExit(wb.main())
