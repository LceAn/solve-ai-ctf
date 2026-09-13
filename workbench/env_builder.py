#!/usr/bin/env python3
"""env_builder —— 比赛/题目级 Docker 环境构建器。

把声明式 env spec（YAML）渲染为 Dockerfile / compose.yaml，构建 L2 比赛层与
L3 题目层镜像，并把产物登记到 env/gen/.built.json——运行时组件（server.py）
只读这个 JSON，不解析 YAML，保持零 pip 依赖。

层级（见 workbench/docker/COMPETITION_ENV_DESIGN.md）：
  L0 ctfbox-base          通用底座
  L1 ctfbox-<category>    七题型层
  L2 ctf-<comp>           比赛层（可选）
  L3 ctf-<comp>-<slug>    题目层（按需）

子命令：
  build    构建 L2/L3（默认跳过"无定制"的题目 spec，--force 强制；--dry-run 只渲染不构建）
  status   spec / 镜像 / 漂移一览（--json 机器可读）
  verify   在构建出的镜像里跑探针命令矩阵（工具存在性 + 版本断言）
  export   docker save 导出比赛镜像（--with-spec 附带 env 归档）
  preheat  预热 L0/L1 底座与题型层镜像
  render   打印渲染产物（Dockerfile / compose.yaml），调试用

安全模型：
  - spec 等同代码（build.pre/post 是本机构建的 shell），必须进 git 走 diff 审查
  - assets[] 强制 sha256（文件）且路径不得逃出 env/assets/<slug>/
  - docker build/run 一律 argv 列表拼装，不走宿主 shell
  - 服务编排（services）网络默认 internal，端口只绑 127.0.0.1
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

API_VERSION = "ctfbox/v1"
BUILT_SCHEMA = 1
HERE = Path(__file__).resolve().parent
DOCKER_DIR = HERE / "docker"
L0_TAG = "ctfbox-base:0.1.0"
# 与 server.py SANDBOX_DEFAULTS.images 保持一致的题型层 tag（版本随 docker/README 演进）
CATEGORY_IMAGES = {
    "misc": "ctfbox-misc:0.1.0",
    "crypto": "ctfbox-crypto:0.1.0",
    "pwn": "ctfbox-pwn:0.1.0",
    "web": "ctfbox-web:0.1.0",
    "reverse": "ctfbox-reverse:0.1.0",
    "forensics": "ctfbox-forensics:0.1.0",
    "ai": "ctfbox-ai:0.1.0",
}
# 题型 → 知识库 playbook（sync-solver 生成 skill 包用）
CATEGORY_PLAYBOOK = {
    "pwn": "playbooks-pwn.md",
    "web": "playbooks-web-ai.md",
    "ai": "playbooks-web-ai.md",
    "crypto": "playbooks-crypto-reverse.md",
    "reverse": "playbooks-crypto-reverse.md",
    "forensics": "playbooks-forensics-misc.md",
    "misc": "playbooks-forensics-misc.md",
}
CATEGORY_SKILL_DESC = {
    "pwn": "二进制利用题型方法论：ELF 分诊、glibc 堆、ROP、seccomp 绕过与可靠性工程",
    "web": "Web/AI 题型方法论：解析器差异、鉴权与状态、提示注入与 LLM 攻击面",
    "ai": "AI 安全题型方法论：提示注入、agent 攻防、模型输出不可信下的验证策略",
    "crypto": "密码/逆向题型方法论：RSA/PRNG/对称密码与现代反编译工作流",
    "reverse": "密码/逆向题型方法论：静态反编译、脱壳、native 与移动端逆向",
    "forensics": "取证/Misc 题型方法论：PCAP、文件系统、隐写与编码链",
    "misc": "取证/Misc 题型方法论：杂项解题、编码链与 puzzles 的通用路径",
}
KNOWN_CATEGORIES = set(CATEGORY_IMAGES)
# slug / 文件名安全字符：competition.py slugify 产生下划线，fetch 产生 c<id>
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# verify 探针矩阵（与各题型层 Dockerfile 实际安装的工具对应；可被 --probe 追加）
PROBES = {
    "common": ["python --version"],
    "pwn": ["gdb --version | head -1", 'python -c "import pwn; print(pwn.__version__)"'],
    "web": ['python -c "import requests, bs4"', "whatweb --version"],
    "crypto": ['python -c "import gmpy2, Crypto, z3"'],
    "reverse": ["objdump --version | head -1", 'python -c "import capstone"'],
    "forensics": ["binwalk --help", 'python -c "import scapy"'],
    "misc": ['python -c "import Crypto, gmpy2, requests, PIL"'],
    "ai": ['python -c "import openai, anthropic, tiktoken"'],
}


class SpecError(ValueError):
    """spec 解析/校验失败。"""


def log(msg: str) -> None:
    print(msg, flush=True)


# ================================================================ YAML 子集
#
# 内置解析器只覆盖 env spec 用到的特性（嵌套映射 / 列表 / 块标量 | / 单行流
# [] {} / 注释 / 引号），装了 PyYAML 时优先用 PyYAML，两实现由测试做一致性回归。


def _strip_comment(line: str) -> str:
    """去掉行尾注释（# 前须是行首或空白，引号内的 # 不算）。"""
    out: list[str] = []
    quote: str | None = None
    prev = ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote and prev != "\\":
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#" and (not out or prev in " \t"):
            break
        else:
            out.append(ch)
        prev = ch
    return "".join(out).rstrip()


def _find_key_sep(s: str) -> int:
    """返回 key 与 value 的分隔冒号位置（后跟空白或行尾，且不在引号内）；无则 -1。"""
    quote: str | None = None
    prev = ""
    for i, ch in enumerate(s):
        if quote:
            if ch == quote and prev != "\\":
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(s) or s[i + 1] in " \t"):
            return i
        prev = ch
    return -1


def _split_flow(s: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _scalar(text: str):
    t = text.strip()
    if t == "":
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [_scalar(p) for p in _split_flow(inner)]
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1].strip()
        d: dict = {}
        for part in _split_flow(inner):
            pos = _find_key_sep(part)
            if pos < 0:
                raise SpecError(f"flow mapping 项缺少冒号：{part!r}")
            d[part[:pos].strip().strip("\"'")] = _scalar(part[pos + 1:])
        return d
    low = t.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def _read_block_scalar(lines: list[tuple[int, str, int]], i: int, key_indent: int,
                       style: str) -> tuple[str, int]:
    """读取 | / |- 块标量；i 指向 key 行的下一行。保留内部空行与 # 注释（shell 脚本）。"""
    n = len(lines)
    buf: list[str] = []
    content_indent: int | None = None
    while i < n:
        raw = lines[i][1]
        stripped = raw.strip()
        ind = len(raw) - len(raw.lstrip(" "))
        if stripped == "":
            buf.append("")
            i += 1
            continue
        if ind <= key_indent:
            break
        if content_indent is None:
            content_indent = ind
        if ind < content_indent:
            break
        buf.append(" " * (ind - content_indent) + stripped)
        i += 1
    while buf and buf[-1] == "":
        buf.pop()
    text = "\n".join(buf)
    if style in ("|", "|+"):
        text += "\n"
    return text, i


def _read_pair(lines: list[tuple[int, str, int]], i: int, rest: str, key_indent: int):
    """读取 `key: <rest>` 的值；i 指向 key 行的下一行。返回 (value, next_i)。"""
    n = len(lines)
    if rest in ("|", "|-", "|+", ">", ">-", ">+"):
        return _read_block_scalar(lines, i, key_indent, rest)
    if rest == "":
        j = i
        while j < n and _strip_comment(lines[j][1]).strip() == "":
            j += 1
        if j < n and lines[j][0] > key_indent:
            return _parse_block(lines, j, lines[j][0])
        return None, i
    return _scalar(rest), i


def _parse_block(lines: list[tuple[int, str, int]], i: int, indent: int):
    n = len(lines)
    while i < n and _strip_comment(lines[i][1]).strip() == "":
        i += 1
    if i >= n:
        return None, i
    ind, raw, _ = lines[i]
    content = _strip_comment(raw).strip()
    if ind < indent or content == "---":
        return None, i
    if content == "-" or content.startswith("- "):
        return _parse_list(lines, i, ind)
    if _find_key_sep(content) >= 0:
        return _parse_map(lines, i, ind)
    return _scalar(content), i + 1


