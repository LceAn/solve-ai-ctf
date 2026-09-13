# 更新日志

本文件记录 Solve-AI-CTF 的重要变更，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [2026-09-12]

### 修复
- **未被平台受理的提交不再锁死 flag**：`submitter.py` 的去重原先只跳过 `dry_run`、不看结局，
  一次 429/网络中断就会把该 flag 判为"已提交"，之后永远拒绝重投（现场只能手改
  `submissions.jsonl` 自救）。现在 `retryable` / `error` 两类历史记录不参与去重，
  并新增 `--force` 显式跳过重复检测。
- **抓题幂等**：`fetch_challs.py` 的去重集合原先在循环外按 slug 快照、循环内不更新，
  列表无平台 ID 时用位置计数生成 slug（`chall-1/2…`），第二次运行必然全部"已存在"。
  改为「平台 ID 优先、否则题目名」作幂等键，注册成功即写回集合。
- 会话失效时 `ctf_session.get_json()` 不再抛裸 `JSONDecodeError`，改为带 HTTP 状态、
  响应片段与排查方向的可读错误。

### 文档
- `flag_hunter.py` 的帮助与注释原写「缺省视为关闭」，与实现（默认开启，与 `/api/autosubmit`
  默认一致，属抢一血设计）相反，已如实更正并说明关闭方式。

### 测试
- `self_test.py`：mock 提交端点新增故障注入（`fail_next` 返回 429），覆盖
  「429 → retryable → 重投成功 → `--force` 绕过」完整链路。
- `test_workbench.py`：新增抓题幂等断言（重跑 `registered=0`、题目总数不变）。端到端 135 → 138。

## [2026-09-11]

### 新增
- 成就系统：`scripts/achievements.py` 规则引擎（first_blood / full_category_clear / speedrun / zero_false_positive / streak）；
  解锁事件写入 `events.jsonl`（`kind:"achievement_unlocked"`），并镜像到 `workbench-data/achievements.json` 便于审计与检索。
- 动态计分排行榜：`scripts/leaderboard.py`。以 SQLite 为查询缓存，按解出人数衰减 + 一血加成；
  重放 `submissions.jsonl` 幂等，`submissions.jsonl` + `case.json` 仍是唯一真源。
- 资源库：`references/links.json`（赛事/工具/知识站点索引）与工作台资源视图。
- 工作台新增成就页与排行榜页。

### 变更
- 前端模块化：`static/app.js` 由 1861 行拆至 309 行，新增 `api/md/sse/state/ui` 与 `views/` 下 14 个视图模块；
  `index.html` 改用 `<script type="module">`。
- `static/style.css` 大幅重写（+551 行改动），配套新视图的版式与状态样式。
- 端到端断言由 74 增至 119。

### 说明
- `static/vendor/` 引入 petite-vue（CSP-safe 包装层：`petite-vue.es.js` 注入 `@vue/reactivity`
  到 `petite-vue-csp`）+ `vue-reactivity`；`state.js` 已用其 `reactive()` 承载全局状态，
  视图层的 `createApp` + `v-scope` 迁移待做。

### 修复
- **知识库接入三类断链**（新增 15 份专项文档后，CLI 搜得到但工作台页面搜不到）：
  - `/api/kb` 的行解析正则 `KB_LINE` 文件名字符类只认 ASCII，9 份中文名文档的命中被静默丢弃
    （实测 `q=lsb`：修复前 0 条 → 修复后 10 条）。改为宽松匹配。
  - `CATEGORY_FILES` 硬编码白名单未登记新文档，按方向检索恒为空
    （实测 `search "反序列化" --category web` → `No matches`）。已按方向登记，并抽出
    `COMMON_FILES` 与 `allowed_files()` 统一入口。
  - `AI-SEARCH-INDEX.md` 参与内容检索，索引条目高分霸榜挤掉正文。
    新增 `EXCLUDED_FROM_SEARCH` 与 `searchable()`，与外部库的 `.idx.md` 过滤保持一致。
- `KB_EXTERNAL_DIR` 原先只写在素材来源说明里，README / SKILL / workbench README 均无记载；
  发布 README 新增「知识库」章节（三种检索用法 + 外部库接入四步 + 上限保护）。
- **Origin 白名单覆盖不全**：`_local_origins()` 只列 `127.0.0.1/localhost/[::1]`，而
  `--host 0.0.0.0 --token` 共享模式下用局域网/Tailscale 地址访问时，所有写操作被判 403
  （表现为"能看不能点"）。改为并集 loopback 别名 + `local_urls()` 枚举的全部本机网卡地址。
- 沙箱镜像文档 `workbench/docker/README.md` 全文每行以 `#` 开头（渲染成整篇标题），
  重写为正常 Markdown 并补全七类镜像清单。

### 文档
- 发布 README 特性与架构两处描述由"4 题型 Playbook"更新为 24 份文档（含 15 份专项弹药库）。

### 测试
- 新增断言：中文名文档必须能经 `/api/kb` 返回；KB 结果不得含索引文件且必须含专题正文；
  `references/*.md` 无孤儿文档（防止再漏登记）；各方向收录指定专题。
- 新增三条静态质量门断言：静态 JS CSP 安全（剔除注释后不得出现 `eval(` / `new Function(`）、
  技能树无 VCS 冲突标记、Origin 白名单覆盖本机全部访问地址。
- 新增运行时断言：`/` 响应必须带 CSP（`script-src 'self'` 且不含 `unsafe-eval`）与
  `X-Content-Type-Options: nosniff`。端到端断言 119 → 135。

### 安全
- `/api/agent/start` 的 `categories` 参数增加白名单校验：该值会拼进 shell 命令串，未校验时可注入任意命令。
- 新增回归用例：注入载荷返回 400，合法 `web,crypto` 正常派发。

