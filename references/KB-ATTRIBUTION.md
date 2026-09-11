# 知识库素材来源与版权声明

## 素材来源

本目录下的以下文件来源于 GitHub 仓库 [Dest1ny-Sec/Des-CTF-Knowledge](https://github.com/Dest1ny-Sec/Des-CTF-Knowledge)（2026-05-30 快照）：

- `SQL.md` / `命令执行.md` / `文件上传漏洞.md` / `文件包含.md` / `SSRF漏洞.md`
- `PHP反序列化漏洞总结.md` / `php代码审计.md` / `SSTI.md` / `JWT.md`
- `图片隐写.md` / `音频隐写.md` / `压缩包总结.md`
- `PAYLOAD-CHEATSHEET.md` / `AI-SEARCH-INDEX.md`

## MIT 许可证范围

上述文件为该仓库自有 MIT 内容（仓库根 LICENSE 为 MIT），可自由使用、修改、分发，需保留原作者署名。

## 未复制内容（版权状态不明）

仓库中的 **1156 篇大赛 WriteUp** 与 **50+ 解题脚本** **未复制进本主仓库**：
- WP 来源为 ctfiot.com 等互联网公开渠道，版权归原作者所有，版权状态与仓库根 MIT 冲突
- 脚本为公开收集，版权归原作者所有

## 运行时接入方式（WP 与脚本）

用户如需检索完整 WP 与脚本，通过环境变量运行时接入，不写入主仓库：

1. 本地 clone 仓库：`git clone https://github.com/Dest1ny-Sec/Des-CTF-Knowledge.git`
2. 设置环境变量：`KB_EXTERNAL_DIR=<克隆路径>`（PowerShell `$env:KB_EXTERNAL_DIR="..."`）
3. 重启 `python solve-ai-ctf/workbench/server.py`
4. 前端「资源库」页点击「📚 外部库」tab 检索

`kb_search.py` 以 `kind="external_kb"` 扫描该目录，跳过 `.idx.md` 索引文件，限制单次扫描 200 文件 / 单文件 5000 行以保证性能。

## 脚本使用约束

仓库的 50+ 脚本如需作为可执行工具使用，**必须先经 `triage.py` 静态分诊**（project_memory 硬约束：未知附件必须先经 triage.py，绝不直接执行）：

```bash
python solve-ai-ctf/scripts/triage.py <脚本目录> --json-out triage.json
```
