# 迭代账本（30 轮功能优化）

> **已归档（2026-10-24）**：本账本记录至 2026-09 初（R1–R47 批次），实际迭代已推进至 R74；完整轮次与验证情况见 `CHANGELOG.md` 与提交历史。

> 2026-09-06 启动。每轮 = 一个真实功能改进 + 测试验证 + 独立提交。
> 验证基线：`test_workbench.py` 113 项断言 + `scripts/self_test.py` + `e2e_env_check.py` 44 项（需 Docker）。
> 待推送提交在本地累积（代理 GitHub 路由故障；R1-R38 已提交（v0.2.0 = R1-R30；v0.2.1 批次 = R31-R38：；剩余 7 轮：R24-26 server.py 拆包（N-06，验收单文件<400行：wb_context/wb_tasks/wb_sandbox/wb_gateway/wb_actions/wb_http 分层，server.py 作 facade）；R27-28 app.js 拆 ES modules（N-11，core/api/views，CSP 'self' 兼容）+eslint；R29 ✅ 文档收尾；R30 ✅ v0.2.0 打标。30 轮全部完成（N-11 的 ES module 全量拆分列入下一阶段）。，后台自动重试推送中）。

## 轮次记录

| 轮 | 内容 | 验证 | 提交 |
|---|---|---|---|
| R1 | 抓题代理自动下载附件：CTFd 系 challenge detail → files 拉取进 case artifacts + sha256 登记（新增 case_manager artifact-add），消灭"附件手动放置" | 单测新增 mock 文件服务断言 | 本轮 |
| R2 | ✅ 沙箱并发上限 max_concurrent_sandbox（默认 4），超限拒绝给可操作提示 | 纯函数断言 | 已提交 |
| R3 | ✅ 网关用量报表 /api/gateway/usage + 系统概况用量面板 | 聚合断言 + API 断言 | 已提交 |
| R4 | ✅ 复盘报告导出 competition.report（flag 自动脱敏 sha256，红线断言） | 3 项新断言 | 已提交 |
| R5 | ✅ triage 签名扩充：SquashFS/UBI/UEFI/ext/ISO/Mach-O 等 + 权重与路由 | 真实字节断言 | 已提交 |
| R6 | ✅ kb_search 命中率统计 + 零命中补洞清单（--stats） | 手工验证 + 套件覆盖 | 已提交 |
| R7 | ✅ platform_adapters 注册表（ctfd/buuctf）+ --adapter 声明 + apply_defaults 缺省补齐（探测失败抓题仍可用）；测试全链路走纯适配器路径 | 适配器断言 + mock 全链路 | 已提交 |
 | R8 | ✅ /api/tasks 服务端过滤（status/agent/limit）+ 前端「只看运行中」开关 | API 断言 | 已提交 |
| R9 | ✅ 网关链路 mock 上游集成测试（401/转发/记账）——大重构安全网 | 3 项断言 | 已提交 |
| R10 | ✅ 沙箱 smoke 测试入套件（Docker 可用才执行，CI 自动跳过） | 真实容器运行断言 | 已提交 |
| R11-13 | ✅ env_builder clean（旧镜像清理/只动 ctf-* 前缀）+ 任务日志轮转（保留最新 200）+ 运维页「导出复盘报告」按钮 | clean dry-run + 轮转断言 | 已提交 |
| R14 | ✅ Flag 猎手策略升级：题目专属正则命中优先提交；整场已解 case 跳过省限额 | 套件回归 | 已提交 |
| R20 | ✅ platform.template.json 补 challenge_detail/solved 配置模板 | json 校验 | 已提交 |
| R21 | ✅ 前端「对账已解」入口（ops 页 → --reconcile） | node check + 套件 | 已提交 |
| R22 | ✅ 环境面板「清理旧镜像」按钮（clean 模式 keep_days/dry_run） | 套件 | 已提交 |
| R23 | ✅ app.js innerHTML 插值审计：157 处 esc 覆盖，2 处可信值加审计标记 | 静态扫描 | 已提交 |
| R15 | ✅ submitter 网络重试与退避（连接类失败重试 2 次；HTTPError 绝不重试防重复提交） | 套件回归 | 已提交 |
| R16 | ✅ fetch_challs --reconcile 平台已解状态对账（N-13②），写 platform_solved_detected 事件 | mock 已解列表断言 | 已提交 |
| R17 | ✅ triage 关键词扩充（七类各 +8~14 个实战词） | 套件回归 | 已提交 |
| R18 | ✅ 文档一致性门：API_HELP ⊇ ACTIONS（抓到 case.init 缺失）+ README 特性同步 | 门断言 | 已提交 |
| R19 | ✅ self_test 滑动窗口限速断言 | self_test 全过 | 已提交 |
| R16 | playbook 参数化条目（真实工具参数卡）N-09② | 待做 | |
| R17 | ctf-lab 三层环境联动文档 + SKILL.md 对齐 | 待做 | |
| R18+ | hunter 策略/日志轮转/分页/env clean/沙箱 smoke 测试/网关 mock 测试…（随前序轮次发现的问题动态插入） | | |

