# CTF Workbench 沙箱镜像

CTF 解题容器环境：按题型分层的工具链镜像，每题开环境即用，AI/队员无需自行安装工具。

## 快速构建

```bash
# 在本目录（docker/）下执行——先建底座再建题型层
docker build -f base/Dockerfile -t ctfbox-base:0.1.0 .

# 全部题型（约 6.5GB 磁盘，首次 5-10 分钟）
for cat in misc crypto pwn web reverse forensics ai; do
  docker build -f $cat/Dockerfile -t ctfbox-$cat:0.1.0 .
done

# 或只建你需要的
docker build -f crypto/Dockerfile -t ctfbox-crypto:0.1.0 .
```

> 国内网络自动走清华镜像源（apt + pip BuildKit cache），无需额外配置。

## 镜像矩阵

| 镜像 | 体积 | 核心工具链 |
|---|---|---|
| ctfbox-base | 379M | python3-slim + bash/git/curl/jq/ripgrep/netcat + tini + /workspace 约定 |
| ctfbox-crypto | 650M | RsaCtfTool + John/hashcat + PARI-GP + pycryptodome/gmpy2/z3 |
| ctfbox-pwn | 1.7G | pwntools + gdb + OneGadget + checksec + qemu-user + 32 位库 |
| ctfbox-web | 611M | sqlmap + gobuster/nmap/whatweb + pyjwt/httpx + flask + mysql/redis 客户端 |
| ctfbox-forensics | 777M | volatility3 + tshark + binwalk/foremost + steghide + yara/exiftool |
| ctfbox-reverse | 1.6G | angr 符号执行 + radare2 + apktool + strace/ltrace |
| ctfbox-misc | 834M | ffmpeg/sox + ImageMagick + pyzbar + pytesseract + pillow |
| ctfbox-ai | ~400M | openai/anthropic/tiktoken（提示注入与 agent 攻防题） |

分层模型（详细设计见 [COMPETITION_ENV_DESIGN.md](COMPETITION_ENV_DESIGN.md)）：

```
L0 ctfbox-base            通用底座
L1 ctfbox-<category>      题型工具链（本目录）
L2 ctf-<comp>             比赛层（可选，env/comp.yaml）
L3 ctf-<comp>-<slug>      题目层（按需，env/challenges/<slug>.yaml）
```

## 使用

镜像由 [CTF Workbench](../workbench/) 的题目容器环境自动调用——AI 领题后 `POST /api/agent-gw/env {"slug":"...","action":"open"}` 即开容器，`action:"exec"` 在容器内执行命令，附件挂载 `/workspace`（读写），产物落回 case 目录。

也可手动使用：

```bash
docker run --rm -it --cap-drop ALL --network none   -v "$(pwd):/workspace" -w /workspace ctfbox-crypto:0.1.0 bash
```

## 安全

容器运行时由 Workbench 服务端统一施加：`--cap-drop ALL` + `no-new-privileges` + 内存/CPU/Pids 三限 + 默认断网 + TTL 看门狗回收。镜像本身不含任何豁免。

## 致谢

分层模型与安全设计参考 [CTF-BTFly](https://github.com/huihuilikaile/CTF-BTFly)（MIT License）。
