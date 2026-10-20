# 专项检查分类索引

按功能列出 Git 已跟踪的全部 `selfcheck_*.py` 与 `check_*.py`，不收录本机未跟踪脚本。
表中的套件名对应 [suites.json](suites.json)；执行条件与命令见[验证指南](../../docs/development/testing.md)。

已核对隔离条件的脚本才进入批量套件。标记“单项执行前核对”的历史脚本保留其用途，执行前需确认配置读取、网络、图形后端、媒体与发布包依赖，不推断其适合自动运行。

新增检查应更新此索引；仓库检查会核对它与 Git 索引一致。

## 主题、资源与动效

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_appearance](../selfcheck_appearance.py) | 单项执行前核对 |
| [selfcheck_appearance_design](../selfcheck_appearance_design.py) | `repository` |
| [selfcheck_appearance_playback](../selfcheck_appearance_playback.py) | 单项执行前核对 |
| [selfcheck_brand_assets](../selfcheck_brand_assets.py) | `offline` |
| [selfcheck_button_feedback](../selfcheck_button_feedback.py) | `offline` |
| [selfcheck_button_focus](../selfcheck_button_focus.py) | `offline` |
| [selfcheck_completion_motion](../selfcheck_completion_motion.py) | 单项执行前核对 |
| [selfcheck_control_dpi](../selfcheck_control_dpi.py) | 单项执行前核对 |
| [selfcheck_control_edges](../selfcheck_control_edges.py) | 单项执行前核对 |
| [selfcheck_control_physical_edges](../selfcheck_control_physical_edges.py) | 单项执行前核对 |
| [selfcheck_light_refinements](../selfcheck_light_refinements.py) | 单项执行前核对 |
| [selfcheck_menu_motion](../selfcheck_menu_motion.py) | 单项执行前核对 |
| [selfcheck_native_control_hit](../selfcheck_native_control_hit.py) | 单项执行前核对 |
| [selfcheck_sidebar_text_theme](../selfcheck_sidebar_text_theme.py) | `offline` |
| [selfcheck_skins](../selfcheck_skins.py) | 单项执行前核对 |
| [selfcheck_smooth_edges](../selfcheck_smooth_edges.py) | `native` |
| [selfcheck_theme_latency](../selfcheck_theme_latency.py) | `offline` |
| [selfcheck_theme_native_reveal](../selfcheck_theme_native_reveal.py) | 单项执行前核对 |
| [selfcheck_theme_palette](../selfcheck_theme_palette.py) | 单项执行前核对 |
| [selfcheck_theme_wave](../selfcheck_theme_wave.py) | 单项执行前核对 |
| [selfcheck_ui_motion](../selfcheck_ui_motion.py) | 单项执行前核对 |

## 仓库、启动与文档

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_check_runner](../selfcheck_check_runner.py) | `repository` |
| [selfcheck_customization_plan](../selfcheck_customization_plan.py) | `repository` |
| [selfcheck_launch_scripts](../selfcheck_launch_scripts.py) | 单项执行前核对 |
| [selfcheck_project_workflow](../selfcheck_project_workflow.py) | `repository` |
| [selfcheck_qt_log](../selfcheck_qt_log.py) | 单项执行前核对 |
| [selfcheck_readme](../selfcheck_readme.py) | `repository` |
| [selfcheck_repository_files](../selfcheck_repository_files.py) | `repository` |
| [selfcheck_repository_map](../selfcheck_repository_map.py) | `repository` |
| [selfcheck_startup](../selfcheck_startup.py) | 单项执行前核对 |
| [selfcheck_startup_danmaku](../selfcheck_startup_danmaku.py) | 单项执行前核对 |
| [selfcheck_startup_requests](../selfcheck_startup_requests.py) | 单项执行前核对 |
| [selfcheck_startup_wmi](../selfcheck_startup_wmi.py) | 单项执行前核对 |
| [selfcheck_watchdog](../selfcheck_watchdog.py) | 单项执行前核对 |
| [selfcheck_website_plan](../selfcheck_website_plan.py) | `repository` |