## 原则

- 每轮必须"真的更好"：有用户可感知的功能或可度量的质量提升，拒绝空转。
- 零 pip 依赖约束不破；安全模型（cap-drop/断网/提交白名单）不放松。
- 每轮全量回归（113+ 断言）后再提交；涉 Docker 的功能跑 e2e_env_check。


---

## R121-R128 新用户视角审计与修复（2026-10-30 批次）

以全新浏览器状态逐页走查 15 个视图 + 真实点击走查核心流程，发现并修复：

| 轮 | 问题 | 修复 |
|---|---|---|
| R121 | 「＋新建比赛」NameError（wb_actions 裸 SCRIPTS_DIR/ROOT 引用，合并遗留） | _core.SCRIPTS_DIR / _core.ROOT，静态扫描全模块确认干净 |
| R122 | 新建比赛→题目工作区→尝试快速记录→Flag 扫描→validate 全流程实测通过 | — |
| R123 | 快速尝试记录静默失败（缺 hypothesis/result 必填参数） | case_manager 支持 hypothesis=quick 自动建"快速记录"假设 |
| R124 | Flag 扫描→候选→validate 流程实测通过 | — |
| R125 | 网关注册→密钥展示→名册刷新浏览器实测通过 | — |
| R126 | 知识库无结果空态优化 | — |

**34 项调研提案全部清零**（S3 虚拟化为 100+ 题时评估项）。回归基线 230 断言全绿。


---

## R129-R141 视觉现代化与深度打磨批次（2026-10-30/31）

| 轮 | 内容 |
|---|---|
| R129 | 侧边栏 2026 现代化（浮起胶囊 active/渐变光条/无边框层次/图标点亮） |
| R130 | panel 内表格统一现代化（圆角容器/粘性表头/行悬停） |
| R141 | 任务输出搜索词 esc 匹配修复（R58 遗留：含 <>& 的搜索词匹配不到）；XSS 验证通过 |

**多 AI 协作体系**（R104-R112 已于前批记录）：网关后端+六端点+鉴权集成+L1 调度+L3 交接+L4 权限分级，
双 AI 全流程实测通过（alpha 认领→写假设→handoff→beta 接手→简报注入 prompt）。
**34 项调研提案全部清零**。回归基线 230 断言 + E2E 45 断言全绿。


---

## R151 新用户巡检：网关面板/成就/排行/系统概况（2026-11-02）

逐页浏览器走查发现并修复三处：

| 问题 | 修复 |
|---|---|
| 网关面板「已吊销（N）」折叠块 HTML 畸形（`<details>` 未闭合，吊销行被浏览器解析挤出到折叠区外永久可见） | details 内嵌套 `<table>` 正确包裹吊销行 |
| 网关表格/env 推送历史显示原始 ISO 时间戳（`10-30T08:59`） | 统一格式化为 `2026-10-30 08:59` |
| 系统概况 Docker 探测用裸 `docker`——WSL 部署上必然 FileNotFoundError 且原始异常直出给用户 | 复用 env_builder.docker_prefix()（探测+磁盘缓存）；异常人话化（命令不存在/超时/daemon 无响应三态）；docker 专项 60s 超时 |
| health.js 在 stale 态（R86 单飞探测期间返回 `{"stale":true}`）直接 `d.server.detail` → TypeError 未捕获，页面永久卡「检测中…」 | stale 友好等待文案（显示已等待秒数）+ 15s 自动重试（上限 5 分钟）+ d.server/d.docker 判空兜底 |

