# CTF Workbench

参考 [CTF-BTFly](https://github.com/huihuilikaile/CTF-BTFly)（本地源码存档见 `tools/CTF-BTFly-1.3.1-source/`）的工作台形态：题目看板、事件时间线、Flag 人工审核、任务派发与实时输出、系统概况。**纯 Python 标准库 + 原生 JS，零新依赖，离线可用，默认仅绑定 127.0.0.1。**

## 启动

```bash
python solve-ai-ctf/workbench/server.py            # http://127.0.0.1:8787（仅本机）
python solve-ai-ctf/workbench/server.py --open     # 启动后自动开浏览器
python solve-ai-ctf/workbench/server.py --port 9000 \
  --agent-cmd "python -u {solver_dir}/demo_solver.py {prompt_file}"   # 启用任务派发
```

- `--agent-cmd`：求解命令模板，占位符 `{prompt_file}`（生成的提示词文件）、`{case_dir}`（题目工作区）、`{solver_dir}`（workbench 目录，含空格路径已自动加引号）。接真实 Agent 时替换为自己的求解器；不配置则任务页只读提示词。
- 服务自动扫描 `比赛/*/`（未初始化的目录显示空态）；右上角下拉切换比赛。

### 多机共享（局域网 / Tailscale，多 AI 协作）

```bash
python solve-ai-ctf/workbench/server.py --host 0.0.0.0 --token <自定义口令>
```

- `--host 0.0.0.0` 时启动横幅**自动列出所有网卡地址**（局域网 192.168.x、Tailscale/WSL 虚拟网卡等），其它机器的 Agent/浏览器直接访问对应地址。
- `--token`（或环境变量 `WB_TOKEN`）开启令牌鉴权：所有 `/api` 请求需带 `Authorization: Bearer <token>`（或 `?token=`）；浏览器首次打开会弹窗输入一次（存 localStorage）。
- **多 Agent 协作入口**：`GET /api/help` 返回完整 API 清单与建议协作流程（取提示词 → 登记 attempt/假设 → candidate 推进 → dry-run 由人工放行）。写操作全部经脚本层校验，多 Agent 并发也不绕过审计。
- ⚠ 不设令牌对局域网开放时，同网段可读取全部比赛数据（submit.live 仍需 confirm），启动日志会显著警告。

## 功能页（对照 CTF-BTFly 与老 warroom 面板）

| 标签 | 内容 | 来源 |
|---|---|---|
| 总览 | 按类别分组的题目卡：状态点、分值、假设/尝试/候选计数、得分进度 | BTFly 全部题目 |
| 题目 | **8 个子页签工作区**：概览（状态流条 + 题面 + 分诊摘要 + 工作区统计）/ 假设阶梯 / 尝试记录（带执行者标签）/ 证据线索 / **排除·失败**（rejected 假设 + 失败尝试，防重复踩坑）/ Flag 候选快审 / **提示词**（continue/fresh/submit/review 四模板 + 一键复制）/ **守则**（SKILL.md 精华） | BTFly 题目工作区 + 老 warroom 七页签 |
| AI 看板 | **多泳道时间线 SVG**：题目事件按 kind 着色、求解任务为跨度条并带 **Agent 彩色标签**；时间窗 6h～30d 可调 | 老 warroom 泳道时间线 |
| Flag 审核 | **🚩 Flag 猎手**（专职代理：一键派发，自主扫描全部 case → 对照 flag 正则校验 → 误报黑名单过滤 → 高置信自动 validated）→ **✅ 可用标志** 区即时展示，每枚带一键提交；**自动提交开关**（默认关）：开启后 dry-run 通过即 `--live`，每轮限额保护 | BTFly 人工审核门的自动化延伸 |
| 运行任务 | 按命令模板派发求解任务（带**执行者标签**），输出实时 tail、可停止；任务记录持久化于 `workbench-data/` | BTFly 任务生命周期 + Pi RPC 输出 |
| 系统概况 | 执行链路图 + 健康卡（服务/脚本层/self_test/Docker/命令模板/数据统计，30s 缓存） | BTFly 系统概况 |
| 时间线 | `events.jsonl` 事件流，**SSE 实时推送**（断线自动重连） | BTFly WebSocket 推送 |
| 文件 / 日志 | case 或整个比赛根目录的只读文件树 + 内容查看（二进制标注，单文件 2MB） | BTFly 文件浏览 |
| 知识库 / 提示词 | `kb_search.py` 检索；按 case 上下文生成 Agent 提示词 | BTFly 提示词模板 |
| 文档 / WP | `docs/*.md` 渲染（迷你 markdown，支持表格/代码块）；题目页可生成 WRITEUP 草稿 | BTFly 解题报告 |
| 比赛动作 | **开赛自动化代理**：🔌 自动对接平台（探测 CTFd 系 API → 自动写入提交脚本配置）+ 📥 自动抓题注册（拉列表逐题建 case）——进度均在「运行任务」页实时可见；另有注册题目、优先级、warroom、追加事件 | — |

## Docker 沙箱执行（参考 CTF-BTFly 落地）

派发任务时勾选「Docker 沙箱执行」，求解器不再跑在宿主机，而是进容器：

- **镜像分层全家桶**（`workbench/docker/`，改编自 BTFly 的 MIT 镜像，工具版本沿用其验证清单）：
  `ctfbox-base`（python-slim + 通用 CLI）→ 按题目类别自动选择：`ctfbox-crypto`（john/gmpy2/z3）、
  `ctfbox-pwn`（pwntools/gdb/qemu，运行时自动 `--cap-add SYS_PTRACE`）、`ctfbox-web`（nmap/sqlmap/gobuster）、
  `ctfbox-reverse`（angr/apktool/strace）、`ctfbox-forensics`（volatility3/tshark/yara）、`ctfbox-misc`（通用兜底）。
  类别镜像未构建时自动回落默认镜像。
- **安全模型**（对齐 BTFly `internal/sandbox/manager.go` 并补上其留白）：
  `--cap-drop ALL` + `--security-opt no-new-privileges` + `--memory/--cpus/--pids-limit` 三限 + 容器名 `ctfwb-sbx-*` 便于对账；**默认 `--network none`**（BTFly 实际用 bridge，我们加严）；**服务端看门狗**超时强制 `docker stop`（BTFly 无任务级超时）。
- **文件交换**：单一 bind mount 双向读写——`case 目录 ↔ /workspace`（附件进、artifacts/WRITEUP 出）、`workbench 只读 ↔ /solver`；命令模板占位符在沙箱下映射为容器内路径（`{prompt_file}`→`/workspace/scratch/agent-prompt.txt`）。容器 `--rm` 用完即清，无需 docker cp/exec。
- **构建**（首次使用前执行一次，走清华源；全家桶约 6.5GB 磁盘）：
  ```bash
  cd solve-ai-ctf/workbench/docker
  docker build -f base/Dockerfile -t ctfbox-base:0.1.0 .
  docker build -f misc/Dockerfile -t ctfbox-misc:0.1.0 .
  docker build -f crypto/Dockerfile -t ctfbox-crypto:0.1.0 .
  docker build -f pwn/Dockerfile -t ctfbox-pwn:0.1.0 .
  docker build -f web/Dockerfile -t ctfbox-web:0.1.0 .
  docker build -f reverse/Dockerfile -t ctfbox-reverse:0.1.0 .
  docker build -f forensics/Dockerfile -t ctfbox-forensics:0.1.0 .
  ```
- **配置**：`POST /api/sandbox`（enabled/image/images/network/memory/cpus/pids/timeout_min/cmd/gateway/upstream_base），任务页勾选框旁实时显示 Docker 与镜像状态。

### 模型网关（API key 不下容器，沿用 BTFly modelgateway 思路）

容器内 AI 求解器需要调模型时，勾选「模型网关」派发任务：

1. server 生成**一次性任务令牌**，经 `-e OPENAI_API_KEY=<token>` 注入容器（真实上游 key 只在宿主环境变量）；
2. 容器内 `OPENAI_BASE_URL` 指向 `http://host.docker.internal:<port>/gw/<token>/v1`（此时沙箱自动切 `bridge` 网络）；
3. server 的 `/gw/<token>/…` 路由校验令牌后**流式转发**到上游（`sandbox.json` 的 `upstream_base` + 环境变量密钥），并按令牌记账（请求数/字节数）；
4. 任务结束（done/failed/lost）令牌自动撤销。

```bash
# 网关所需环境变量
export WB_UPSTREAM_BASE="https://api.openai.com"     # 或自建中转
export OPENAI_API_KEY="sk-..."                        # 真实 key 只存宿主
```

- 停止沙箱任务 = `docker stop`（区别于宿主任务的信号终止）。

## Flag 自主闭环（猎手 → 可用标志 → 提交）

```
比赛开始 → 点「启动猎手扫描」（或经任务系统定时派发）
  → flag_hunter.py：扫描全部 case → 对照题目 flag 正则自主校验（误报黑名单兜底）
  → 高置信候选自动 validated → 前端「✅ 可用标志」即时展示
  → 人工点「提交…」走 dry-run 预览后放行；或开启「自动提交」由猎手直接 dry-run→--live（每轮限额）
```

- 提交脚本即 `scripts/submitter.py`：平台适配器（`config/platform.template.json`）+ 滑动窗口限速 + flag 哈希去重，猎手只是它的调用方。
- 猎手是确定性脚本（`workbench/flag_hunter.py`，零依赖可独立运行）；需要真正"读题解题"的 AI 智能体，用题目页「提示词」的 submit 模板派发任务即可，产出的候选同样汇入本闭环。
- 安全层级：误报黑名单 → 正则校验 → dry-run 预览 → 限额（默认 3/轮）→ submitter 去重。每层都可独立拦截。

## 开赛自动化（对接 → 抓题 → 解题 → 提交 全链路）

比赛开始后的标准节奏，每一步都有专职代理与实时进度（「运行任务」页看输出流）：

```
① 🔌 自动对接平台（platform-agent）
   探测 CTFd 系 API → 写入 platform 段（列表/提交端点）→ 提交脚本即就绪
② 📥 自动抓题（chall-agent）
   拉取题目列表 → 逐题自动注册 case（附件手动放入 artifacts/）
③ ⚡ 派发求解（solver 任务，可选 Docker 沙箱 + 模型网关）
④ 🚩 Flag 猎手（默认自动提交抢一血）→ 🎉 全局 toast 报喜
```

- 前置：环境变量设置平台令牌（如 `CTF_TOKEN`，见比赛管理页显示的变量名）
- 代理均为确定性脚本：`workbench/platform_agent.py`、`workbench/fetch_challs.py`，可独立 CLI 运行
- 对接代理目前覆盖 CTFd 系形态；其它平台需人工对照 `config/platform.template.json` 填列表端点后，抓题代理即可工作

## 架构约定

- **server.py 只做两件事**：读 JSON 数据文件渲染 API；把写操作以 list-argv 子进程转发给 `solve-ai-ctf/scripts/` 既有脚本。校验、状态机、限速、去重都在脚本里，UI 不重写。
- **安全**：默认仅 127.0.0.1；路径防目录穿越；动作白名单 + 枚举二次校验；`submit.live` 需显式 `confirm:true`；凭证只走环境变量；共享模式务必配 `--token`。
- **数据不变**：artifacts 不可变；UI 写操作全部经脚本落盘。

## 测试

```bash
python solve-ai-ctf/workbench/test_workbench.py   # 临时目录起真实服务，41 项断言（含令牌鉴权/看板/提示词模板）
python solve-ai-ctf/scripts/self_test.py          # 既有脚本回归
```

## 路线图（对照 CTF-BTFly 尚未实现）

- Windows 原生沙箱（BTFly 2.7.2 的 sandbox-broker/runner 方案）或 Docker 沙箱执行
- 多模型/多 Agent 协作模式（黑板/超级模式）；MCP Server 绑定与 Tool Pack 管理
- 模型用量统计；主题系统