## 侧栏、控件与其他交互

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_add_room_folder](../selfcheck_add_room_folder.py) | 单项执行前核对 |
| [selfcheck_add_room_hints](../selfcheck_add_room_hints.py) | 单项执行前核对 |
| [selfcheck_alt_tab_orientation](../selfcheck_alt_tab_orientation.py) | 单项执行前核对 |
| [selfcheck_avatars](../selfcheck_avatars.py) | 单项执行前核对 |
| [selfcheck_bili_2k_live](../selfcheck_bili_2k_live.py) | 单项执行前核对 |
| [selfcheck_bili_cookies](../selfcheck_bili_cookies.py) | `offline` |
| [selfcheck_cover_cache](../selfcheck_cover_cache.py) | 单项执行前核对 |
| [selfcheck_delete](../selfcheck_delete.py) | 单项执行前核对 |
| [selfcheck_drag_scroll](../selfcheck_drag_scroll.py) | 单项执行前核对 |
| [selfcheck_drag_wheel](../selfcheck_drag_wheel.py) | 单项执行前核对 |
| [selfcheck_duplicate_tile_controls](../selfcheck_duplicate_tile_controls.py) | 单项执行前核对 |
| [selfcheck_encoders](../selfcheck_encoders.py) | 单项执行前核对 |
| [selfcheck_folder_blank_menu](../selfcheck_folder_blank_menu.py) | `offline` |
| [selfcheck_folder_card_drag](../selfcheck_folder_card_drag.py) | 单项执行前核对 |
| [selfcheck_folder_card_size](../selfcheck_folder_card_size.py) | `offline` |
| [selfcheck_folder_drag](../selfcheck_folder_drag.py) | 单项执行前核对 |
| [selfcheck_folder_icons](../selfcheck_folder_icons.py) | 单项执行前核对 |
| [selfcheck_general_settings](../selfcheck_general_settings.py) | `offline` |
| [selfcheck_hls_proxy](../selfcheck_hls_proxy.py) | 单项执行前核对 |
| [selfcheck_live_alert](../selfcheck_live_alert.py) | 单项执行前核对 |
| [selfcheck_live_alert_sort](../selfcheck_live_alert_sort.py) | 单项执行前核对 |
| [selfcheck_localization](../selfcheck_localization.py) | 单项执行前核对 |
| [selfcheck_main_notices](../selfcheck_main_notices.py) | `offline` |
| [selfcheck_offline_badges](../selfcheck_offline_badges.py) | 单项执行前核对 |
| [selfcheck_orientation_work](../selfcheck_orientation_work.py) | 单项执行前核对 |
| [selfcheck_overseas_playback_live](../selfcheck_overseas_playback_live.py) | 单项执行前核对 |
| [selfcheck_overseas_stability](../selfcheck_overseas_stability.py) | 单项执行前核对 |
| [selfcheck_poller_lifecycle](../selfcheck_poller_lifecycle.py) | 单项执行前核对 |
| [selfcheck_resolve_retry](../selfcheck_resolve_retry.py) | 单项执行前核对 |
| [selfcheck_search](../selfcheck_search.py) | 单项执行前核对 |
| [selfcheck_settings_status](../selfcheck_settings_status.py) | 单项执行前核对 |
| [selfcheck_sidebar_avatar](../selfcheck_sidebar_avatar.py) | 单项执行前核对 |
| [selfcheck_sidebar_collapse](../selfcheck_sidebar_collapse.py) | 单项执行前核对 |
| [selfcheck_sidebar_performance](../selfcheck_sidebar_performance.py) | 单项执行前核对 |
| [selfcheck_smart_folder_sources](../selfcheck_smart_folder_sources.py) | 单项执行前核对 |
| [selfcheck_smart_folders](../selfcheck_smart_folders.py) | 单项执行前核对 |
| [selfcheck_sort_manager](../selfcheck_sort_manager.py) | `offline` |
| [selfcheck_tile_bottom_order](../selfcheck_tile_bottom_order.py) | `offline` |
| [selfcheck_tile_overlay](../selfcheck_tile_overlay.py) | 单项执行前核对 |
| [selfcheck_tile_ui](../selfcheck_tile_ui.py) | 单项执行前核对 |
| [selfcheck_ui3](../selfcheck_ui3.py) | 单项执行前核对 |
| [selfcheck_user_notice](../selfcheck_user_notice.py) | 单项执行前核对 |
| [selfcheck_wall_card_replacement](../selfcheck_wall_card_replacement.py) | 单项执行前核对 |

