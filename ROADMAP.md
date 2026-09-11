# 未来更新计划（Roadmap）

> 最近更新：2026-09-11。仅用于已授权的 CTF 比赛与靶场。计划按"先稳后扩"推进。

## 短期

- **平台适配器抽象**：把 CTFd / BUUCTF 特定逻辑收敛为适配器接口，方便新增平台。
  目前同一平台的知识散在四处——`platform_agent.py`（探测）、`ctf_session.py`（登录/拉题）、
  `presets/*.json`（预设）、`fetch_challs.py`（类别过滤），`competition.json` 里再写一份提交配置。
  目标：新增平台只加一个适配器文件 + 一份预设，不改 server / agent 代码。
- **`GET /api/help` 与 README 协作 API 章节对齐**：两边目前各写各的，容易漏字段。

## 中期

- **`server.py` 模块化**：单文件已 2200+ 行（HTTP 路由 / 任务生命周期 / Docker 沙箱 / 模型网关 /
  平台代理 / SSE / 视图缓存全在一处）。按职责拆包，保持零第三方依赖。
- **复盘报告导出**（Markdown：时间线 + 假设树 + 最终 payload + 教训）。
- **知识库扩充**：每类题型的 playbook 补充**带完整参数**的可复现条目（现有多为要点式）；
  每场比赛收尾按模板往 `case-corpus.md` 追加案例，避免语料只来自单场比赛。
- **模型网关用量报表**（按 case / 按题型统计 token 消耗）。
- **分诊与对账**：扩充 `triage.py` 的文件签名覆盖（容器镜像、固件、数据库文件）；
  增加「拉取平台已解列表 → 与本地 case 状态对账」的动作。

## 长期 / 想法

- 多比赛并行时的资源隔离策略（沙箱并发上限、主机资源预算）。
- 与 `ctf-lab` 本地环境（Ghidra / pwndbg 等）的联动说明。

## 已完成

- **2026-09-11 沙箱镜像清单文档化**：`workbench/docker/README.md` 补全七类镜像的基座、
  关键工具版本与用途，并修正全文每行以 `#` 开头导致的渲染问题。
- **2026-09-11 前端模块化**：`static/app.js` 由 1861 行拆至 309 行，新增 `api/md/sse/state/ui`
  与 `views/` 下 14 个视图模块，`index.html` 改用 `<script type="module">`。
- **2026-09-11 静态质量门**：`test_workbench.py` 增补三条断言——静态 JS CSP 安全
  （去注释后无 `eval(` / `new Function(`）、无 VCS 冲突标记、Origin 白名单覆盖本机全部地址。
- **2026-09-05 安全加固**：CSP / nosniff / Referrer-Policy 响应头；mdRender 链接 scheme 白名单；
  `/api/agent/start` 参数白名单；`shell=True` 全清（宿主侧一律 argv 调用）；
  共享模式无 token 时硬拒绝启动（需显式 `--allow-insecure`）。
