# CTF Workbench 沙箱镜像

题型分层的沙箱镜像（参考 CTF-BTFly images/，MIT License）+ 比赛/题目级定制环境
（[COMPETITION_ENV_DESIGN.md](COMPETITION_ENV_DESIGN.md)）。

## 镜像矩阵

```
L0 ctfbox-base       python-slim 底座：通用 CLI + tini + ctf 用户 + /workspace 约定
                     + 烤入约束层（CLAUDE.md/AGENTS.md + 七类题型 skill 包）
L1 ctfbox-<category> 题型层，按需构建：
                       misc      binwalk/exiftool/7z + pycryptodome/gmpy2/z3/requests/pillow
                       crypto    john + gmpy2/pycryptodome/sympy/z3
                       pwn       gdb/checksec/qemu-user/patchelf + pwntools/ropper
                       web       dirb/gobuster/nmap/sqlmap/whatweb + requests/bs4/pyjwt
                       reverse   apktool/jd-gui 运行库/ltrace/strace + angr
                       forensics binwalk/foremost/exiftool/sleuthkit/tshark/yara + volatility3/scapy
                       ai        openai/anthropic/tiktoken/jsonlines（提示注入与 agent 攻防题）
L2 ctf-<comp>        比赛层（可选）：比赛统一工具/私有脚本，env spec comp.yaml 定义
L3 ctf-<comp>-<slug> 题目层（按需）：精确 glibc、题目依赖、services 复现栈
```

## 构建命令

```bash
cd solve-ai-ctf/workbench/docker
docker build -f base/Dockerfile -t ctfbox-base:0.1.0 .
docker build -f misc/Dockerfile -t ctfbox-misc:0.1.0 .
# 其余题型层按需：pwn / web / crypto / reverse / forensics / ai
# 或一键预热（按比赛 env spec 推断题型）：
python solve-ai-ctf/workbench/env_builder.py preheat 比赛/xxx
```

约束层资产由生成器维护（勿手改 `base/CLAUDE.md`、`base/AGENTS.md`、`base/skills/`）：

```bash
python solve-ai-ctf/workbench/env_builder.py sync-solver          # 生成/同步
python solve-ai-ctf/workbench/env_builder.py sync-solver --check  # 漂移检查
```

源文件：`base/../envs/solver/CLAUDE.md`（工作区约定+红线）与 `../../references/playbooks-*.md`
（题型方法论 skill 包）。改完重跑 sync + 重建 L0（L1/L2/L3 重构建后继承）。

## 运行约定（由 workbench server 自动拼装）

- `-v <case目录>:/workspace` 读写（attachments 进、artifacts/WRITEUP 出）；workbench 目录 → `/solver:ro`
- `--cap-drop ALL` + `--security-opt no-new-privileges` + 内存/CPU/Pids 三限（spec 只许收紧）
- 默认 `--network none`；多服务题目加入 compose internal 网络；网关开启时附加 bridge
- 容器名 `ctfwb-<taskID>`，超时由 server 看门狗 `docker stop`（有 services 时连带 `compose down -v`）
- pwn 类目自动加回 `SYS_PTRACE`；spec 可显式声明 `run.caps` 白名单
