# 仓库文件分类清单

> 类型：参考 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-16 ｜ 读者：维护者

## 本页用法

本页是文件级清单，不是架构说明。

- 找某个文件归谁管：先看“软件本体与插件功能范围”，再在“已跟踪的其他文件”中按分类查找。
- 新增或删除已跟踪文件时同步更新对应清单；`dev/selfcheck_repository_map.py` 会核对清单与 Git 索引一致。
- 目录与运行入口的整体关系见[架构总览](architecture/overview.md)；本机资料不进入版本库和发布包。

盘点日期：2026-10-19；当时完成分类盘点并删除四个过时脚本，详见[整理审查](archive/repository-cleanup-review.md)。
最近整理：2026-11-15，移除不再使用的旧网站原型截图；2026-11-14 的文档分层调整见[归档记录](archive/docs-organization-20261114.md)。
以下按当前工作区与 Git 索引盘点，不代表远端仓库状态；未读取真实配置、账号数据或媒体内容。

## 软件本体与插件功能范围

| 路径 | 用途 |
| --- | --- |
| `ddm/` | 软件本体，包括外观、播放器、弹幕、账号与插件接口 |
| `blivedm/` | B站弹幕协议实现 |
| `assets/`、`favicon.ico` | 软件图标、平台图标与资源 |
| `main.py`、`requirements.txt`、`run.cmd`、`run-console.cmd` | 软件入口、依赖和启动脚本 |
| `plugins_user/` | 本仓库只跟踪 `_template_platform/` 开发模板；其余为本机安装副本、旧目录或更新暂存，现行插件源码在独立插件仓库 |
| `libmpv-2.dll` | 本机播放运行库；使用 `dev/fetch_mpv.py` 下载并按来源清单校验，不进入 Git |

