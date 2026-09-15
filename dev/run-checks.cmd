@echo off
rem 跑一遍全部分功能自检（离屏，不弹窗口，不动真实配置）
setlocal
set "PROJ=%~dp0.."
set "PY=%PROJ%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe"
if not exist "%PY%" goto nopy

cd /d "%PROJ%"
set "DDM_NO_SAVE=1"
set "PYTHON_VLC_LIB_PATH=%PROJ%\libvlc.dll"
set "PYTHONIOENCODING=utf-8"

for %%f in ("%PROJ%\dev\selfcheck_*.py") do (
    echo === %%~nf ===
    "%PY%" -u "%%f"
    echo.
)
echo 全部跑完。
pause
exit /b 0

:nopy
echo 没找到 Python 解释器，请先建虚拟环境并安装 requirements.txt
pause
