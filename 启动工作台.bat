@echo off
chcp 65001 >nul
cd /d "%~dp0"
title CTF Workbench - http://127.0.0.1:8787
echo ==========================================================
echo   CTF Workbench
echo   http://127.0.0.1:8787
echo.
echo   关闭此窗口即停止服务。
echo   可选参数示例：
echo     启动工作台.bat --competition "2608 ISG"
echo     启动工作台.bat --host 0.0.0.0 --token YOUR_TOKEN
echo ==========================================================
echo.
python "启动工作台.py" --open %*
if errorlevel 1 (
  echo.
  echo [启动失败] 请确认已安装 Python 3.11+ 并在 PATH 中。
  pause
)
