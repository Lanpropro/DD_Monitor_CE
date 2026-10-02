@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
rem 带控制台启动，方便看实时日志（取流、重连、设置变更等）
setlocal
set "PROJ=%~dp0"

set "PY=%PROJ%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe"
if not exist "%PY%" goto nopy

cd /d "%PROJ%"
"%PY%" "%PROJ%main.py"
set "RESULT=%ERRORLEVEL%"
echo.
echo 程序已退出，退出码：%RESULT%。
pause
exit /b %RESULT%

:nopy
echo 没找到 Python 解释器，请先建虚拟环境：
echo   python -m venv .venv
echo   .venv\Scripts\pip install -r requirements.txt
pause
exit /b 1