## 布局、窗口与全屏

| 脚本 | 执行分类 |
| --- | --- |
| [check_live_restore](../check_live_restore.py) | `live` |
| [selfcheck_corner_drag_updates](../selfcheck_corner_drag_updates.py) | 单项执行前核对 |
| [selfcheck_corner_resize](../selfcheck_corner_resize.py) | 单项执行前核对 |
| [selfcheck_corner_resize_live](../selfcheck_corner_resize_live.py) | 单项执行前核对 |
| [selfcheck_corner_small_resize](../selfcheck_corner_small_resize.py) | 单项执行前核对 |
| [selfcheck_corner_state](../selfcheck_corner_state.py) | 单项执行前核对 |
| [selfcheck_feedback_layout](../selfcheck_feedback_layout.py) | 单项执行前核对 |
| [selfcheck_fullscreen_audio](../selfcheck_fullscreen_audio.py) | 单项执行前核对 |
| [selfcheck_fullscreen_border](../selfcheck_fullscreen_border.py) | 单项执行前核对 |
| [selfcheck_fullscreen_controls](../selfcheck_fullscreen_controls.py) | `offline` |
| [selfcheck_fullscreen_cursor](../selfcheck_fullscreen_cursor.py) | 单项执行前核对 |
| [selfcheck_fullscreen_native_focus](../selfcheck_fullscreen_native_focus.py) | 单项执行前核对 |
| [selfcheck_fullscreen_quality](../selfcheck_fullscreen_quality.py) | 单项执行前核对 |
| [selfcheck_fullscreen_switch](../selfcheck_fullscreen_switch.py) | 单项执行前核对 |
| [selfcheck_layout_16](../selfcheck_layout_16.py) | `offline` |
| [selfcheck_layout_growth_empty](../selfcheck_layout_growth_empty.py) | `offline` |
| [selfcheck_layout_live_priority](../selfcheck_layout_live_priority.py) | 单项执行前核对 |
| [selfcheck_layout_none](../selfcheck_layout_none.py) | 单项执行前核对 |
| [selfcheck_layout_playback](../selfcheck_layout_playback.py) | 单项执行前核对 |
| [selfcheck_nav_layout](../selfcheck_nav_layout.py) | 单项执行前核对 |
| [selfcheck_orientation_layout](../selfcheck_orientation_layout.py) | 单项执行前核对 |
| [selfcheck_pane_borders](../selfcheck_pane_borders.py) | 单项执行前核对 |
| [selfcheck_portrait](../selfcheck_portrait.py) | 单项执行前核对 |
| [selfcheck_portrait_compact](../selfcheck_portrait_compact.py) | 单项执行前核对 |
| [selfcheck_portrait_native](../selfcheck_portrait_native.py) | 单项执行前核对 |
| [selfcheck_portrait_sidebar_return](../selfcheck_portrait_sidebar_return.py) | 单项执行前核对 |
| [selfcheck_portrait_small](../selfcheck_portrait_small.py) | 单项执行前核对 |
| [selfcheck_preset_resize](../selfcheck_preset_resize.py) | 单项执行前核对 |
| [selfcheck_preset_state](../selfcheck_preset_state.py) | 单项执行前核对 |
| [selfcheck_resize_preview_cleanup](../selfcheck_resize_preview_cleanup.py) | 单项执行前核对 |
| [selfcheck_resize_surface](../selfcheck_resize_surface.py) | `native` |
| [selfcheck_resize_widgets](../selfcheck_resize_widgets.py) | `native` |
| [selfcheck_room_presets](../selfcheck_room_presets.py) | `offline` |
| [selfcheck_slots](../selfcheck_slots.py) | 单项执行前核对 |
| [selfcheck_tile_fullscreen](../selfcheck_tile_fullscreen.py) | 单项执行前核对 |
| [selfcheck_window_resize](../selfcheck_window_resize.py) | `native` |

## 弹幕与表情

