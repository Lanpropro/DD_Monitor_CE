# 专项检查分类索引

按功能列出 Git 已跟踪的全部 `selfcheck_*.py` 与 `check_*.py`，不收录本机未跟踪脚本。
表中的套件名对应 [suites.json](suites.json)；执行条件与命令见[验证指南](../../docs/development/testing.md)。

已核对隔离条件的脚本才进入批量套件。标记“单项执行前核对”的历史脚本保留其用途，执行前需确认配置读取、网络、图形后端、媒体与发布包依赖，不推断其适合自动运行。

新增检查应更新此索引；仓库检查会核对它与 Git 索引一致。

## 当前回归与历史诊断

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_development_hang](../selfcheck_development_hang.py) | `offline`；本机开发入口的外部看门狗、只采调用栈、目标进程退出后结束；不作为真实卡死定位证据 |
| [selfcheck_responsiveness](../selfcheck_responsiveness.py) | `smoke` / `offline` |
| [selfcheck_diagnostic_session](../selfcheck_diagnostic_session.py) | `offline`；隔离进程验证未决专项启动、手动现场标记、列表快照与消息隐私，不替代真实故障复现 |
| [selfcheck_sidebar_diagnostics](../selfcheck_sidebar_diagnostics.py) | `offline`；模型对照、旧动画目标、拖放恢复、原生窗口只读、环形与记录大小上限、隐私；Windows单项原生后端补查现有HWND，不作为真实故障复现 |
| [selfcheck_on_demand_diagnostics](../selfcheck_on_demand_diagnostics.py) | `offline`；空闲不采集、即时错位快照、一次拖放/取消/超时后的清理、请求校验、Windows .NET/Qt 管道通信与诊断包内容；仅隔离夹具，不作为真实故障复现 |

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
| [selfcheck_widget_lifetime](../selfcheck_widget_lifetime.py) | `offline` / `smoke`；真实 Qt 菜单进退、操作与异常收尾、背景主题槽销毁回收；离屏，无媒体／账号／外网 |
| [selfcheck_smooth_edges](../selfcheck_smooth_edges.py) | `native` |
| [selfcheck_theme_latency](../selfcheck_theme_latency.py) | `offline` |
| [selfcheck_theme_native_reveal](../selfcheck_theme_native_reveal.py) | Windows屏幕外单项；默认检查原生裁剪和软件回退，`--render-thread` 检查圆形shader、视频透明孔、GUI暂停时继续渲染、反向切换及移动取消；不移动鼠标或激活窗口，不作为真实直播性能证据 |
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
| [selfcheck_qt_log](../selfcheck_qt_log.py) | `offline`；临时日志目录，无控制台消息；字体库info原生过滤、并发回调、warning与fatal保留 |
| [selfcheck_logging](../selfcheck_logging.py) | `offline`；临时日志、脱敏、轮转、启动失败与线程异常 |
| [selfcheck_readme](../selfcheck_readme.py) | `repository` |
| [selfcheck_repository_files](../selfcheck_repository_files.py) | `repository` |
| [selfcheck_repository_map](../selfcheck_repository_map.py) | `repository` |
| [selfcheck_startup](../selfcheck_startup.py) | 单项执行前核对 |
| [selfcheck_startup_danmaku](../selfcheck_startup_danmaku.py) | 单项执行前核对 |
| [selfcheck_startup_requests](../selfcheck_startup_requests.py) | 单项执行前核对 |
| [selfcheck_startup_wmi](../selfcheck_startup_wmi.py) | 单项执行前核对 |
| [selfcheck_watchdog](../selfcheck_watchdog.py) | 单项执行前核对 |

