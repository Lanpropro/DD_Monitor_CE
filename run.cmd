@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
rem 双击启动 DD监控室CE（不开控制台窗口）。要看日志请用 run-console.cmd
setlocal
set "DDM_SETTINGS_PROCESS=1"
if not defined DDM_QTQUICK_DANMAKU set "DDM_QTQUICK_DANMAKU=0"
set "PROJ=%~dp0"
if exist "%PROJ%work\deps\PySide6\QtCore.pyd" set "PYTHONPATH=%PROJ%work\deps;%PYTHONPATH%"

set "PY=%PROJ%.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\pythonw.exe"
if not exist "%PY%" goto nopy

start "" "%PY%" "%PROJ%main.py"
exit /b 0

:nopy
echo 没找到 Python 解释器。
echo 请在本目录执行：  python -m venv .venv
echo 然后执行：        .venv\Scripts\pip install -r requirements.txt
pause
exit /b 1
