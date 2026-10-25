@echo off
chcp 65001 >nul
rem 默认仅运行仓库检查；用 --list 查看其他套件。
setlocal
set "PROJ=%~dp0.."
if exist "%PROJ%\work\deps\PySide6\QtCore.pyd" set "PYTHONPATH=%PROJ%\work\deps;%PYTHONPATH%"
set "PY=%PROJ%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%PROJ%\..\DD_Monitor-venv\Scripts\python.exe"
if exist "%PY%" goto ready
set "PY=python"
where python >nul 2>&1 || goto nopy
:ready
cd /d "%PROJ%" || exit /b 1
set "DDM_NO_SAVE=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%PY%" -u "%PROJ%\dev\run_checks.py" %*
exit /b %errorlevel%
:nopy
echo 没找到 Python 解释器，请先建虚拟环境并安装 requirements.txt
exit /b 1