## 侧栏、控件与其他交互

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_picture_in_picture](../selfcheck_picture_in_picture.py) | `smoke` / `offline`；临时房间、1～16路布局边界、六路单主布局与横竖比例、主画面选择／预览／取消／保存、整窗实时合成／Windows原生拖动接管及Esc取消／源视频窗口保持静止、悬浮控件暂停同步／松手最终位置、拖动换位与缓冲缩放、缩放置顶、原音量／静音继承、分路面板与监控室同步、头像单行紧凑布局／后加载头像更新、深浅主题透明度／圆角、共用喇叭与滚轮行为对照／快捷键及退出恢复；Windows原生单项 `--native` 另验证仅关闭与返回监控室的最小化／托盘状态、本地横竖 MP4 的核心／HWND／进度、DWM 实时合成缩放及弹幕、醒目留言归属；`--live-resize` 可见连续帧取证，`--audio-preview` 输出隔离音量面板截图 |
| [selfcheck_pip_picker](../selfcheck_pip_picker.py) | `smoke` / `offline`；独立进程覆盖入墙优先、文件夹分块及智能归属／副本、上下重复入口鼠标／键盘勾选同步与单份组合、墙外选择与清理、80候选头像网格、中文／全拼／首字母／多词及文件夹搜索与关注栏对照、搜索重排与选择保持、预览拖动／取消；复用隔离主窗口 fixture，不与其他主窗口测试共用进程 |


| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_add_room_folder](../selfcheck_add_room_folder.py) | 离屏合成数据；添加归类、并发失败提示、网络错误分类与诊断脱敏 |
| [selfcheck_mobile_share](../selfcheck_mobile_share.py) | `offline`；手机中文分享、短链接跳转及后台查询，无账号和外网 |
| [selfcheck_add_room_hints](../selfcheck_add_room_hints.py) | 单项执行前核对 |
| [selfcheck_alt_tab_orientation](../selfcheck_alt_tab_orientation.py) | Windows 原生单项；空配置、禁用插件装载，最大化跟随屏幕，还原保留最大化前的窗口方向 |
| [selfcheck_avatars](../selfcheck_avatars.py) | 单项执行前核对 |
| [selfcheck_bili_2k_live](../selfcheck_bili_2k_live.py) | 单项执行前核对 |
| [selfcheck_bili_plugin_boundary](../selfcheck_bili_plugin_boundary.py) | `offline`、`smoke` |
| [selfcheck_bili_cookies](../selfcheck_bili_cookies.py) | `offline` |
| [selfcheck_cover_cache](../selfcheck_cover_cache.py) | 单项执行前核对 |
| [selfcheck_delete](../selfcheck_delete.py) | 单项执行前核对 |
| [selfcheck_drag_scroll](../selfcheck_drag_scroll.py) | 单项执行前核对 |
| [selfcheck_drag_wheel](../selfcheck_drag_wheel.py) | `native`；合成视频与 60 次应用内拖放，报告 UI 心跳与抓起耗时；`--physical` 需交互桌面 |
| [selfcheck_drag_lifecycle](../selfcheck_drag_lifecycle.py) | `offline` / `smoke`；首次快照准备在显示后完成、拖动中不补做；按视觉帧合并拖影、静止不重复移动、落点合并及拖放/取消恢复 |
| [selfcheck_sidebar_hit_test](../selfcheck_sidebar_hit_test.py) | `offline` / `smoke`；命中后端回退、透明遮挡、外部窗口、子控件与混合DPI坐标；CI另在Windows原生后端验证可见拖影下命中，不移动系统鼠标或激活测试窗口 |
| [selfcheck_drag_diagnostics](../selfcheck_drag_diagnostics.py) | `native`；合成拖放、COM 变化、阶段耗时、左键状态与模拟主线程停顿，不执行真实 OLE 拖动；根 `run.cmd --check-sidebar-drag` 另以离屏/隔离后端验证每次拖动的有界耗时汇总 |
| [selfcheck_room_placement](../selfcheck_room_placement.py) | `offline` / `smoke`；纯 Python 替身检查房间分配、换格、音频位置归属和启动去重，不导入 UI 或播放器 |
| [selfcheck_room_placement_native](../selfcheck_room_placement_native.py) | `native`；屏外合成窗口、双路本地视频，检查换格时 libmpv/HWND 保留、进度连续、位置音频和退出释放，无账号或外网 |
| [selfcheck_duplicate_tile_controls](../selfcheck_duplicate_tile_controls.py) | 单项执行前核对 |
| [selfcheck_encoders](../selfcheck_encoders.py) | 单项执行前核对 |
| [selfcheck_folder_blank_menu](../selfcheck_folder_blank_menu.py) | `offline` |
| [selfcheck_folder_card_drag](../selfcheck_folder_card_drag.py) | `offline` |
| [selfcheck_folder_card_size](../selfcheck_folder_card_size.py) | `offline` |
| [selfcheck_folder_drag](../selfcheck_folder_drag.py) | `offline` |
| [selfcheck_folder_icons](../selfcheck_folder_icons.py) | 单项执行前核对 |
| [selfcheck_general_settings](../selfcheck_general_settings.py) | `offline`、`smoke` |
| [selfcheck_startup_windows](../selfcheck_startup_windows.py) | `offline`、`smoke`；隔离配置与空插件，检查构建期间无独立小窗口和 HWND、底栏过滤范围、首次最大化、横竖屏和隐藏重开；未开播格子初始化不重入窗口绘制，下一轮事件仍清空画面/状态（默认及1.5倍原生后端复查）；原生专项检查可见时 Qt 与 Win32 客户区尺寸一致，在独立 Windows 桌面执行，不作为真实冷启动耗时依据 |
| [selfcheck_system_tray](../selfcheck_system_tray.py) | `offline` / `smoke`；托盘设置保存／重置、默认停止观看取流、恢复与手动暂停保留、录制保护、首次关闭选择及记忆、退出；隔离配置、无真实账号或鼠标操作 |
| [selfcheck_settings_process](../selfcheck_settings_process.py) | 单项执行；保存取消与主线程隔离；windows 下 `--native-zorder` 检查屏幕外独立设置窗口归属、遮挡及重开，不移动光标或激活窗口；`--embedded-native` 检查屏幕外跨页 HWND/DPI；`--footer-native` 检查首次进入插件、切页返回和同进程关闭重开时原生内容完整位于分配区域、取消／保存不被覆盖；`--restart-native` 检查安装/删除后的真实退出、隔离重启与无残留设置进程；`--native-focus` 会显示测试窗口并临时移动光标，须单独授权 |
| [selfcheck_settings_occlusion](../selfcheck_settings_occlusion.py) | `native`；隔离设置进程与 Quick 弹幕窗口，检查打开、移动、缩放、隐藏、最小化、重开及退出后的裁剪恢复；屏幕外窗口，不移动光标或激活窗口 |
| [selfcheck_single_instance](../selfcheck_single_instance.py) | `offline` / `smoke`；隔离锁目录和真实子进程，检查重复／并发启动、启动中唤回、异常退出恢复、重启释放，以及第二实例在加载配置前退出 |
| [check_settings_process_playback](../check_settings_process_playback.py) | 单项执行；需本机插件源码、双路合成媒体、libmpv、FFmpeg 和音频设备 |
| [selfcheck_hls_proxy](../selfcheck_hls_proxy.py) | `offline`；仅本机 HTTP，清单/分片转发、连接复用、非阻塞停止与资源回收，无账号或外网 |
| [selfcheck_live_alert](../selfcheck_live_alert.py) | 单项执行前核对 |
| [selfcheck_live_alert_sort](../selfcheck_live_alert_sort.py) | 单项执行前核对 |
| [selfcheck_localization](../selfcheck_localization.py) | 单项执行前核对 |
| [selfcheck_main_notices](../selfcheck_main_notices.py) | `offline`、`smoke`；包含开播提醒满墙后的目标选择、替换、取消、空格优先与去重 |
| [selfcheck_notification_center](../selfcheck_notification_center.py) | `smoke`、`offline` |
| [selfcheck_offline_badges](../selfcheck_offline_badges.py) | 单项执行前核对 |
| [selfcheck_orientation_work](../selfcheck_orientation_work.py) | 单项执行前核对 |
| [selfcheck_overseas_playback_live](../selfcheck_overseas_playback_live.py) | 单项执行前核对 |
| [selfcheck_overseas_stability](../selfcheck_overseas_stability.py) | 单项执行前核对 |
| [selfcheck_poller_lifecycle](../selfcheck_poller_lifecycle.py) | `offline`；受控 QThread、延迟完成回调与下一轮归属，退出不再起轮询，无账号或外网 |
| [selfcheck_resolve_retry](../selfcheck_resolve_retry.py) | `offline`；取流失败、恢复、下播、清格和隐藏后的重连清理，使用替身和空插件 |
| [selfcheck_search](../selfcheck_search.py) | 单项执行前核对 |
| [selfcheck_settings_status](../selfcheck_settings_status.py) | 单项执行前核对 |
| [selfcheck_sidebar_avatar](../selfcheck_sidebar_avatar.py) | 单项执行前核对 |
| [selfcheck_sidebar_collapse](../selfcheck_sidebar_collapse.py) | 独立 Sidebar；检查封面挂起/重裁及同步切换，可离屏执行 |
| [selfcheck_workspace_controls](../selfcheck_workspace_controls.py) | `offline`；独立功能轨、24 插件不挤压卡片、搜索/固定/持久化、原动作与卸载、收起/竖屏往返、关注筛选/密度、菜单与插件商店；离屏无账号或网络 |
| [selfcheck_continuous_corners](../selfcheck_continuous_corners.py) | `offline`；连续曲线边界、圆形/胶囊保留、输入编辑、样式状态与调色板切换、菜单和复选操作；仅合成界面 |
| [selfcheck_workspace_pages](../selfcheck_workspace_pages.py) | `offline`；嵌入页替换/返回、互斥切换、宿主隐藏/恢复和插件卸载；无账号或媒体 |
| [selfcheck_sidebar_performance](../selfcheck_sidebar_performance.py) | `native`；60 张合成封面、完整布局切换与屏外封面恢复；`--players` 使用 FFmpeg 生成本地视频，`--background` 置于屏幕外且不激活；耗时仅作功能检查记录 |
| [selfcheck_startup_scroll_diagnostics](../selfcheck_startup_scroll_diagnostics.py) | `offline` / `smoke`；实际离屏滚轮事件保持投递、每次滚动定长汇总、视频窗口/核心初始化阶段分开计时且排除后台线程；启动12秒内记录Qt慢事件与总量，并识别子控件慢绘制而不重复累计窗口耗时；保留返回/异常，以独立进程验证真实notify；仅验证采集机制 |
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
| [selfcheck_stream_info](../selfcheck_stream_info.py) | `offline`；合成播放器属性、格子右键入口、单位换算、逐格刷新及窗口清理；根入口 `run.cmd --check-stream-info` 另含 Windows 原生独立全屏窗口归属回归，不连接直播或读取账号 |
| [selfcheck_notice_close](../selfcheck_notice_close.py) | `run.cmd --check-notice-close`；Windows 原生／离屏通知关闭、动画停走时两类通知独立收尾、重开取消旧收尾、删除幂等、自动超时及两类通知只读采集上限；合成通知，不替代久用或负载故障复现 |
| [selfcheck_danmaku_motion_diagnostics](../selfcheck_danmaku_motion_diagnostics.py) | 原生单项；隔离 Quick 层数值采集上限、隐藏恢复、控件保留；不接入渲染线程、不读取消息，不替代真实回退复现 |
| [check_live_restore](../check_live_restore.py) | `live` |
| [selfcheck_corner_drag_updates](../selfcheck_corner_drag_updates.py) | 单项执行前核对 |
| [selfcheck_corner_resize](../selfcheck_corner_resize.py) | 单项执行前核对 |
| [selfcheck_corner_resize_live](../selfcheck_corner_resize_live.py) | 单项执行前核对 |
| [selfcheck_corner_small_resize](../selfcheck_corner_small_resize.py) | 单项执行前核对 |
| [selfcheck_corner_state](../selfcheck_corner_state.py) | 单项执行前核对 |
| [selfcheck_feedback_layout](../selfcheck_feedback_layout.py) | 单项执行前核对 |
| [selfcheck_fullscreen_audio](../selfcheck_fullscreen_audio.py) | 单项执行前核对 |
| [selfcheck_fullscreen_capture](../selfcheck_fullscreen_capture.py) | 离屏单项；几何事件上限与过滤器回收、采集边界、异步观察者清理、返回／异常及嵌套退出；无账号／外网，不是实际性能证据 |
| [selfcheck_fullscreen_volume](../selfcheck_fullscreen_volume.py) | 离屏：全屏方向键音量、调音量解除静音、上下限、输入隔离及保存 |
| [selfcheck_fullscreen_border](../selfcheck_fullscreen_border.py) | 单项执行前核对 |
| [selfcheck_playback_badges](../selfcheck_playback_badges.py) | `smoke` / `offline` |
| [selfcheck_playback_controls](../selfcheck_playback_controls.py) | `smoke` / `offline`；独立导入、旧类身份、音量边界与信号、按键交互、刷新显隐与父对象销毁、深浅主题及多缩放绘制；无媒体／账号／外网 |
| [selfcheck_fullscreen_controls](../selfcheck_fullscreen_controls.py) | `offline`；全屏底栏动画、Qt 透明窗口、输入期间原生像素可见性、窗口跟随及隐藏／恢复回归；原生 Windows 下可用 `python dev/checks/bootstrap.py dev/selfcheck_fullscreen_controls.py --desktop` 检查实际桌面合成，会短暂显示测试窗口 |
| [selfcheck_fullscreen_cursor](../selfcheck_fullscreen_cursor.py) | 单项执行前核对 |
| [selfcheck_fullscreen_native_focus](../selfcheck_fullscreen_native_focus.py) | 单项执行前核对 |
| [selfcheck_fullscreen_enter_focus](../selfcheck_fullscreen_enter_focus.py) | `native`；隔离输入控件验证全屏底栏隐藏/显示时一次Enter聚焦、工具窗口激活、小键盘及重绑定、跨屏鼠标位置、不误提交草稿，以及输入保护、点击视频释放焦点后恢复闲置收起；暂停共享动画时钟后连续三轮进出全屏，底栏仍完成收起和展开；不读取账号或发送弹幕，不代替用户真实复现 |
| [selfcheck_empty_tile_quality](../selfcheck_empty_tile_quality.py) | 离线替身；关闭平台房间、空格子旧画质编号及重启恢复 |
| [selfcheck_douyu_diagnostics](../selfcheck_douyu_diagnostics.py) | 离线替身；采集器功能回归，不作为真实故障定位依据 |
| [selfcheck_douyu_deep_capture](../selfcheck_douyu_deep_capture.py) | 本机 HTTP／分段 FLV；逐包解析、单连接转发和采集失败不改字节 |
| [selfcheck_douyu_cdn_control](../selfcheck_douyu_cdn_control.py) | 离线替身；自动／指定线路的请求与实际 CDN、失败映射脱敏采样、原生画质不变及恢复默认线路策略 |
| [selfcheck_douyu_transport](../selfcheck_douyu_transport.py) | 本机 HTTP；边缘源 TLS 密码套件兼容范围、证书校验及转发会话注入 |
| [selfcheck_douyu_quality_order](../selfcheck_douyu_quality_order.py) | 离线替身；斗鱼 2K 菜单顺序和原生取流档位映射 |
| [selfcheck_fullscreen_quality](../selfcheck_fullscreen_quality.py) | 离屏纯画质／取流逻辑；隔离原生呈现，窗口生命周期另见下项 |
| [selfcheck_fullscreen_switch](../selfcheck_fullscreen_switch.py) | `native`，包含于根 `run.cmd --check-fullscreen-layers`；固定屏幕外且不接受焦点，验证进入先绘制重建底栏再显示全屏 HWND、退出先画好恢复的底栏再撤下全屏、共享弹幕及浮动 SC 转移、留言保留、零画面墙重排、原位置恢复、快捷键与 HWND 连续性；非 Windows 后端跳过，不是实际性能证据 |
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
| [selfcheck_resize_surface](../selfcheck_resize_surface.py) | `native`；无mpv输出时保留Qt遮罩且不构建原生裁剪区，播放器子窗口创建/替换、尺寸/DPI/遮罩更新与重试生命周期 |
| [selfcheck_resize_widgets](../selfcheck_resize_widgets.py) | `native` |
| [selfcheck_pane_danmaku](../selfcheck_pane_danmaku.py) | `smoke` / `offline`；画面墙右键直接转换、顶部头像展开选择／收起／滚动／动效中断／缓存更新、多个弹幕栏、独立关联与共享连接、换位／换台／清空、录制保护、重启及组合恢复、横竖屏所有格位；`--native` 加本地静音 MP4 核心／HWND／进度检查，根 `run.cmd --check-wall-panes` 统一执行 |
| [selfcheck_room_presets](../selfcheck_room_presets.py) | `offline` |
| [selfcheck_slots](../selfcheck_slots.py) | 单项执行前核对 |
| [selfcheck_tile_fullscreen](../selfcheck_tile_fullscreen.py) | 单项执行前核对 |
| [selfcheck_window_resize](../selfcheck_window_resize.py) | `native` |
| [selfcheck_window_move_restore](../selfcheck_window_move_restore.py) | `native`；原生标题栏消息委托、无鼠标接管/替代窗口、同屏移动不隐藏且不重排、等尺寸最大化原生还原及双击；功能回归不代替真实鼠标与视觉验收 |
| [selfcheck_display_transition](../selfcheck_display_transition.py) | `native`；方向切换排布合并与异常恢复；`--screens --players 3` 使用双屏、123张合成关注和三路本地视频，检查3/6/16格原生跨屏/DPI、连续播放、几何、HWND/播放器保持及无替代窗口；不代表实际拖动帧率 |

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
| [selfcheck_danmaku_render_thread](../selfcheck_danmaku_render_thread.py) | `native`；另以 `--unthrottled` 检查不等待垂直同步时的实际滚动速度 |
| [selfcheck_danmaku_retention](../selfcheck_danmaku_retention.py) | 单项执行前核对 |
| [selfcheck_danmaku_room_switches](../selfcheck_danmaku_room_switches.py) | `offline` |
| [selfcheck_danmaku_smoothness](../selfcheck_danmaku_smoothness.py) | 单项执行前核对 |
| [selfcheck_danmaku_sort](../selfcheck_danmaku_sort.py) | 单项执行前核对 |
| [selfcheck_live_danmaku](../selfcheck_live_danmaku.py) | 单项执行前核对 |
| [selfcheck_live_danmaku_live](../selfcheck_live_danmaku_live.py) | 单项执行前核对 |
| [selfcheck_super_chat](../selfcheck_super_chat.py) | `offline`；状态、官方六档金额边界、两处实际像素、正文自适应高度与完整换行 |
| [selfcheck_sc_simulator](../selfcheck_sc_simulator.py) | `offline`；SC 模拟、多条纵向排列、独立折叠计时与关闭、滚动定位、画面／弹幕栏独立位置与实际对照、设置重开及重置、全屏恢复、紧凑控件及外置单位、共用大小和透明度、画面自动等比缩放与手动大小叠加／预览及实时重排、小画面弹幕缩放曲线单调及大画面不变、正文留白与背景混色；合成消息、隔离数据 |
| [selfcheck_video_danmaku](../selfcheck_video_danmaku.py) | `offline`；含后台尺寸重绘、最终像素／进度、两个尺寸缓存、旧结果丢弃与 GUI 事件交付；主窗口路由、设置和连接取消保留全部断言，在独立进程运行，隔离此前栅格／Quick夹具 |
| [selfcheck_video_danmaku_controls](../selfcheck_video_danmaku_controls.py) | `offline`；含按格独立设置、全局隔离、SC 范围、全屏、换格、空格及重启恢复 |
| [selfcheck_danmaku_color](../selfcheck_danmaku_color.py) | `offline`；根入口 `run.cmd --check-danmaku-color` 另验 Windows Quick RGB 纹理；合成文字，无直播连接 |
| [selfcheck_video_danmaku_native](../selfcheck_video_danmaku_native.py) | 单项执行前核对 |
| [selfcheck_video_danmaku_quick](../selfcheck_video_danmaku_quick.py) | `native` |

