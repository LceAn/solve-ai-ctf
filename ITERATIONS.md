# 迭代账本（30 轮功能优化）

> 2026-09-06 启动。每轮 = 一个真实功能改进 + 测试验证 + 独立提交。
> 验证基线：`test_workbench.py` 113 项断言 + `scripts/self_test.py` + `e2e_env_check.py` 44 项（需 Docker）。
> 待推送提交在本地累积（代理 GitHub 路由故障；R1-R7 已提交，后台自动重试推送中）。

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
| R8 | BUUCTF 适配器迁移 + presets 并入 + submitter 走适配器 | 待做 | |
| R9 | 平台已解状态对账（拉取已解列表 → 对齐本地 case 状态）N-13② | 待做 | |
| R10-12 | server.py 按职责拆包（tasks/gateway/sandbox/http），单文件 <400 行 N-06 | 待做 | |
| R13-15 | app.js 拆 ES modules + lint N-11 | 待做 | |
| R16 | playbook 参数化条目（真实工具参数卡）N-09② | 待做 | |
| R17 | ctf-lab 三层环境联动文档 + SKILL.md 对齐 | 待做 | |
| R18+ | hunter 策略/日志轮转/分页/env clean/沙箱 smoke 测试/网关 mock 测试…（随前序轮次发现的问题动态插入） | | |

## 原则

- 每轮必须"真的更好"：有用户可感知的功能或可度量的质量提升，拒绝空转。
- 零 pip 依赖约束不破；安全模型（cap-drop/断网/提交白名单）不放松。
- 每轮全量回归（113+ 断言）后再提交；涉 Docker 的功能跑 e2e_env_check。
