# 专项检查分类索引

按功能列出 Git 已跟踪的全部 `selfcheck_*.py` 与 `check_*.py`，不收录本机未跟踪脚本。
表中的套件名对应 [suites.json](suites.json)；执行条件与命令见[验证指南](../../docs/development/testing.md)。

已核对隔离条件的脚本才进入批量套件。标记“单项执行前核对”的历史脚本保留其用途，执行前需确认配置读取、网络、图形后端、媒体与发布包依赖，不推断其适合自动运行。

新增检查应更新此索引；仓库检查会核对它与 Git 索引一致。

## 当前回归与历史诊断

- 当前回归：`repository`、`smoke`、`offline`、`native`、`live` 中明确登记的脚本；其中 smoke 复用离屏回归并增加临时插件接口检查，每个 PR 自动运行。
- 待复核／历史诊断：下表标记“单项执行前核对”的脚本。这个标记表示尚未批准批量执行，不代表已废弃；再次使用前核对当前断言和隔离条件，通过后再纳入套件。
- 文件继续保留现有位置；分类依据套件元数据和本索引，不通过移动脚本改变导入路径。

## 主题、资源与动效

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_appearance](../selfcheck_appearance.py) | 单项执行前核对 |
| [selfcheck_appearance_design](../selfcheck_appearance_design.py) | `repository` |
| [selfcheck_appearance_playback](../selfcheck_appearance_playback.py) | 单项执行前核对 |
| [selfcheck_badge_memory](../selfcheck_badge_memory.py) | `native` |
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
| [selfcheck_settings_transition](../selfcheck_settings_transition.py) | 单项执行；设置动画快照、打断与录制页滚动，使用合成数据 |

