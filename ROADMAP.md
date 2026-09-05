# 未来更新计划（Roadmap）

> 最近更新：2026-09-06。仅用于已授权的 CTF 比赛与靶场。计划按"先稳后扩"推进。

## 短期

- ~~平台适配器抽象~~ ✅ 2026-09-06 骨架落地：`workbench/platform_adapters.py`（ctfd/buuctf）+ `--adapter` 声明 + 预设统一；新增平台 = 一个 Adapter 子类。
- ~~沙箱镜像清单文档化~~ ✅ 2026-09-05：七类题型镜像 + 四层矩阵见 `workbench/docker/README.md`；
  比赛/题目级定制（env spec + env_builder）见 `workbench/docker/COMPETITION_ENV_DESIGN.md`。
- `GET /api/help` 输出与 README 的协作 API 章节对齐。

## 中期

- ~~复盘报告导出~~ ✅ 2026-09-06：`competition.py report` / `competition.report` 动作（flag 自动脱敏）。
- 知识库扩充：每类题型的 playbook 补充实战案例条目。
- 模型网关的用量报表（按 case / 按题型统计 token 消耗）。

## 长期 / 想法

- 多比赛并行时的资源隔离策略（沙箱并发上限、主机资源预算）。
- 与 `ctf-lab` 本地环境（Ghidra/pwndbg 等）的联动说明。
