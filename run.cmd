@echo off
rem 双击启动 DD 监控室（不开控制台窗口）。要看日志请用 run-console.cmd
setlocal
set "PROJ=%~dp0"

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
