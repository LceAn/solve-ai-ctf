# 迭代账本（30 轮功能优化）

> 2026-09-06 启动。每轮 = 一个真实功能改进 + 测试验证 + 独立提交。
> 验证基线：`test_workbench.py` 113 项断言 + `scripts/self_test.py` + `e2e_env_check.py` 44 项（需 Docker）。
> 待推送提交在本地累积（代理 GitHub 路由故障，后台自动重试中）。

## 轮次记录

| 轮 | 内容 | 验证 | 提交 |
|---|---|---|---|
| R1 | 抓题代理自动下载附件：CTFd 系 challenge detail → files 拉取进 case artifacts + sha256 登记（新增 case_manager artifact-add），消灭"附件手动放置" | 单测新增 mock 文件服务断言 | 本轮 |
| R2 | 沙箱并发上限（sandbox.json max_concurrent_sandbox） | 待做 | |
| R3 | 模型网关用量报表（/api/gateway/usage + 前端） | 待做 | |
| R4 | 复盘报告导出（Markdown：时间线+假设树+尝试+flag） | 待做 | |
| R5 | triage 签名扩充（容器镜像/固件/数据库/模型文件 + 兜底描述）N-13① | 待做 | |
| R6 | kb_search 检索命中率统计 + 零命中回流清单 N-09③ | 待做 | |
| R7 | 平台适配器抽象骨架（base + 注册机制，platform_agent/fetch_challs 走接口）N-07 | 待做 | |
| R8 | BUUCTF 适配器迁移 + presets 并入 | 待做 | |
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