## 插件、更新与发布

| 脚本 | 执行分类 |
| --- | --- |
| [selfcheck_setup](../selfcheck_setup.py) | `offline`；安装输入白名单、初始清单及卸载脚本边界，不运行安装器 |
| [check_setup_install](../check_setup_install.py) | 单项 Windows 后台隔离安装、修复、更新与卸载；需明确传入包路径，已有安装时拒绝执行 |
| [check_setup_permissions](../check_setup_permissions.py) | 单项 Windows 后台检查；需原生入口和 ISCC，使用独立 AppId、临时目录 ACL 及合成安装验证目录写入权限拦截和可写自定义路径安装 |
| [selfcheck_data_paths](../selfcheck_data_paths.py) | `offline`：离屏、合成数据，验证安装版与便携版路径、迁移与失败回退、数据设置入口及更新提权分支；不调用真实 UAC、不读真实账号 |
| [selfcheck_image_cache](../selfcheck_image_cache.py) | `offline`；临时图片与数据目录、新图替换/共享引用/失败保留、跨进程清理保护、饼图选择及后台清理；不联网、不读真实账号 |
| [selfcheck_ui_components](../selfcheck_ui_components.py) | `offline`；共用组件入口、按需导入、原类身份、旧设置函数兼容、按钮信号及实际页面复用；离屏、临时数据，无账号/外网 |
| [check_setup_data_cleanup](../check_setup_data_cleanup.py) | 单项 Windows 后台检查；先构建原生入口，再传入 ISCC；使用独立登记和合成文件验证软件目录／独立数据目录的默认保留、勾选清理、中文路径、链接保护及额外文件保留 |
| [check_release_package](../check_release_package.py) | 单项执行前核对 |
| [selfcheck_close_release](../selfcheck_close_release.py) | 单项执行前核对 |
| [selfcheck_download_retry](../selfcheck_download_retry.py) | 单项执行前核对 |
| [selfcheck_fixed_exe_entry](../selfcheck_fixed_exe_entry.py) | 单项执行前核对 |
| [selfcheck_online](../selfcheck_online.py) | 合成响应；发布正文刷新、清单回退、下载校验及插件升级事务 |
| [selfcheck_online_ui](../selfcheck_online_ui.py) | 离屏合成数据；64 项商店与 16 项已安装紧凑列表、固定搜索／状态筛选／排序／详情与目录变化、深浅主题及长文本；刷新／页签／保存区边界、列表末尾留白、未保存选择与隐藏条目重建清理；下载期间筛选与滚动、详情更新及待重启、关闭/重开普通及独立设置、后台完成/退出收尾、当前版本正文及更新保存衔接 |
| [selfcheck_parallel_plugin_downloads](../selfcheck_parallel_plugin_downloads.py) | 单项执行前核对 |
| [selfcheck_plugin_cache](../selfcheck_plugin_cache.py) | 单项执行前核对 |
| [selfcheck_plugin_drop_restart](../selfcheck_plugin_drop_restart.py) | 单项执行前核对 |
| [selfcheck_plugin_rename](../selfcheck_plugin_rename.py) | 单项执行前核对 |
| [selfcheck_plugin_settings](../selfcheck_plugin_settings.py) | 单项执行前核对 |
| [selfcheck_plugin_update_notes](../selfcheck_plugin_update_notes.py) | 单项执行前核对 |
| [selfcheck_plugin_windows_lock](../selfcheck_plugin_windows_lock.py) | 单项执行前核对 |
| [selfcheck_plugin_controls](../selfcheck_plugin_controls.py) | `offline`；插件控件分配、换位与回收；等分格子跨 599/600 宽度边界时统一音量条样式，手动不等宽独立判断，全屏／布局切换恢复及各格音量保留 |
| [selfcheck_plugin_credentials](../selfcheck_plugin_credentials.py) | `offline` |
| [selfcheck_plugin_notices](../selfcheck_plugin_notices.py) | `offline` |
| [selfcheck_plugins](../selfcheck_plugins.py) | 单项执行前核对 |
| [selfcheck_plugin_contract](../selfcheck_plugin_contract.py) | `smoke`；临时插件的装载、事件、平台注册与卸载 |
| [selfcheck_release_metadata](../selfcheck_release_metadata.py) | `offline` |
| [selfcheck_hotfix_updates](../selfcheck_hotfix_updates.py) | `smoke` / `offline`；同版本修订号、hotfix 标签、包校验与回滚；根入口 `run.cmd --check-hotfix-updates` |
| [selfcheck_update_install](../selfcheck_update_install.py) | 单项执行前核对 |
| [selfcheck_legacy_cleanup](../selfcheck_legacy_cleanup.py) | `offline`；历史包哈希、备份迁移、用户数据及链接保护 |
| [selfcheck_update_notifications](../selfcheck_update_notifications.py) | 单项执行前核对 |
| [selfcheck_windows_version](../selfcheck_windows_version.py) | 单项执行前核对 |

