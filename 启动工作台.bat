@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CTF Workbench
mode con: cols=100 lines=32 >nul 2>&1
python "启动工作台.py" --open %*
if errorlevel 1 (
  echo.
  echo   启动失败：请确认已安装 Python 3.11+ 并加入 PATH。
  echo   可用参数：--competition "比赛名"   --host 0.0.0.0 --token YOUR_TOKEN
  echo.
  pause
)
