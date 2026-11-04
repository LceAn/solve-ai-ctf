@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CTF Workbench - LAN Share
mode con: cols=100 lines=40 >nul 2>&1
echo.
echo   LAN share mode: other AIs on the same network can join with the code printed below.
echo.
python "启动工作台.py" --lan --open %*
if errorlevel 1 (
  echo.
  echo   启动失败：请确认已安装 Python 3.11+ 并加入 PATH。
  echo   共享模式等价于：python 启动工作台.py --lan
  echo   若同网段连不上，请允许 python 通过 Windows 防火墙（端口 8787）。
  echo.
  pause
)