## 播放、音频、取流与录制

| 脚本 | 执行分类 |
| --- | --- |
| [check_preview_live](../check_preview_live.py) | 单项执行前核对 |
| [selfcheck_audio_audit](../selfcheck_audio_audit.py) | 音量漂移、均衡开关与声道滤镜共存；替身内核、离屏 |
| [selfcheck_audio_cycle_shortcut](../selfcheck_audio_cycle_shortcut.py) | 单项执行前核对 |
| [selfcheck_audio_hotplug](../selfcheck_audio_hotplug.py) | 单项执行前核对 |
| [selfcheck_audio_owner](../selfcheck_audio_owner.py) | 单项执行前核对 |
| [selfcheck_playback_recovery](../selfcheck_playback_recovery.py) | `offline` / `smoke`；恢复控制器的退避、冻结、稳定播放、关闭收尾及主窗口兼容/插件事件，使用本地替身 |
| [selfcheck_player_lifetime](../selfcheck_player_lifetime.py) | `offline` / `smoke`；构造、重绑、释放参数、音频设备刷新调度及错误反馈、各平台恢复任务去重与定时器回收。单项 Windows 原生用例检查普通格子延迟创建 GPU 输出、本地图片出帧与取消；窗口不激活、不移鼠标，静音且媒体无音轨，不读取账号或联网，不作为真实卡顿性能依据 |
| [selfcheck_mpv_com_lifetime](../selfcheck_mpv_com_lifetime.py) | `native`；Windows 本地静音 WAV、真实 WASAPI，反复刷新音频设备、终止/释放及预览清理，检查刷新后继续播放及 COM apartment 不变；不执行 OLE 拖动，属于功能回归，不代替真实故障采集 |
| [selfcheck_audio_routing](../selfcheck_audio_routing.py) | 合成 PCM 验证音量、路由及均衡后的响度差/静音/关闭还原；需 FFmpeg、libmpv、numpy |
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
| [selfcheck_recording](../selfcheck_recording.py) | `offline`；FFmpeg 与临时合成视频、本机 HTTP 的功能回归，含手动回放停止/恢复、缓存升级、录制计时、画质请求取消及过期源恢复；不能作为真实性能改善依据 |
| [selfcheck_recording_shutdown](../selfcheck_recording_shutdown.py) | `offline`；FFmpeg 功能回归：退出保存完整录制、等待重连的分段和主动导出的回放，清理未保存缓存；隔离账号和安装插件 |
| [selfcheck_recording_service](../selfcheck_recording_service.py) | `offline`；会话边界、未封口尾段、分段租约、录制后端归属/卸载恢复及增长索引边界；临时文件/替身，无账号或外网 |
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
| [selfcheck_room_status_controller](../selfcheck_room_status_controller.py) | `offline` / `smoke`；合成信号检查轮询父对象、请求去重、平台参数、刷新排队、旧回调和关闭清理 |
| [selfcheck_room_images](../selfcheck_room_images.py) | `offline` / `smoke`；合成加载器检查图片分流、横幅去重、回填和线程引用清理；临时缓存与真实 Qt 线程检查主线程回填及关闭，无账号或外网 |

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
| [selfcheck_follow_refresh](../selfcheck_follow_refresh.py) | `offline`；合成关注列表、替身轮询器，检查刷新连点、头像补充阶段、失败与空列表恢复 |
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
| [selfcheck_douyu_recovery](../selfcheck_douyu_recovery.py) | `offline`；验证失败反馈、EOF恢复、正常进度／暂停等静帧排除、2与8检查阈值差异及稳定后重置退避；不代表真实播放稳定性 |
