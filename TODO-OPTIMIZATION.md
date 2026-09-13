# TODO-OPTIMIZATION — 待优化清单（2026-09-12 全项目审查）

> 面向接手者。本文档由 2026-09-04 ~ 09-12 四轮代码审查汇总而成，覆盖 workbench 前后端、
> 脚本层、平台对接层、沙箱、知识库与仓库工程。每条含**问题描述 / 影响范围 / 优先级 / 建议方案**。
> 做完一项就把它移到文末「已完成」并补一行记录。

## 项目快照（接手前先读）

- **架构**：`workbench/server.py`（HTTP API + 动作白名单，纯标准库）→ `scripts/`（状态机与校验层，
  所有写操作经此落盘）→ `比赛/<赛事>/`（数据真源：`competition.json` / `cases/*/case.json` /
  `events.jsonl` / `submissions.jsonl`）。Web UI 在 `workbench/static/`（原生 ES module + vendored
  petite-vue，无构建）。
- **测试基线**：`scripts/self_test.py`（工具链，含 mock 平台/429 故障注入）全绿；
  `workbench/test_workbench.py` 端到端 **138 通过 / 0 失败**（含 CSP 质量门、注入回归、幂等回归）。
  改动后这两个必须全绿再提交。
- **安全基线**：CSP `script-src 'self'`（无 unsafe-eval）、nosniff、Referrer-Policy 全响应路径注入；
  宿主侧已无 `shell=True`；`--host 0.0.0.0` 无 token 硬拒绝；Origin 白名单覆盖全部本机地址；
  `/api/agent/start` 参数白名单。这些都有回归断言守着——**改 CSP/鉴权相关代码前先看断言**。
- **同步流程**：开发在 `solve-ai-ctf/`，发布靠 `scripts/sync_publish.py`（复制 + 一致性校验），
  然后从 `_publish/solve-ai-ctf` 推 GitHub。别手工 cp（历史上漂移过两次）。

---

## P0 — 尽快处理

### T-01 发布副本被外部机制清空载荷类文档（8 份知识库文件缺失）

- **问题描述**：`references/` 的 8 份文档（SQL.md / SSTI.md / PAYLOAD-CHEATSHEET.md /
  PHP反序列化漏洞总结.md / php代码审计.md / 命令执行.md / 文件上传漏洞.md / 文件包含.md）
  写入 `_publish/solve-ai-ctf/references/` 后约 2 秒被移除。已排除：写入失败（117KB 校验通过后消失）、
  文件名因素（中性名也删）、脚本因素（cp/shutil/重试一致）、内容因素（同内容在主目录长期存在）。
  **连 git commit 都留不住**（对象入库但工作树被清空，status 永久显示已删除）。
- **影响范围**：公开仓库知识库 16/24 份；`AI-SEARCH-INDEX.md` 引用了不存在的条目；克隆者按索引
  找文件会 404。`sync_publish.py` 的 `UNDELIVERABLE` 集合已登记这 8 份（校验会跳过它们，别误删）。
- **优先级**：P0（仓库内容不完整，影响所有克隆者）
- **建议方案**：在宿主机常规终端（非沙箱）查杀软/EDR 的隔离记录，给 `_publish/` 加白名单后重跑
  `python scripts/sync_publish.py`；或临时改为从 GitHub Release/附件分发这批文档。

## P1 — 近期安排

### T-02 `server.py` 单文件 2268 行，职责耦合

- **问题描述**：HTTP 路由、任务生命周期、Docker 沙箱拼装、模型网关代理、SSE、视图缓存、
  平台代理派发全在一个文件里，四轮迭代从 1798 行涨到 2268。
- **影响范围**：任何新功能都在同一文件冲突；安全审查面大（本次注入修复就花在它上面）。
- **优先级**：P1（架构债，越晚拆越贵）
- **建议方案**：按职责拆包（保持零第三方依赖）：`http/`（路由+响应头）、`tasks/`（生命周期+看门狗）、
  `sandbox/`（容器参数）、`gateway/`（令牌+转发）、`platforms/`（配合 T-03）。分多次提交，每步跑
  `test_workbench.py`。**别与其他改动混在一个 commit。**

### T-03 平台适配器未抽象，CTFd/BUUCTF 逻辑散落四处

