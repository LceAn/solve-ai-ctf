# solve-ai-ctf 根目录整理 + GitHub 仓库清理方案

现状结论：根目录混有 9 月两仓 merge 时的对比遗留物（约 105KB、全仓零引用）、被跟踪的临时文件、5 份停在 9 月的过时规划文档；远端挂着一条已完全合并的陈旧分支 `backup/local-43-rounds`；CHANGELOG 缺 R57–R71 记录。工作区另有上个会话遗留的 R72 未提交改动（已确认：测试绿就先提交）。

## 第一步：安置 R72 未提交改动
- 跑 CI 同款测试：`python scripts/self_test.py`、`python workbench/test_workbench.py`
- 全绿 → 单独提交为 R72（board2 agent 汇总卡），消息沿用仓库现有中文风格；若红则停下报告，不强行提交

## 第二步：删除零引用遗留物（git 历史仍可找回）
- `git rm`：`their_server_dump.py`（103KB 对方 server 全量 dump）、`my_eps.txt`、`their_eps.txt`（API 端点对比清单）、`.tmp-probe/def.txt`（误入库的 1 字节临时文件）
- 磁盘删除未跟踪垃圾：`.tmp-dash/`、根目录 `__pycache__/`
- `.gitignore` 增加 `.tmp-*/` 规则防复发

## 第三步：文档归档与补账
- 新建 `docs/`，`git mv` 收纳 5 份：ROADMAP.md、ITERATIONS.md、TODO-OPTIMIZATION.md、优化提案-工作台全面调研-20260906.md、优化提案-收尾盘点.md；每份开头加一行归档状态说明（截至时间，后续进度看 CHANGELOG）
- 修正收尾盘点文档里的互引路径
- CHANGELOG.md 补 `[2026-10-23]` 段，从 git log 提炼 R57–R71 要点
- README 快速开始补一行 `启动工作台.py` 的启动方式（该启动器目前零文档）
- 根目录保留：README、CHANGELOG、SKILL（被 wb_core.py:337、competition.py:408 等运行时引用，不可移动）、LICENSE、.gitignore

## 第四步：验证（对齐 .github/workflows/ci.yml）
- `python -m compileall -q .` + 两套测试 + `npx eslint static/`（error 零）

## 第五步：提交推送
- 整理改动单独提交（中文描述风格），push main

## 第六步：GitHub 远端清理
- 删除远端陈旧分支 `backup/local-43-rounds`（已验证是 main 的祖先，完全合并，安全）；`git fetch --prune`
- 检查远端标签：v0.2.0/v0.2.1 若在远端默认保留
- 仓库 topics：本机无 gh CLI，尝试 git credential 取 token 调 GitHub API 设置 topics（ctf / ai-agents / docker / security 等）；失败则给出网页手动设置的标签清单
- description 已存在且准确，不动

不做的事：不重写 git 历史（仓库仅几 MB，their_server_dump.py 删档后留在历史里无害）；不动 references/ 中文命名知识库文件、不动 比赛/ 与 workbench-data/（均已 ignore 的本地数据）。