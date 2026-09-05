# envs/ —— 比赛环境 spec 模板与示例

本目录是 [COMPETITION_ENV_DESIGN.md](../COMPETITION_ENV_DESIGN.md) 的配套模板（P0 阶段产物），
env_builder.py（P1）落地后直接以这里的文件为渲染模板。

| 文件 | 用途 |
|---|---|
| `comp.example.yaml` | 比赛级 spec：复制到 `比赛/xxx/env/comp.yaml` 后填写 |
| `challenge.pwn-glibc235.example.yaml` | 题目级 spec 示例：pwn 题，锁定 glibc 2.35 |
| `challenge.web-lamp.example.yaml` | 题目级 spec 示例：web 题，services 编排本地复现 LNMP |
| `Dockerfile.tmpl` | builder 渲染用的参数化模板（展示 spec → Dockerfile 的映射） |
| `solver/CLAUDE.md` | 约束层：随 L0 烤入镜像，双写为 AGENTS.md 兼容 codex 生态 |

约定：YAML spec 是**构建期**格式（等同代码，进 git 审查）；运行时组件只读
`env/gen/.built.json`（JSON）。题目 spec 逐字段覆盖比赛 spec。