浏览器实测：吊销行收进折叠（2 行）、时间戳无原始 T、健康页三态文案均正确。回归 230 断言（+1 R151 健康人话化断言）。


---

## R152-R153 认领态过期一致性 + 文档对齐（2026-11-02）

| 轮 | 内容 |
|---|---|
| R152 | `wb_gateway.active_claims()`（只读过期惰性过滤）接入 `board_data`——弃坑 agent 的过期认领此前会让题目滞留「已认领」态最长 45min 不进无人认领条；+1 断言（过期/存活混合 store 过滤精确） |
| R153 | CHANGELOG 补 R120-R151 批次（新用户审计/视觉现代化/网关打磨三段）；README 版本注记对齐（v0.3.0 + 未发布批次至 R151） |
| 测试基建 | health detail 断言窗口放宽至 150s 并预热 docker_prefix——R151 后健康构建含 WSL docker 探测，慢 WSL 下 >30s（本机实测 60s+），原 5s 窗必挂；CI 无 docker 时首查即中不受影响 |


---

## R154 eslint 门抓获 env.js 丢函数回归（2026-11-02）

- eslint（errors-only，CI 同款）对 env.js 报 2 个 no-undef：`doVerify` / `scheduleRefresh`。
  **node --check 查不出这类错**——R145/146 结构修复时把 renderComp 内嵌的 `doVerify` 删丢
  （「验证」按钮点击即 ReferenceError）；`scheduleRefresh` 则是 opsEnv 移植残留引用（从未定义过，
  停服务后刷新永不执行）。从 a415b0e~1 恢复 doVerify 契约（POST /api/env/verify）并模块化，
  scheduleRefresh 改为正确的 renderEnv()。
- 防再发：测试套件静态检查区新增第 5 项「eslint static 0 errors」（本地有 node_modules 时跑，
  无则跳过由 CI lint 步骤兜底）——本地套件与 CI 门从此不再静默分叉。


---

## R154b docker prefix 陈值即用（stale-while-revalidate）（2026-11-02）

- **实测抓包**：prefix 磁盘缓存 1h TTL 一过期，首个 Docker 请求陪跑 WSL 冷探测——
  `/api/env/status` 实测 **97.8s** 才返回，环境页整段时间卡「加载环境状态…」；
  健康页有 stale+重试 UX 兜着，环境页/任务派发路径没有。
- **修复**：磁盘有陈值时请求路径即时返回陈前缀（机器上 docker 前缀几乎不变，风险趋零），
  后台线程重探刷新；重探失败保留陈值并清 `_DOCKER_PROBED` 允许后续重试（60s 负缓存节奏不变）。
  WSL 存活探测抽为 `_probe_wsl_locked()` 前台/后台共用。
- **自摆乌龙被自家门拦截**：首版用 `_prefix_cache_load(max_age=0.0)` 读陈值——语义是
  「age ≤ 0」即只命中未来时间戳，陈值永远读不到；**新增的 R154 断言当场红**，
  改为专用 `_prefix_cache_load_any()`（不看年龄）。回归断言先于上线发现问题，正是门的价值。
- **测试打桩教训**：patch `env_builder.threading.Thread` 打在了全局 threading 模块上，
  桩内再调 Thread 无限递归（RecursionError 崩整套件）——改为只替换 env_builder 视角的
  threading 属性（SimpleNamespace shim），零全局污染。
- 断言：隔离临时缓存文件 + threading shim（不碰真实缓存、不真探 WSL），CI/Linux 通用。


---

## v0.4.0 发布（2026-11-02）