| 脚本 | 执行分类 |
| --- | --- |
| [check_emoticon_live](../check_emoticon_live.py) | 单项执行前核对 |
| [check_live_danmaku_motion](../check_live_danmaku_motion.py) | `live` |
| [check_medal_size](../check_medal_size.py) | 单项执行前核对 |
| [selfcheck_danmaku](../selfcheck_danmaku.py) | 单项执行前核对 |
| [selfcheck_danmaku_button](../selfcheck_danmaku_button.py) | 单项执行前核对 |
| [selfcheck_danmaku_composer](../selfcheck_danmaku_composer.py) | `offline` |
| [selfcheck_danmaku_connection](../selfcheck_danmaku_connection.py) | `offline` |
| [selfcheck_danmaku_emoji](../selfcheck_danmaku_emoji.py) | 单项执行前核对 |
| [selfcheck_danmaku_limit_migration](../selfcheck_danmaku_limit_migration.py) | 单项执行前核对 |
| [selfcheck_danmaku_limit_settings](../selfcheck_danmaku_limit_settings.py) | 单项执行前核对 |
| [selfcheck_danmaku_menu](../selfcheck_danmaku_menu.py) | 单项执行前核对 |
| [selfcheck_danmaku_render_thread](../selfcheck_danmaku_render_thread.py) | `native` |
| [selfcheck_danmaku_retention](../selfcheck_danmaku_retention.py) | 单项执行前核对 |
| [selfcheck_danmaku_room_switches](../selfcheck_danmaku_room_switches.py) | `offline` |
| [selfcheck_danmaku_send](../selfcheck_danmaku_send.py) | `offline` |
| [selfcheck_danmaku_smoothness](../selfcheck_danmaku_smoothness.py) | 单项执行前核对 |
| [selfcheck_danmaku_sort](../selfcheck_danmaku_sort.py) | 单项执行前核对 |
| [selfcheck_emoticon_tabs](../selfcheck_emoticon_tabs.py) | `offline` |
| [selfcheck_live_danmaku](../selfcheck_live_danmaku.py) | 单项执行前核对 |
| [selfcheck_live_danmaku_live](../selfcheck_live_danmaku_live.py) | 单项执行前核对 |
| [selfcheck_video_danmaku](../selfcheck_video_danmaku.py) | `offline` |
| [selfcheck_video_danmaku_controls](../selfcheck_video_danmaku_controls.py) | `offline` |
| [selfcheck_video_danmaku_native](../selfcheck_video_danmaku_native.py) | 单项执行前核对 |
| [selfcheck_video_danmaku_quick](../selfcheck_video_danmaku_quick.py) | `native` |

## 插件、更新与发布

| 脚本 | 执行分类 |
| --- | --- |
| [check_release_package](../check_release_package.py) | 单项执行前核对 |
| [selfcheck_close_release](../selfcheck_close_release.py) | 单项执行前核对 |
| [selfcheck_download_retry](../selfcheck_download_retry.py) | 单项执行前核对 |
| [selfcheck_fixed_exe_entry](../selfcheck_fixed_exe_entry.py) | 单项执行前核对 |
| [selfcheck_online](../selfcheck_online.py) | 单项执行前核对 |
| [selfcheck_online_ui](../selfcheck_online_ui.py) | 单项执行前核对 |
| [selfcheck_parallel_plugin_downloads](../selfcheck_parallel_plugin_downloads.py) | 单项执行前核对 |
| [selfcheck_plugin_cache](../selfcheck_plugin_cache.py) | 单项执行前核对 |
| [selfcheck_plugin_drop_restart](../selfcheck_plugin_drop_restart.py) | 单项执行前核对 |
| [selfcheck_plugin_rename](../selfcheck_plugin_rename.py) | 单项执行前核对 |
| [selfcheck_plugin_settings](../selfcheck_plugin_settings.py) | 单项执行前核对 |
| [selfcheck_plugin_update_notes](../selfcheck_plugin_update_notes.py) | 单项执行前核对 |
| [selfcheck_plugin_windows_lock](../selfcheck_plugin_windows_lock.py) | 单项执行前核对 |
| [selfcheck_plugins](../selfcheck_plugins.py) | 单项执行前核对 |
| [selfcheck_release_metadata](../selfcheck_release_metadata.py) | `offline` |
| [selfcheck_update_install](../selfcheck_update_install.py) | 单项执行前核对 |
| [selfcheck_update_notifications](../selfcheck_update_notifications.py) | 单项执行前核对 |
| [selfcheck_windows_version](../selfcheck_windows_version.py) | 单项执行前核对 |

