# 更新日志

本文件记录 Solve-AI-CTF 的重要变更，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [未发布] - 2026-09-05

### 新增
- case.init 动作与题目列表「初始化 case」按钮：手工目录场景的补救入口。
- 尝试记录结局筛选 chips（全部/成功/部分进展/失败/出错）。
- 预设管理：`/api/presets` 枚举 + 开赛自动化页预设下拉（BUUCTF 预设内置）。
- 模型网关异常包裹与 `--verbose` 请求日志；任务面板容器徽标与起止时间。
- 可用标志一键复制；反馈系统 toast 队列（info/ok/warn/err）与全局 busy 流光条。
- 快捷键 `Alt+1..9` 切换页面，`?` 呼出帮助浮层（快捷键 + Agent 协作端点）。
- 系统概况题型镜像全家桶状态卡（七镜像逐一 ✓/✗）。

### 性能
- 比赛视图 mtime 缓存（签名含全部 case.json），写动作后自动失效。

### 修复
- 模型网关未捕获异常导致连接中断。
- Flag 流水线与方向下拉的数据一致性（视图缓存失效盲区）。

## 2026-09-05
- case.init 动作：手工目录场景的 case 补救入口（API + 题目列表按钮）
- 服务端健壮性：模型网关异常包裹、--verbose 请求日志、listen backlog 提升
- 性能：比赛视图 mtime 缓存（写动作后自动失效），题目多时显著减少 IO
- 预设管理：/api/presets 枚举 + 开赛自动化页预设下拉（BUUCTF 预设内置）
- 尝试记录：结局筛选 chips（全部/成功/部分进展/失败）
- 任务面板：容器徽标、起止时间、富化状态行
- 可用标志：一键复制；反馈系统：toast 队列（info/ok/warn/err）+ 全局 busy 流光条
- 快捷键：Alt+1..9 切页面，? 呼出帮助（快捷键表 + Agent 协作端点）
- 平台会话：ctf_session 模块（表单登录 + nonce CSRF + session 拉题），BUUCTF 预设
- 开赛自动化：平台对接代理（探测写配置）+ 抓题代理（限额/类别过滤）
- 安全：CSP/nosniff/Referrer-Policy 响应头、mdRender scheme 白名单（作者提交）

## 2026-08-30
- 首个公开版本：确定性工具链 + 本地 Web 工作台 + Docker 沙箱 + Flag 猎手
>>>>>>> 00f7cfd (十轮优化：预设管理/视图缓存/网关加固/筛选chips/case.init/CHANGELOG)

## [未发布] - 2026-08-30

### 新增
- 新增 `CHANGELOG.md` 与 `ROADMAP.md`。
- README 增加文档索引。

### 说明
- 本次为文档整理，工作台、代理与沙箱代码未改动。

## [初始版本] - 2026-08-30

- 项目创建：AI 驱动的 CTF 解题工作台（分诊 → 假设 → 有界执行 → 验证 → 提交 → 复盘）。
- 本地 Web 控制台（`workbench/`）、Docker 沙箱执行、Flag 自动识别与自动提交、多 Agent 协作接口、知识库检索。
- 平台对接：CTFd 系探测与 BUUCTF 预设（表单登录 + 会话拉题）。
