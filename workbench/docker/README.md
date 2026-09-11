# CTF Workbench 沙箱镜像

分层设计参考 [CTF-BTFly](https://github.com/huihuilikaile/CTF-BTFly) 的 `images/`（MIT License），
并在其留白处加强：**默认断网**、任务级超时强停、`--cap-drop ALL`。

## 镜像清单

所有题型层都 `FROM ctfbox-base:0.1.0`，是薄增量层；目录名与 `resolve_competition` 的
题目类别一一对应，server 按 case 的 category 自动选择，未构建时回落 `ctfbox-misc`。

| 镜像 | 基座 | 关键内容 | 用途 |
|---|---|---|---|
| `ctfbox-base:0.1.0` | `python:3.11-slim` | 通用 CLI、`ctf` 用户、`/workspace` 约定、`PIP_MIRROR` 构建参数 | 所有题型层的公共基座，本身也可兜底执行 |
| `ctfbox-misc:0.1.0` | base | pycryptodome 3.20 · gmpy2 2.1.5 · sympy 1.13.3 · z3-solver 4.13.4 · requests · beautifulsoup4 · pillow · numpy | Misc / 编码链 / 综合小题 |
| `ctfbox-crypto:0.1.0` | base | gmpy2 2.2.1 · pycryptodome 3.23.0 · sympy 1.14.0 · z3-solver 4.15.1 | 密码学：格子/Coppersmith/SMT |
| `ctfbox-pwn:0.1.0` | base | pwntools 4.14.1 · ropper 1.13.13 | 二进制利用；运行时自动追加 `--cap-add SYS_PTRACE` |
| `ctfbox-web:0.1.0` | base | beautifulsoup4 4.13.4 · httpx 0.28.1 · pyjwt 2.10.1 · requests 2.32.4 | Web 题脚本化打点 |
| `ctfbox-reverse:0.1.0` | base | angr 9.2.170 | 符号执行 / 约束求解 |
| `ctfbox-forensics:0.1.0` | base | oletools 0.60.2 · scapy 2.6.1 · volatility3 2.26.2 | 取证：文档、流量、内存镜像 |

体积以本地实际构建结果为准，可用
`docker images --filter reference='ctfbox-*' --format '{{.Repository}} {{.Size}}'` 查看。

## 构建

在 `workbench/docker/` 目录下执行（首次全量构建约需 6.5GB 磁盘，走 `PIP_MIRROR` 可换源）：

```bash
docker build -f base/Dockerfile      -t ctfbox-base:0.1.0      .
docker build -f misc/Dockerfile      -t ctfbox-misc:0.1.0      .
docker build -f crypto/Dockerfile    -t ctfbox-crypto:0.1.0    .
docker build -f pwn/Dockerfile       -t ctfbox-pwn:0.1.0       .
docker build -f web/Dockerfile       -t ctfbox-web:0.1.0       .
docker build -f reverse/Dockerfile   -t ctfbox-reverse:0.1.0   .
docker build -f forensics/Dockerfile -t ctfbox-forensics:0.1.0 .
```

## 运行约定

由 workbench server 自动拼装，无需手写 `docker run`：

- `-v <case目录>:/workspace` — 读写（attachments 进，artifacts / WRITEUP 出）
- `-v <workbench目录>:/solver:ro` — 只读（`{solver_dir}` 占位符 → `/solver`）
- `--network none`（默认，可配置 `bridge`；启用模型网关时自动切 `bridge`）
- `--cap-drop ALL`、`--security-opt no-new-privileges`
- `--memory` / `--cpus` / `--pids-limit` 三限
- 容器名 `ctfwb-sbx-*`，超时由 server 看门狗 `docker stop` 强停