def _parse_map(lines: list[tuple[int, str, int]], i: int, indent: int):
    out: dict = {}
    n = len(lines)
    while i < n:
        ind, raw, _ = lines[i]
        content = _strip_comment(raw).strip()
        if content == "" or content == "---":
            i += 1
            continue
        if ind < indent:
            break
        if ind > indent:
            raise SpecError(f"第 {lines[i][2]} 行：缩进异常（期望 {indent} 个空格）")
        if content == "-" or content.startswith("- "):
            break
        pos = _find_key_sep(content)
        if pos < 0:
            raise SpecError(f"第 {lines[i][2]} 行：期望 'key: value'，读到 {content!r}")
        key = content[:pos].strip().strip("\"'")
        value, i = _read_pair(lines, i + 1, content[pos + 1:].strip(), indent)
        out[key] = value
    return out, i


def _parse_list(lines: list[tuple[int, str, int]], i: int, indent: int):
    items: list = []
    n = len(lines)
    while i < n:
        ind, raw, _ = lines[i]
        content = _strip_comment(raw).strip()
        if content == "" or content == "---":
            i += 1
            continue
        if ind < indent:
            break
        if ind > indent:
            raise SpecError(f"第 {lines[i][2]} 行：列表项缩进异常")
        if not (content == "-" or content.startswith("- ")):
            break
        if content == "-":
            value, i = _parse_block(lines, i + 1, indent + 1)
            items.append(value)
            continue
        rest = content[2:].strip()
        pos = _find_key_sep(rest)
        if pos < 0:
            items.append(_scalar(rest))
            i += 1
            continue
        # "- key: value" 起头的字典项；后续键在 indent+2 处续行
        d: dict = {}
        key = rest[:pos].strip().strip("\"'")
        value, i = _read_pair(lines, i + 1, rest[pos + 1:].strip(), indent + 2)
        d[key] = value
        while i < n:
            ind2, raw2, _ = lines[i]
            c2 = _strip_comment(raw2).strip()
            if c2 == "" or c2 == "---":
                i += 1
                continue
            if ind2 < indent + 2:
                break
            if ind2 > indent + 2:
                raise SpecError(f"第 {lines[i][2]} 行：字典项续行缩进异常")
            p2 = _find_key_sep(c2)
            if p2 < 0:
                raise SpecError(f"第 {lines[i][2]} 行：期望 'key: value'，读到 {c2!r}")
            k2 = c2[:p2].strip().strip("\"'")
            v2, i = _read_pair(lines, i + 1, c2[p2 + 1:].strip(), indent + 2)
            d[k2] = v2
        items.append(d)
    return items, i


