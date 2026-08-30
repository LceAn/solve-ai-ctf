# CTF Workbench 沙箱镜像
#
# 分层设计（参考 CTF-BTFly images/，MIT License）：
#   ctfbox-base  —— python:3.12-slim + 通用 CLI + ctf 用户 + /workspace 约定
#   ctfbox-misc  —— misc/密码/取证常用 Python 库与工具（薄增量）
#   其余题型层按需仿照 misc/Dockerfile 添加（pwn 需 gdb/pwntools，web 需 sqlmap 等）。
#
# 构建（在 workbench/docker/ 目录下）：
#   docker build -f base/Dockerfile -t ctfbox-base:0.1.0 .
#   docker build -f misc/Dockerfile -t ctfbox-misc:0.1.0 .
#
# 运行约定（由 workbench server 自动拼装）：
#   -v <case目录>:/workspace          读写（attachments 进、artifacts/WRITEUP 出）
#   -v <workbench目录>:/solver:ro    只读（{solver_dir} 占位符 → /solver）
#   --network none（默认，可配置 bridge）
#   --cap-drop ALL --security-opt no-new-privileges --memory --cpus --pids-limit
#   容器名 ctfwb-<taskID>，超时由 server 看门狗 docker stop
