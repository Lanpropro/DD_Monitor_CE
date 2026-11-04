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
if /i "%~1"=="--mobile" goto mobile
if exist "%PROJ%work\deps\PySide6\QtCore.pyd" set "PYTHONPATH=%PROJ%work\deps;%PYTHONPATH%"

set "PY=%PROJ%.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=F:\CodexAppManager\Code\DD_Monitor-venv\Scripts\pythonw.exe"
if not exist "%PY%" goto nopy

set "DIAG_ARG=%~1"
if /i "%DIAG_ARG:~0,19%"=="--diagnose-session=" goto diagnosticSession
if /i "%~1"=="--sc-simulator" goto scsimulator
if /i "%~1"=="--check-widget-lifetime" goto widgetLifetimeCheck
if /i "%~1"=="--check-diagnostics" goto diagnosticsCheck
if /i "%~1"=="--check-image-cache" goto imageCacheCheck
if /i "%~1"=="--check-fullscreen-layers" goto fullscreenLayersCheck
if /i "%~1"=="--check-wall-replacement" goto wallReplacementCheck
if /i "%~1"=="--check-sc-layers" goto scLayersCheck
if /i "%~1"=="--check-stream-info" goto streamInfoCheck
if /i "%~1"=="--check-notice-close" goto noticeCloseCheck
if /i "%~1"=="--diagnose-responsiveness" goto responsiveness
if /i "%~1"=="--diagnose-fullscreen" goto fullscreen
if /i "%~1"=="--diagnose-douyu" goto douyu
if /i "%~1"=="--diagnose-douyu-deep" goto douyuDeep
if /i "%~1"=="--diagnose-fullscreen-input" set "DDM_FULLSCREEN_INPUT_CAPTURE=1"
if /i "%~1"=="--diagnose-control-swap" set "DDM_CONTROL_SWAP_CAPTURE=1"
if /i "%~1"=="--diagnose-wall-replacement" set "DDM_WALL_REPLACEMENT_CAPTURE=1"
if /i "%~1"=="--diagnose-sc" set "DDM_SC_PAINT_CAPTURE=1"
if /i "%~1"=="--diagnose-danmaku-motion" set "DDM_DANMAKU_MOTION_CAPTURE=1"
if /i "%~1"=="--diagnose-notice-close" set "DDM_NOTICE_CLOSE_CAPTURE=1"
rem TEMP BUG-001: remove diagnostic redirect after the drag/OLE recurrence is fixed.
start "" "%PY%" "%PROJ%dev\diagnose_drag_windows.py"
exit /b 0

:diagnosticsCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_diagnostics
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_diagnostic_session
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_development_hang
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\selfcheck_diagnostics.py"
exit /b %errorlevel%

:widgetLifetimeCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_widget_lifetime
exit /b %errorlevel%

:imageCacheCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_image_cache
exit /b %errorlevel%

:fullscreenLayersCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_fullscreen_controls.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_fullscreen_switch.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_settings_occlusion.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_plugin_controls.py" ControlsTests.test_independent_fullscreen_moves_docked_input_and_preserves_drafts ControlsTests.test_danmaku_swap_docks_input_before_new_geometry ControlsTests.test_hot_swap_refreshes_native_audio_controls_at_final_geometry
exit /b %errorlevel%

:wallReplacementCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_main_notices.py" MainNoticesTests.test_live_replacement_accepts_window_dispatch_before_widget_events MainNoticesTests.test_live_replacement_trace_preserves_window_dispatch
if errorlevel 1 exit /b %errorlevel%
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_main_notices.py" MainNoticesTests.test_live_notice_selects_one_replacement_without_expanding_full_wall MainNoticesTests.test_live_replacement_can_cancel_and_does_not_accept_sidebar_clicks MainNoticesTests.test_live_notice_uses_visible_empty_slot_before_replacement_and_skips_duplicates
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_wall_card_replacement.py"
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

:noticeCloseCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_notice_close.py"
if errorlevel 1 exit /b %errorlevel%
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_main_notices.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_notification_center.py"
exit /b %errorlevel%

:diagnosticSession
start "" "%PY%" "%PROJ%main.py" "%~1"
exit /b 0

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

:mobile
where flutter.bat >nul 2>nul
if errorlevel 1 (
    echo 请先将 Flutter SDK 的 bin 目录加入 PATH。
    exit /b 1
)
pushd "%PROJ%mobile"
call flutter.bat run
set "MOBILE_EXIT=%ERRORLEVEL%"
popd
exit /b %MOBILE_EXIT%