## 播放、音频、取流与录制

| 脚本 | 执行分类 |
| --- | --- |
| [check_preview_live](../check_preview_live.py) | 单项执行前核对 |
| [selfcheck_audio_audit](../selfcheck_audio_audit.py) | 单项执行前核对 |
| [selfcheck_audio_cycle_shortcut](../selfcheck_audio_cycle_shortcut.py) | 单项执行前核对 |
| [selfcheck_audio_hotplug](../selfcheck_audio_hotplug.py) | 单项执行前核对 |
| [selfcheck_audio_owner](../selfcheck_audio_owner.py) | 单项执行前核对 |
| [selfcheck_audio_routing](../selfcheck_audio_routing.py) | 单项执行前核对 |
| [selfcheck_auto_quality](../selfcheck_auto_quality.py) | 单项执行前核对 |
| [selfcheck_auto_quality_live](../selfcheck_auto_quality_live.py) | 单项执行前核对 |
| [selfcheck_auto_quality_switch_live](../selfcheck_auto_quality_switch_live.py) | 单项执行前核对 |
| [selfcheck_bili_codec](../selfcheck_bili_codec.py) | `offline` |
| [selfcheck_bili_quality](../selfcheck_bili_quality.py) | 单项执行前核对 |
| [selfcheck_douyin_stream_fallback](../selfcheck_douyin_stream_fallback.py) | 单项执行前核对 |
| [selfcheck_mpv](../selfcheck_mpv.py) | `native` |
| [selfcheck_platform_preview](../selfcheck_platform_preview.py) | 单项执行前核对 |
| [selfcheck_platform_preview_live](../selfcheck_platform_preview_live.py) | 单项执行前核对 |
| [selfcheck_platform_quality](../selfcheck_platform_quality.py) | 单项执行前核对 |
| [selfcheck_platform_quality_live](../selfcheck_platform_quality_live.py) | 单项执行前核对 |
| [selfcheck_preview](../selfcheck_preview.py) | 单项执行前核对 |
| [selfcheck_preview_collapsed](../selfcheck_preview_collapsed.py) | 单项执行前核对 |
| [selfcheck_preview_popup](../selfcheck_preview_popup.py) | 单项执行前核对 |
| [selfcheck_quality](../selfcheck_quality.py) | 单项执行前核对 |
| [selfcheck_recording](../selfcheck_recording.py) | 单项执行前核对 |
| [selfcheck_recording_shutdown](../selfcheck_recording_shutdown.py) | 单项执行前核对 |
| [selfcheck_replay_scope](../selfcheck_replay_scope.py) | 单项执行前核对 |
| [selfcheck_stream_recovery](../selfcheck_stream_recovery.py) | `offline` |
| [selfcheck_stream_relay](../selfcheck_stream_relay.py) | 单项执行前核对 |
| [selfcheck_video_surface](../selfcheck_video_surface.py) | 单项执行前核对 |
| [selfcheck_video_surface_growth](../selfcheck_video_surface_growth.py) | 单项执行前核对 |
| [selfcheck_volume_channel](../selfcheck_volume_channel.py) | 单项执行前核对 |
| [selfcheck_volume_popup](../selfcheck_volume_popup.py) | `offline` |

