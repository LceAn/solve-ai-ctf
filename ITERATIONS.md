# 迭代账本（30 轮功能优化）

> 2026-09-06 启动。每轮 = 一个真实功能改进 + 测试验证 + 独立提交。
> 验证基线：`test_workbench.py` 113 项断言 + `scripts/self_test.py` + `e2e_env_check.py` 44 项（需 Docker）。
> 待推送提交在本地累积（代理 GitHub 路由故障；R1-R23 已提交（23/30）；剩余 7 轮：R24-26 server.py 拆包（N-06，验收单文件<400行：wb_context/wb_tasks/wb_sandbox/wb_gateway/wb_actions/wb_http 分层，server.py 作 facade）；R27-28 app.js 拆 ES modules（N-11，core/api/views，CSP 'self' 兼容）+eslint；R29 ctf-lab 联动文档 + SKILL.md 同步；R30 v0.2.0 tag + CHANGELOG 收尾，后台自动重试推送中）。

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
