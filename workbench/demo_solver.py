"""演示用「求解器」：读取 workbench 派发的提示词文件，分阶段打印进度。"""
import sys
import time
from pathlib import Path

args = sys.argv[1:]
prompt = Path(args[0]).read_text(encoding="utf-8") if args else ""
title = next((l for l in prompt.splitlines() if l.startswith("# 题目")), "# 题目：（未知）")
print(f"[solver] 收到提示词，题目：{title.strip('# ')}")
for i, phase in enumerate(["分诊附件", "登记假设阶梯", "有界执行与验证"], 1):
    print(f"[solver] 阶段 {i}/3：{phase} …", flush=True)
    time.sleep(1.2)
print("[solver] 完成（演示脚本，不产生真实 flag）", flush=True)
