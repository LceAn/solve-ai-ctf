# 更新日志

本文件记录 Solve-AI-CTF 的重要变更，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### 优化（R167：两个看板各归其位）
**AI 看板（给其他 AI 看）**
- 顶部「协作态势」四指标：活跃 agent / 认领中 / 运行任务 / 交接记录。
- 名册新增「状态」列（活跃 / 空闲 / 离线 / 已吊销），不再只靠裸时间判断。
- 新增「交接记录」表（时间 / 题目 / 交接人 / 简报摘要），数据来自 `directory` 新增返回的
  `handoffs`（最多 20 条）。
- 接入说明与事件图例改为折叠，首屏空间让给态势与名册；重复空态合并。

**流程看板（给人看）**
- 新增作战摘要：题目 / 已解·已交 / 受阻 / 候选待验 + 完成度进度条与百分比。
- 停滞最久提示：超过 24h 未更新的未完成题，题名标黄并给出状态。
- 卡片显示负责人（`@agent`）与「运行中」标记。
- 数据分期加载：先按比赛数据渲染，再异步叠加认领/任务，网关不可用不影响主视图。

### 修复（R166：主题跟随系统）
- **首屏一直深色**：`<html data-theme="dark">` 写死，与系统偏好无关。改为
  `/static/theme-init.js` 在样式表之前决定主题：`?theme=` > 用户选择 > `prefers-color-scheme`。
- 手动切换写入 `localStorage`；**Shift+点击**主题按钮清除选择、恢复跟随系统；
  未手动选择过时，系统主题变化会实时跟随。
- 带 `?theme=` 进入后点切换会清掉该参数，避免刷新时被 URL 覆盖。
- 删除无用的 `theme-pending` CSS 规则。

### 新增（R165：流程看板）
- 新页面 **「流程看板」**（解题组第 2 项）：按 case 状态分六列的看板——
  待开始 / 侦察·假设 / 受阻 / 候选待验 / 已解待交 / 已提交。
- 卡片显示：题名、分数、分类、假设/尝试/候选计数、停留时长与最后事件；
  未完成且超过 24h 未更新的题左侧标黄（"停滞"），鼠标悬停有完整信息。
- 顶部流程带展示各阶段计数，点击横向滚动到对应列；点击卡片直接进入题目工作区。
- 已放弃 / 无效的题不占列，底部单独一行列出。

### 优化（R164：交付与页面细节）
- **交付包支持「仅已解」**：脚本 `--solved-only` + 文档页下拉（全部题目 / 仅已解）。
  只打包 `solved/submitted/closed` 的题目；比赛级 `docs/*.md` 仍全量（说明里注明）。
- **环境表格列合并**：`spec` 与 `服务` 两列常为「—」，合并为一列「配置」，列数 7 → 6。
- **`/api/resources` 缺关键词返回 200 空结果**（原 400），与 `/api/docs/tree` 口径一致。
- **文档页空态**：未选文档时右侧 60% 纯空白 → 居中提示「未选择文档」。
- 表头统一小写 `tag / base`。

### 优化（R163：启动屏）
- **启动输出重做**：原来只有一行 `CTF Workbench → url (root=...)`，现在是有层次的信息块——
  版本、地址、数据根、比赛数（默认比赛与题数）、沙箱、鉴权、求解命令模板状态。
  终端支持 ANSI 时着色（地址青、状态绿/黄/红、标签灰），重定向到日志时自动降级纯文本。
- **`启动工作台.bat` 精简**：去掉手绘 `====` 边框与重复说明，只保留编码、标题、窗口尺寸
  （100×32）与 Python 调用；失败时给出可操作的提示。
- 清理验收时误建的 `比赛/new-ctf`（0 题空壳）。

