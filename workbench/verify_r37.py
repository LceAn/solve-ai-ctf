#!/usr/bin/env python3
"""R37 一次性验证：warroom 增强（Flags 列 / 候选计数 / 环境镜像段）。"""
import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("comp_mod", HERE.parent / "scripts" / "competition.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

tmp = Path(tempfile.mkdtemp(prefix="dash_verify_"))
comp = tmp / "dd"
args = argparse.Namespace(comp_dir=comp, name="D", scope="", competition_id="",
                          platform_config=None,
                          rate_limit="min_interval_seconds=0,max_per_window=20,window_seconds=300",
                          force=False, output=None)
m.cmd_init(args)

subprocess.run([sys.executable, str(HERE.parent / "scripts" / "competition.py"), "add-challenge",
                str(comp), "--name", "C1", "--category", "misc", "--slug", "c1"],
               capture_output=True)
case = comp / "cases/c1/case.json"
d = json.loads(case.read_text(encoding="utf-8"))
d["candidates"].append({"id": "C0001", "value": "flag{x}", "status": "accepted"})
case.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
env = comp / "env/gen"
env.mkdir(parents=True, exist_ok=True)
(env / ".built.json").write_text(json.dumps(
    {"schema": 1, "images": {"c1": {"image": "ctf-dd-c1:1"}}}), encoding="utf-8")
m.cmd_dashboard(argparse.Namespace(comp_dir=comp, output=None))

html = (comp / "warroom.html").read_text(encoding="utf-8")
checks = {"Flags列": "Flags" in html, "镜像段": "题目环境镜像" in html,
          "镜像tag": "ctf-dd-c1:1" in html, "候选计数": "1/1 接受" in html}
print(checks)
import shutil
shutil.rmtree(tmp, ignore_errors=True)
assert all(checks.values())
print("R37 verified")