- 自 v0.3.0（10-25）起六个未发布批次合并为单一 v0.4.0 章节：多 AI 协作体系
  （网关/调度/交接/权限分级）+ 视觉现代化 + 新用户审计修复 + 性能与质量门。
- 回归基线 56 → 234 断言 + eslint 静态门。tag: v0.4.0


---

## R155 侧边栏动真格：emoji 图标全线退役，内联 SVG 单色图标体系（2026-11-02）

**自省**：R129 那轮只调了配色/圆角/active 光条，图标仍是 emoji——那才是"上个世纪感"的真正
来源（跨平台渲染不一致、无法跟随主题、与克制科技风打架；代码里 `filter: grayscale(.55)`
给 emoji 降饱和这个补丁就是证据）。且 CSS 留有历次编辑叠加残留
（`.nav-group-label` 同规则重复声明 padding/letter-spacing、`#tabs` 定义两次）。

| 项 | 改动 |
|---|---|
| 图标体系 | 15 个导航按钮 emoji → 内联 SVG 描边图标（dashboard/十字准星/旗帜/节点图/闪电/奖杯/时钟/立方/心率/链环/书/文档/文件夹/奖章/滑杆），`stroke: currentColor` 随主题，零依赖 CSP 安全 |
| 三态 | 静止 muted3 灰 → 悬停提亮 → 激活 accent 蓝（emoji 时代的 grayscale 滤镜补丁退役）；**亮色主题自动换深色描边**（emoji 做不到） |
| 指示条 | active 光条从悬挑按钮外（left:-10px 易裁切）挪回按钮内部 left:2px |
| 折叠态 | 60px 图标栏居中对齐（实测偏差 <3px）、标签隐藏、全部按钮补 title 提示（折叠悬停可辨）；展开/折叠加 width 过渡 |
| 清理 | 重复声明合并；env 按钮补缺失 aria-label |
| 断言 | 静态门：nav 内 SVG 图标 ≥14 且 emoji span 为 0（防退化回 emoji） |

浏览器实测：15/15 SVG、三态色值正确、折叠居中、亮色跟随、指示条入位。


---

## R156 Fixed Sidebar 布局规范对齐（STYLEKIT sidebar-fixed）（2026-11-02）

按 Fixed Sidebar 风格规范逐项整改壳层，清理全部违规点：

| 规范项 | 整改 |
|---|---|
| fixed 定位 + 主区左边距 | `#sidebar` flex 子元素 → `position: fixed` 256px（w-64）；`#mainwrap` margin-left 联动（折叠 60px 图标栏）；过渡统一 150ms |
| 移动端抽屉 | 原 1024 图标栏 + 768 底部横条两套方案 → `<1024px` 离屏抽屉：hamburger 按钮（SVG 三线图标）+ 遮罩层 + Escape/点导航/点遮罩三路关闭；抽屉态强制完整展开（覆盖桌面折叠残态，`display: revert`） |
| 禁渐变文字 | 品牌名/页标题 background-clip:text 全部退役 → 实色（品牌 b 段 accent 色） |
| 禁蓝→紫渐变/发光 | logo 瓦片 --grad（蓝→紫）→ 实色 accent；激活底 tab-on-grad 渐变 → 平色 accent-bg + 1px 描边圈；激活指示条去 glow（Solid Active State，稳定锚点不漂浮） |
| Magnetic Icon Shift | hover 图标 translateX(2px) 右移引导视线（无缩放无花哨） |
| 禁玻璃态默认 | topbar backdrop-filter 退役 → 实色底 |
| 字重/层级 | font-weight 800/750 → 700 上限 |
| reduced-motion | 已有全局降级块（核对在位） |

**过程 bug（浏览器实测抓获）**：遮罩层插在 aside 与 mainwrap 之间，`+` 相邻兄弟选择器失效
——折叠后侧栏缩 60px 但主区 margin 仍 256px（内容被盖 196px）。改 `~` 通用兄弟修复。

断言：R156 静态门（fixed 定位/边距联动/汉堡/遮罩/抽屉态/reduced-motion 六要素齐查）。
浏览器实测：桌面 fixed 256/256、折叠 60/60 还原 256、800px 抽屉开合/遮罩/导航即收 全通过。