## 比赛二路插件

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_match_sync](../selfcheck_match_sync.py) | 单项执行前核对 |
| [selfcheck_match_sync_admission](../selfcheck_match_sync_admission.py) | 单项执行前核对 |
| [selfcheck_match_sync_alignment](../selfcheck_match_sync_alignment.py) | 单项执行前核对 |
| [selfcheck_match_sync_appearance](../selfcheck_match_sync_appearance.py) | 单项执行前核对 |
| [selfcheck_match_sync_assistance](../selfcheck_match_sync_assistance.py) | 单项执行前核对 |
| [selfcheck_match_sync_audio_thread](../selfcheck_match_sync_audio_thread.py) | 单项执行前核对 |
| [selfcheck_match_sync_chat](../selfcheck_match_sync_chat.py) | 单项执行前核对 |
| [selfcheck_match_sync_comparison](../selfcheck_match_sync_comparison.py) | 单项执行前核对 |
| [selfcheck_match_sync_control](../selfcheck_match_sync_control.py) | 单项执行前核对 |
| [selfcheck_match_sync_crop_generation](../selfcheck_match_sync_crop_generation.py) | 单项执行前核对 |
| [selfcheck_match_sync_crop_style](../selfcheck_match_sync_crop_style.py) | 单项执行前核对 |
| [selfcheck_match_sync_danmaku_settings](../selfcheck_match_sync_danmaku_settings.py) | 单项执行前核对 |
| [selfcheck_match_sync_douyu_picture](../selfcheck_match_sync_douyu_picture.py) | 单项执行前核对 |
| [selfcheck_match_sync_empty](../selfcheck_match_sync_empty.py) | 单项执行前核对 |
| [selfcheck_match_sync_entry](../selfcheck_match_sync_entry.py) | 单项执行前核对 |
| [selfcheck_match_sync_exe](../selfcheck_match_sync_exe.py) | 单项执行前核对 |
| [selfcheck_match_sync_feedback](../selfcheck_match_sync_feedback.py) | 单项执行前核对 |
| [selfcheck_match_sync_four_compare](../selfcheck_match_sync_four_compare.py) | 单项执行前核对 |
| [selfcheck_match_sync_fullscreen_cursor](../selfcheck_match_sync_fullscreen_cursor.py) | 单项执行前核对 |
| [selfcheck_match_sync_health](../selfcheck_match_sync_health.py) | 单项执行前核对 |
| [selfcheck_match_sync_host_release](../selfcheck_match_sync_host_release.py) | 单项执行前核对 |
| [selfcheck_match_sync_late_buffer](../selfcheck_match_sync_late_buffer.py) | 单项执行前核对 |
| [selfcheck_match_sync_live](../selfcheck_match_sync_live.py) | 单项执行前核对 |
| [selfcheck_match_sync_lock](../selfcheck_match_sync_lock.py) | 单项执行前核对 |
| [selfcheck_match_sync_main_quality](../selfcheck_match_sync_main_quality.py) | 单项执行前核对 |
| [selfcheck_match_sync_media](../selfcheck_match_sync_media.py) | 单项执行前核对 |
| [selfcheck_match_sync_mpv_compat](../selfcheck_match_sync_mpv_compat.py) | 单项执行前核对 |
| [selfcheck_match_sync_multistream](../selfcheck_match_sync_multistream.py) | 单项执行前核对 |
| [selfcheck_match_sync_native](../selfcheck_match_sync_native.py) | 单项执行前核对 |
| [selfcheck_match_sync_offsets](../selfcheck_match_sync_offsets.py) | 单项执行前核对 |
| [selfcheck_match_sync_overseas](../selfcheck_match_sync_overseas.py) | 单项执行前核对 |
| [selfcheck_match_sync_playback](../selfcheck_match_sync_playback.py) | 单项执行前核对 |
| [selfcheck_match_sync_recovery](../selfcheck_match_sync_recovery.py) | 单项执行前核对 |
| [selfcheck_match_sync_refinement](../selfcheck_match_sync_refinement.py) | 单项执行前核对 |
| [selfcheck_match_sync_refinement_media](../selfcheck_match_sync_refinement_media.py) | 单项执行前核对 |
| [selfcheck_match_sync_responsiveness](../selfcheck_match_sync_responsiveness.py) | 单项执行前核对 |
| [selfcheck_match_sync_retry_rows](../selfcheck_match_sync_retry_rows.py) | 单项执行前核对 |
| [selfcheck_match_sync_session](../selfcheck_match_sync_session.py) | 单项执行前核对 |
| [selfcheck_match_sync_shortcuts](../selfcheck_match_sync_shortcuts.py) | 单项执行前核对 |
| [selfcheck_match_sync_smoothing](../selfcheck_match_sync_smoothing.py) | 单项执行前核对 |
| [selfcheck_match_sync_startup_clock](../selfcheck_match_sync_startup_clock.py) | 单项执行前核对 |
| [selfcheck_match_sync_status](../selfcheck_match_sync_status.py) | 单项执行前核对 |
| [selfcheck_match_sync_timer](../selfcheck_match_sync_timer.py) | 单项执行前核对 |
| [selfcheck_match_sync_tracking](../selfcheck_match_sync_tracking.py) | 单项执行前核对 |
| [selfcheck_match_sync_two_stream](../selfcheck_match_sync_two_stream.py) | 单项执行前核对 |
| [selfcheck_match_sync_ui](../selfcheck_match_sync_ui.py) | 单项执行前核对 |
| [selfcheck_match_sync_video](../selfcheck_match_sync_video.py) | 单项执行前核对 |
| [selfcheck_match_sync_volume](../selfcheck_match_sync_volume.py) | 单项执行前核对 |

