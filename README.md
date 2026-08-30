# Solve-AI-CTF

AI 驱动的 CTF 解题工作台：**分诊 → 假设 → 有界执行 → 验证 → 提交 → 复盘** 全流程留痕，内置本地 Web 控制台、Docker 沙箱执行、Flag 自动识别与抢一血式自动提交、多 Agent 协作接口。

> 仅用于**已授权**的 CTF 比赛、靶场与安全研究。请勿用于未授权目标。

## 特性

- **确定性工具链**（纯 Python 标准库，零 pip 依赖，可离线）：比赛/题目/case 状态机、附件静态分诊、flag 扫描校验、提交器（平台适配器 + 限速 + 去重）
- **本地 Web 工作台**（`workbench/`）：题目看板、方向导航、假设阶梯/尝试/证据工作区、AI 看板泳道时间线、SSE 实时事件、文件浏览、知识库检索
- **开赛自动化代理**：自动对接平台（探测 CTFd 系 API → 写提交脚本配置）、自动抓题批量注册、Flag 猎手（自主扫描校验 → 抢一血式自动提交 → 全局 toast 报喜）
- **Docker 沙箱执行**：按题目类别自动选镜像（crypto/pwn/web/reverse/forensics/misc 七层），`--cap-drop ALL` + 资源三限 + 默认断网 + 超时看门狗强停
- **模型网关**：容器内 AI 求解器经一次性任务令牌调用上游模型，真实 API key 不下容器，按令牌记账
- **多 Agent 协作**：局域网/Tailscale 共享（`--host 0.0.0.0 --token`），`GET /api/help` 即完整协作 API
- **知识库**：题型 Playbook + 分诊路由 + 案例语料，`kb_search.py` 检索

## 快速开始

```bash
# 起本地工作台（浏览器打开 http://127.0.0.1:8787）
python solve-ai-ctf/workbench/server.py --open

# 开赛三步（比赛管理页点按钮，或 CLI）：
python solve-ai-ctf/workbench/platform_agent.py 比赛/xxx   # ① 对接平台，写提交配置
python solve-ai-ctf/workbench/fetch_challs.py 比赛/xxx     # ② 自动抓题注册
# ③ 页面派发求解任务（可勾 Docker 沙箱 / 模型网关）

# Flag 猎手：自动扫描全部 case → 校验 → 自动提交抢一血
python solve-ai-ctf/workbench/flag_hunter.py 比赛/xxx
```

平台令牌只放环境变量（如 `CTF_TOKEN`），绝不写入文件。

### BUUCTF（buuoj.cn）开箱即用

```bash
export CTF_CREDENTIALS_JSON='{"username": "你的账号", "password": "你的密码"}'
python solve-ai-ctf/workbench/server.py
# 比赛管理 → 开赛自动化 → 「套用预设并自动对接」→「派发抓题代理」
```
预设含表单登录（nonce CSRF）与会话拉题（/api/v1/challenges.cache），全站 1900+ 题可自动注册。

## Docker 沙箱

```bash
cd solve-ai-ctf/workbench/docker
docker build -f base/Dockerfile -t ctfbox-base:0.1.0 .
docker build -f misc/Dockerfile -t ctfbox-misc:0.1.0 .
# 其余题型层（pwn/web/crypto/reverse/forensics）按需构建，见 docker/README.md
```

## 测试

```bash
python solve-ai-ctf/workbench/test_workbench.py   # 端到端 56 项断言（含 mock 平台/令牌/代理）
python solve-ai-ctf/scripts/self_test.py          # 工具链自检
```

## 架构

```
workbench/server.py   ← 数据 API + 动作白名单（list-argv 子进程调用 scripts/）
  ├── scripts/        ← 状态机与校验层（competition/case_manager/triage/submitter/kb_search）
  ├── workbench/      ← Web 控制台 + 专职代理（platform_agent/fetch_challs/flag_hunter）
  ├── docker/         ← 沙箱镜像（base + 六题型层）
  └── references/     ← 知识库（4 题型 Playbook + 路由/语料/评测）
```

所有写操作都经脚本层校验后落盘——Web UI 不重写任何状态机逻辑，多 Agent 并发也不绕过审计。

## 安全设计

- 未知附件只做静态分诊，绝不直接执行
- 沙箱：cap-drop ALL、no-new-privileges、内存/CPU/Pids 三限、默认断网、超时强停
- 提交：默认 dry-run，`--live` 需显式确认；滑动窗口限速 + flag 哈希去重
- 凭证只存环境变量；模型网关一次性令牌，上游 key 不下容器
- 共享模式强制 `--token` 鉴权

## 致谢

[Docker 镜像分层与安全模型](workbench/docker/) 参考了 [CTF-BTFly](https://github.com/huihuilikaile/CTF-BTFly)（MIT License）的设计，并在其留白处（默认断网、任务超时）做了加强。

## License

[MIT](LICENSE)

---

## 文档

- [CHANGELOG.md](CHANGELOG.md) — 更新日志
- [ROADMAP.md](ROADMAP.md) — 未来更新计划