### 新增（R162：一键打包交付）
- **`scripts/export_package.py`**：把整场比赛打成单个 zip，用于赛后交付/归档。
  - 内容：`复盘报告.md`、`writeups/`（比赛级 `docs/*.md` + 题目级 `WRITEUP*.md`）、
    `cases/<slug>.json`、`events.jsonl`、`交付说明.md`（索引 + 题目清单 + 脱敏声明）。
  - **真实 flag 一律脱敏**为 `flag{…脱敏·sha256:xxxxxxxx}`，覆盖 case 文本、writeup 与事件流；
    已验证 7 个候选 flag 打包后 0 明文泄漏。
  - 默认不含附件；`--include-artifacts` 显式开启（单文件 >20MB 跳过并告警）。
- 动作 **`competition.export`** + 下载路由 **`GET /api/export/download`**
  （路径严格限制在 `<比赛>/交付/*.zip`）。
- **文档 / WP 页新增「打包交付」按钮**：生成后直接显示下载条（文件数 / 大小 / 脱敏处数）。

### 优化（R161：验收后的三条改进）
- **`selftest.run` 异步化**：此前同步跑 `self_test.py`（timeout 120s），点「运行 self_test」
  前端要干等两分钟。现在立即返回，配套 `GET /api/selftest` 返回
  `{started,running,exit,elapsed,output}`，前端每秒轮询并显示已运行秒数。
- **`/api/docs/tree` 未配置不再 404**：返回 `200 + {configured:false, tree:[]}`，
  调用方可区分「没配置」与「路径错误」（前端原本已按 `S.comp.docs_path` 短路）。
- **`competition.init` 拒绝未知参数**：此前误传 `dir` 会被静默忽略、改用 `name` 生成目录名，
  容易建错目录；现在直接报错并列出可用参数。
- **新增 `workbench/acceptance.py`**：52 项端到端验收（35 个只读路由 + 20 个写操作 + 异步自检 +
  任务派发），使用带时间戳的临时比赛、跑完自动删除，不污染真实数据。
- **`achievement.check` 半初始化库报错**：`submissions` 表由 `leaderboard.py` 建，而动作只在
  库文件不存在时跑 `achievements.py init`——一旦库里有 `achievements` 表但没有 `submissions`
  （首次先跑过成就检查），之后每次都 `no such table: submissions`。改为无条件跑两个幂等 init。
- 成就页提示改为解析 `{"new_unlocks":N}`（原先用 `/unlocked (\d+)/` 匹配 JSON，永远显示"✓"）。

### 修复（R160：全功能验收，4 处运行时错误）
- **`selftest.run` 动作 500**：`wb_actions` 引用 `_HEALTH_CACHE` 但 N-06 拆包时未导入
  （定义在 `wb_sandbox`）——「运行 self_test」按钮此前必失败。
- **保存沙箱配置 500**：`wb_routes.sandbox_save` 使用 `SANDBOX_DEFAULTS` 未导入。
- **停题目服务 500**：`wb_routes.env_services_down` 调用 `_compose_down` 未导入。
- **`/api/prompt` 未知 slug 返回 500**：`build_prompt` 的 `ValueError` 未捕获，改为 404 可读错误。

### 修复（本地部署体验，R159）
- **启动即报 `unknown competition`**：`启动工作台.py` 在未指定比赛时硬传 `--competition demo-env`，
  而多数环境没有该目录。改为自动挑第一个含 `competition.json` 的比赛。
- **数据根识别**：`root` 原先固定为仓库目录，工作区布局（`CTF/比赛/` + `CTF/solve-ai-ctf/`）
  下扫描不到比赛。改为：仓库内有 `比赛/` 用它，否则用父目录。
- 新增 **`启动工作台.bat`**：双击启动并自动打开浏览器，服务端参数原样透传。

### 变更（R158：全局布局系统，收敛装饰）
- **统一布局标尺**：主区 padding 收敛为 24/32/56（删掉重复且被覆盖的 `main` 定义）；
  页头标题 20 → 24px、描述 13px；区块标题去掉竖条与中文 uppercase 字距。
- **去装饰层**：卡片移除玻璃模糊、渐变描边伪元素、hover 阴影漂移；统计卡移除顶部渐变条、
  右上柔光与 hover 上浮；主按钮由渐变改为实心 accent。
- **统计卡**：`flex` 改 `grid auto-fit` 等分，数字 26px/650；解出进度改为带标签的三段式
  （已解 N/M · 进度条 · 百分比），不再是无线索的蓝线。
