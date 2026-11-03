"""wb_banner —— 启动横幅（ANSI 颜色；非 TTY 自动降级为纯文本）。

放在这里而不是 wb_http：启动输出会越来越长（地址/数据/比赛/沙箱/鉴权），
单独成模块便于调整排版，也避免把 IO 细节塞进路由代码。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

DIM = "\033[90m"
BOLD = "\033[1m"
WHITE = "\033[97m"
CYAN = "\033[1;36m"
BLUE = "\033[1;34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def _enable_vt() -> bool:
    """Windows 控制台启用 ANSI 转义；非 TTY（重定向到日志）返回 False。"""
    if not sys.stdout.isatty():
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return True
    except Exception:  # noqa: BLE001
        return False


def _version() -> str:
    """从 CHANGELOG 取最新版本号；有 Unreleased 段则标 +dev。"""
    try:
        text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text(
            encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("## [v"):
                ver = line.split("[", 1)[1].split("]", 1)[0]
                return ver + ("+dev" if "## [Unreleased]" in text[:400] else "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def print_banner(*, url: str, root: Path, comps: list[dict], default: str = "",
                 sandbox_enabled: bool = False, token: bool = False,
                 agent_cmd: bool = False, exposed: bool = False,
                 lan_urls: Iterable[str] = ()) -> None:
    color = _enable_vt()

    def c(code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if color else text

    ver = _version()
    print()
    print("  " + c(BOLD + BLUE, "CTF Workbench") + (f"  {c(DIM, ver)}" if ver else ""))
    print("  " + c(DIM, "local-first · multi-agent · 本地工作台"))
    print("  " + c(DIM, "─" * 52))
    print()

    def pad(label: str, width: int = 4) -> str:
        """按显示列宽补齐（中文占 2 列），保证各行值左对齐。"""
        cells = sum(2 if ord(ch) > 0x2E80 else 1 for ch in label)
        return label + " " * max(0, width - cells)

    def row(label: str, value: str) -> None:
        print(f"  {c(DIM, pad(label))}  {value}")

    row("地址", c(CYAN, url))
    for i, lan in enumerate(lan_urls):
        row("共享" if i == 0 else "", c(CYAN, lan))
    row("数据", c(WHITE, str(root)))
    if comps:
        current = default or str(comps[0].get("dir") or "")
        entry = next((x for x in comps if x.get("dir") == current), None)
        detail = f"{len(comps)} 场 · 默认 {current}"
        if entry and entry.get("challenges"):
            detail += f"（{entry['challenges']} 题）"
        row("比赛", c(WHITE, detail))
    else:
        row("比赛", c(YELLOW, "暂无 — 到「比赛管理」初始化"))

    row("沙箱", c(GREEN, "已启用") if sandbox_enabled else c(DIM, "未启用（宿主直跑）"))
    if token:
        row("鉴权", c(GREEN, "已启用令牌（Agent 请求带 Bearer）"))
    elif exposed:
        row("鉴权", c(RED, "⚠ 对外绑定但未设令牌 —— 同网段可读比赛数据"))
    else:
        row("鉴权", c(DIM, "本机访问，无需令牌"))
    row("求解", c(GREEN, "已配置命令模板") if agent_cmd else c(YELLOW, "未配置（可先用演示 Agent）"))

    print()
    print("  " + c(DIM, "Ctrl+C 停止服务 · 关闭窗口同样停止"))
    print(flush=True)