## 仓库、启动与文档

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_check_runner](../selfcheck_check_runner.py) | `repository` |
| [selfcheck_customization_plan](../selfcheck_customization_plan.py) | `repository` |
| [selfcheck_launch_scripts](../selfcheck_launch_scripts.py) | 单项执行前核对 |
| [selfcheck_project_workflow](../selfcheck_project_workflow.py) | `repository` |
| [selfcheck_qt_log](../selfcheck_qt_log.py) | `offline`；临时日志目录，无控制台 Qt 消息 |
| [selfcheck_logging](../selfcheck_logging.py) | `offline`；临时日志、脱敏、轮转、启动失败与线程异常 |
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
| [selfcheck_add_room_folder](../selfcheck_add_room_folder.py) | 离屏合成数据；添加归类、并发失败提示、网络错误分类与诊断脱敏 |
| [selfcheck_mobile_share](../selfcheck_mobile_share.py) | `offline`；手机中文分享、短链接跳转及后台查询，无账号和外网 |
| [selfcheck_add_room_hints](../selfcheck_add_room_hints.py) | 单项执行前核对 |
| [selfcheck_alt_tab_orientation](../selfcheck_alt_tab_orientation.py) | 单项执行前核对 |
| [selfcheck_avatars](../selfcheck_avatars.py) | 单项执行前核对 |
| [selfcheck_bili_2k_live](../selfcheck_bili_2k_live.py) | 单项执行前核对 |
| [selfcheck_bili_plugin_boundary](../selfcheck_bili_plugin_boundary.py) | `offline`、`smoke` |
| [selfcheck_bili_cookies](../selfcheck_bili_cookies.py) | `offline` |
| [selfcheck_cover_cache](../selfcheck_cover_cache.py) | 单项执行前核对 |
| [selfcheck_delete](../selfcheck_delete.py) | 单项执行前核对 |
| [selfcheck_drag_scroll](../selfcheck_drag_scroll.py) | 单项执行前核对 |
| [selfcheck_drag_wheel](../selfcheck_drag_wheel.py) | 单项执行前核对 |
| [selfcheck_drag_lifecycle](../selfcheck_drag_lifecycle.py) | `offline` / `smoke` |
| [selfcheck_duplicate_tile_controls](../selfcheck_duplicate_tile_controls.py) | 单项执行前核对 |
| [selfcheck_encoders](../selfcheck_encoders.py) | 单项执行前核对 |
| [selfcheck_folder_blank_menu](../selfcheck_folder_blank_menu.py) | `offline` |
| [selfcheck_folder_card_drag](../selfcheck_folder_card_drag.py) | 单项执行前核对 |
| [selfcheck_folder_card_size](../selfcheck_folder_card_size.py) | `offline` |
| [selfcheck_folder_drag](../selfcheck_folder_drag.py) | 单项执行前核对 |
| [selfcheck_folder_icons](../selfcheck_folder_icons.py) | 单项执行前核对 |
| [selfcheck_general_settings](../selfcheck_general_settings.py) | `offline`、`smoke` |
| [selfcheck_system_tray](../selfcheck_system_tray.py) | `offline` / `smoke`；模拟托盘、首次关闭选择及记忆、后台保持、恢复和退出；隔离配置、无真实账号或鼠标操作 |
| [selfcheck_settings_process](../selfcheck_settings_process.py) | 单项执行；保存取消与主线程隔离；windows 下 `--native-zorder` 检查屏幕外独立设置窗口归属、遮挡及重开，不移动光标或激活窗口；`--embedded-native` 检查屏幕外跨页 HWND/DPI，`--restart-native` 检查安装/删除后的真实退出、隔离重启与无残留设置进程；`--native-focus` 会显示测试窗口并临时移动光标，须单独授权 |
| [check_settings_process_playback](../check_settings_process_playback.py) | 单项执行；需本机插件源码、双路合成媒体、libmpv、FFmpeg 和音频设备 |
| [selfcheck_hls_proxy](../selfcheck_hls_proxy.py) | 单项执行前核对 |
| [selfcheck_live_alert](../selfcheck_live_alert.py) | 单项执行前核对 |
| [selfcheck_live_alert_sort](../selfcheck_live_alert_sort.py) | 单项执行前核对 |
| [selfcheck_localization](../selfcheck_localization.py) | 单项执行前核对 |
| [selfcheck_main_notices](../selfcheck_main_notices.py) | `offline`、`smoke` |
| [selfcheck_notification_center](../selfcheck_notification_center.py) | `smoke`、`offline` |
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
| [selfcheck_frequent_sort](../selfcheck_frequent_sort.py) | `offline`、`smoke`；主动观看计分、快照刷新、文件夹与持久化 |
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
| [selfcheck_fullscreen_volume](../selfcheck_fullscreen_volume.py) | 离屏：全屏方向键音量、调音量解除静音、上下限、输入隔离及保存 |
| [selfcheck_fullscreen_border](../selfcheck_fullscreen_border.py) | 单项执行前核对 |
| [selfcheck_fullscreen_controls](../selfcheck_fullscreen_controls.py) | `offline` |
| [selfcheck_fullscreen_cursor](../selfcheck_fullscreen_cursor.py) | 单项执行前核对 |
| [selfcheck_fullscreen_native_focus](../selfcheck_fullscreen_native_focus.py) | 单项执行前核对 |
| [selfcheck_fullscreen_quality](../selfcheck_fullscreen_quality.py) | 单项执行前核对 |
| [selfcheck_fullscreen_switch](../selfcheck_fullscreen_switch.py) | 单项执行前核对 |
| [selfcheck_layout_16](../selfcheck_layout_16.py) | `offline`、`smoke` |
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
| [selfcheck_danmaku_connection](../selfcheck_danmaku_connection.py) | `offline` |
| [selfcheck_danmaku_emoji](../selfcheck_danmaku_emoji.py) | 单项执行前核对 |
| [selfcheck_danmaku_limit_migration](../selfcheck_danmaku_limit_migration.py) | 单项执行前核对 |
| [selfcheck_danmaku_limit_settings](../selfcheck_danmaku_limit_settings.py) | 单项执行前核对 |
| [selfcheck_danmaku_menu](../selfcheck_danmaku_menu.py) | 单项执行前核对 |
| [selfcheck_danmaku_actions](../selfcheck_danmaku_actions.py) | `offline`；单条悬停、点击、复制和房间绑定发送，使用替身输入控件 |
| [selfcheck_danmaku_render_thread](../selfcheck_danmaku_render_thread.py) | `native` |
| [selfcheck_danmaku_retention](../selfcheck_danmaku_retention.py) | 单项执行前核对 |
| [selfcheck_danmaku_room_switches](../selfcheck_danmaku_room_switches.py) | `offline` |
| [selfcheck_danmaku_smoothness](../selfcheck_danmaku_smoothness.py) | 单项执行前核对 |
| [selfcheck_danmaku_sort](../selfcheck_danmaku_sort.py) | 单项执行前核对 |
| [selfcheck_live_danmaku](../selfcheck_live_danmaku.py) | 单项执行前核对 |
| [selfcheck_live_danmaku_live](../selfcheck_live_danmaku_live.py) | 单项执行前核对 |
| [selfcheck_super_chat](../selfcheck_super_chat.py) | `offline` |
| [selfcheck_sc_simulator](../selfcheck_sc_simulator.py) | `offline`；虚拟 SC 控制台按钮、倒计时与临时数据隔离 |
| [selfcheck_video_danmaku](../selfcheck_video_danmaku.py) | `offline` |
| [selfcheck_video_danmaku_controls](../selfcheck_video_danmaku_controls.py) | `offline` |
| [selfcheck_video_danmaku_native](../selfcheck_video_danmaku_native.py) | 单项执行前核对 |
| [selfcheck_video_danmaku_quick](../selfcheck_video_danmaku_quick.py) | `native` |