---

## R169 流程看板深打磨——揭开并修复整个 SSE 事件总线三层断裂（2026-11-05）

新功能首测（流程看板 R165/R167）：渲染/流程节点跳转/卡片深链/认领人 @AI1 回填全部通过，
但**SSE 实时联动失效**——登记假设后看板不刷新。逐层下钻发现是三层叠加断裂：

| 层 | 断裂 | 修复 |
|---|---|---|
| ① 前端 | pipeline/board 的 wb-event 处理直接 renderPipeline()——重绘的是内存旧 S.comp（计数永不更新） | 先 loadCompetition() 拉新再重绘 + 300ms 防抖收敛事件风暴 |
| ② 脚本层 | case 事件只写 cases/<slug>/case.json 的 events[]，从不进比赛级 events.jsonl——而 SSE 流端点只 tail 后者（events.jsonl 尾条停在 10-28） | case_manager.event() 中心化镜像到 comp events.jsonl（detail 带 slug；9 个调用点补传 case_dir）；附带复活 achievements speedrun 死规则（它读的 case_initialized 从未存在过） |
| ③ 启动 | **R157 重构遗失 startEventStream 调用**（app.js 只剩离开时间线时的 stopEventStream）——事件源从未建立，总线全死，时间线「SSE 实时推送」名存实亡 | init 恢复 startEventStream（事件流常开服务全部视图）；切换比赛重订流（URL 绑定 dir）；移除随页启停 |

排查方法学：手动 dispatch wb-event 链路正常 → 新开测试 EventSource 证伪流端点 → events.jsonl
mtime 取证（事件根本没写入）→ 反向定位脚本层与启动层。

**端到端实测**：登记第 6 条假设 → 流程看板 2.6s 内自动「假设 6 刚刚」、时间线实时插入条目。
+1 断言（总线三要素静态门）。demo 数据已还原、测试 agent 已吊销。


---

## R170 AI 看板局域网共享中心——一键热切换（2026-11-06）

用户之问：「ai看板里启动的局域网服务呢？都没有个位置可以看吗？」——实测确认缺口：
R168 的共享面板只有指导文案，**没有任何从网页开启共享的入口**（必须重启进程双击 bat），
topbar 也没有常驻状态可见。

| 件 | 实现 |
|---|---|
| 后端热切换 | `wb_http.switch_share_mode()`：关旧监听（daemon 化防 SSE 长连接阻塞）→ 按新模式重绑同端口 → 更新 RUNTIME/lan_urls/base_url → 清 Origin 白名单缓存；绑定失败自动回绑本机 |
| main 服务循环 | 原单次 `serve_forever()` 被 shutdown 打断即**整个进程退出**（首测一键开启直接打死服务）——改循环检测 RUNTIME["server"] 换新续跑 + server_switching 标志防竞态 |
| 路由 | `POST /api/share {enabled}`（admin 门拒 agent key 与匿名，实测 403）；开启前预落常驻令牌（新令牌随响应返回供浏览器静默续期）+ 入网码；切换经 0.25s timer 先应答后执行（worker 内同步切换自等待死锁） |
| 面板 | 本机态：「⚡ 开启局域网共享」按钮；共享态：「■ 停止共享」+ 地址/入网码/复制接入指令；切换后轮询 join-info 等落地（连接瞬断自动重试） |
| topbar 芯片 | 常驻「仅本机/共享中」状态（非管理员会话自动隐藏），点击直达共享面板——**任何页面都能一眼看到局域网服务状态** |
| 令牌归一 | `lan_token()` 移至 wb_core（--lan 启动与热切换共用，消除循环依赖） |

**E2E 实测**：芯片 仅本机→共享中（LAN 地址 192.168.56.1:8787 + 入网码显示）→停止→仅本机；
agent key/匿名切共享均 403；名册/认领/交接数据全程无损。**途中清掉 Windows SO_REUSEADDR
双绑导致的双实例**（新旧进程同抢 8787 分流请求——历史疑难场景，本次靠 netstat 双 LISTENING 实锤）。
