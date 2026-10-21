#!/usr/bin/env python3
"""R55-K2：kb 检索统计桥接——wb_routes 经 run_script 调用 kb_search.stats_data。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent


def load() -> dict:
    spec = importlib.util.spec_from_file_location("kb_mod", _here / "kb_search.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kb_mod"] = mod
    spec.loader.exec_module(mod)
    return mod.stats_data()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--last", type=int, default=500)
    args = ap.parse_args()
    print(json.dumps(load(), ensure_ascii=False))
