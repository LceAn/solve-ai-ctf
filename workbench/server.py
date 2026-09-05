"""CTF Workbench 服务层 facade（N-06 拆包：逻辑在 wb_core/wb_tasks/wb_actions/wb_sandbox/wb_http）。

用法不变：
    python solve-ai-ctf/workbench/server.py [--port 8787] [--competition "比赛/xxx"] [--open]
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import env_builder as envb  # noqa: E402,F401
import wb_actions  # noqa: E402,F401
import wb_core as _core  # noqa: E402
import wb_http  # noqa: E402,F401
import wb_routes  # noqa: E402,F401
import wb_sandbox  # noqa: E402,F401
import wb_tasks  # noqa: E402,F401
from wb_actions import ACTIONS  # noqa: E402,F401
from wb_core import (configure, prune_task_logs, resolve_competition, safe_join)  # noqa: E402,F401
from wb_http import Handler, main  # noqa: E402,F401
from wb_sandbox import gateway_usage, sandbox_config, sandbox_status  # noqa: E402,F401
from wb_tasks import (TASKS, board_data, docker_stop_container,  # noqa: E402,F401
                      split_cmd_template, validate_bind_security)

_MODULES = (_core, wb_tasks, wb_actions, wb_sandbox, wb_http, wb_routes, envb)


def __getattr__(name: str):
    """动态转发可变全局与未显式导出的名字（configure 之后的取值始终新鲜）。"""
    for module in _MODULES:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module 'server' has no attribute {name!r}")


if __name__ == "__main__":
    raise SystemExit(main())