## 插件、更新与发布

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_setup](../selfcheck_setup.py) | `offline`；安装输入白名单、初始清单及卸载脚本边界，不运行安装器 |
| [check_setup_install](../check_setup_install.py) | 单项 Windows 后台隔离安装、修复、更新与卸载；需明确传入包路径，已有安装时拒绝执行 |
| [check_setup_permissions](../check_setup_permissions.py) | 单项 Windows 后台检查；需原生入口和 ISCC，使用独立 AppId、临时目录 ACL 及合成安装验证目录写入权限拦截和可写自定义路径安装 |
| [selfcheck_data_paths](../selfcheck_data_paths.py) | `offline`：离屏、合成数据，验证安装版与便携版路径、迁移与失败回退、数据设置入口及更新提权分支；不调用真实 UAC、不读真实账号 |
| [check_setup_data_cleanup](../check_setup_data_cleanup.py) | 单项 Windows 后台检查；先构建原生入口，再传入 ISCC；使用独立登记和合成文件验证软件目录／独立数据目录的默认保留、勾选清理、中文路径、链接保护及额外文件保留 |
| [check_release_package](../check_release_package.py) | 单项执行前核对 |
| [selfcheck_close_release](../selfcheck_close_release.py) | 单项执行前核对 |
| [selfcheck_download_retry](../selfcheck_download_retry.py) | 单项执行前核对 |
| [selfcheck_fixed_exe_entry](../selfcheck_fixed_exe_entry.py) | 单项执行前核对 |
| [selfcheck_online](../selfcheck_online.py) | 合成响应；发布正文刷新、清单回退、下载校验及插件升级事务 |
| [selfcheck_online_ui](../selfcheck_online_ui.py) | 离屏合成数据；下载期间关闭/重开普通及独立设置、后台完成/退出收尾、当前版本正文及更新保存衔接 |
| [selfcheck_parallel_plugin_downloads](../selfcheck_parallel_plugin_downloads.py) | 单项执行前核对 |
| [selfcheck_plugin_cache](../selfcheck_plugin_cache.py) | 单项执行前核对 |
| [selfcheck_plugin_drop_restart](../selfcheck_plugin_drop_restart.py) | 单项执行前核对 |
| [selfcheck_plugin_rename](../selfcheck_plugin_rename.py) | 单项执行前核对 |
| [selfcheck_plugin_settings](../selfcheck_plugin_settings.py) | 单项执行前核对 |
| [selfcheck_plugin_update_notes](../selfcheck_plugin_update_notes.py) | 单项执行前核对 |
| [selfcheck_plugin_windows_lock](../selfcheck_plugin_windows_lock.py) | 单项执行前核对 |
| [selfcheck_plugin_controls](../selfcheck_plugin_controls.py) | `offline` |
| [selfcheck_plugin_credentials](../selfcheck_plugin_credentials.py) | `offline` |
| [selfcheck_plugin_notices](../selfcheck_plugin_notices.py) | `offline` |
| [selfcheck_plugins](../selfcheck_plugins.py) | 单项执行前核对 |
| [selfcheck_plugin_contract](../selfcheck_plugin_contract.py) | `smoke`；临时插件的装载、事件、平台注册与卸载 |
| [selfcheck_release_metadata](../selfcheck_release_metadata.py) | `offline` |
| [selfcheck_update_install](../selfcheck_update_install.py) | 单项执行前核对 |
| [selfcheck_legacy_cleanup](../selfcheck_legacy_cleanup.py) | `offline`；历史包哈希、备份迁移、用户数据及链接保护 |
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
| [selfcheck_player_lifetime](../selfcheck_player_lifetime.py) | `offline` / `smoke`；构造、重绑与释放参数，不调用原生音频 |
| [selfcheck_mpv_com_lifetime](../selfcheck_mpv_com_lifetime.py) | `native`；Windows 本地静音 WAV、真实 WASAPI，反复终止/释放及预览清理，检查 COM apartment 不变；不执行 OLE 拖动 |
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
| [selfcheck_preview_scroll](../selfcheck_preview_scroll.py) | `offline`；65行紧凑关注栏，滚轮取流竞态、漏发离开事件与悬停重绘 |
| [selfcheck_quality](../selfcheck_quality.py) | 单项执行前核对 |
| [selfcheck_recording](../selfcheck_recording.py) | 合成视频与本机HTTP，含过期地址分片续录、403重新取流与停止／切房隔离；单项执行前核对 |
| [selfcheck_recording_shutdown](../selfcheck_recording_shutdown.py) | 单项执行前核对 |
| [selfcheck_replay_scope](../selfcheck_replay_scope.py) | 单项执行前核对 |
| [selfcheck_stream_recovery](../selfcheck_stream_recovery.py) | `offline` |
| [selfcheck_stream_relay](../selfcheck_stream_relay.py) | 单项执行前核对 |
| [selfcheck_video_surface](../selfcheck_video_surface.py) | 单项执行前核对 |
| [selfcheck_video_surface_growth](../selfcheck_video_surface_growth.py) | 单项执行前核对 |
| [selfcheck_volume_channel](../selfcheck_volume_channel.py) | 单项执行前核对 |