## 直播平台

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_douyin_restart_cache](../selfcheck_douyin_restart_cache.py) | 单项执行前核对 |
| [selfcheck_douyin_room_source](../selfcheck_douyin_room_source.py) | 单项执行前核对 |
| [selfcheck_global_live](../selfcheck_global_live.py) | 单项执行前核对 |
| [selfcheck_huya_live](../selfcheck_huya_live.py) | 单项执行前核对 |
| [selfcheck_huya_watch](../selfcheck_huya_watch.py) | 单项执行前核对 |
| [selfcheck_live_platforms](../selfcheck_live_platforms.py) | 单项执行前核对 |
| [selfcheck_platform_login_expiry](../selfcheck_platform_login_expiry.py) | 单项执行前核对 |
| [selfcheck_platform_logo_background](../selfcheck_platform_logo_background.py) | `offline` |
| [selfcheck_platform_offline_tiles](../selfcheck_platform_offline_tiles.py) | `offline` |
| [selfcheck_platform_storage](../selfcheck_platform_storage.py) | 单项执行前核对 |
| [selfcheck_room_status](../selfcheck_room_status.py) | `offline` |

## 账号、登录与关注导入

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_account_dialog](../selfcheck_account_dialog.py) | 单项执行前核对 |
| [selfcheck_account_recovery](../selfcheck_account_recovery.py) | 单项执行前核对 |
| [selfcheck_account_render](../selfcheck_account_render.py) | 单项执行前核对 |
| [selfcheck_accounts](../selfcheck_accounts.py) | 单项执行前核对 |
| [selfcheck_domestic_follows](../selfcheck_domestic_follows.py) | 单项执行前核对 |
| [selfcheck_douyin_account_import](../selfcheck_douyin_account_import.py) | 单项执行前核对 |
| [selfcheck_douyin_follow_cache](../selfcheck_douyin_follow_cache.py) | 单项执行前核对 |
| [selfcheck_douyin_follow_resolution](../selfcheck_douyin_follow_resolution.py) | 单项执行前核对 |
| [selfcheck_douyin_profile_add](../selfcheck_douyin_profile_add.py) | 单项执行前核对 |
| [selfcheck_douyin_ui_follows](../selfcheck_douyin_ui_follows.py) | 单项执行前核对 |
| [selfcheck_follow_folders](../selfcheck_follow_folders.py) | `offline` |
| [selfcheck_follow_import](../selfcheck_follow_import.py) | 单项执行前核对 |
| [selfcheck_follow_refresh](../selfcheck_follow_refresh.py) | 单项执行前核对 |
| [selfcheck_oauth](../selfcheck_oauth.py) | 单项执行前核对 |
| [selfcheck_oauth_accounts](../selfcheck_oauth_accounts.py) | 单项执行前核对 |
| [selfcheck_oauth_guide](../selfcheck_oauth_guide.py) | 单项执行前核对 |
| [selfcheck_platform_accounts](../selfcheck_platform_accounts.py) | 单项执行前核对 |
| [selfcheck_platform_follow_reopen](../selfcheck_platform_follow_reopen.py) | 单项执行前核对 |
| [selfcheck_platform_follows](../selfcheck_platform_follows.py) | 单项执行前核对 |
| [selfcheck_qr_refresh](../selfcheck_qr_refresh.py) | 单项执行前核对 |
| [selfcheck_qr_responsiveness](../selfcheck_qr_responsiveness.py) | 单项执行前核对 |
| [selfcheck_remove_follow_position](../selfcheck_remove_follow_position.py) | 单项执行前核对 |