- **表格统一**：表头 11/600、行高约 40、去斑马纹改 hover；`ops` 平台状态表去掉
  `max-width:640px` 铺满卡片。
- **页面级修复**：
  - `ops` 三个派发按钮从横贯整卡改回常规宽度（flex column 的 stretch 所致），去掉卡片彩色左边条；
  - `health` 宽屏固定 3 列，消除 4+2 的尾部空洞；
  - `detail` 无题目时给出空态引导（此前整片空白），筛选标签「方向」不再竖排；
  - `kb` 检索表单撑满列宽并换行（此前挤在 300px 内）；
  - `tasks` 派发表单下拉/输入各占整行、按钮等分。
- 新增 `?tab=` 深链接（可分享定位，也便于自动化截图）。
- 彩色 emoji 图标统一灰度化，避免与单色 SVG 体系混排。

### 变更（R157：侧边栏信息架构与视觉重做）
- **品牌栏 66px → 56px**，与顶栏对齐（此前差 10px）；emoji 蝴蝶换成单色 SVG 标志；
  折叠按钮从底部移入品牌栏，折叠态沉底居中、箭头翻转。
- **信息架构重排**：分组由 3/6/4/2 调整为 **解题 3 / 监控 4 / 资源 4 / 管理 4**；
  「环境」「系统概况」从监控归入管理，排行榜回到监控组。保留原有 14 个入口与 data-tab。
- **导航项**：34 → 36px 行高、18px 图标、组间距 10px；选中态去掉内描边圈，
  只留 soft 底色 + 贴边 2px 锚线；分组标签提升到 11px/600 并去掉中文 uppercase 字距。
- **分类子导航**：单列 7 行 → **两列网格**，且**仅在「题目工作区」显示**
  （此前在总览页也占约 150px，把「管理」组挤出 900px 视口且滚动条不可见）。
- **折叠态 60px 图标栏**：按钮沉底居中、分组用极淡分隔线、行高 40px。
- **亮色主题**：侧栏底色加深一档，与主区拉开层次。

## [v0.4.0] — 2026-11-02

> 主题：**多 AI 协作体系**（Agent 网关 → 调度 → 交接 → 权限分级）+ 视觉现代化 +
> 60 轮新用户视角审计修复。自 v0.3.0 起按批积累，回归基线 56 → 234 断言 + eslint 门。

#### R104-R154b 批次明细

### 修复（新用户审计 + 一致性）
- **docker prefix 陈值即用（R154b）**：磁盘缓存 TTL 过期后首个 Docker 请求不再陪跑
  WSL 冷探测（`/api/env/status` 实测 97.8s 挂起）——陈前缀即时返回 + 后台线程重探刷新。
- **env.js 丢函数（R154）**：结构修复误删嵌套 `doVerify`（验证按钮点击即 ReferenceError）；
  `scheduleRefresh` 移植残留引用——本地套件新增 eslint 门（CI 同款 errors-only）防再发。
- **新用户审计批（R121-R126）**：「＋新建比赛」NameError（合并遗留裸 `SCRIPTS_DIR` 引用）；
  快速尝试记录静默失败（`case_manager` 支持 `hypothesis=quick` 自动建承载假设）；
  知识库无结果空态给检索建议。
- **任务输出搜索（R141）**：查询词与内容同 esc——含 `<>&` 的搜索词此前永远匹配不到。
- **env.js 结构修复（R145/R146）**：清理历次编辑残留的孤立 `}` 与错位代码块（`node --check` 验证）。
- **网关面板（R151）**：「已吊销（N）」折叠块 HTML 畸形（`<details>` 未闭合，吊销行漏出折叠区）；
  ISO 时间戳人话化（`10-30T08:59` → `2026-10-30 08:59`）。
- **系统概况（R151）**：Docker 健康探测复用 `docker_prefix()`（裸 `docker` 在 WSL 部署必然
  FileNotFoundError 且原始异常直出）；异常人话化三态 + docker 专项 60s 超时；
  健康页 stale 态（探测单飞期间）不再卡「检测中…」——友好等待 + 15s 自动重试。