## 比赛二路插件

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_match_sync](../selfcheck_match_sync.py) | 单项执行前核对 |
| [selfcheck_match_sync_reserve](../selfcheck_match_sync_reserve.py) | 单项执行；合成时钟、假取流、临时插件设置，验证可选缓冲与持续补充，不联网 |
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
| [selfcheck_match_sync_retry_rows](../selfcheck_match_sync_retry_rows.py) | 单项执行；使用 Windows 原生后端验证全屏窗口重挂、对照框选与拖动，不联网 |
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
| [selfcheck_platform_reauthentication](../selfcheck_platform_reauthentication.py) | 单项执行前核对；强制重新登录路由与目标平台会话清理 |
| [selfcheck_failed_stream_quality](../selfcheck_failed_stream_quality.py) | 单项执行前核对；取流失败后的平台画质菜单 |
| [selfcheck_platform_offline_tiles](../selfcheck_platform_offline_tiles.py) | `offline` |
| [selfcheck_platform_storage](../selfcheck_platform_storage.py) | 单项执行前核对 |
| [selfcheck_room_status](../selfcheck_room_status.py) | `offline` |

## 账号、登录与关注导入

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_account_dialog](../selfcheck_account_dialog.py) | 单项执行前核对 |
| [selfcheck_account_login_reopen](../selfcheck_account_login_reopen.py) | `native` |
| [selfcheck_account_recovery](../selfcheck_account_recovery.py) | 单项执行前核对 |
| [selfcheck_account_render](../selfcheck_account_render.py) | 单项执行前核对 |
| [selfcheck_accounts](../selfcheck_accounts.py) | 单项执行前核对 |
| [selfcheck_domestic_follows](../selfcheck_domestic_follows.py) | 单项执行前核对 |
| [selfcheck_douyin_account_import](../selfcheck_douyin_account_import.py) | 单项执行前核对 |
| [selfcheck_douyin_follow_cache](../selfcheck_douyin_follow_cache.py) | 单项执行前核对 |
| [selfcheck_douyin_follow_resolution](../selfcheck_douyin_follow_resolution.py) | 单项执行前核对 |
| [selfcheck_douyin_profile_add](../selfcheck_douyin_profile_add.py) | 单项执行前核对 |
| [selfcheck_douyin_room_verification](../selfcheck_douyin_room_verification.py) | 本地 WebEngine 验证页、身份核对、取消重试与首次添加复用 |
| [selfcheck_douyin_ui_follows](../selfcheck_douyin_ui_follows.py) | 单项执行前核对 |
| [selfcheck_follow_folders](../selfcheck_follow_folders.py) | `offline` |
| [selfcheck_follow_import](../selfcheck_follow_import.py) | 离屏合成数据；覆盖32/33位原关注＋1位新增的归类隔离、结果提示与头像范围、主动勾选归类、取消勾选与保存 |
| [selfcheck_follow_stress](../selfcheck_follow_stress.py) | 隔离离屏压力测试：模拟登录、3000关注／750主播，无真实网络或配置写入；输出 results/follow-stress.json |
| [selfcheck_pinyin_search](../selfcheck_pinyin_search.py) | `offline`；两处拼音搜索与750行缓存回归 |
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

## 独立诊断工具

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_diagnostics](../selfcheck_diagnostics.py) | 单项执行前核对；Windows .NET Framework，临时模拟目录，不读取真实账号配置，不启动主软件 |

| [selfcheck_huya_live_eof](../selfcheck_huya_live_eof.py) | 离线验证虎牙实时流结束后的缓存播放与自动恢复 |