模块职责与状态所有权见[架构总览](architecture/overview.md#10-详细模块职责)。

## 已跟踪的其他文件：逐项标注

- `docs/features/image-cache.md`
- `docs/features/picture-in-picture.md`
- `docs/development/ui-components.md`

### 独立诊断工具

- `dev/watch_development_hang.py`
- `dev/selfcheck_development_hang.py`

- `tools/diagnostics/Collector.cs`
- `tools/diagnostics/NativeDependencies.cs`
- `tools/diagnostics/OnDemand.cs`
- `tools/diagnostics/Program.cs`
- `tools/diagnostics/README.md`
- `dev/build_diagnostics.ps1`
- `dev/diagnostics_tests.cs`
- `dev/selfcheck_diagnostics.py`
- `dev/selfcheck_diagnostic_session.py`
- `dev/selfcheck_sidebar_diagnostics.py`
- `dev/selfcheck_on_demand_diagnostics.py`
- `dev/selfcheck_responsiveness.py`
- `dev/selfcheck_fullscreen_capture.py`

### GitHub 协作与检查

- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/1-bug.yml`
- `.github/ISSUE_TEMPLATE/2-feature.yml`
- `.github/ISSUE_TEMPLATE/3-question.yml`
- `.github/ISSUE_TEMPLATE/config.yml`
- `.github/workflows/repository-checks.yml`
- `.github/workflows/issue-reproducibility.yml`

### 专项检查脚本

- `dev/selfcheck_image_cache.py`
- `dev/selfcheck_picture_in_picture.py`
- `dev/selfcheck_pip_picker.py`
- `dev/selfcheck_ui_components.py`
- `dev/check_emoticon_live.py`
- `dev/check_live_danmaku_motion.py`
- `dev/check_live_restore.py`
- `dev/check_medal_size.py`
- `dev/check_preview_live.py`
- `dev/check_release_package.py`
- `dev/check_setup_install.py`
- `dev/check_setup_permissions.py`
- `dev/check_setup_data_cleanup.py`
- `dev/check_setup_reinstall.py`
- `dev/selfcheck_setup.py`
- `dev/selfcheck_data_paths.py`
- `dev/build_setup.py`
- `dev/build_program_inventory.py`
- `dev/selfcheck_legacy_cleanup.py`
- `dev/installer/ChineseSimplified.isl`
- `dev/installer/ChineseSimplified-LICENSE.txt`
- `dev/installer/wizard.png`
- `dev/installer/helper.cpp`
- `dev/selfcheck_account_dialog.py`
- `dev/selfcheck_account_login_reopen.py`
- `dev/selfcheck_account_recovery.py`
- `dev/selfcheck_account_render.py`
- `dev/selfcheck_accounts.py`
- `dev/selfcheck_add_room_folder.py`
- `dev/selfcheck_add_room_hints.py`
- `dev/selfcheck_mobile_share.py`
- `dev/selfcheck_alt_tab_orientation.py`
- `dev/selfcheck_appearance.py`
- `dev/selfcheck_appearance_design.py`
- `dev/selfcheck_appearance_playback.py`
- `dev/selfcheck_audio_audit.py`
- `dev/selfcheck_audio_normalization.py`
- `dev/selfcheck_audio_cycle_shortcut.py`
- `dev/selfcheck_audio_hotplug.py`
- `dev/selfcheck_audio_owner.py`
- `dev/selfcheck_audio_routing.py`
- `dev/selfcheck_badge_memory.py`
- `dev/selfcheck_auto_quality.py`
- `dev/selfcheck_auto_quality_live.py`
- `dev/selfcheck_auto_quality_switch_live.py`
- `dev/selfcheck_bili_2k_live.py`
- `dev/selfcheck_bili_codec.py`
- `dev/selfcheck_bili_cookies.py`
- `dev/selfcheck_bili_plugin_boundary.py`
- `dev/selfcheck_bili_quality.py`
- `dev/selfcheck_brand_assets.py`
- `dev/selfcheck_button_feedback.py`
- `dev/selfcheck_button_focus.py`
- `dev/selfcheck_check_runner.py`
- `dev/selfcheck_close_release.py`
- `dev/selfcheck_completion_motion.py`
- `dev/selfcheck_control_dpi.py`
- `dev/selfcheck_control_edges.py`
- `dev/selfcheck_control_physical_edges.py`
- `dev/selfcheck_corner_drag_updates.py`
- `dev/selfcheck_corner_resize.py`
- `dev/selfcheck_corner_resize_live.py`
- `dev/selfcheck_corner_small_resize.py`
- `dev/selfcheck_corner_state.py`
- `dev/selfcheck_cover_cache.py`
- `dev/selfcheck_customization_plan.py`
- `dev/selfcheck_danmaku.py`
- `dev/selfcheck_danmaku_button.py`
- `dev/selfcheck_danmaku_connection.py`
- `dev/selfcheck_danmaku_emoji.py`
- `dev/selfcheck_danmaku_limit_migration.py`
- `dev/selfcheck_danmaku_limit_settings.py`
- `dev/selfcheck_danmaku_menu.py`
- `dev/selfcheck_danmaku_actions.py`
- `dev/selfcheck_danmaku_blocking.py`
- `dev/selfcheck_danmaku_render_thread.py`
- `dev/selfcheck_danmaku_retention.py`
- `dev/selfcheck_danmaku_room_switches.py`
- `dev/selfcheck_danmaku_smoothness.py`
- `dev/selfcheck_danmaku_sort.py`
- `dev/selfcheck_danmaku_unicode.py`
- `dev/selfcheck_super_chat.py`
- `dev/selfcheck_sc_simulator.py`
- `dev/sc_simulator.py`
- `dev/run-sc-simulator.cmd`
- `dev/selfcheck_delete.py`
- `dev/selfcheck_domestic_follows.py`
- `dev/selfcheck_douyin_account_import.py`
- `dev/selfcheck_display_transition.py`
- `dev/selfcheck_window_move_restore.py`
- `dev/selfcheck_douyin_follow_cache.py`
- `dev/selfcheck_douyin_follow_resolution.py`
- `dev/selfcheck_douyin_profile_add.py`
- `dev/selfcheck_douyin_room_verification.py`
- `dev/selfcheck_douyin_restart_cache.py`
- `dev/selfcheck_douyin_room_source.py`
- `dev/selfcheck_douyin_startup.py`
- `dev/selfcheck_douyin_stream_fallback.py`
- `dev/selfcheck_douyin_ui_follows.py`
- `dev/selfcheck_download_retry.py`
- `dev/selfcheck_drag_scroll.py`
- `dev/selfcheck_drag_lifecycle.py`
- `dev/selfcheck_sidebar_hit_test.py`
- `dev/selfcheck_drag_diagnostics.py`
- `dev/diagnose_control_swap.py`
- `dev/diagnose_drag_windows.py`
- `dev/diagnose_super_chat.py`
- `dev/diagnose_danmaku_motion.py`
- `dev/diagnose_notice_close.py`
- `dev/selfcheck_notice_close.py`
- `dev/selfcheck_danmaku_motion_diagnostics.py`
- `dev/diagnose_wall_replacement.py`
- `dev/diagnose_window_resize.py`
- `dev/selfcheck_room_placement.py`
- `dev/selfcheck_room_placement_native.py`
- `dev/selfcheck_drag_wheel.py`
- `dev/selfcheck_duplicate_tile_controls.py`
- `dev/selfcheck_encoders.py`
- `dev/selfcheck_feedback_layout.py`
- `dev/selfcheck_fixed_exe_entry.py`
- `dev/selfcheck_folder_blank_menu.py`
- `dev/selfcheck_folder_card_drag.py`
- `dev/selfcheck_folder_card_size.py`
- `dev/selfcheck_folder_drag.py`
- `dev/selfcheck_folder_icons.py`
- `dev/selfcheck_follow_folders.py`
- `dev/selfcheck_follow_import.py`
- `dev/selfcheck_failed_stream_quality.py`
- `dev/selfcheck_empty_tile_quality.py`
- `dev/selfcheck_douyu_diagnostics.py`
- `dev/selfcheck_douyu_deep_capture.py`
- `dev/selfcheck_douyu_cdn_control.py`
- `dev/selfcheck_douyu_transport.py`
- `dev/selfcheck_douyu_recovery.py`
- `dev/selfcheck_douyu_quality_order.py`
- `dev/selfcheck_follow_stress.py`
- `dev/selfcheck_pinyin_search.py`
- `dev/selfcheck_follow_refresh.py`
- `dev/selfcheck_fullscreen_audio.py`
- `dev/selfcheck_fullscreen_volume.py`
- `dev/selfcheck_fullscreen_border.py`
- `dev/selfcheck_playback_badges.py`
- `dev/selfcheck_playback_controls.py`
- `dev/selfcheck_fullscreen_controls.py`
- `dev/selfcheck_fullscreen_cursor.py`
- `dev/selfcheck_fullscreen_native_focus.py`
- `dev/selfcheck_fullscreen_enter_focus.py`
- `dev/selfcheck_fullscreen_quality.py`
- `dev/selfcheck_fullscreen_switch.py`
- `dev/selfcheck_general_settings.py`
- `dev/selfcheck_settings_autosave.py`
- `dev/selfcheck_appearance_options.py`
- `dev/selfcheck_ui_polish.py`
- `dev/selfcheck_card_drop.py`
- `dev/selfcheck_settings_navigation.py`
- `dev/selfcheck_settings_layout.py`
- `dev/selfcheck_system_tray.py`
- `dev/selfcheck_settings_process.py`
- `dev/selfcheck_settings_control.py`
- `dev/selfcheck_settings_occlusion.py`
- `dev/check_settings_process_playback.py`
- `dev/selfcheck_global_live.py`
- `dev/selfcheck_hls_proxy.py`
- `dev/selfcheck_huya_live_eof.py`
- `dev/selfcheck_huya_live.py`
- `dev/selfcheck_huya_watch.py`
- `dev/selfcheck_launch_scripts.py`
- `dev/selfcheck_layout_16.py`
- `dev/selfcheck_layout_growth_empty.py`
- `dev/selfcheck_window_layout.py`
- `dev/selfcheck_layout_live_priority.py`
- `dev/selfcheck_layout_none.py`
- `dev/selfcheck_layout_playback.py`
- `dev/selfcheck_light_refinements.py`
- `dev/selfcheck_live_alert.py`
- `dev/selfcheck_live_alert_sort.py`
- `dev/selfcheck_live_danmaku.py`
- `dev/selfcheck_live_danmaku_live.py`
- `dev/selfcheck_live_platforms.py`
- `dev/selfcheck_localization.py`
- `dev/selfcheck_main_notices.py`
- `dev/selfcheck_notification_center.py`
- `dev/selfcheck_match_sync_host_release.py`
- `dev/selfcheck_menu_motion.py`
- `dev/selfcheck_mpv.py`
- `dev/selfcheck_mpv_com_lifetime.py`
- `dev/selfcheck_player_lifetime.py`
- `dev/selfcheck_stream_info.py`
- `dev/selfcheck_single_instance.py`
- `dev/selfcheck_playback_recovery.py`
- `dev/selfcheck_stream_playback.py`
- `dev/selfcheck_codec_control.py`
- `dev/selfcheck_native_control_hit.py`
- `dev/selfcheck_nav_layout.py`
- `dev/selfcheck_oauth.py`
- `dev/selfcheck_playback_capture.py`
- `dev/capture_playback.py`
- `dev/selfcheck_browser_accounts.py`
- `dev/selfcheck_oauth_accounts.py`
- `dev/selfcheck_oauth_guide.py`
- `dev/selfcheck_offline_badges.py`
- `dev/selfcheck_online.py`
- `dev/selfcheck_online_ui.py`
- `dev/selfcheck_orientation_layout.py`
- `dev/selfcheck_orientation_work.py`
- `dev/selfcheck_overseas_playback_live.py`
- `dev/selfcheck_overseas_stability.py`
- `dev/selfcheck_pane_borders.py`
- `dev/selfcheck_parallel_plugin_downloads.py`
- `dev/selfcheck_platform_accounts.py`
- `dev/selfcheck_platform_follow_reopen.py`
- `dev/selfcheck_platform_follows.py`
- `dev/selfcheck_platform_login_expiry.py`
- `dev/selfcheck_platform_logo_background.py`
- `dev/selfcheck_platform_reauthentication.py`
- `dev/selfcheck_platform_offline_tiles.py`
- `dev/selfcheck_platform_preview.py`
- `dev/selfcheck_platform_preview_live.py`
- `dev/selfcheck_platform_quality.py`
- `dev/selfcheck_platform_quality_live.py`
- `dev/selfcheck_platform_storage.py`
- `dev/selfcheck_plugin_cache.py`
- `dev/selfcheck_plugin_controls.py`
- `dev/selfcheck_plugin_credentials.py`
- `dev/selfcheck_plugin_notices.py`
- `dev/selfcheck_plugin_drop_restart.py`
- `dev/selfcheck_plugin_rename.py`
- `dev/selfcheck_plugin_settings.py`
- `dev/selfcheck_plugin_update_notes.py`
- `dev/selfcheck_plugin_windows_lock.py`
- `dev/selfcheck_plugins.py`
- `dev/selfcheck_plugin_contract.py`
- `dev/selfcheck_plugin_replacements.py`
- `dev/selfcheck_plugin_worker.py`
- `dev/selfcheck_poller_lifecycle.py`
- `dev/selfcheck_portrait.py`
- `dev/selfcheck_portrait_compact.py`
- `dev/selfcheck_portrait_native.py`
- `dev/selfcheck_portrait_sidebar_return.py`
- `dev/selfcheck_portrait_small.py`
- `dev/selfcheck_preset_resize.py`
- `dev/selfcheck_preset_state.py`
- `dev/selfcheck_preview.py`
- `dev/selfcheck_preview_collapsed.py`
- `dev/selfcheck_preview_popup.py`
- `dev/selfcheck_preview_scroll.py`
- `dev/selfcheck_project_workflow.py`
- `dev/selfcheck_qr_refresh.py`
- `dev/selfcheck_qr_responsiveness.py`
- `dev/selfcheck_qt_log.py`
- `dev/selfcheck_logging.py`
- `dev/selfcheck_quality.py`
- `dev/selfcheck_readme.py`
- `dev/selfcheck_recording.py`
- `dev/selfcheck_recording_service.py`
- `dev/selfcheck_recording_shutdown.py`
- `dev/selfcheck_release_metadata.py`
- `dev/selfcheck_hotfix_updates.py`
- `dev/selfcheck_app_updates.py`
- `dev/selfcheck_remove_follow_position.py`
- `dev/selfcheck_replay_scope.py`
- `dev/selfcheck_repository_files.py`
- `dev/selfcheck_repository_map.py`
- `dev/selfcheck_resize_preview_cleanup.py`
- `dev/selfcheck_resize_surface.py`
- `dev/selfcheck_resize_widgets.py`
- `dev/selfcheck_resolve_retry.py`
- `dev/selfcheck_room_presets.py`
- `dev/selfcheck_room_preset_control.py`
- `dev/selfcheck_pane_danmaku.py`
- `dev/selfcheck_room_status.py`
- `dev/selfcheck_live_elapsed.py`
- `dev/selfcheck_room_status_controller.py`
- `dev/selfcheck_room_images.py`
- `dev/selfcheck_search.py`
- `dev/selfcheck_settings_status.py`
- `dev/selfcheck_sidebar_avatar.py`
- `dev/selfcheck_sidebar_collapse.py`
- `dev/selfcheck_sidebar_performance.py`
- `dev/selfcheck_sidebar_text_theme.py`
- `dev/selfcheck_skins.py`
- `dev/selfcheck_slots.py`
- `dev/selfcheck_smart_folder_sources.py`
- `dev/selfcheck_smart_folders.py`
- `dev/selfcheck_smooth_edges.py`
- `dev/selfcheck_sort_manager.py`
- `dev/selfcheck_frequent_sort.py`
- `dev/selfcheck_startup.py`
- `dev/selfcheck_startup_danmaku.py`
- `dev/selfcheck_startup_requests.py`
- `dev/selfcheck_startup_windows.py`
- `dev/selfcheck_startup_scroll_diagnostics.py`
- `dev/selfcheck_startup_wmi.py`
- `dev/selfcheck_stream_recovery.py`
- `dev/selfcheck_stream_relay.py`
- `dev/selfcheck_theme_latency.py`
- `dev/selfcheck_theme_native_reveal.py`
- `dev/selfcheck_theme_palette.py`
- `dev/selfcheck_theme_wave.py`
- `dev/selfcheck_tile_bottom_order.py`
- `dev/selfcheck_tile_fullscreen.py`
- `dev/selfcheck_tile_overlay.py`
- `dev/selfcheck_tile_ui.py`
- `dev/selfcheck_ui3.py`
- `dev/selfcheck_ui_motion.py`
- `dev/selfcheck_settings_transition.py`
- `dev/selfcheck_update_install.py`
- `dev/selfcheck_update_notifications.py`
- `dev/selfcheck_user_notice.py`
- `dev/selfcheck_video_danmaku.py`
- `dev/selfcheck_danmaku_color.py`
- `dev/selfcheck_video_danmaku_controls.py`
- `dev/selfcheck_video_danmaku_native.py`
- `dev/selfcheck_video_danmaku_quick.py`
- `dev/selfcheck_video_surface.py`
- `dev/selfcheck_video_surface_growth.py`
- `dev/selfcheck_volume_channel.py`
- `dev/selfcheck_wall_card_replacement.py`
- `dev/selfcheck_watchdog.py`
- `dev/selfcheck_widget_lifetime.py`
- `dev/selfcheck_widget_modules.py`
- `dev/selfcheck_functional_modules.py`
- `dev/selfcheck_sidebar_folder_control.py`
- `dev/selfcheck_sidebar_order.py`
- `dev/selfcheck_sidebar_presentation.py`
- `dev/selfcheck_dialog_modules.py`
- `dev/selfcheck_wall_border.py`
- `dev/selfcheck_workspace_controls.py`
- `dev/selfcheck_continuous_corners.py`
- `dev/selfcheck_workspace_pages.py`
- `dev/selfcheck_window_resize.py`
- `dev/selfcheck_windows_version.py`

### 其他已跟踪文件

- `results/.gitignore`
- `docs/assets/screenshots/overview3_Landscape_mode.png`

### 历史记录

- `docs/archive/BUG-STATUS-2026-10-02.md`
- `docs/archive/douyu-playback-202611.md`
- `docs/archive/window-interaction-investigations-202610.md`
- `docs/archive/testing-isolation-202611.md`
- `docs/archive/README.md`
- `docs/archive/appearance-implementation-202610.md`
- `docs/archive/skins-implementation-202610.md`
- `docs/archive/resize-performance-202611.md`
- `docs/archive/responsiveness-capture-202611.md`
- `docs/archive/ui-components-202611.md`
- `docs/archive/workspace-maintenance-202610.md`
- `docs/archive/customization-plan-202610.md`
- `docs/archive/docs-organization-20261114.md`
- `docs/archive/bili-shadowreplay-learning.md`
- `docs/archive/liveaquarium-learning.md`
- `docs/archive/match-sync-ocr-evaluation.md`
- `docs/archive/pr11-pr12-integration-testing.md`
- `docs/archive/pr6-pr7-layout-testing.md`
- `docs/archive/repository-cleanup-review.md`
- `docs/archive/repository-integration-20261019.md`

### 开发指南

- `docs/development/README.md`
- `docs/development/testing.md`
- `docs/development/douyu-diagnostics.md`
- `docs/development/responsiveness-capture.md`
- `docs/development/windows-installer.md`
- `docs/development/workspace-maintenance.md`

### 架构与文档规范

- `docs/architecture/README.md`
- `docs/architecture/overview.md`
- `docs/architecture/ui-boundaries.md`
- `docs/standards/documentation.md`

### 性能基准

- `dev/benchmarks/README.md`
- `dev/benchmarks/benchmark_danmaku_frames.py`
- `dev/benchmarks/benchmark_video_danmaku_render.py`

### 构建、维护与复现工具

- `dev/benchmark_match_sync_ocr.ps1`
- `dev/build_release.ps1`
- `dev/build_windows_version.py`
- `dev/fetch_mpv.py`
- `dev/probe_danmaku_live.py`
- `dev/pyi_rth_pyside6_paths.py`
- `dev/repro_d3d_quality.py`
- `dev/repro_tile_lifecycle.py`
- `dev/screens.py`

### 根目录协作文件

- `.gitignore`
- `.gitattributes`
- `AGENTS.md`
- `CONTRIBUTING.md`
- `LICENSE`
- `README.md`

### 检查入口与分类

- `dev/README.md`
- `dev/checks/README.md`
- `dev/checks/bootstrap.py`
- `dev/checks/build_native_crash.cmd`
- `dev/checks/native_crash.cpp`
- `dev/checks/widget_cases.py`
- `dev/checks/suites.json`
- `dev/run-checks.cmd`
- `dev/run_checks.py`
- `dev/selfcheck_documents.py`

### 版本说明

- `docs/releases/README.md`
- `docs/releases/RELEASE-v0.1.md`
- `docs/releases/RELEASE-v0.2.md`
- `docs/releases/RELEASE-v0.3.1.md`
- `docs/releases/RELEASE-v0.3.md`
- `docs/releases/RELEASE-v0.4.md`
- `docs/releases/RELEASE-v0.5.md`
- `docs/releases/RELEASE-v0.5.1.md`
- `docs/releases/RELEASE-v0.5.2-super-chat.md`
- `docs/releases/RELEASE-v0.5.2.md`
- `docs/releases/RELEASE-v0.6.md`
- `docs/releases/RELEASE-v0.7.md`
- `docs/releases/RELEASE-v0.7.1.md`
- `docs/releases/RELEASE-v0.7.2.md`
- `docs/releases/RELEASE-v0.7.2-hotfix.2.md`
- `docs/releases/RELEASE-v0.7.3.md`
- `docs/releases/UNRELEASED.md`

### 资源与发布辅助工具

- `dev/tools/README.md`
- `dev/tools/build_brand_assets.py`
- `dev/tools/build_plugin_catalog.py`
- `dev/tools/sync_release_notes.py`

### 项目文档与截图

- `docs/NOTICE.md`
- `docs/README.md`
- `docs/features/README.md`
- `docs/references/README.md`
- `docs/features/appearance-design.md`
- `docs/bug-cases.md`
- `docs/features/customization-plan.md`
- `docs/online-updates.md`
- `docs/assets/screenshots/overview1_Landscape_mode.png`
- `docs/assets/screenshots/overview1_Portrait_Mode.png`
- `docs/assets/screenshots/overview2_Landscape_mode.png`
- `docs/assets/screenshots/overview2_Portrait_Mode.png`
- `docs/assets/screenshots/overview4_Landscape_mode.png`
- `docs/assets/screenshots/overview5_Landscape_mode.png`
- `docs/plugins.md`
- `docs/repository-map.md`
- `docs/features/resize-performance.md`
- `docs/features/room-presets-design.md`
- `docs/features/skins.md`

### Flutter 移动端

- `mobile/.gitignore`
- `mobile/.metadata`
- `mobile/README.md`
- `mobile/analysis_options.yaml`
- `mobile/android/.gitignore`
- `mobile/android/app/build.gradle.kts`
- `mobile/android/app/src/debug/AndroidManifest.xml`
- `mobile/android/app/src/main/AndroidManifest.xml`
- `mobile/android/app/src/main/kotlin/io/github/lanpropro/ddmonitor/MainActivity.kt`
- `mobile/android/app/src/main/res/drawable-v21/launch_background.xml`
- `mobile/android/app/src/main/res/drawable/launch_background.xml`
- `mobile/android/app/src/main/res/mipmap-hdpi/ic_launcher.png`
- `mobile/android/app/src/main/res/mipmap-mdpi/ic_launcher.png`
- `mobile/android/app/src/main/res/mipmap-xhdpi/ic_launcher.png`
- `mobile/android/app/src/main/res/mipmap-xxhdpi/ic_launcher.png`
- `mobile/android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png`
- `mobile/android/app/src/main/res/values-night/styles.xml`
- `mobile/android/app/src/main/res/values/styles.xml`
- `mobile/android/app/src/profile/AndroidManifest.xml`
- `mobile/android/build.gradle.kts`
- `mobile/android/gradle.properties`
- `mobile/android/gradle/wrapper/gradle-wrapper.properties`
- `mobile/android/settings.gradle.kts`
- `mobile/integration_test/watch_test.dart`
- `mobile/ios/.gitignore`
- `mobile/ios/Flutter/AppFrameworkInfo.plist`
- `mobile/ios/Flutter/Debug.xcconfig`
- `mobile/ios/Flutter/Release.xcconfig`
- `mobile/ios/Runner.xcodeproj/project.pbxproj`
- `mobile/ios/Runner.xcodeproj/project.xcworkspace/contents.xcworkspacedata`
- `mobile/ios/Runner.xcodeproj/project.xcworkspace/xcshareddata/IDEWorkspaceChecks.plist`
- `mobile/ios/Runner.xcodeproj/project.xcworkspace/xcshareddata/WorkspaceSettings.xcsettings`
- `mobile/ios/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme`
- `mobile/ios/Runner.xcworkspace/contents.xcworkspacedata`
- `mobile/ios/Runner.xcworkspace/xcshareddata/IDEWorkspaceChecks.plist`
- `mobile/ios/Runner.xcworkspace/xcshareddata/WorkspaceSettings.xcsettings`
- `mobile/ios/Runner/AppDelegate.swift`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Contents.json`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-1024x1024@1x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-20x20@1x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-20x20@2x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-20x20@3x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-29x29@1x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-29x29@2x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-29x29@3x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-40x40@1x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-40x40@2x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-40x40@3x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-60x60@2x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-60x60@3x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-76x76@1x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-76x76@2x.png`
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/Icon-App-83.5x83.5@2x.png`
- `mobile/ios/Runner/Assets.xcassets/LaunchImage.imageset/Contents.json`
- `mobile/ios/Runner/Assets.xcassets/LaunchImage.imageset/LaunchImage.png`
- `mobile/ios/Runner/Assets.xcassets/LaunchImage.imageset/LaunchImage@2x.png`
- `mobile/ios/Runner/Assets.xcassets/LaunchImage.imageset/LaunchImage@3x.png`
- `mobile/ios/Runner/Assets.xcassets/LaunchImage.imageset/README.md`
- `mobile/ios/Runner/Base.lproj/LaunchScreen.storyboard`
- `mobile/ios/Runner/Base.lproj/Main.storyboard`
- `mobile/ios/Runner/Info.plist`
- `mobile/ios/Runner/Runner-Bridging-Header.h`
- `mobile/ios/Runner/SceneDelegate.swift`
- `mobile/ios/RunnerTests/RunnerTests.swift`
- `mobile/lib/app.dart`
- `mobile/lib/design.dart`
- `mobile/lib/follow_view.dart`
- `mobile/lib/main.dart`
- `mobile/lib/monitor_model.dart`
- `mobile/lib/platforms/bilibili.dart`
- `mobile/lib/wall_view.dart`
- `mobile/lib/wall_layout.dart`
- `mobile/lib/watch_session.dart`
- `mobile/pubspec.lock`
- `mobile/pubspec.yaml`
- `mobile/test/app_test.dart`
- `mobile/test/bilibili_test.dart`
- `mobile/test/model_test.dart`
- `mobile/test/watch_session_test.dart`

- `dev/native_diagnostics_fixture.cpp`
- `dev/build_native_diagnostics.cmd`
- `dev/selfcheck_native_diagnostics.py`
- `dev/selfcheck_settings_diagnostics.py`
- `tools/diagnostics/CommandLine.cs`
- `tools/native_diagnostics/capture.cpp`

## 仅本机存在的其他资料

此处只列目录和文件入口，不展开真实配置、账号、缓存、录制内容或临时依赖。
忽略状态以现有 Git 规则为准，忽略并不表示文件已从磁盘删除。

| 路径或模式 | 标注 | 当前处理 |
| --- | --- | --- |
| `videos/` | 宣传片工程、素材和中间产物 | 已忽略；保留 |
| `Video_reference/` | 宣传片参考视频和音乐 | 已忽略；保留 |
| `raw/` | 原始录制素材目录，未核验具体来源与保留价值 | 现有规则判定为忽略；保留 |
| `results/promo-final/` | 最终宣传成片与封面 | 已忽略；保留 |
| `results/` 其他内容 | `archive/` 保存本体旧版本 ZIP；最新本体的正式附件与一个解压入口、各插件最新正式 ZIP 的边界见[本机工作区维护](development/workspace-maintenance.md) | 已忽略（除 .gitignore）；非最终资料移入 `work/` |
| `work/` | 混合临时目录：构建、依赖、Git 工作树、测试截图及宣传资料 | 已忽略；不整体清理 |
| `docs/local/archive/handoffs/`、`PROJECT_STATE.md` | 历史交接归档与当前交接入口 | 已忽略；不进入 `results/` 或发布包 |
| `docs/local/README.md`、`docs/local/idea.md` | 本机资料索引与需求建议 | 已忽略；待办、诊断、验收及历史资料按目录收口 |
| `docs/local/archive/promo/` | 宣传片脚本、素材、封面及交付过程文档 | 已忽略；保留 |
| `dev/*promo*`、`dev/*highlight*`、`dev/*videotogether*`、`dev/test_video_*.py` | 宣传片专项脚本与校验工具；不含 selfcheck_video_* 软件测试 | 已忽略；保留 |
| `dev/preview_*.py`、`dev/run-preview.cmd`、`dev/make_shots.py`、`dev/thumb_sheet.py` | 软件开发预览、截图工具，仍与软件维护相关 | 已忽略；保留 |
| `dev/mock_portrait2.py`、`docs/local/archive/prototypes/portrait-bar.png`、`docs/local/archive/prototypes/portrait-current.png`、`docs/local/archive/prototypes/portrait-mock.png` | 旧竖屏原型及截图 | 已忽略；保留 |
| `cache/`、`logs/`、`recordings/`、`__pycache__/` | 软件运行数据、录制与 Python 缓存 | 已忽略；不读取内容、不清理 |
| `ddm_plugins_dd3l0oxq/` | 名称疑似插件临时目录；当前无法核实目录内容及来源 | 不属于已跟踪源码；保留 |

## 本机未跟踪保护项

以下只标记现状，不删除、不一并暂存：

- `dev/mock_portrait.py`：竖屏开发原型。
- `dev/portrait_mock.html`：竖屏网页原型。
- `plugins_user/.updates/`：插件更新暂存。
- `plugins_user/match_sync/`：本机插件副本。
- `utils/`：可能包含配置、账号及本机工具；不读取真实配置或整体归类为杂项。

## 整理结论

严格属于其他任务的内容包括独立网站资料、宣传片工程、参考素材和宣传过程工具；
测试、构建、软件文档和开发原型属于软件维护资料，已单独标出。
本轮文档移动与四项删除见 [整理审查](archive/repository-cleanup-review.md)，软件和打包读取路径已相应调整。
清单自身及其检查脚本也是仓库维护文件，新增后纳入上方逐项列表。

逐模块职责与状态归属见[详细模块职责](architecture/overview.md#10-详细模块职责)。