## [2026-09-05]

## [未发布] - 2026-09-06

### 安全（对照桌面《系统优化清单》N-01~N-03/N-12）
- **N-02 根治**：任务派发全面去 `shell=True`——`TaskManager.start/run_custom` 改为
  argv 列表 + `shell=False`；新增 `split_cmd_template`（argv 词法：外层引号剥离、
  占位符路径安全替换；不支持 `&&`/`|`/`>` 与环境变量展开）。沙箱 docker run、
  开赛代理、Flag 猎手、env 构建全部走 argv。
- **N-01 收尾**：`/api/agent/start` 的 `categories` 白名单校验（清单记录的修复未落到
  主工作副本，本次随 N-02 一并落地并补回归断言：注入载荷 400、合法值放行）。
- **N-03**：非回环绑定且未配置令牌时拒绝启动（`--allow-insecure` 显式豁免），
  README「共享模式强制 --token」从此名实相符。
- **N-12（部分）**：`/api` POST 增加 Origin/Host 一致性校验（浏览器跨站 403，
  非浏览器客户端不受影响）；`--verbose` 请求日志落地并对 `?token=` 脱敏。
- **N-08**：README 去掉硬编码断言数；CI 新增文档卫生检查（合并冲突标记、
  README 硬编码计数即红）。
- **N-04**：`scripts/sync_publish.py`——主目录 → 发布副本单向同步，
  复制后 diff 断言零差异（目标侧多余文件自动清理）。

## [未发布] - 2026-09-05

### 新增
- 约束层进镜像（PDF"规则界定边界"落地）：`env_builder sync-solver` 生成
  CLAUDE.md/AGENTS.md 双写与七类题型 skill 包（源自 references/playbooks-*.md），
  随 L0 烤入所有层继承；比赛级覆盖仍走运行时挂载（spec constraints，免重建）。
- 第七层题型镜像 `ctfbox-ai`（openai/anthropic/tiktoken/jsonlines），
  全链路类别映射：抓题归一化（ai/llm/model）→ 镜像选择 → verify 探针。
- `services.*.env.FLAG` 占位强校验：真值形态直接拒绝构建（flag 只能来自平台实例）。
- 比赛/题目级 Docker 环境（四层镜像矩阵：底座 → 题型 → 比赛 → 题目）：
  声明式 env spec（`比赛/<dir>/env/`）+ `workbench/env_builder.py`
  （build / status / verify / export / preheat / render），运行时只读 `env/gen/.built.json`。
- server 镜像选择优先级：case env.image → env 题目层 → L2 比赛层 → 题型层 → 兜底；
  spec 可显式声明 cap 白名单与资源上限（只允许收紧）。
- 多服务题目编排：env spec `services` → compose（internal 网络），
  solver 容器加入服务网络，任务结束/超时/手动停止连带 `compose down -v`。
- `/api/env/status|build|verify` 端点与「比赛管理 → 🐳 环境」面板
  （L0/L1/L2 状态、题目层构建/验证按钮、spec 漂移提示）。
- `competition.py init` 创建 env 骨架；`add-challenge` 自动生成题目 spec 骨架。
- docker CLI 发现层：PATH 的 docker/docker.exe 优先，Windows 回退 `wsl docker`
  （文件路径自动翻译 /mnt/<盘>/...）——Docker 只装在 WSL 的机器全链路可用。
- case.init 动作与题目列表「初始化 case」按钮：手工目录场景的补救入口。
- 尝试记录结局筛选 chips（全部/成功/部分进展/失败/出错）。
- 预设管理：`/api/presets` 枚举 + 开赛自动化页预设下拉（BUUCTF 预设内置）。
- 模型网关异常包裹与 `--verbose` 请求日志；任务面板容器徽标与起止时间。
- 可用标志一键复制；反馈系统 toast 队列（info/ok/warn/err）与全局 busy 流光条。
- 快捷键 `Alt+1..9` 切换页面，`?` 呼出帮助浮层（快捷键 + Agent 协作端点）。
- 系统概况题型镜像全家桶状态卡（七镜像逐一 ✓/✗）。
- 平台会话：`ctf_session` 模块（表单登录 + nonce CSRF + session 拉题），BUUCTF 预设。
- 开赛自动化：平台对接代理（探测写配置）+ 抓题代理（限额/类别过滤）。

### 性能
- 比赛视图 mtime 缓存（签名含全部 case.json），写动作后自动失效，题目多时显著减少 IO。

### 安全
- CSP / X-Content-Type-Options / Referrer-Policy 响应头（四条响应路径全注入）。
- mdRender 链接 scheme 白名单，杜绝 `javascript:` / `data:` 型 XSS。
- docker CLI 发现层：PATH 的 docker/docker.exe 优先，Windows 回退 `wsl docker`
  （文件路径自动翻译 /mnt/<盘>/...）——Docker 只装在 WSL 的机器全链路可用。
- 镜像存在性批量缓存：一次 `docker images` 取代逐个 inspect，
  WSL 通道下 env/status 从 ~10s 降到 ~1s；构建后自动失效。
- 比赛视图 mtime 缓存（签名含全部 case.json），写动作后自动失效。

### 修复
- 模型网关未捕获异常导致连接中断。
- Flag 流水线与方向下拉的数据一致性（视图缓存失效盲区）。
- CHANGELOG 残留未解决的合并冲突标记。

## [2026-08-30]

- 首个公开版本：确定性工具链 + 本地 Web 工作台 + Docker 沙箱 + Flag 猎手。
- 新增 `CHANGELOG.md` 与 `ROADMAP.md`，README 增加文档索引。