- **无人认领条（R152）**：`board_data` 改走 `wb_gateway.active_claims()`——弃坑 agent 的
  过期认领此前会让题目滞留「已认领」态最长 45 分钟。
- **dispatch top_mine 误判（R119）**：bool(holder) 任何人持有都算我的 → 显式接手强制转移
  认领永不触发——改为 holder.agent_id == agent.id；显式接手时强制转移他人残留认领。
- board2 过滤 chips 绑定作用域 bug（元素插在图例后但查询在图例内，onchange 绑 null）。

### 新增（多 AI 协作体系）
- **Agent 协作网关** `workbench/wb_gateway.py` + `/api/agent-gw/*` 六端点：
  注册（发 agw_ 密钥只显示一次存哈希）/ 心跳 / 题目认领（TTL 45min 防重复劳动、
  冲突 409）/ 释放 / 名册 / 吊销（立即失效+认领自动释放）。
- **L1 调度端点** `GET /api/agent-gw/dispatch`："我该干哪题？"——按 prioritize 公式
  选题（跳过已解/他人认领），我的认领优先续做，自动完成认领并**内联完整 prompt** +
  alternatives + 全局态势；显式指定 slug 时跳过状态过滤（交接接手场景）。
- **L2 认领态上板**：无人认领条排除已被网关认领的题。
- **L3 交接简报** `POST /api/agent-gw/handoff {slug, summary, findings[]}`——弃坑 AI
  留结构化简报并自动释放认领；dispatch 命中同题时 prompt 自动注入简报（接手秒懂上下文）。
- **L4 权限分级**：agent 注册支持 role（solver/observer）——observer 全写拒绝；
  solver 写 case.* 自动代为认领，写【他人认领】的题 403 E_NOT_CLAIMED（防互删守护）。
- agent key 鉴权集成：X-Agent-Key 头或 Bearer agw_… 等同 session 权限（注册协作者，
  仍受动作白名单与提交器约束）；管理端点（注册/吊销）拒 agent key（E_ADMIN_ONLY）。
- 看板页「🌐 Agent 网关」面板：名册表（能力/认领/心跳/吊销）、注册模态框（密钥一次性展示）。
- 排行榜侧栏「AI 协作榜（近 24h）」、空态也渲染。

### 增强
- **视觉现代化（R129-R140）**：侧边栏 2026 风格（浮起胶囊 active/渐变光条）、panel 内表格统一
  （圆角容器/粘性表头/行悬停）、深色分层背景体系。
- **网关（R115/R137/R144）**：存储 mtime 签名读缓存（面板高频刷新免重复读盘）；directory
  活性计算（last_seen_minutes/claims_count）与 `?name=` 过滤；认领徽章过期倒计时（<10min ⏳）；
  dispatch 注入已有 flag 候选提示 + handoffs 历史接力链。
- **看板（R76-R84/R142-R143）**：agent 态势卡点击过滤、任务泳道 slug/沙箱/实时尾行输出、
  悬停交叉高亮、题目泳道深链接、「无人认领」提醒条、协作快照一键 Markdown。
- **性能**：`competition_view` mtime 签名缓存、`file_tree` TTL 缓存、任务存储 revision 签名缓存、
  `/api/tasks` rev 轻量轮询、SSE 事件流追加读、静态资源 ETag/304。
- **测试**：run_custom 并发竞态修复（Popen 先注册后持久化）+ 80/80 风暴验证；
  回归基线 56 → 234 断言 + eslint 静态门。
- README「多 Agent 协作」章节重写——网关完整用法（注册/dispatch/claim/handoff）。

### 运维鲁棒性
- Docker 探测 timeout 150s、失败不缓存 + 60s 负缓存；health_detail 单飞探测（双检锁）。
- 网关限速窗口全程持锁、计费写回加锁、防 revoke 竞态；任务日志每 30 分钟定时轮转。
- 真实提交两段防误触（confirm + flag 前 6 字符输入校验）；文件查看器行号 + 截断防护。