- **问题描述**：同一平台的知识分布在 `platform_agent.py`（探测）、`ctf_session.py`（登录/拉题）、
  `presets/*.json`（预设）、`fetch_challs.py`（字段映射/类别过滤），`competition.json` 里再写一份提交配置。
- **影响范围**：新增平台要改 4+ 个文件；平台行为变更（如 BUUCTF 改版）要到处找。
- **优先级**：P1（ROADMAP 短期第 1 项，尚未动工）
- **建议方案**：定义适配器接口（probe / login / list_challenges / submit / parse_response），
  CTFd 与 BUUCTF 各实现一个 adapter，`competition.json` 只声明 `adapter: buuctf`。
  验收：新增一个平台只加一个文件 + 一份预设。

### T-04 `flag_hunter` 默认 live 提交 vs README「默认 dry-run」的表述冲突

- **问题描述**：README 安全设计写「提交：默认 dry-run，`--live` 需显式确认」，而 flag 猎手
  `cfg.get("enabled", True)` **默认开启**且直接走 `--live`（受 `max_live` 限流）。
  `test_workbench.py` 断言了"默认开启"——这是有意的抢一血设计，但文档没有说明这个例外。
- **影响范围**：不知情的使用者在真实比赛里可能意外触发自动提交（虽有 dry-run 预检 + 限流 +
  flag 正则校验兜底）。
- **优先级**：P1（产品决策，二选一即可，半天工作量）
- **建议方案**：① 在 README 安全章节标注「Flag 猎手是显式启动的抢一血通道，默认自动 live，
  由 max_live 与正则校验保护」；② 或改默认关闭，同时更新测试断言。**选哪个由维护者拍板，
  当前代码实现是 ① 的语义。**

## P2 — 排期处理

### T-05 知识库缺可复现参数，语料来源单一

- **问题描述**：4 份题型 Playbook 多为要点式，缺「可直接复现的关键参数」（能力蓝图自己指出的短板）；
  `case-corpus.md` 案例语料主要来自单场比赛。
- **影响范围**：AI 求解器检索到 Playbook 后仍需现场摸索参数，提速有限。
- **优先级**：P2
- **建议方案**：① 每场比赛收尾按模板追加「题型/关键参数/决定性证据/失败方向」到 case-corpus；
  ② 每类题型补 1-2 个带完整参数的可复现条目；③ `kb_search.py` 加零命中查询统计反哺补洞。
  注意：新增 `references/*.md` 必须同时登记进 `CATEGORY_FILES` 或 `COMMON_FILES` 或
  `EXCLUDED_FROM_SEARCH`——`test_workbench.py` 有"无孤儿文档"断言，漏登记会直接红。

### T-06 比赛目录成熟度两极（本地数据治理）

- **问题描述**：BUUCTF 16 case 全规范；ISG 3 case（2 个有 case.json）；京沪深 2 个手工目录
  无 case.json、7.1G 裸附件；香港 4.1G 比赛文档从未初始化。
- **影响范围**：看板/统计对这些比赛基本空白；13G 未分诊附件占磁盘。
- **优先级**：P2（属本地数据治理，不影响代码仓库）
- **建议方案**：用 `case.init` 动作补历史目录的 case.json；纯附件目录先 `triage.py` 批量分诊
  再决定去留；`_archive/quarantine/` 的两份 exe（已哈希登记）如需执行必须先进 Docker 沙箱。

### T-07 分诊覆盖与平台对账

- **问题描述**：`triage.py` 约 16-18 类文件签名，容器镜像/固件/数据库文件覆盖有限；
  平台侧"本题已解"状态无回写对账（`submissions.jsonl` 只记本地提交）。
- **影响范围**：特殊附件分诊不出类型；平台已解的题本地可能仍标记未解，重复劳动。
- **优先级**：P2
- **建议方案**：扩充签名表并加 `file`/`binwalk` 式兜底描述；新增「拉取平台已解列表 → 与本地
  case 状态对账」动作（依赖 T-03 的适配器接口）。

### T-08 `/api/help` 与 README 协作 API 章节漂移

- **问题描述**：两边各写各的，API 增删后容易漏字段（ROADMAP 短期第 2 项）。
- **影响范围**：多 Agent 协作者按过时文档调用会踩空。
- **优先级**：P2（小工作量，顺手做）
- **建议方案**：`/api/help` 的输出由单一数据结构生成，README 的 API 表从同一结构导出
  （或测试断言两边字段集一致）。