def parse_yaml_text(text: str):
    """解析 env spec 的 YAML 子集（零依赖回退实现）。"""
    lines: list[tuple[int, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        indent_str = raw[: len(raw) - len(raw.lstrip(" "))]
        if "\t" in indent_str:
            raise SpecError(f"第 {lineno} 行：tab 缩进不受支持（请用空格）")
        lines.append((len(indent_str), raw, lineno))
    value, _ = _parse_block(lines, 0, 0)
    return {} if value is None else value


def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return "{}" if not v else "{}"
    if isinstance(v, list):
        return "[]" if not v else "[]"
    s = str(v)
    if "\n" in s:
        body = "\n".join("  " + ln for ln in s.rstrip("\n").split("\n"))
        return "|\n" + body
    risky = (s == "" or s != s.strip()
             or re.search(r"[:#{}\[\],&*?|>%@`\"'!]", s)
             or s.lower() in ("true", "false", "null", "yes", "no", "on", "off")
             or re.fullmatch(r"[-+.\d]+", s) is not None)
    return json.dumps(s, ensure_ascii=False) if risky else s


def yaml_dump(obj, indent: int = 0) -> str:
    """把 dict/list 序列化为 compose 用的 YAML（值一律走安全标量规则）。"""
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(yaml_dump(v, indent + 1))
            elif isinstance(v, dict):
                lines.append(f"{pad}{k}: {{}}")
            elif isinstance(v, list):
                lines.append(f"{pad}{k}: []")
            else:
                lines.append(f"{pad}{k}: {_yaml_scalar(v)}")
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict) and v:
                sub = yaml_dump(v, indent + 1).lstrip()
                first, _, rest = sub.partition("\n")
                lines.append(f"{pad}- {first}")
                if rest:
                    lines.append(rest)
            else:
                lines.append(f"{pad}- {_yaml_scalar(v)}")
    return "\n".join(lines)


def load_yaml_file(path: Path) -> tuple[dict, str]:
    """读 YAML：优先 PyYAML，缺失时用内置子集解析器。返回 (data, parser_name)。"""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ImportError:
        data = parse_yaml_text(text)
        if not isinstance(data, dict):
            raise SpecError(f"{path.name}: 顶层必须是映射")
        return data, "mini"
    try:
        data = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        raise SpecError(f"{path.name}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise SpecError(f"{path.name}: 顶层必须是映射")
    return data, "pyyaml"


# ================================================================ spec 基础


def deep_merge(base: dict, override: dict) -> dict:
    """题目 spec 覆盖比赛 spec：dict 递归合并，其余类型整体替换，None 视为未设置。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def normalize_name(s: str) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", str(s).lower()).strip("-")
    name = re.sub(r"-{2,}", "-", name)
    return name[:40].strip("-") or "comp"


def spec_hash(spec: dict) -> str:
    blob = json.dumps(spec, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def image_tag(comp_name: str, slug: str, s_hash: str) -> str:
    return f"ctf-{normalize_name(comp_name)}-{normalize_name(slug)}:{time.strftime('%Y%m%d')}-{s_hash[:8]}"


def comp_image_tag(comp_name: str, s_hash: str) -> str:
    return f"ctf-{normalize_name(comp_name)}:{time.strftime('%Y%m%d')}-{s_hash[:8]}"


def env_paths(comp_dir: Path) -> dict[str, Path]:
    env = comp_dir / "env"
    return {
        "env": env,
        "comp_yaml": env / "comp.yaml",
        "challenges": env / "challenges",
        "assets": env / "assets",
        "gen": env / "gen",
        "built": env / "gen" / ".built.json",
    }


def list_challenge_specs(comp_dir: Path) -> list[Path]:
    return sorted((comp_dir / "env" / "challenges").glob("*.yaml"))


def load_specs(comp_dir: Path) -> dict:
    """读比赛级 + 全部题目 spec。返回 {comp, challenges: {slug: spec}, problems: []}。"""
    paths = env_paths(comp_dir)
    result: dict = {"comp": {}, "challenges": {}, "problems": [],
                    "comp_spec_file": "", "parser": "mini", "has_env": paths["comp_yaml"].exists()}
    if not paths["comp_yaml"].exists():
        return result
    try:
        comp_spec, parser = load_yaml_file(paths["comp_yaml"])
        result["comp"], result["parser"], result["comp_spec_file"] = comp_spec, parser, "comp.yaml"
    except SpecError as exc:
        result["problems"].append(f"comp.yaml: {exc}")
    for path in list_challenge_specs(comp_dir):
        try:
            spec, _ = load_yaml_file(path)
        except SpecError as exc:
            result["problems"].append(f"{path.name}: {exc}")
            continue
        slug = str(spec.get("slug") or path.stem)
        if not isinstance(spec, dict):
            result["problems"].append(f"{path.name}: 顶层必须是映射")
            continue
        spec = dict(spec)
        spec.setdefault("slug", slug)
        result["challenges"][slug] = spec
    return result


def merged_spec(comp_spec: dict, chall_spec: dict) -> dict:
    return deep_merge(comp_spec, chall_spec)


def base_for(comp_name: str, slug: str, category: str, chall_spec: dict,
             built: dict | None = None) -> str:
    """FROM 目标：题目 spec 显式钉死 > 已构建的 L2 > 题型层默认。

    只看题目 spec 自己的 base（不接收 merged）——comp.yaml 的 base 仅用于构建
    L2 比赛层，绝不作为题目缺省，否则 web 题会继承 misc 底座、丢掉题型工具。
    """
    explicit = str((chall_spec.get("base") or "")).strip()
    if explicit:
        return explicit
    comp_rec = (built or {}).get("comp") or {}
    if comp_rec.get("image"):
        return str(comp_rec["image"])
    return CATEGORY_IMAGES.get(category, L0_TAG)


def spec_is_empty(spec: dict) -> bool:
    """没有定制内容（纯 base 换名/纯骨架）→ build 默认跳过。"""
    b = spec.get("build") or {}
    if b.get("apt") or b.get("pip") or b.get("npm"):
        return False
    if _script_meaningful(str(b.get("pre") or "")) or _script_meaningful(str(b.get("post") or "")):
        return False
    if spec.get("assets") or spec.get("files") or spec.get("services"):
        return False
    run = spec.get("run") or {}
    if run.get("caps") or run.get("network") not in (None, "none"):
        return False
    return True


def validate_spec(comp_dir: Path, comp_name: str, slug: str, merged: dict,
                  is_challenge: bool) -> list[str]:
    """构建前校验：版本、命名、assets 路径逃逸与 sha256、services 形状、resources 只紧不松。"""
    problems: list[str] = []
    api = str(merged.get("api") or API_VERSION)
    if api != API_VERSION:
        problems.append(f"api 版本不支持：{api}（期望 {API_VERSION}）")
    if is_challenge:
        spec_slug = str(merged.get("slug") or slug)
        if not SLUG_RE.match(spec_slug):
            problems.append(f"slug 不合法：{spec_slug}")
        category = str(merged.get("category") or "misc").lower()
        if category not in KNOWN_CATEGORIES:
            problems.append(f"未知 category：{category}")
    run = merged.get("run") or {}
    caps = run.get("caps") or []
    if not isinstance(caps, list) or any(not isinstance(c, str) for c in caps):
        problems.append("run.caps 必须是字符串列表")
    res = run.get("resources") or {}
    if not isinstance(res, dict):
        problems.append("run.resources 必须是映射")
    if run.get("network") not in (None, "none", "bridge", "services"):
        problems.append(f"run.network 不支持：{run.get('network')}")
    assets_root = (env_paths(comp_dir)["assets"] / slug).resolve() if is_challenge else None
    for idx, a in enumerate(merged.get("assets") or []):
        src = str(a.get("src") or "")
        if not src:
            problems.append(f"assets[{idx}] 缺 src")
            continue
        if is_challenge:
            try:
                resolved = (assets_root / src).resolve()  # type: ignore[union-attr]
                resolved.relative_to(assets_root)  # type: ignore[union-attr]
            except (ValueError, OSError):
                problems.append(f"assets[{idx}] 路径逃逸：{src}")
                continue
            if not resolved.exists():
                problems.append(f"assets[{idx}] 文件不存在：{src}")
                continue
            if resolved.is_file() and str(a.get("sha256") or "").strip():
                want = str(a["sha256"]).strip().lower()
                got = hashlib.sha256(resolved.read_bytes()).hexdigest()
                if got != want and re.fullmatch(r"[0-9a-f]{64}", want):
                    problems.append(f"assets[{idx}] sha256 不符：{src}（期望 {want[:12]}…，实际 {got[:12]}…）")
                elif not re.fullmatch(r"[0-9a-f]{64}", want):
                    problems.append(f"assets[{idx}] sha256 不是 64 位十六进制（填 sha256sum 的输出）")
    for idx, f in enumerate(merged.get("files") or []):
        dst = str(f.get("dst") or "")
        if dst.startswith("/") or ".." in Path(dst).parts or not dst:
            problems.append(f"files[{idx}] dst 必须是 /workspace 内的相对路径：{dst!r}")
    services = merged.get("services") or {}
    if not isinstance(services, dict):
        problems.append("services 必须是映射")
    else:
        for name, s in services.items():
            if not isinstance(s, dict) or not s.get("image"):
                problems.append(f"services.{name} 缺 image")
            port = s.get("ports")
            if port and not all("127.0.0.1:" in str(p) for p in ([port] if isinstance(port, str) else port)):
                problems.append(f"services.{name}.ports 只允许绑定 127.0.0.1")
    return problems


# ================================================================ 渲染


def _script_meaningful(script: str) -> bool:
    """空脚本判定：去掉注释后只剩 no-op（:）或空行 → 无意义，不渲染 RUN 层。"""
    for line in str(script or "").splitlines():
        line = _strip_comment(line).strip()
        if line and line != ":":
            return True
    return False


def render_dockerfile(comp_name: str, slug: str, spec: dict, base: str,
                      mirrors: dict | None) -> str:
    """把 spec 渲染为 Dockerfile（权威实现；envs/Dockerfile.tmpl 只是映射说明）。"""
    mirrors = mirrors or {}
    build = spec.get("build") or {}
    L: list[str] = []
    add = L.append
    add("# 由 workbench/env_builder.py 自动生成 —— 勿手改；修改 env spec 后重新 build")
    add(f"# 比赛层/题目层: ctf-{normalize_name(comp_name)}-{normalize_name(slug)}")
    add(f"FROM {base}")
    add("ARG DEBIAN_FRONTEND=noninteractive")
    if mirrors.get("apt"):
        add(f"ARG APT_MIRROR={mirrors['apt']}")
    if mirrors.get("pip"):
        add(f"ARG PIP_MIRROR={mirrors['pip']}")
    add("USER root")
    apt = [str(p) for p in (build.get("apt") or [])]
    if apt:
        add("RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \\")
        add("    --mount=type=cache,target=/var/lib/apt,sharing=locked \\")
        add("    apt-get -o Acquire::Retries=5 update \\")
        add("    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \\")
        for p in apt:
            add(f"        {p} \\")
        add("    && rm -rf /var/lib/apt/lists/*")
    pip = [str(p) for p in (build.get("pip") or [])]
    if pip:
        add("RUN --mount=type=cache,target=/root/.cache/pip \\")
        idx = f" -i {mirrors['pip']}" if mirrors.get("pip") else ""
        add(f"    pip install --no-cache-dir{idx} " + " ".join(pip))
    npm = [str(p) for p in (build.get("npm") or [])]
    if npm:
        add("RUN --mount=type=cache,target=/root/.npm \\")
        reg = f" --registry={mirrors['npm']}" if mirrors.get("npm") else ""
        add(f"    npm install -g{reg} " + " ".join(npm))
    for a in spec.get("assets") or []:
        src, dst = str(a.get("src") or ""), str(a.get("dst") or "")
        if not src or not dst:
            continue
        mode = "--chmod=755 " if not src.endswith("/") else ""
        add(f"COPY {mode}context/{src} {dst}")
    for phase, style in (("pre", "PRE"), ("post", "POST")):
        script = str(build.get(phase) or "")
        if _script_meaningful(script):
            add(f"RUN <<'CTFBOX_{style}'")
            L.extend(script.rstrip("\n").splitlines())
            add(f"CTFBOX_{style}")
    add("USER ctf")
    add("WORKDIR /workspace")
    return "\n".join(L) + "\n"


def compose_project(comp_name: str, slug: str) -> str:
    return f"ctf-{normalize_name(comp_name)}-{normalize_name(slug)}"


def compose_dict(comp_name: str, slug: str, spec: dict) -> tuple[dict, list[str]]:
    """services → compose 字典。网络默认 internal；返回 (dict, problems)。"""
    problems: list[str] = []
    services_out: dict = {}
    slug_n = normalize_name(slug)
    for name, s in (spec.get("services") or {}).items():
        name_n = normalize_name(str(name))
        if not name_n or name_n in services_out:
            problems.append(f"services 服务名不合法或重复：{name}")
            continue
        entry: dict = {"image": str(s.get("image"))}
        command = s.get("command")
        if command:
            entry["command"] = ([str(c) for c in command] if isinstance(command, list)
                                else ["sh", "-c", str(command)])
        env = s.get("env") or {}
        if isinstance(env, dict) and env:
            entry["environment"] = {str(k): str(v) for k, v in env.items()}
            # flag 卫生：题目服务容器里的 FLAG 只允许占位值，真值只能来自平台实例
            if "FLAG" in entry["environment"] and not re.match(r"flag\{placeholder",
                                                               entry["environment"]["FLAG"]):
                problems.append(f"services.{name}.env.FLAG 必须是占位值"
                                f"（flag{{placeholder-…}}），真值只能来自平台实例")
        volumes: list[str] = []
        mount = str(s.get("mount") or "").strip()
        if mount:
            parts = [p.strip() for p in mount.split("->")]
            if len(parts) != 2 or not parts[0] or not parts[1]:
                problems.append(f"services.{name}.mount 语法：源 -> 目标（如 src/ -> /var/www/html）")
            else:
                src_rel = parts[0].lstrip("/")
                if not _safe_asset_rel(src_rel):
                    problems.append(f"services.{name}.mount 源路径逃逸：{parts[0]}")
                else:
                    volumes.append(f"../../assets/{slug_n}/{src_rel}:{parts[1]}:ro")
        init_sql = str(s.get("init_sql") or "").strip()
        if init_sql:
            if not _safe_asset_rel(init_sql):
                problems.append(f"services.{name}.init_sql 路径逃逸：{init_sql}")
            else:
                volumes.append(f"../../assets/{slug_n}/{init_sql}:/docker-entrypoint-initdb.d/{Path(init_sql).name}:ro")
        if volumes:
            entry["volumes"] = volumes
        ports = s.get("ports")
        if ports:
            entry["ports"] = ([str(ports)] if isinstance(ports, str)
                              else [str(p) for p in ports])
        entry["networks"] = ["challnet"]
        services_out[name_n] = entry
    doc = {
        "name": compose_project(comp_name, slug),
        "services": services_out,
        "networks": {"challnet": {"internal": True}},
    }
    return doc, problems


def _safe_asset_rel(rel: str) -> bool:
    p = Path(rel)
    return bool(rel) and not p.is_absolute() and ".." not in p.parts


def runtime_mounts(comp_dir: Path, slug: str, merged: dict) -> tuple[list[dict], list[str]]:
    """files[] 与 constraints（CLAUDE.md/skills）→ 运行时 ro 挂载（改文件免重建）。"""
    mounts: list[dict] = []
    problems: list[str] = []
    env_dir = env_paths(comp_dir)["env"]
    assets_slug = (env_dir / "assets" / slug).resolve()
    for idx, f in enumerate(merged.get("files") or []):
        src_rel = str(f.get("src") or "")
        dst = str(f.get("dst") or "")
        if not _safe_asset_rel(src_rel):
            problems.append(f"files[{idx}] src 路径逃逸：{src_rel!r}")
            continue
        host = assets_slug / src_rel
        if not host.exists():
            problems.append(f"files[{idx}] 文件不存在：{src_rel}")
            continue
        mounts.append({"host": str(host), "container": f"/workspace/{dst.lstrip('/')}".rstrip("/")})
    cons = merged.get("constraints") or {}
    claudemd = str(cons.get("claudemd") or "").strip()
    if claudemd:
        host = (env_dir / claudemd).resolve()
        try:
            host.relative_to(env_dir.resolve())
        except ValueError:
            problems.append(f"constraints.claudemd 路径逃逸：{claudemd}")
        else:
            if host.is_file():
                mounts.append({"host": str(host), "container": "/workspace/CLAUDE.md"})
            else:
                problems.append(f"constraints.claudemd 文件不存在：{claudemd}")
    for skill in cons.get("skills") or []:
        skill_dir = env_dir / "solver" / "skills" / str(skill)
        if skill_dir.is_dir():
            mounts.append({"host": str(skill_dir.resolve()),
                           "container": f"/workspace/.claude/skills/{skill}"})
    return mounts, problems


# ================================================================ docker
#
# docker CLI 发现：PATH 里的 docker/docker.exe 优先；Windows 下回退 WSL
# （`wsl docker ...`，文件路径须经 docker_path() 翻译为 /mnt/<盘>/...）。
# 这样「Docker Desktop 未装、docker 只在 WSL 里」的机器（本机）也能全链路工作。

_DOCKER_PREFIX: list[str] | None = None
_DOCKER_PROBED = False
_PREFIX_LOCK = threading.Lock()


def docker_prefix() -> list[str] | None:
    """返回 docker CLI 调用前缀（如 ["docker"] 或 ["wsl", "docker"]）；不可用为 None。

    R34 修复：探测加锁；失败不缓存——Docker 稍后起来时下一次调用会重试，
    且并发首探的失败结果不会覆盖成功值。
    """
    global _DOCKER_PREFIX, _DOCKER_PROBED
    with _PREFIX_LOCK:
        if _DOCKER_PROBED:
            return _DOCKER_PREFIX
        if shutil.which("docker") or shutil.which("docker.exe"):
            _DOCKER_PREFIX = ["docker"]
            _DOCKER_PROBED = True
            return _DOCKER_PREFIX
        if os.name == "nt":
            try:
                r = subprocess.run(["wsl", "docker", "version",
                                    "--format", "{{.Server.Version}}"],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=30)
                if r.returncode == 0:
                    _DOCKER_PREFIX = ["wsl", "docker"]
                    _DOCKER_PROBED = True
                    return _DOCKER_PREFIX
            except Exception:  # noqa: BLE001
                pass
        return None


def _to_wsl_path(p) -> str:
    s = str(p).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):(/.*)?$", s)
    if m:
        return f"/mnt/{m.group(1).lower()}{m.group(2) or ''}"
    return s


def docker_path(p) -> str:
    """传给 docker CLI 的文件路径：WSL 前缀下翻译 Windows 路径，否则原样。"""
    prefix = docker_prefix()
    if prefix and prefix[0] == "wsl":
        return _to_wsl_path(p)
    return str(p)


def docker_available() -> bool:
    return docker_prefix() is not None


# 本地镜像 tag 集合（短 TTL 缓存）：一次 `docker images` 代替 N 次逐个 inspect——
# WSL 通道下每次调用都要起一个 wsl 进程，env/status 曾因此串行 ~10s。
_IMAGES_CACHE: tuple[float, frozenset] | None = None
_IMAGES_META: tuple[float, dict] | None = None
_IMAGES_TTL = 5.0


def docker_images_meta(max_age: float = 30.0) -> dict:
    """tag → {size, created}（R42：标准环境页展示用；短 TTL 缓存）。"""
    global _IMAGES_META
    now = time.time()
    if _IMAGES_META is not None and now - _IMAGES_META[0] <= max_age:
        return _IMAGES_META[1]
    prefix = docker_prefix()
    meta: dict = {}
    if prefix:
        try:
            r = subprocess.run([*prefix, "images", "--format",
                                "{{.Repository}}:{{.Tag}}	{{.Size}}	{{.CreatedAt}}"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            for line in (r.stdout or "").splitlines():
                parts = line.split("	")
                if len(parts) == 3 and not parts[0].endswith(":"):
                    meta[parts[0]] = {"size": parts[1], "created": parts[2][:19]}
        except Exception:  # noqa: BLE001
            pass
    _IMAGES_META = (now, meta)
    return meta


def docker_images_invalidate() -> None:
    global _IMAGES_CACHE, _IMAGES_META
    _IMAGES_CACHE = None
    _IMAGES_META = None


def docker_images_set(max_age: float = _IMAGES_TTL) -> frozenset:
    global _IMAGES_CACHE
    now = time.time()
    if _IMAGES_CACHE is not None and now - _IMAGES_CACHE[0] <= max_age:
        return _IMAGES_CACHE[1]
    prefix = docker_prefix()
    tags: frozenset = frozenset()
    if prefix:
        try:
            r = subprocess.run([*prefix, "images", "--format", "{{.Repository}}:{{.Tag}}"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
            if r.returncode == 0:
                tags = frozenset(line.strip() for line in r.stdout.splitlines()
                                 if line.strip() and not line.strip().endswith(":"))
        except Exception:  # noqa: BLE001
            tags = frozenset()
    _IMAGES_CACHE = (now, tags)
    return tags


def docker_image_exists(tag: str) -> bool:
    prefix = docker_prefix()
    if not prefix or not tag:
        return False
    return tag in docker_images_set()


def docker_digest(tag: str) -> str:
    prefix = docker_prefix()
    if not prefix:
        return ""
    try:
        r = subprocess.run([*prefix, "image", "inspect", tag, "-f", "{{.Id}}"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


# ================================================================ 构建产物登记


def read_built(comp_dir: Path) -> dict:
    path = env_paths(comp_dir)["built"]
    data = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"schema": BUILT_SCHEMA, "images": {}, "comp": None}
    if not isinstance(data, dict) or data.get("schema") != BUILT_SCHEMA:
        return {"schema": BUILT_SCHEMA, "images": {}, "comp": None}
    data.setdefault("images", {})
    return data


def save_built(comp_dir: Path, built: dict) -> None:
    path = env_paths(comp_dir)["built"]
    path.parent.mkdir(parents=True, exist_ok=True)
    built["schema"] = BUILT_SCHEMA
    built["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path.write_text(json.dumps(built, ensure_ascii=False, indent=1), encoding="utf-8")


# ================================================================ build


def build_one(comp_dir: Path, slug: str, spec: dict, comp_spec: dict, built: dict,
              force: bool = False, dry_run: bool = False,
              lock: "threading.Lock | None" = None) -> dict | None:
    """构建单个题目层；返回登记记录（跳过/失败见返回的 status 字段）。"""
    comp_name = str(comp_spec.get("comp") or comp_dir.name)
    category = str(spec.get("category") or "misc").lower()
    merged = merged_spec(comp_spec, spec)
    problems = validate_spec(comp_dir, comp_name, slug, merged, is_challenge=True)
    if problems:
        raise SpecError(f"{slug}: " + "；".join(problems))
    if spec_is_empty(merged) and not force:
        log(f"[build] {slug}: skipped-empty（spec 无定制，直接用题型层镜像；--force 可强制构建）")
        return {"slug": slug, "status": "skipped-empty",
                "note": "spec 无定制内容（纯骨架），直接用题型层镜像即可；--force 可强制构建"}
    paths = env_paths(comp_dir)
    gen_slug = paths["gen"] / slug
    ctx = gen_slug / "context"
    if gen_slug.exists():
        shutil.rmtree(gen_slug)
    ctx.mkdir(parents=True)
    # assets 校验已过 → 复制进构建上下文
    assets_root = paths["assets"] / slug
    for a in merged.get("assets") or []:
        src = assets_root / str(a.get("src") or "")
        if src.exists():
            target = ctx / str(a.get("src") or "")
            target.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                shutil.copy2(src, target)
    base = base_for(comp_name, slug, category, spec, built)
    dockerfile = render_dockerfile(comp_name, slug, merged, base, merged.get("mirrors"))
    (gen_slug / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    services_meta: dict = {}
    if merged.get("services"):
        doc, problems2 = compose_dict(comp_name, slug, merged)
        if problems2:
            raise SpecError(f"{slug}: " + "；".join(problems2))
        (gen_slug / "compose.yaml").write_text(yaml_dump(doc) + "\n", encoding="utf-8")
        services_meta = {"services": True, "project": doc["name"],
                         "network": doc["name"] + "_challnet",
                         "compose_file": f"env/gen/{slug}/compose.yaml"}
    tag = image_tag(comp_name, slug, spec_hash(merged))
    log(f"[build] {slug}: FROM {base} → {tag}")
    if dry_run:
        log(f"[build] {slug}: dry-run，仅渲染 gen/{slug}/（Dockerfile"
            + (" + compose.yaml" if services_meta else "") + "），未调用 docker")
        return {"slug": slug, "status": "dry-run", "image": tag, "base": base,
                **services_meta}
    prefix = docker_prefix()
    if not prefix:
        raise RuntimeError("Docker 引擎不可达：启动 Docker Desktop（或 WSL docker）后重试（或用 --dry-run 只渲染）")
    argv = [*prefix, "build", "-f", docker_path(gen_slug / "Dockerfile"), "-t", tag,
            docker_path(ctx)]
    proc = subprocess.run(argv)
    if proc.returncode != 0:
        raise RuntimeError(f"{slug}: docker build 失败（exit {proc.returncode}）")
    docker_images_invalidate()
    record = {"slug": slug, "status": "built", "image": tag, "base": base,
              "category": category, "spec_hash": spec_hash(merged),
              "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "digest": docker_digest(tag), **services_meta}
    if lock is not None:
        with lock:
            built.setdefault("images", {})[slug] = record
            save_built(comp_dir, built)
    else:
        built.setdefault("images", {})[slug] = record
        save_built(comp_dir, built)
    log(f"[build] {slug}: ✓ {tag}")
    return record


def build_comp_image(comp_dir: Path, comp_spec: dict, built: dict,
                     dry_run: bool = False) -> dict | None:
    """构建 L2 比赛层（comp.yaml 无任何定制内容时跳过）。"""
    comp_name = str(comp_spec.get("comp") or comp_dir.name)
    if not comp_spec:
        return None
    paths = env_paths(comp_dir)
    gen = paths["gen"] / "_comp"
    if gen.exists():
        shutil.rmtree(gen)
    gen.mkdir(parents=True)
    base = str(comp_spec.get("base") or "").strip() or L0_TAG
    dockerfile = render_dockerfile(comp_name, "_comp", comp_spec, base,
                                   comp_spec.get("mirrors"))
    (gen / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    tag = comp_image_tag(comp_name, spec_hash(comp_spec))
    log(f"[build] 比赛层 {comp_name}: FROM {base} → {tag}")
    if dry_run:
        log("[build] 比赛层: dry-run，未调用 docker")
        return {"status": "dry-run", "image": tag, "base": base}
    prefix = docker_prefix()
    if not prefix:
        raise RuntimeError("Docker 引擎不可达：启动 Docker Desktop（或 WSL docker）后重试（或用 --dry-run 只渲染）")
    argv = [*prefix, "build", "-f", docker_path(gen / "Dockerfile"), "-t", tag,
            docker_path(gen / "context")]
    (gen / "context").mkdir(exist_ok=True)
    proc = subprocess.run(argv)
    if proc.returncode != 0:
        raise RuntimeError(f"比赛层 docker build 失败（exit {proc.returncode}）")
    docker_images_invalidate()
    record = {"status": "built", "image": tag, "base": base,
              "spec_hash": spec_hash(comp_spec),
              "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "digest": docker_digest(tag)}
    built["comp"] = record
    save_built(comp_dir, built)
    log(f"[build] 比赛层: ✓ {tag}")
    return record


# ================================================================ 镜像选择（server 调用）


def resolve_image(comp_dir: Path, slug: str, category: str, *,
                  default_image: str = "", category_images: dict | None = None,
                  exists=None) -> dict:
    """沙箱镜像选择优先级（COMPETITION_ENV_DESIGN.md §5）：

    case env.image → 题目层(.built.json) → spec 钉住的 base → L2 比赛层
    → 题型层 → 兜底镜像。返回 {image, source, ok, ...services 元数据}。
    """
    exists = exists or docker_image_exists
    category_images = category_images or CATEGORY_IMAGES
    out: dict = {"image": "", "source": "", "ok": False, "preferred": "",
                 "services": False, "network": "", "project": "", "compose_file": "",
                 "mounts": [], "explicit_missing": ""}
    specs = load_specs(comp_dir)
    chall_spec = specs["challenges"].get(slug) or {}
    merged = merged_spec(specs["comp"], chall_spec) if chall_spec else {}
    mounts, mount_problems = runtime_mounts(comp_dir, slug, merged) if merged else ([], [])
    out["mounts"] = mounts
    out["mount_problems"] = mount_problems
    built = read_built(comp_dir)
    candidates: list[tuple[str, str, dict]] = []
    case_json = comp_dir / "cases" / slug / "case.json"
    try:
        env_img = (json.loads(case_json.read_text(encoding="utf-8"))
                   .get("env") or {}).get("image")
    except Exception:  # noqa: BLE001
        env_img = None
    if env_img:
        candidates.append(("case", str(env_img), {}))
    rec = (built.get("images") or {}).get(slug) or {}
    if rec.get("image"):
        candidates.append(("challenge", str(rec["image"]), rec))
    # 只认题目 spec 自己钉的 base；comp.yaml 的 base 属于 L2，不当题目缺省
    pinned = str((chall_spec.get("base") or "")).strip() if chall_spec else ""
    if pinned:
        candidates.append(("pinned", pinned, {}))
    comp_rec = built.get("comp") or {}
    if comp_rec.get("image"):
        candidates.append(("comp", str(comp_rec["image"]), {}))
    cat_img = (category_images or {}).get(category) or ""
    if cat_img:
        candidates.append(("category", cat_img, {}))
    if default_image:
        candidates.append(("fallback", default_image, {}))
    out["preferred"] = candidates[0][1] if candidates else default_image
    explicit = {"case", "challenge"}  # 显式指定的镜像缺失 → 硬报错，不许静默换镜像
    for source, tag, rec_meta in candidates:
        out.update({"image": tag, "source": source})
        if source in explicit and not exists(tag):
            out["explicit_missing"] = source
            out["ok"] = False
            return out
        if rec_meta.get("services"):
            out.update({"services": True, "network": rec_meta.get("network", ""),
                        "project": rec_meta.get("project", ""),
                        "compose_file": rec_meta.get("compose_file", "")})
        if exists(tag):
            out["ok"] = True
            return out
    return out


# ================================================================ docker runtime（R41）


def docker_runtime() -> dict:
    """Docker 运行态：本工具相关容器（沙箱/题目服务）与磁盘占用。"""
    prefix = docker_prefix()
    out: dict = {"containers": [], "disk": {}}
    if not prefix:
        return out
    try:
        r = subprocess.run([*prefix, "ps", "-a", "--format",
                            "{{.Names}}	{{.Image}}	{{.Status}}"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        for line in (r.stdout or "").splitlines():
            parts = line.split("	")
            if len(parts) == 3 and (parts[0].startswith("ctfwb-") or parts[1].startswith("ctf-")):
                out["containers"].append({"name": parts[0], "image": parts[1],
                                          "status": parts[2]})
    except Exception as exc:  # noqa: BLE001
        out["ps_error"] = repr(exc)[:120]
    try:
        r = subprocess.run([*prefix, "system", "df", "--format",
                            "{{.Type}}	{{.Size}}	{{.Reclaimable}}"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        for line in (r.stdout or "").splitlines():
            parts = line.split("	")
            if len(parts) >= 3:
                out["disk"][parts[0]] = {"size": parts[1], "reclaimable": parts[2]}
    except Exception as exc:  # noqa: BLE001
        out["df_error"] = repr(exc)[:120]
    return out


# ================================================================ status


def status_data(comp_dir: Path) -> dict:
    """API/UI 用的环境状态总览（纯 JSON，供 server 与 env_builder status 共用）。"""
    specs = load_specs(comp_dir)
    built = read_built(comp_dir)
    comp_name = str(specs["comp"].get("comp") or comp_dir.name)
    challenges = []
    comp_entry = comp_dir / "competition.json"
    registered: dict[str, dict] = {}
    try:
        for c in json.loads(comp_entry.read_text(encoding="utf-8")).get("challenges", []):
            registered[str(c.get("slug"))] = c
    except Exception:  # noqa: BLE001
        pass
    for slug in sorted(set(registered) | set(specs["challenges"])):
        spec = specs["challenges"].get(slug) or {"slug": slug,
                                                 "category": (registered.get(slug) or {}).get("category", "misc")}
        merged = merged_spec(specs["comp"], spec)
        category = str(merged.get("category") or "misc").lower()
        rec = (built.get("images") or {}).get(slug) or {}
        challenges.append({
            "slug": slug,
            "name": (registered.get(slug) or {}).get("name", slug),
            "category": category,
            "has_spec": slug in specs["challenges"],
            "customized": not spec_is_empty(merged) if slug in specs["challenges"] else False,
            "services": bool(merged.get("services")),
            "base": base_for(comp_name, slug, category, spec, built),
            "built": rec if rec else None,
            "stale": bool(rec.get("spec_hash") and slug in specs["challenges"]
                          and rec["spec_hash"] != spec_hash(merged)),
        })
    comp_rec = built.get("comp") or {}
    docker_ok = docker_available()
    meta = docker_images_meta() if docker_ok else {}
    l1 = {cat: {"image": img, "ok": docker_image_exists(img) if docker_ok else False,
                "size": (meta.get(img) or {}).get("size", ""),
                "created": (meta.get(img) or {}).get("created", "")}
          for cat, img in CATEGORY_IMAGES.items()}
    return {
        "comp": comp_name,
        "dir": comp_dir.name,
        "runtime": docker_runtime(),
        "has_env": specs["has_env"],
        "parser": specs["parser"],
        "problems": specs["problems"],
        "docker_ok": docker_ok,
        "l0": {"image": L0_TAG, "ok": docker_image_exists(L0_TAG) if docker_ok else False},
        "l1": l1,
        "l2": {**comp_rec, "tag_hint": comp_image_tag(comp_name, spec_hash(specs["comp"]))}
              if specs["comp"] else None,
        "challenges": challenges,
    }


# ================================================================ clean（R11）


def env_images(comp_dir: Path) -> list[str]:
    """当前登记在 .built.json 里的全部比赛/题目镜像 tag。"""
    built = read_built(comp_dir)
    tags = []
    if (built.get("comp") or {}).get("image"):
        tags.append(str(built["comp"]["image"]))
    for rec in (built.get("images") or {}).values():
        if rec.get("image") and rec["image"] not in tags:
            tags.append(str(rec["image"]))
    return tags


def prune_env_images(comp_dir: Path, keep_days: int = 7,
                     dry_run: bool = False) -> dict:
    """清理旧的比赛/题目镜像：只保留 keep_days 天内构建的和当前 .built.json 登记的。

    docker 本地镜像按创建时间过滤（通过 docker images --format 拿 CreatedSince 不可靠，
    这里用 `docker images --format {{.ID}} {{.CreatedAt}}` 的 ISO 时间判断）。
    """
    prefix = docker_prefix()
    if not prefix:
        raise RuntimeError("Docker 引擎不可达")
    keep = set(env_images(comp_dir))
    cutoff = time.time() - keep_days * 86400
    removed, kept = [], []
    r = subprocess.run([*prefix, "images", "--format",
                        "{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    for line in (r.stdout or "").splitlines():
        if "\t" not in line or not line.split("\t")[0].startswith("ctf-"):
            continue  # 只动本工具打的 ctf-<comp> 系列镜像，绝不碰其他镜像
        tag, _iid, created = line.split("\t", 2)
        if ":<none>" in tag or tag.endswith(":"):
            continue
        try:
            ts = time.mktime(time.strptime(created[:19], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if tag in keep or ts >= cutoff:
            kept.append(tag)
            continue
        removed.append(tag)
        if not dry_run:
            subprocess.run([*prefix, "rmi", "-f", tag], capture_output=True, timeout=120)
    return {"removed": removed, "kept": len(kept)}


# ================================================================ verify


def verify_image(image: str, category: str, extra_probes: list[str] | None = None,
                 timeout: int = 120) -> dict:
    probes = list(PROBES.get("common", [])) + list(PROBES.get(category, []))
    probes += [str(p) for p in (extra_probes or [])]
    results = []
    prefix = docker_prefix()
    for probe in probes:
        if not prefix:
            results.append({"probe": probe, "ok": False, "detail": "docker 不可达"})
            continue
        try:
            proc = subprocess.run(
                [*prefix, "run", "--rm", "--network", "none",
                 "--memory", "512m", "--pids-limit", "64", image, "sh", "-c", probe],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout)
            ok = proc.returncode == 0
            detail = (proc.stdout or proc.stderr or "").strip().splitlines()
            results.append({"probe": probe, "ok": ok,
                            "detail": (detail[-1] if detail else "")[:120]})
        except subprocess.TimeoutExpired:
            results.append({"probe": probe, "ok": False, "detail": "timeout"})
        except Exception as exc:  # noqa: BLE001
            results.append({"probe": probe, "ok": False, "detail": repr(exc)[:120]})
    return {"image": image, "category": category, "results": results,
            "ok": bool(results) and all(r["ok"] for r in results)}


# ================================================================ push（R42）


def registry_config() -> str:
    """仓库地址（workbench-data/registry.json {"registry": "..."}）。"""
    path = HERE.parent / "workbench-data" / "registry.json"
    try:
        return str((json.loads(path.read_text(encoding="utf-8")) or {}).get("registry") or "")
    except Exception:  # noqa: BLE001
        return ""


def push_images(comp_dir: Path, slugs: list[str], registry: str = "",
                include_comp: bool = True) -> dict:
    """把已构建的 L2/L3 镜像打 tag 推送到仓库。真实凭证只在本机 docker login。"""
    built = read_built(comp_dir)
    reg = (registry or registry_config()).strip().rstrip("/")
    if not reg:
        raise RuntimeError("未配置仓库地址：--registry REG 或 环境页「仓库推送」保存")
    tags: list[str] = []
    if include_comp and (built.get("comp") or {}).get("image"):
        tags.append(str(built["comp"]["image"]))
    images = built.get("images") or {}
    for slug in (slugs or sorted(images)):
        rec = images.get(slug) or {}
        if rec.get("image") and rec["image"] not in tags:
            tags.append(str(rec["image"]))
    if not tags:
        raise RuntimeError("没有已构建的比赛/题目镜像可推送（先 build）")
    prefix = docker_prefix()
    if not prefix:
        raise RuntimeError("Docker 引擎不可达")
    results = []
    for tag in tags:
        remote = f"{reg}/{tag}"
        subprocess.run([*prefix, "tag", tag, remote], capture_output=True, timeout=120)
        r = subprocess.run([*prefix, "push", remote], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=3600)
        ok = r.returncode == 0
        results.append({"local": tag, "remote": remote, "ok": ok,
                        "detail": "" if ok else (r.stderr or r.stdout or "")[-160:]})
        log(f"[push] {'✓' if ok else '✗'} {remote}")
    return {"results": results, "ok": all(x["ok"] for x in results), "registry": reg}


# ================================================================ export


def export_images(comp_dir: Path, slugs: list[str], out: Path,
                  with_spec: bool = False) -> dict:
    built = read_built(comp_dir)
    tags: list[str] = []
    if (built.get("comp") or {}).get("image"):
        tags.append(str(built["comp"]["image"]))
    images = built.get("images") or {}
    for slug in (slugs or sorted(images)):
        rec = images.get(slug) or {}
        if rec.get("image") and rec["image"] not in tags:
            tags.append(str(rec["image"]))
    if not tags:
        raise RuntimeError("没有已构建的比赛/题目镜像可导出（先 build）")
    prefix = docker_prefix()
    if not prefix:
        raise RuntimeError("Docker 引擎不可达")
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([*prefix, "save", "-o", docker_path(out), *tags])
    if proc.returncode != 0:
        raise RuntimeError(f"docker save 失败（exit {proc.returncode}）")
    spec_archive = ""
    if with_spec:
        spec_archive = str(out.with_suffix(out.suffix + ".env.tar.gz"))
        with tarfile.open(spec_archive, "w:gz") as tf:
            env_dir = env_paths(comp_dir)["env"]
            for p in sorted(env_dir.rglob("*")):
                if not p.is_file() or "/gen/" in str(p).replace("\\", "/"):
                    continue
                tf.add(p, arcname=str(p.relative_to(comp_dir)))
    return {"out": str(out), "images": tags, "spec_archive": spec_archive}


# ================================================================ preheat


def _docker_build(argv_desc: str, dockerfile: Path, context: Path, tag: str) -> None:
    prefix = docker_prefix()
    if not prefix:
        raise RuntimeError("Docker 引擎不可达")
    log(f"[preheat] {argv_desc} → {tag}")
    proc = subprocess.run([*prefix, "build", "-f", docker_path(dockerfile),
                           "-t", tag, docker_path(context)])
    if proc.returncode != 0:
        raise RuntimeError(f"{argv_desc} 构建失败（exit {proc.returncode}）")
    docker_images_invalidate()


def rebuild_base() -> dict:
    """R46-E2：重建 L0 底座——先同步约束层资产，再 docker build base。

    L1/L2/L3 不会自动跟随（需要各自重建），前端在操作后给出提示。
    """
    sync = sync_solver_assets()
    prefix = docker_prefix()
    if not prefix:
        raise RuntimeError("Docker 引擎不可达")
    log(f"[base] 约束层同步完成（写入 {len(sync['changed'])} 个文件）")
    _docker_build("L0 base（含最新约束层/skill 包）",
                  DOCKER_DIR / "base" / "Dockerfile", DOCKER_DIR, L0_TAG)
    return {"synced": len(sync["changed"]), "ok": True}


def preheat(comp_dir: Path, categories: list[str] | None = None,
            check_only: bool = False, rebuild: bool = False) -> dict:
    specs = load_specs(comp_dir)
    cats = set(categories or [])
    if not cats:
        for spec in specs["challenges"].values():
            cats.add(str(spec.get("category") or "misc").lower())
        cats.add(str(specs["comp"].get("base") or "misc").split(":")[0].replace("ctfbox-", ""))
    cats = {c for c in cats if c in KNOWN_CATEGORIES} or {"misc"}
    plan = [( "L0", L0_TAG, DOCKER_DIR / "base" / "Dockerfile" )]
    plan += [("L1", CATEGORY_IMAGES[c], DOCKER_DIR / c / "Dockerfile") for c in sorted(cats)]
    if rebuild:
        missing = plan
    else:
        missing = [p for p in plan if not docker_image_exists(p[1])]
    if check_only:
        return {"missing": [{"tier": t, "image": i} for t, i, _ in missing],
               "ok": not missing}
    if not docker_available():
        raise RuntimeError("Docker 引擎不可达")
    for tier, tag, dockerfile in missing:
        _docker_build(tier, dockerfile, DOCKER_DIR, tag)
    return {"built": [{"tier": t, "image": i} for t, i, _ in missing], "ok": True}


# ================================================================ 约束层同步
#
# PDF 的"规则界定边界"：约束层（CLAUDE.md/AGENTS.md + 题型 skill 包）随 L0 烤入
# 镜像，所有层继承；比赛级覆盖走运行时挂载（constraints.claudemmd/skills，免重建）。
# skills 由知识库 playbook 生成——只给方向与范围，不写"xx 漏洞怎么发包"级别的细节。


def sync_solver_assets(check_only: bool = False) -> dict:
    """把约束层资产同步进 L0 构建上下文（workbench/docker/base/），幂等。

    - envs/solver/CLAUDE.md → base/CLAUDE.md + base/AGENTS.md（双写兼容 codex 生态）
    - references/playbooks-*.md → base/skills/<category>/SKILL.md（题型 skill 包）
    """
    src_claude = HERE / "docker" / "envs" / "solver" / "CLAUDE.md"
    base_dir = HERE / "docker" / "base"
    refs = HERE.parent / "references"
    claude_text = src_claude.read_text(encoding="utf-8")
    plan: list[tuple[Path, str]] = [(base_dir / name, claude_text)
                                    for name in ("CLAUDE.md", "AGENTS.md")]
    for cat, playbook in sorted(CATEGORY_PLAYBOOK.items()):
        pb = refs / playbook
        text = pb.read_text(encoding="utf-8") if pb.exists() else ""
        plan.append((base_dir / "skills" / cat / "SKILL.md",
                     "---\n"
                     f"name: ctf-{cat}\n"
                     f"description: {CATEGORY_SKILL_DESC[cat]}。与当前证据冲突时，证据优先。\n"
                     "---\n\n"
                     f"<!-- 生成自 references/{playbook}，勿手改；"
                     "改 playbook 后重跑 env_builder sync-solver -->\n\n"
                     + text))
    changed: list[str] = []
    for path, content in plan:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        changed.append(str(path.relative_to(HERE)))
        if not check_only:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return {"changed": changed, "ok": True}


# ================================================================ CLI


def _cmd_build(args) -> int:
    comp_dir = args.comp_dir.resolve()
    if not comp_dir.is_dir():
        log(f"✗ 比赛目录不存在：{comp_dir}")
        return 2
    specs = load_specs(comp_dir)
    if specs["problems"]:
        for p in specs["problems"]:
            log(f"✗ spec 问题：{p}")
        return 2
    if not specs["has_env"]:
        log(f"✗ {comp_dir / 'env' / 'comp.yaml'} 不存在：先 competition.py init 或复制 envs/comp.example.yaml")
        return 2
    built = read_built(comp_dir)
    built_before = json.dumps(built, sort_keys=True)
    failed = 0
    if args.comp_image or args.all:
        try:
            build_comp_image(comp_dir, specs["comp"], built, dry_run=args.dry_run)
        except (SpecError, RuntimeError) as exc:
            log(f"✗ {exc}")
            failed += 1
    slugs = list(dict.fromkeys(args.slug)) if args.slug else (
        sorted(specs["challenges"]) if args.all else [])
    if not args.slug and not args.all and not args.comp_image:
        log(" nothing to build：用 --slug <slug> 指定题目，--all 构建全部，--comp-image 构建比赛层")
        return 0
    jobs = max(1, int(args.jobs))
    targets = []
    for slug in slugs:
        spec = specs["challenges"].get(slug)
        if not spec:
            log(f"✗ {slug}: env/challenges/{slug}.yaml 不存在")
            failed += 1
            continue
        targets.append((slug, spec))
    lock = threading.Lock()

    def _build_one(item):
        slug, spec = item
        try:
            build_one(comp_dir, slug, spec, specs["comp"], built,
                      force=args.force, dry_run=args.dry_run, lock=lock)
            return 0
        except (SpecError, RuntimeError) as exc:
            log(f"✗ {exc}")
            return 1

    if jobs > 1 and len(targets) > 1 and not args.dry_run:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            failed += sum(pool.map(_build_one, targets))
    else:
        for item in targets:
            failed += _build_one(item)
    if not args.dry_run and json.dumps(built, sort_keys=True) != built_before:
        save_built(comp_dir, built)
    if args.push and not args.dry_run:
        reg = args.push.rstrip("/")
        for rec in ([built.get("comp")] if built.get("comp") else []) + list(built.get("images", {}).values()):
            tag, image = rec.get("image"), rec.get("image")
            if not tag or rec.get("status") != "built":
                continue
            if "/" not in tag.split(":")[0]:
                image = f"{reg}/{tag}"
                subprocess.run(["docker", "tag", tag, image], check=False)
            log(f"[push] {image}")
            if subprocess.run(["docker", "push", image]).returncode != 0:
                log(f"✗ push 失败：{image}")
                failed += 1
    log(f"BUILD DONE failed={failed}")
    return 1 if failed else 0


def _cmd_status(args) -> int:
    comp_dir = args.comp_dir.resolve()
    data = status_data(comp_dir)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    log(f"比赛：{data['comp']}（{comp_dir.name}）  env spec：{'有' if data['has_env'] else '无（competition.py init 会创建骨架）'}"
        f"  解析器：{data['parser']}")
    for p in data["problems"]:
        log(f"  ⚠ {p}")
    log(f"Docker：{'可用' if data['docker_ok'] else '不可用'}  L0 {data['l0']['image']}: "
        f"{'✓' if data['l0']['ok'] else '✗'}")
    missing_l1 = [c for c, v in data["l1"].items() if not v["ok"]]
    log(f"L1 题型层：{len(data['l1']) - len(missing_l1)}/{len(data['l1'])} 就绪"
        + (f"（缺 {', '.join(missing_l1)} → preheat）" if missing_l1 else ""))
    l2 = data.get("l2") or {}
    if l2:
        log(f"L2 比赛层：{'✓ ' + l2['image'] if l2.get('image') else '未构建（--comp-image）'}"
            f"  最新 spec → {l2.get('tag_hint', '')}")
    for ch in data["challenges"]:
        rec = ch.get("built") or {}
        state = f"✓ {rec['image']}" if rec.get("image") else ("骨架" if not ch["customized"] else "未构建")
        drift = "（spec 已改，需重建）" if ch.get("stale") else ""
        svc = " · services" if ch.get("services") else ""
        log(f"  [{ch['category']:9s}] {ch['slug']:28s} {state}{drift}{svc}")
    return 0


def _cmd_verify(args) -> int:
    comp_dir = args.comp_dir.resolve()
    built = read_built(comp_dir)
    specs = load_specs(comp_dir)
    targets: list[tuple[str, str]] = []  # (image, category)
    if args.image:
        targets.append((args.image, args.category or "misc"))
    for slug in args.slug or []:
        rec = (built.get("images") or {}).get(slug) or {}
        if not rec.get("image"):
            log(f"✗ {slug}: 未构建（先 build --slug {slug}）")
            return 2
        targets.append((str(rec["image"]),
                        str(rec.get("category") or specs["challenges"].get(slug, {}).get("category") or "misc")))
    if not targets:
        log(" nothing to verify：用 --slug 或 --image 指定目标")
        return 0
    failed = 0
    for image, category in targets:
        log(f"[verify] {image}（{category}）")
        report = verify_image(image, category, list(args.probe or []))
        for r in report["results"]:
            log(f"  {'✓' if r['ok'] else '✗'} {r['probe']}" + (f"  → {r['detail']}" if r["detail"] else ""))
        if not report["ok"]:
            failed += 1
    log(f"VERIFY DONE failed={failed}")
    return 1 if failed else 0


def _cmd_export(args) -> int:
    comp_dir = args.comp_dir.resolve()
    out = Path(args.out) if args.out else comp_dir / "env-export.tar"
    result = export_images(comp_dir, args.slug or [], out, with_spec=args.with_spec)
    log(f"[export] {result['out']}（{len(result['images'])} 个镜像）")
    if result.get("spec_archive"):
        log(f"[export] spec 归档：{result['spec_archive']}")
    return 0


def _cmd_preheat(args) -> int:
    comp_dir = args.comp_dir.resolve() if args.comp_dir else None
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] if args.categories else None
    result = preheat(comp_dir, cats, check_only=args.check, rebuild=args.rebuild)
    if args.check:
        for m in result["missing"]:
            log(f"  缺 {m['tier']} {m['image']}")
        log(f"PREHEAT CHECK missing={len(result['missing'])}")
        return 0
    for b in result.get("built", []):
        log(f"  ✓ {b['tier']} {b['image']}")
    log("PREHEAT DONE")
    return 0


def _cmd_render(args) -> int:
    comp_dir = args.comp_dir.resolve()
    specs = load_specs(comp_dir)
    built = read_built(comp_dir)
    if args.comp:
        base = str(specs["comp"].get("base") or L0_TAG)
        print(render_dockerfile(str(specs["comp"].get("comp") or comp_dir.name),
                                "_comp", specs["comp"], base, specs["comp"].get("mirrors")))
        return 0
    slug = args.slug or ""
    spec = specs["challenges"].get(slug)
    if not spec:
        log(f"✗ env/challenges/{slug}.yaml 不存在")
        return 2
    merged = merged_spec(specs["comp"], spec)
    problems = validate_spec(comp_dir, str(specs["comp"].get("comp") or comp_dir.name),
                             slug, merged, is_challenge=True)
    for p in problems:
        log(f"⚠ {p}")
    print(render_dockerfile(str(specs["comp"].get("comp") or comp_dir.name), slug, merged,
                            base_for(str(specs["comp"].get("comp") or comp_dir.name), slug,
                                     str(merged.get("category") or "misc").lower(), spec, built),
                            merged.get("mirrors")))
    if merged.get("services"):
        doc, problems2 = compose_dict(str(specs["comp"].get("comp") or comp_dir.name), slug, merged)
        if problems2:
            for p in problems2:
                log(f"⚠ {p}")
        print("\n# ---- compose.yaml ----")
        print(yaml_dump(doc))
    return 0


def _cmd_sync(args) -> int:
    result = sync_solver_assets(check_only=args.check)
    if args.check:
        for c in result["changed"]:
            log(f"  漂移：{c}")
        log(f"SYNC CHECK drift={len(result['changed'])}")
        return 1 if result["changed"] else 0
    for c in result["changed"]:
        log(f"  ✓ 写入 {c}")
    log(f"SYNC DONE files={len(result['changed'])}")
    return 0


def _cmd_clean(args) -> int:
    result = prune_env_images(args.comp_dir.resolve(), keep_days=args.keep_days,
                              dry_run=args.dry_run)
    for tag in result["removed"]:
        log(f"  {'[dry] 将删除' if args.dry_run else '✓ 已删除'} {tag}")
    log(f"CLEAN DONE removed={len(result['removed'])} kept={result['kept']}")
    return 0


def _cmd_rebuild_base(args) -> int:
    result = rebuild_base()
    log(f"REBUILD BASE DONE synced={result['synced']}")
    return 0


def _cmd_push(args) -> int:
    result = push_images(args.comp_dir.resolve(), args.slug or [],
                         registry=args.registry, include_comp=not args.no_comp)
    log(f"PUSH DONE ok={result['ok']} pushed={sum(1 for r in result['results'] if r['ok'])}"
        f"/{len(result['results'])}")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
        sys.stderr.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="构建 L2 比赛层 / L3 题目层镜像")
    p.add_argument("comp_dir", type=Path)
    p.add_argument("--slug", action="append", default=[], help="题目 slug（可重复）")
    p.add_argument("--all", action="store_true", help="构建比赛层 + 全部题目 spec")
    p.add_argument("--comp-image", action="store_true", help="构建 L2 比赛层")
    p.add_argument("--force", action="store_true", help="无定制内容的 spec 也强制构建")
    p.add_argument("--dry-run", action="store_true", help="只渲染 gen/ 产物，不调用 docker")
    p.add_argument("--push", default="", metavar="REG", help="构建后推送到镜像仓库（如 registry/namespace）")
    p.add_argument("--jobs", type=int, default=2, help="题目层并行构建数（默认 2；1=串行）")

    p = sub.add_parser("status", help="spec / 镜像 / 漂移一览")
    p.add_argument("comp_dir", type=Path)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("verify", help="镜像探针矩阵（工具存在性 + 版本断言）")
    p.add_argument("comp_dir", type=Path)
    p.add_argument("--slug", action="append", default=[])
    p.add_argument("--image", default="")
    p.add_argument("--category", default="misc")
    p.add_argument("--probe", action="append", default=[], help="追加探针命令（容器内 sh -c）")

    p = sub.add_parser("export", help="docker save 导出比赛镜像")
    p.add_argument("comp_dir", type=Path)
    p.add_argument("--slug", action="append", default=[])
    p.add_argument("--out", default="")
    p.add_argument("--with-spec", action="store_true", help="附带 env/ 归档（gen/context 除外）")

    p = sub.add_parser("preheat", help="预热 L0/L1 底座与题型层")
    p.add_argument("comp_dir", type=Path, nargs="?", default=None)
    p.add_argument("--categories", default="", help="逗号分隔题型（缺省按 env spec 推断）")
    p.add_argument("--check", action="store_true", help="只检查缺失，不构建")
    p.add_argument("--rebuild", action="store_true", help="强制重建（忽略已有镜像）")

    p = sub.add_parser("render", help="打印渲染产物（调试）")
    p.add_argument("comp_dir", type=Path)
    p.add_argument("--slug", default="")
    p.add_argument("--comp", action="store_true", help="渲染比赛层")

    p = sub.add_parser("sync-solver", help="同步约束层资产进 L0 构建上下文（CLAUDE.md/AGENTS.md + skill 包）")
    p.add_argument("--check", action="store_true", help="只检查漂移，不写入")

    p = sub.add_parser("rebuild-base", help="重建 L0 底座（先 sync-solver 再 build，约束层随镜像更新）")

    p = sub.add_parser("push", help="推送已构建镜像到仓库（凭证只在本机 docker login）")
    p.add_argument("comp_dir", type=Path)
    p.add_argument("--slug", action="append", default=[])
    p.add_argument("--registry", default="", help="仓库地址（缺省读 workbench-data/registry.json）")
    p.add_argument("--no-comp", action="store_true", help="不推比赛层")

    p = sub.add_parser("clean", help="清理旧的比赛/题目层镜像（磁盘卫生）")
    p.add_argument("comp_dir", type=Path)
    p.add_argument("--keep-days", type=int, default=7, help="保留最近 N 天构建的镜像（默认 7）")
    p.add_argument("--dry-run", action="store_true", help="只列出将删除的镜像")

    args = ap.parse_args(argv)
    try:
        return {"build": _cmd_build, "status": _cmd_status, "verify": _cmd_verify,
                "export": _cmd_export, "preheat": _cmd_preheat, "render": _cmd_render,
                "sync-solver": _cmd_sync, "clean": _cmd_clean,
                "push": _cmd_push, "rebuild-base": _cmd_rebuild_base}[args.cmd](args)
    except SpecError as exc:
        log(f"✗ spec 错误：{exc}")
        return 2
    except RuntimeError as exc:
        log(f"✗ {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
