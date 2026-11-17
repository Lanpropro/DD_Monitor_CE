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
if /i "%~1"=="--check-media-sources" goto mediaSourcesCheck
if /i "%DIAG_ARG%"=="--diagnose-session" set "DIAG_ARG=--diagnose-session=%~2"
if /i "%DIAG_ARG:~0,19%"=="--diagnose-session=" goto diagnosticSession
if /i "%~1"=="--check-plugin-replacements" goto pluginReplacementsCheck
if /i "%~1"=="--accept-live-translate" goto liveTranslateAcceptance
if /i "%~1"=="--check-danmaku-color" goto danmakuColorCheck
if /i "%~1"=="--check-danmaku-settings" goto danmakuSettingsCheck
if /i "%~1"=="--check-settings-search" goto settingsSearchCheck
if /i "%~1"=="--check-settings-controls" goto settingsControlsCheck
if /i "%~1"=="--check-update-settings" goto updateSettingsCheck
if /i "%~1"=="--check-portrait-ui" goto portraitUiCheck
if /i "%~1"=="--check-tray-menu" goto trayMenuCheck
if /i "%~1"=="--check-browser-accounts" goto browserAccountsCheck
if /i "%~1"=="--check-danmaku-independent" goto danmakuIndependentCheck
if /i "%~1"=="--sc-simulator" goto scsimulator
if /i "%~1"=="--check-widget-lifetime" goto widgetLifetimeCheck
if /i "%~1"=="--check-ui-polish" goto uiPolishCheck
if /i "%~1"=="--check-douyu-source-recovery" goto douyuSourceRecoveryCheck
if /i "%~1"=="--check-live-buffering" goto liveBufferingCheck
if /i "%~1"=="--check-playback-feedback" goto playbackFeedbackCheck
if /i "%~1"=="--check-playback-controls" goto playbackControlsCheck
if /i "%~1"=="--check-live-elapsed" goto liveElapsedCheck
if /i "%~1"=="--check-functional-modules" goto functionalModulesCheck
if /i "%~1"=="--check-widget-boundaries" goto widgetBoundariesCheck
if /i "%~1"=="--check-room-add" goto roomAddCheck
if /i "%~1"=="--check-follow-import" goto followImportCheck
if /i "%~1"=="--check-room-presets" goto roomPresetsCheck
if /i "%~1"=="--check-sidebar-drag" goto sidebarDragCheck
if /i "%~1"=="--check-preview-scroll" goto previewScrollCheck
if /i "%~1"=="--check-diagnostics" goto diagnosticsCheck
if /i "%~1"=="--check-qt-log" goto qtLogCheck
if /i "%~1"=="--check-native-memory" goto nativeMemoryCheck
if /i "%~1"=="--check-picture-in-picture" goto pictureInPictureCheck
if /i "%~1"=="--check-audio-normalization" goto audioNormalizationCheck
if /i "%~1"=="--check-wall-panes" goto wallPanesCheck
if /i "%~1"=="--check-sidebar-navigation" goto sidebarNavigationCheck
if /i "%~1"=="--check-wall-removal" goto wallRemovalCheck
if /i "%~1"=="--check-continuous-corners" goto continuousCornersCheck
if /i "%~1"=="--check-hotfix-updates" goto hotfixUpdatesCheck
if /i "%~1"=="--check-app-updates" goto appUpdatesCheck
if /i "%~1"=="--check-update-progress" goto updateProgressCheck
if /i "%~1"=="--preview-updates" goto updatePreview
if /i "%~1"=="--check-bili-profile" goto biliProfileCheck
if /i "%~1"=="--check-settings-control" goto settingsControlCheck
if /i "%~1"=="--check-settings-scroll" goto settingsScrollCheck
if /i "%~1"=="--check-settings-shutdown" goto settingsShutdownCheck
if /i "%~1"=="--check-settings-performance" goto settingsPerformanceCheck
if /i "%~1"=="--check-window-layout" goto windowLayoutCheck
if /i "%~1"=="--check-window-resize-trace" goto windowResizeTraceCheck
if /i "%~1"=="--check-cross-screen" goto crossScreenCheck
if /i "%~1"=="--check-window-state" goto windowStateCheck
if /i "%~1"=="--check-dialog-modules" goto dialogModulesCheck
if /i "%~1"=="--check-stream-playback" goto streamPlaybackCheck
if /i "%~1"=="--check-sidebar-folders" goto sidebarFoldersCheck
if /i "%~1"=="--check-folder-expansion" goto folderExpansionCheck
if /i "%~1"=="--preview-folder-stress" goto folderStressPreview
if /i "%~1"=="--check-folder-stress" goto folderStressCheck
if /i "%~1"=="--check-sidebar-order" goto sidebarOrderCheck
if /i "%~1"=="--check-sidebar-presentation" goto sidebarPresentationCheck
if /i "%~1"=="--check-update-install" goto updateInstallCheck
if /i "%~1"=="--check-image-cache" goto imageCacheCheck
if /i "%~1"=="--check-fullscreen-layers" goto fullscreenLayersCheck
if /i "%~1"=="--check-wall-replacement" goto wallReplacementCheck
if /i "%~1"=="--check-sc-layers" goto scLayersCheck
if /i "%~1"=="--check-stream-info" goto streamInfoCheck
if /i "%~1"=="--check-playback-capture" goto playbackCaptureCheck
if /i "%~1"=="--capture-playback" goto playbackCapture
if /i "%~1"=="--check-notice-close" goto noticeCloseCheck
if /i "%~1"=="--diagnose-responsiveness" goto responsiveness
if /i "%~1"=="--diagnose-fullscreen" goto fullscreen
if /i "%~1"=="--diagnose-douyu" goto douyu
if /i "%~1"=="--diagnose-douyu-deep" goto douyuDeep
if /i "%~1"=="--diagnose-fullscreen-input" set "DDM_FULLSCREEN_INPUT_CAPTURE=1"
if /i "%~1"=="--diagnose-settings-scroll" set "DDM_SETTINGS_SCROLL_CAPTURE=1"
if /i "%~1"=="--diagnose-settings-performance" set "DDM_SETTINGS_PERFORMANCE_CAPTURE=1"
if /i "%~1"=="--diagnose-control-swap" set "DDM_CONTROL_SWAP_CAPTURE=1"
if /i "%~1"=="--diagnose-wall-replacement" set "DDM_WALL_REPLACEMENT_CAPTURE=1"
if /i "%~1"=="--diagnose-sc" set "DDM_SC_PAINT_CAPTURE=1"
if /i "%~1"=="--diagnose-danmaku-motion" set "DDM_DANMAKU_MOTION_CAPTURE=1"
if /i "%~1"=="--diagnose-notice-close" set "DDM_NOTICE_CLOSE_CAPTURE=1"
if /i "%~1"=="--diagnose-window-resize" set "DDM_WINDOW_RESIZE_CAPTURE=1"
if /i "%~1"=="--diagnose-window-dpi-profile" (
    set "DDM_WINDOW_RESIZE_CAPTURE=1"
    set "DDM_WINDOW_DPI_PROFILE=1"
)
if /i "%~1"=="--diagnose-live-elapsed" set "DDM_LIVE_ELAPSED_CAPTURE=1"
rem TEMP BUG-001: remove diagnostic redirect after the drag/OLE recurrence is fixed.
start "" "%PY%" "%PROJ%dev\diagnose_drag_windows.py"
exit /b 0

:liveElapsedCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_live_elapsed
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_room_status_controller
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_room_status
exit /b %errorlevel%

:previewScrollCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_preview_scroll
if errorlevel 1 exit /b %errorlevel%
set "DDM_NO_SAVE=1"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_preview_scroll.py" --native
exit /b %errorlevel%

:continuousCornersCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_continuous_corners
exit /b %errorlevel%

:uiPolishCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_ui_polish
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_settings_navigation
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_settings_layout
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_card_drop
exit /b %errorlevel%

:browserAccountsCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_browser_accounts
exit /b %errorlevel%

:updateInstallCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_NO_SAVE=1"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_update_install.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_setup.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_online_ui.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_settings_process.py"
exit /b %errorlevel%

:wallRemovalCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_main_notices
exit /b %errorlevel%

:sidebarNavigationCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_workspace_controls
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_workspace_pages
exit /b %errorlevel%

:wallPanesCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_NO_SAVE=1"
set "DDM_CHECK_MODE=offline"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_pane_danmaku.py" --native
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_pane_danmaku
exit /b %errorlevel%

:audioNormalizationCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_NO_SAVE=1"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_audio_normalization
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_audio_audit.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_audio_routing.py"
exit /b %errorlevel%

:pictureInPictureCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_NO_SAVE=1"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_picture_in_picture.py" --native
if errorlevel 1 exit /b %errorlevel%
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_picture_in_picture.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_pip_picker
exit /b %errorlevel%

:qtLogCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_logging
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_qt_log
exit /b %errorlevel%

:nativeMemoryCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_NO_SAVE=1"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_check_runner.py"
if not "%errorlevel%"=="0" exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_sidebar_presentation.py" SidebarPresentationTests.test_tool_reordering_invalidates_removed_layout_items SidebarPresentationTests.test_orientation_changes_invalidate_removed_layout_items SidebarPresentationTests.test_sidebar_creation_and_local_server_leave_no_stale_item_bindings SidebarPresentationTests.test_menu_entries_follow_side_and_collapse_and_retain_pip_entry
if not "%errorlevel%"=="0" exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_on_demand_diagnostics.py"
if not "%errorlevel%"=="0" exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_layout_growth_empty.py"
if not "%errorlevel%"=="0" exit /b %errorlevel%
rem Native child-window reparenting is broken in Qt 6.11.2's offscreen plugin.
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_system_tray.py"
if not "%errorlevel%"=="0" exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_sidebar_presentation.py" SidebarPresentationTests.test_tool_reordering_invalidates_removed_layout_items SidebarPresentationTests.test_orientation_changes_invalidate_removed_layout_items SidebarPresentationTests.test_sidebar_creation_and_local_server_leave_no_stale_item_bindings SidebarPresentationTests.test_menu_entries_follow_side_and_collapse_and_retain_pip_entry SidebarPresentationTests.test_native_reparented_windows_release_backing_stores
exit /b %errorlevel%

:diagnosticsCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_diagnostic_settings_layout
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_on_demand_diagnostics
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_diagnostics
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_diagnostic_session
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_development_hang
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_settings_diagnostics.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\selfcheck_diagnostics.py"
exit /b %errorlevel%

:danmakuIndependentCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_video_danmaku_controls
exit /b %errorlevel%

:danmakuColorCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_danmaku_color.py"
if errorlevel 1 exit /b %errorlevel%
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_danmaku_color.py" --native
exit /b %errorlevel%

:playbackControlsCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_playback_controls
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_ui_components
exit /b %errorlevel%

:sidebarDragCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_drag_lifecycle
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_hit_test
if errorlevel 1 exit /b %errorlevel%
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_drag_diagnostics.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_folder_drag
exit /b %errorlevel%

:hotfixUpdatesCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_hotfix_updates
exit /b %errorlevel%


:sidebarPresentationCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_presentation
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sort_manager
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_order
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_widget_modules
exit /b %errorlevel%

:sidebarOrderCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_order
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sort_manager
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_frequent_sort
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_folder_control
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_folder_card_drag
exit /b %errorlevel%

:folderStressPreview
for %%A in (%*) do if /i "%%~A"=="--smoke" goto folderStressSmoke
start "" "%PY%" "%PROJ%dev\folder_stress_preview.py" %*
exit /b 0

:folderStressSmoke
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_NO_SAVE=1"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\folder_stress_preview.py" %*
exit /b %errorlevel%

:folderStressCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_NO_SAVE=1"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_folder_stress.py"
exit /b %errorlevel%

:folderExpansionCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_folder_control
if errorlevel 1 exit /b %errorlevel%
set "DDM_NO_SAVE=1"
set "QT_QPA_PLATFORM=offscreen"
set "DDM_CHECK_MODE=offline"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_audio_cycle_shortcut.py" --folders-only
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_general_settings.py" --folder-mode-only
exit /b %errorlevel%

:sidebarFoldersCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_folder_control
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_frequent_sort
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sort_manager
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sidebar_hit_test
exit /b %errorlevel%

:streamPlaybackCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_stream_playback
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_codec_control
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_bili_codec
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_playback_recovery
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_startup_windows
exit /b %errorlevel%

:dialogModulesCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_dialog_modules
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_general_settings
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_settings_layout
exit /b %errorlevel%

:windowStateCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_startup_windows
if not "%errorlevel%"=="0" exit /b %errorlevel%
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_startup_windows.py" StartupWindowsTests.test_startup_restores_normal_geometry_saved_on_close StartupWindowsTests.test_initial_maximize_keeps_a_smaller_normal_restore_rectangle StartupWindowsTests.test_saved_maximized_state_keeps_normal_size_after_restart StartupWindowsTests.test_invalid_saved_geometry_uses_initial_maximized_default StartupWindowsTests.test_native_maximized_client_is_ready_before_first_paint
exit /b %errorlevel%

:windowLayoutCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_window_layout
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_layout_growth_empty
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_layout_16
if not "%errorlevel%"=="0" exit /b %errorlevel%
:windowResizeTraceCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_window_move_restore.py" MoveRestoreTests.test_resize_trace_records_native_order_and_nested_layout_work MoveRestoreTests.test_resize_trace_covers_menu_orientation_and_restores_wrappers MoveRestoreTests.test_resize_trace_stops_at_session_limit MoveRestoreTests.test_first_native_size_arms_wall_before_qt_resizes_children MoveRestoreTests.test_dpi_profile_is_opt_in_bounded_and_stops_on_flush MoveRestoreTests.test_native_video_and_bar_keep_handles_without_promoting_bar_children MoveRestoreTests.test_dpi_notifications_wait_for_geometry_and_merge MoveRestoreTests.test_dpi_batch_skips_deleted_children_and_stops_with_owner
if not "%errorlevel%"=="0" exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_resize_widgets
exit /b %errorlevel%

:crossScreenCheck
call "%PROJ%run.cmd" --check-window-resize-trace
if not "%errorlevel%"=="0" exit /b %errorlevel%
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_native_control_hit.py"
if not "%errorlevel%"=="0" exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_fullscreen_controls.py"
exit /b %errorlevel%

:settingsScrollCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_appearance_options.py" AppearanceOptionsTests.test_scroll_capture_is_bounded_and_does_not_consume_wheel_or_record_text AppearanceOptionsTests.test_wheel_changes_only_horizontal_sliders_and_chains_nested_lists AppearanceOptionsTests.test_appearance_page_wheel_moves_its_outer_scroll_area AppearanceOptionsTests.test_embedded_native_wheels_reach_appearance_and_update_pages_repeatedly
if errorlevel 1 exit /b %errorlevel%
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_settings_process.py" --scroll-native
exit /b %errorlevel%

:settingsPerformanceCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_settings_performance.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_ui_components.py" ComponentTests.test_action_button_keeps_hover_feedback_when_entered_programmatically ComponentTests.test_font_selector_preserves_family_api_and_emits_edits ComponentTests.test_font_search_filters_without_committing_and_reopens_at_current_family ComponentTests.test_font_search_keeps_native_keyboard_and_mouse_selection ComponentTests.test_font_popup_caps_list_at_eight_rows_and_stays_on_screen ComponentTests.test_select_popup_keeps_layout_and_native_keyboard_commit_cancel ComponentTests.test_selectors_keep_content_width_in_wide_layouts
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_settings_layout.py" SettingsLayoutTests.test_wide_pages_use_two_columns_and_same_control_objects SettingsLayoutTests.test_narrow_pages_stack_without_horizontal_scroll_and_keep_edits SettingsLayoutTests.test_show_event_plugin_hook_keeps_identity_on_reopen
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_ui_components.py" ComponentTests.test_real_pages_use_shared_controls_and_follow_theme
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_appearance_options.py" AppearanceOptionsTests.test_gallery_covers_thumbnail_and_keeps_import_drop_contract
exit /b %errorlevel%

:settingsShutdownCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_settings_control
if errorlevel 1 exit /b %errorlevel%
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_settings_process.py" --shutdown-native
exit /b %errorlevel%

:settingsControlCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_settings_control
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_general_settings
exit /b %errorlevel%

:updatePreview
if /i "%~2"=="--smoke" (
    set "CHECK_PY=%PY:pythonw.exe=python.exe%"
    goto updatePreviewSmoke
)
start "" "%PY%" "%PROJ%dev\update_preview.py"
exit /b 0

:updatePreviewSmoke
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_update_preview
exit /b %errorlevel%

:updateProgressCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_update_download_progress
exit /b %errorlevel%

:biliProfileCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_mobile_share
exit /b %errorlevel%

:appUpdatesCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_app_updates
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_hotfix_updates
exit /b %errorlevel%

:widgetBoundariesCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_widget_modules
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_wall_border
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_ui_components
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_widget_lifetime
exit /b %errorlevel%

:roomPresetsCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_room_preset_control
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_room_presets
exit /b %errorlevel%

:widgetLifetimeCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_widget_lifetime
exit /b %errorlevel%

:imageCacheCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_image_cache
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_extra_cache
exit /b %errorlevel%

:portraitUiCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_settings_card_layout
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_portrait_ui
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

:danmakuSettingsCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_ui_components
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_danmaku_blocking
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_super_chat
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_sc_simulator
exit /b %errorlevel%

:settingsSearchCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_pinyin_search
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_ui_components
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_danmaku_blocking -- BlockingEditorTests
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_notification_center -- NotificationTests.test_settings_navigation_places_notifications_before_shortcuts NotificationTests.test_banner_blur_settings_roundtrip_and_reset NotificationTests.test_notification_switches_support_keyboard_click_and_explicit_states NotificationTests.test_notification_settings_cards_fit_themes_and_small_dialog NotificationTests.test_notification_sections_keep_compact_controls_readable_at_large_font_and_narrow_width NotificationTests.test_notification_retention_segments_trigger_existing_autosave_contract
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_workspace_controls -- WorkspaceControlTests.test_function_search_supports_pinyin_and_keeps_action_order
exit /b %errorlevel%

:trayMenuCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "TRAY_CHECK_FAILED="
for %%T in (SystemTrayTests.test_tray_preview_retains_pre_minimize_layout_and_restores_window SystemTrayTests.test_tray_picture_in_picture_resumes_only_selected_and_reholds_on_close TrayLayoutPreviewTests TrayMenuChoicesTests SystemTrayTests.test_default_hide_releases_watching_and_restore_reconnects SystemTrayTests.test_disabled_and_minimized_keep_playback SystemTrayTests.test_manual_pause_and_changed_room_are_not_resumed SystemTrayTests.test_recording_and_pending_capture_are_preserved) do (
    "%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_system_tray -- %%T
    if errorlevel 1 set "TRAY_CHECK_FAILED=1"
)
if defined TRAY_CHECK_FAILED exit /b 1
exit /b 0

:updateSettingsCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_update_settings
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_update_download_progress -- UpdateDownloadTests.test_app_update_action_keeps_its_left_anchor_through_transfer_states UpdateDownloadTests.test_plugin_expansion_moves_only_its_column_and_keeps_one_footer UpdateDownloadTests.test_plugin_cards_keep_text_inside_at_large_font_and_narrow_width UpdateDownloadTests.test_plugin_columns_resize_filter_sort_and_keep_download_controls UpdateDownloadTests.test_plugin_controls_use_shared_library_and_preserve_actions_and_check_signals
exit /b %errorlevel%

:settingsControlsCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_shortcut_settings
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_menu_drag
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_settings_layout -- SettingsLayoutTests.test_tray_retains_menu_order_and_visibility SettingsLayoutTests.test_tray_cards_and_menu_controls_fit_narrow_wide_and_large_fonts SettingsLayoutTests.test_tray_changes_drag_and_default_restore_use_existing_autosave SettingsLayoutTests.test_separate_menu_sections_preserve_drafts_and_save_only_tray_edits SettingsLayoutTests.test_both_menu_sections_fit_large_fonts_and_narrow_wide_sizes
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_ui_polish -- UiPolishTests.test_menu_editor_and_runtime_keep_order_callbacks_and_visibility UiPolishTests.test_narrow_menu_preview_drag_selection_hidden_rows_and_single_owner
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_settings_layout -- SettingsLayoutTests.test_recording_page_reuses_controls_and_preserves_codec_and_switch_contracts SettingsLayoutTests.test_recording_page_retains_plugin_insertion_anchor_and_owned_values SettingsLayoutTests.test_recording_controls_save_native_deltas_and_reopen_without_touching_plugin_fields SettingsLayoutTests.test_recording_page_keeps_directory_inline_and_units_outside_at_wide_and_narrow_sizes
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_notification_center -- NotificationTests.test_banner_display_switch_preserves_blur_and_uses_existing_autosave NotificationTests.test_banner_blur_settings_roundtrip_and_reset NotificationTests.test_settings_navigation_places_notifications_before_shortcuts NotificationTests.test_banner_preview_can_shrink_below_preferred_width_and_remains_right_aligned NotificationTests.test_notification_sections_keep_compact_controls_readable_at_large_font_and_narrow_width
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_settings_control
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

:playbackCapture
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "PLAYBACK_CAPTURE_LABEL=%~2"
if not defined PLAYBACK_CAPTURE_LABEL set "PLAYBACK_CAPTURE_LABEL=unknown"
"%CHECK_PY%" "%PROJ%dev\capture_playback.py" --label "%PLAYBACK_CAPTURE_LABEL%"
exit /b %errorlevel%

:playbackCaptureCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_playback_capture.py"
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_on_demand_diagnostics.py"
exit /b %errorlevel%

:diagnosticSession
start "" "%PY%" "%PROJ%main.py" "%DIAG_ARG%"
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

:functionalModulesCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_functional_modules
exit /b %errorlevel%

:douyuSourceRecoveryCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_player_lifetime -- SourceRecoveryTests
exit /b %errorlevel%

:pluginReplacementsCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_NO_SAVE=1"
set "QT_QPA_PLATFORM=offscreen"
set "DDM_CHECK_MODE=offline"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_plugin_replacements.py"
exit /b %errorlevel%

:liveBufferingCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_player_lifetime -- LiveBufferingTests
exit /b %errorlevel%

:playbackFeedbackCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_playback_recovery
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_playback_feedback
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_playback_badges
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_stream_playback
if errorlevel 1 exit /b %errorlevel%
set "DDM_CHECK_MODE=offline"
set "QT_QPA_PLATFORM=windows"
"%CHECK_PY%" "%PROJ%dev\checks\bootstrap.py" "%PROJ%dev\selfcheck_playback_feedback.py" --native-feedback
exit /b %errorlevel%

:liveTranslateAcceptance
if /i "%~2"=="--smoke" goto liveTranslateAcceptanceSmoke
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
pushd "%PROJ%"
if errorlevel 1 exit /b 1
"%CHECK_PY%" -u "%PROJ%dev\accept_live_translate.py"
set "ACCEPT_EXIT=%errorlevel%"
popd
exit /b %ACCEPT_EXIT%

:liveTranslateAcceptanceSmoke
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
set "DDM_NO_SAVE=1"
set "QT_QPA_PLATFORM=offscreen"
"%CHECK_PY%" "%PROJ%dev\accept_live_translate.py" --smoke
exit /b %errorlevel%

:mediaSourcesCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_media_sources
exit /b %errorlevel%

:followImportCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_follow_import_ui
exit /b %errorlevel%

:roomAddCheck
set "CHECK_PY=%PY:pythonw.exe=python.exe%"
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_room_add_entry
if errorlevel 1 exit /b %errorlevel%
"%CHECK_PY%" "%PROJ%dev\run_checks.py" --script selfcheck_room_add_inline
exit /b %errorlevel%
