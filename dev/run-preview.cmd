@echo off
rem 把界面渲染成 PNG 存到 dev\preview\（改完样式看效果用）
setlocal
set "PROJ=%~dp0.."
set "PY=%PROJ%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\python.exe"
if not exist "%PY%" goto nopy

cd /d "%PROJ%"
set "DDM_NO_SAVE=1"
set "PYTHON_VLC_LIB_PATH=%PROJ%\libvlc.dll"
set "PYTHONIOENCODING=utf-8"
if not exist "%PROJ%\dev\preview" mkdir "%PROJ%\dev\preview"

for %%f in ("%PROJ%\dev\preview_*.py") do (
    echo === %%~nf ===
    "%PY%" -u "%%f"
)
echo.
echo 图片在 dev\preview\
explorer "%PROJ%\dev\preview"
exit /b 0

:nopy
echo 没找到 Python 解释器，请先建虚拟环境并安装 requirements.txt
pause
