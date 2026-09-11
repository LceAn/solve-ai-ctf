# 更新日志

本文件记录 Solve-AI-CTF 的重要变更，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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
- **Origin 白名单覆盖不全**：`_local_origins()` 只列 `127.0.0.1/localhost/[::1]`，而
  `--host 0.0.0.0 --token` 共享模式下用局域网/Tailscale 地址访问时，所有写操作被判 403
  （表现为"能看不能点"）。改为并集 loopback 别名 + `local_urls()` 枚举的全部本机网卡地址。
- 沙箱镜像文档 `workbench/docker/README.md` 全文每行以 `#` 开头（渲染成整篇标题），
  重写为正常 Markdown 并补全七类镜像清单。

### 测试
- 新增三条静态质量门断言：静态 JS CSP 安全（剔除注释后不得出现 `eval(` / `new Function(`）、
  技能树无 VCS 冲突标记、Origin 白名单覆盖本机全部访问地址。
- 新增运行时断言：`/` 响应必须带 CSP（`script-src 'self'` 且不含 `unsafe-eval`）与
  `X-Content-Type-Options: nosniff`。端到端断言 119 → 124。

### 安全
- `/api/agent/start` 的 `categories` 参数增加白名单校验：该值会拼进 shell 命令串，未校验时可注入任意命令。
- 新增回归用例：注入载荷返回 400，合法 `web,crypto` 正常派发。

## [2026-09-05]

### 新增
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

### 修复
- 模型网关未捕获异常导致连接中断。
- Flag 流水线与方向下拉的数据一致性（视图缓存失效盲区）。
- CHANGELOG 残留未解决的合并冲突标记。

## [2026-08-30]

- 首个公开版本：确定性工具链 + 本地 Web 工作台 + Docker 沙箱 + Flag 猎手。
- 新增 `CHANGELOG.md` 与 `ROADMAP.md`，README 增加文档索引。