## P3 — 顺手做

### T-09 前端无 lint / 格式化约束

- **问题描述**：`static/` 拆成 19 个 ES module 后仍无 ESLint/Prettier；CI 只 `compileall` + 两个测试。
- **影响范围**：多人接手后风格漂移；低级错误（未用变量、`==`）无人拦。
- **优先级**：P3
- **建议方案**：加 `eslint`（推荐 flat config，`npm i -D eslint` 一次性），CI 跑 `eslint static/`。
  注意 `static/vendor/` 要忽略。

### T-10 `cmd_status` 函数级无状态枚举校验

- **问题描述**：`case_manager.py` 的 `cmd_status()` 直接写 `case["status"] = args.status`，
  枚举校验只靠 argparse `choices`（`STATUSES` 集合定义了但函数内未用）。
- **影响范围**：CLI 路径安全；但若被 Python import 直接调用（绕过 argparse），任意字符串可写入
  status，前端 `s-${status}` 样式静默失效。
- **优先级**：P3（防御性）
- **建议方案**：函数开头加 `if args.status not in STATUSES: return 2`（两行）。

### T-11 令牌握手细节

- **问题描述**：`/api/auth/exchange` 已实现「裸 token → 15 分钟 session」，但交换端点本身
  接受 `?token=` 查询串（会进访问日志）。
- **影响范围**：本地单机可忽略；共享模式下日志泄露即 token 泄露（token 本身仍需交换才可用，
  风险有限）。
- **优先级**：P3
- **建议方案**：exchange 改为只读 POST body 里的 token；日志对该参数脱敏。

---

## 本机环境注意事项（接手者在同一台机器上工作必读）

1. **GitHub 推送**：直连被旧代理环境变量误导（`http_proxy=127.0.0.1:54202` 已失效）。
   Clash Party 的 mihomo 监听 `0.0.0.0:7890`——git 一律带
   `-c http.proxy=http://127.0.0.1:7890 -c http.sChannelCheckRevoke=false`。
   凭据在 GitHub Desktop 的 wincred（`%LOCALAPPDATA%/GitHubDesktop/app-*/resources/app/git/mingw64/libexec/git-core/`）。
   **必须 `-c credential.helper=` 清空 helper 链**，否则弹 UI 挂起。SSH 到 github.com 不通
   （`~/.ssh/id_ed25519` 未在账号注册 + 全局 insteadOf 重写）。
2. **`_publish/` 目录会吞载荷类文件**（见 T-01），别浪费时间反复重试。
3. **Git Bash 对非 ASCII 路径不可靠**：中文路径会被 wrapper 当命令执行。涉及中文路径的文件操作
   一律用 Python（`shutil`/`pathlib`）。
4. **`core.autocrlf=true`**：`git add` 对未改动文件报 LF→CRLF 警告是噪声，用 `git diff -w` 验证。
5. **行尾与 `.gitignore`**：发布仓库的 `.gitignore` 是发布态专用（多 venv/workbench-data 等规则），
   `sync_publish.py` 已排除不覆盖——**不要手工把主目录 .gitignore 复制过去**。

## 已完成（2026-09 批次，避免重做）

- 安全：mdRender scheme 白名单（XSS）、CSP/nosniff/Referrer-Policy 全路径注入、
  `/api/agent/start` categories 白名单（命令注入）、宿主侧 `shell=True` 全清、
  共享模式无 token 硬拒绝（`--allow-insecure` 显式放行）、Origin 白名单覆盖全部本机地址
- 功能：详情页轮询 + 表单状态快照回填、前端模块化（app.js 1861→309 行，19 个 module）、
  成就系统、动态计分排行榜、知识库扩充至 24 份 + 分类登记 + 中文名可检索、
  submitter 未受理提交不再锁死 flag（`--force`）、抓题幂等（平台 ID/名称键）、
  ctf_session 可读错误、亮色主题、aria 可访问性
- 工程：根仓库 git 化 + 大文件策略、`sync_publish.py` 同步脚本、CHANGELOG/ROADMAP 恢复维护、
  docker README 七镜像清单、静态质量门（CSP 安全/冲突标记/孤儿文档/Origin 覆盖）

> 详细历史与每项的证据行号见工作区 `系统优化/系统优化清单.md`（本地档案，不在本仓库）。
