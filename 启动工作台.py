#!/usr/bin/env python3
"""一键启动本地工作台（ROOT 固定为本仓库，比赛数据在 比赛/ 下）。"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
HERE = REPO / "workbench"
spec = importlib.util.spec_from_file_location("wb_server", HERE / "server.py")
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)
wb.configure(root=REPO, scripts=REPO / "scripts", static=HERE / "static")
argv = ["server.py", "--port", "8787", "--open"]
if len(sys.argv) > 1:
    argv += ["--competition", sys.argv[1]]
else:
    argv += ["--competition", "demo-env"]
raise SystemExit(wb.main())