## [2026-10-25] — v0.3.0

> 本段补记 2026-10-21 ~ 10-25 的 R57–R75 轮次与仓库整理；逐轮细节见提交历史。

### 新增
- **AI 协作看板**（R65/R72–R74）：warroom 大屏视觉体系（明度四层/大数字统计）；`/api/board`
  新增 agents 汇总（运行/完成/失败计数、覆盖题数、最近活动），前端 Agent 态势卡 + 泳道按题聚合；
  泳道副标（题目带类别与事件数、任务带沙箱标记）、事件点悬停 detail 摘要、「协作快照」一键把
  当前态势转 Markdown 进剪贴板。
- **SSE 事件总线**（R62）：`wb-event` CustomEvent，看板/总览在题目新增、状态变更、尝试与候选
  登记时即时刷新，免等 30s 轮询。
- **eslint 质量门**（R63）：flat config + CI 步骤 + devDeps（vendor 忽略），首轮即抓出并修复
  4 个真 bug（新建比赛模态框丢失、模板串换行解析错误、跨模块引用未导入、retry 回调未定义变量）。
- 体验补强一批：任务输出工具条（搜索高亮/自动滚动暂停/日志下载，R58）、尝试快速记录（R60）、
  时间线事件类型过滤与导出 Markdown（R59/R70）、任务深链接 `?task=`（R69）、比赛级 writeup
  新建（docs.write 白名单动作，R68）、镜像推送历史（push-history.jsonl + 页面表格，R67）、
  系统概况自动刷新与 self_test 输出折叠（R61）、比赛下拉分组（R59）、窄屏补盲（R70/R71）。
- 知识库检索增强：CJK 长词 2 字滑窗子词（命中率 99%→100%，R64）、命中词高亮（R66）。

### 修复
- **WSL 冷启动沙箱派发失败**（R57）：`_image_exists` 逐个 inspect 在冷启动下 20s 超时被误判
  「镜像不存在」导致派发全挂；改走镜像集合缓存，测试加 prefix 预热与 180s 派发超时。
- **cmd /c wsl 前缀带引号参数撕裂**（R57）：沙箱 run 全挂的执行路径根因；归一化为 `wsl --exec`。
- 环境页性能三层修复（R57）：docker_prefix 落盘缓存 1h TTL（冷探 100s→0.02s）、status_data
  10s TTL、服务端 5min docker 保热循环；另加全局错误捕获（限频 toast）。

### 仓库工程（本次整理）
- 根目录清理：删除 9 月两仓 merge 遗留的对比产物（`their_server_dump.py`、`my_eps.txt`、
  `their_eps.txt`、`.tmp-probe/`，均零引用，历史仍可找回）；`.gitignore` 新增 `.tmp-*/` 规则。
- 文档归档：ROADMAP、迭代账本、TODO-OPTIMIZATION、优化提案 ×2 迁入 `docs/` 并标注归档
  状态；根目录只保留 README / CHANGELOG / SKILL / LICENSE。
- README 文档索引更新（含 SKILL.md 与 `docs/` 入口、`启动工作台.py` 启动方式）。
- **CI 恢复绿灯**（10-23 起连红 8 次的两层根因）：① R69–R74 引入 3 处 eslint error
  （board2 的 `toast` 未导入、kb 高亮转义多余 `\^`、`URLSearchParams`/`history` 未声明全局）；
  ② GitHub runner 自带 Docker 但无本地 ctfbox 镜像，沙箱 smoke 与 R34 并行构建两道门由
  「docker 可用」收紧为「docker 可用**且所需镜像已构建**」（本地有镜像仍真跑）；另
  env/status 测试超时 90s→180s（docker_prefix 冷探可达 100s+）。
- GitHub 远端清理：删除已完全合入 main 的陈旧分支 `backup/local-43-rounds`；设置仓库 topics。

### 测试
- 端到端断言 207 → **211–212 项 0 失败**（有 Docker 真跑沙箱 smoke 为 212，无 Docker 跳过
  记 1 项为 211）；`scripts/self_test.py` 全绿；GitHub CI 恢复 success。

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
