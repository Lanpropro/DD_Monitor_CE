@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
rem 双击启动 DD监控室CE（不开控制台窗口）。要看日志请用 run-console.cmd
setlocal
set "DDM_SETTINGS_PROCESS=1"
set "DDM_QTQUICK_DANMAKU=1"
set "DDM_FOLDER_MOTION_CAPTURE=1"
set "DDM_THEME_CAPTURE=1"
set "DDM_FULLSCREEN_CAPTURE=1"
set "PROJ=%~dp0"
if exist "%PROJ%work\deps\PySide6\QtCore.pyd" set "PYTHONPATH=%PROJ%work\deps;%PYTHONPATH%"

set "PY=%PROJ%.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\pythonw.exe"
if not exist "%PY%" goto nopy

if /i "%~1"=="--sc-simulator" goto scsimulator
if /i "%~1"=="--check-widget-lifetime" goto widgetLifetimeCheck
if /i "%~1"=="--check-sc-layers" goto scLayersCheck
if /i "%~1"=="--check-stream-info" goto streamInfoCheck
if /i "%~1"=="--diagnose-responsiveness" goto responsiveness
if /i "%~1"=="--diagnose-fullscreen" goto fullscreen
if /i "%~1"=="--diagnose-douyu" goto douyu
if /i "%~1"=="--diagnose-douyu-deep" goto douyuDeep
if /i "%~1"=="--diagnose-fullscreen-input" set "DDM_FULLSCREEN_INPUT_CAPTURE=1"
if /i "%~1"=="--diagnose-sc" set "DDM_SC_PAINT_CAPTURE=1"
if /i "%~1"=="--diagnose-danmaku-motion" set "DDM_DANMAKU_MOTION_CAPTURE=1"
rem TEMP BUG-001: remove diagnostic redirect after the drag/OLE recurrence is fixed.
start "" "%PY%" "%PROJ%dev\diagnose_drag_windows.py"
exit /b 0

:widgetLifetimeCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_widget_lifetime
exit /b %errorlevel%

:scLayersCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_sc_simulator.py" NativeSurfaceTests
if errorlevel 1 exit /b %errorlevel%
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_sc_simulator.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_super_chat.py"
exit /b %errorlevel%

:streamInfoCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_stream_info.py" StreamInfoTests.test_stream_dialog_follows_independent_fullscreen_owner_and_survives_exit
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_danmaku_motion_diagnostics.py"
if errorlevel 1 exit /b %errorlevel%
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_stream_info.py"
exit /b %errorlevel%

:responsiveness
start "" "%PY%" "%PROJ%main.py" --diagnose-responsiveness
exit /b 0

:douyu
start "" "%PY%" "%PROJ%dev\diagnose_drag_windows.py" --diagnose-douyu
exit /b 0

:douyuDeep
start "" "%PY%" "%PROJ%dev\diagnose_drag_windows.py" --diagnose-douyu-deep
exit /b 0

:fullscreen
start "" "%PY%" "%PROJ%dev\diagnose_drag_windows.py" --diagnose-fullscreen
exit /b 0

:scsimulator
if /i "%~2"=="--smoke" (
    start "" "%PY%" "%PROJ%dev\sc_simulator.py" --smoke
) else (
    start "" "%PY%" "%PROJ%dev\sc_simulator.py"
)
exit /b 0

:nopy
echo 没找到 Python 解释器。
echo 请在本目录执行：  python -m venv .venv
echo 然后执行：        .venv\Scripts\pip install -r requirements.txt
pause
exit /b 1
