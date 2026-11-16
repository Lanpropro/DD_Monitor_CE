# 架构总览

> 类型：架构 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-17 ｜ 读者：贡献者、维护者

本页说明软件本体如何组成：有哪些进程、代码分几层、状态由谁持有、一次播放或一次设置保存经过哪些模块。
文件级清单见[仓库文件分类清单](../repository-map.md)，单条功能的交互细节见对应设计文档。

## 本页导航

- [定位与边界](#1-定位与边界) · [进程与运行形态](#2-进程与运行形态) · [代码分层与依赖方向](#3-代码分层与依赖方向)
- [启动与关闭](#4-启动与关闭) · [职责域与代表模块](#5-职责域与代表模块) · [状态所有权与生命周期规则](#6-状态所有权与生命周期规则)
- [关键数据流](#7-关键数据流) · [扩展点](#8-扩展点) · [修改时先看哪里](#9-修改时先看哪里)
- [详细模块职责](#10-详细模块职责)

## 1. 定位与边界

DD监控室CE 是 Windows 桌面应用，核心能力是同一面画面墙里播放多路直播，并逐路控制画质、声音、弹幕和录制。
本体内置 B 站；其他平台、比赛二路、B 站互动和录制切片由独立插件提供。

| 属于本体 | 不属于本体 |
| --- | --- |
| 窗口与布局、画面墙、播放器生命周期、弹幕接收与绘制 | 虎牙/斗鱼/抖音/Twitch/YouTube 的取流与接口解析 |
| 设置、账号会话、图片缓存、录制进程、更新器 | 平台专属登录页、礼物与表情业务 |
| 插件装载、事件分发、宿主 API、诊断入口 | 插件自己的界面、数据目录和后台进程 |

插件是**受信任的进程内代码**，能力与本体代码等价；不能把它当作权限沙箱。需要隔离时由插件使用
`--plugin-worker` 启动自己的进程。

技术栈：Python + PySide6（固定 6.11.2）、libmpv（`python-mpv`，运行库 `libmpv-2.dll`）、
外部 FFmpeg（录制与转码）、Qt Quick（部分弹幕/主题表面）。依赖清单以 `requirements.txt` 为准。

本架构只描述 Windows 桌面端。仓库中的 `mobile/` 是独立移动端实验，开发尚未完成，不参与桌面端的启动、
插件装载和发布流程；完成后再补独立的架构与发布文档。

## 2. 进程与运行形态

| 进程 | 启动方式 | 职责 | 退出 |
| --- | --- | --- | --- |
| 主界面进程 | 源码版 `run.cmd` 当前经 `dev/diagnose_drag_windows.py` 启动 `main.py`；打包版使用 `DD监控室CE.exe` | Qt 主窗口、播放器、弹幕、录制、插件、更新 | 关闭窗口或托盘退出 |
| 独立设置进程 | `main.py --settings-worker`（`DDM_SETTINGS_PROCESS=1` 时预热/打开） | 承载常规、弹幕、录制、通知、快捷键页面 | 设置窗口关闭或主程序退出 |
| 插件工作进程 | `main.py --plugin-worker <目录> <模块>` | 插件自己的后台任务，不构造宿主界面 | 插件自行管理 |
| 更新助手 | `main.py --apply-update <计划>` / `--apply-update-elevated` | 等待主程序退出、替换文件、必要时请求 UAC | 完成或失败后退出 |
| 独立诊断工具 | `tools/diagnostics` 构建的 EXE | 用户按需抓取窗口现场和已有日志 | 用户关闭 |

源码开发版允许多开；打包版通过 `ddm/single_instance.py` 限制每个用户一个实例，重复启动时唤回已有窗口。
主界面与设置进程通过标准输出上的 JSON 行通信，前缀为 `DDM_SETTINGS:`；不是网络端口，也不共享 Qt 对象。

## 3. 代码分层与依赖方向

```text
入口        main.py / ddm/app.py
             |
宿主协调    app_*.py、*_control.py、*_lifecycle.py（持有 Qt 对象与业务状态）
             |
职责模块    sidebar_*、wall_*、tile_*、stream_*、danmaku_*、recording_*、settings_*、plugin_* …
             |
基础能力    ddm/ui/*、theme.py、motion.py、widget_support.py、corner_geometry.py
             |
兼容出口    widgets.py、sidebar_cards.py（只做旧名字导出，不放实现）
```

依赖规则：

- 聚合入口只保留真正需要的接线：启动/关闭、跨模块编排、Qt 生命周期和必要的状态所有权。
  其余实现按功能留在职责模块；新增代码不把功能实现堆进 `app.py`、`dialogs.py`、`widgets.py`。
- 职责模块不反向导入 `ddm/app.py`、`ddm/dialogs.py`、`ddm/widgets.py`；需要宿主能力时通过构造参数、
  回调或 signal 传入，避免反向依赖和导入循环。
- 这是新增和迁移代码的依赖目标。当前 `danmaku_blocking.py` 仍在方法内导入 `SettingsDialog`，若干诊断模块仍导入 `MainWindow`；整理这些既有入口时应逐项核对生命周期，不把目标规则写成已全部实现。
- 判断标准：把这段代码删掉后，宿主还能不能正常工作？只有“接线/编排/生命周期”必须留在宿主；
  按钮绘制、协议解析、数据校验、文件格式等都应回到职责模块。
- 历史兼容入口逐步迁移，不要求一次改完。
- 基础控件不依赖画面墙、播放器或主窗口；主题令牌集中在 `ddm/theme.py`，不在页面里另建配色表。
- `ddm/widgets.py` 只保留兼容导出，项目内部直接导入职责模块；兼容导出必须指向同一对象，不复制类。

## 4. 启动与关闭

启动顺序（`main.py` → `ddm/app.py:main`）：

1. 解析入口模式（更新助手、设置进程、插件进程或主程序），主程序先初始化数据目录；
2. 创建 `QApplication`，打包版获取单实例锁，安装中文翻译、全局 QSS 和窗口图标；
3. 读取 `utils/config.json`，应用主题，处理首次用户告知、上次更新残留和旧版文件清理；
4. 还原关注房间与画面墙占位，构造 `MainWindow`（控制器、播放器表、侧栏、画面墙、托盘、快捷键）；
5. 安装按需诊断端点与界面看门狗，显示窗口，异步检查本体与插件更新；
6. 进入 Qt 事件循环；退出码在事件循环结束后统一处理更新/重启/进程退出。

关闭顺序（`MainWindow.closeEvent`）：

1. 托盘按用户选择可能只隐藏窗口，不进入销毁流程；
2. 退出画中画与全屏、隐藏窗口、置 `_closing` 防止迟到取流回调访问已释放播放器；
3. 停止设置进程、更新任务、轮询与计时器，关闭录制并发出 `app.closing` 事件；
4. 卸载插件、保存配置、停止弹幕与预览、释放全部播放器；
5. 等待后台线程收尾，清理更新/插件检查任务，最后由 `main()` 处理更新助手或重启。

改关闭流程时先确认：迟到回调、线程等待、Qt 父子销毁和配置保存四件事是否仍然成立。

## 5. 职责域与代表模块

| 职责域 | 代表模块 | 边界 |
| --- | --- | --- |
| 宿主协调 | `app.py`、`app_accounts.py`、`app_notices.py`、`app_shortcuts.py`、`app_updates.py` | 持有窗口状态、Qt 生命周期和跨模块编排 |
| 窗口与布局 | `window_layout.py`、`layouts.py`、`layout_picker.py`、`wall_layout.py`、`wall_widgets.py`、`resize_layout.py` | 几何、比例与方向；播放器归播放域 |
| 画面墙与格子 | `wall_*`、`tile_*`、`pane_danmaku.py`、`pane_source_picker.py` | 格子内容、类型与换位；播放器核心不在这里重建 |
| 侧栏与关注 | `sidebar_*`、`follow_folders.py`、`search.py`、`live_alert.py`、`watch_history.py` | 卡片、排序、文件夹与预览；账号身份归账号域 |
| 播放与流 | `player.py`、`stream_playback.py`、`playback_*`、`bili.py`、`bili_workers.py`、`hls_proxy.py`、`codec_control.py` | 取流、解码、重连与状态；原生窗口由 `video_surface.py` 约束 |
| 弹幕与 SC | `danmaku_*`、`live_danmaku*`、`video_danmaku*`、`super_chat*`、`video_super_chat.py` | 接收、过滤、排版与绘制；发送归插件 |
| 录制与回放 | `recording*.py`、`capture_control.py`、`recording_service.py` | FFmpeg 进程、片段与回放；界面状态归格子 |
| 设置 | `settings_*`、`settings_process.py`、`settings_worker.py`、`shortcut_actions.py` | 页面、独立进程与保存应用；配置默认值归 `config.py` |
| 外观与主题 | `theme.py`、`theme_*`、`skin*`、`appearance_preferences.py`、`continuous_corners.py`、`motion.py` | 令牌、材质、皮肤与动效；不接管播放器 |
| 账号与平台 | `account_*`、`oauth*`、`login.py`、`web_login.py`、`platform_login.py`、`profile_room.py` | 会话与关注读取；平台协议在插件 |
| 插件 | `plugins.py`、`plugin_*.py`、`workspace_*.py` | 契约、装载、凭据与工作区入口 |
| 更新与发布 | `app_updates.py`、`update_*.py`、`online*.py`、`release_repository.py`、`verified_download.py` | 检查、下载、校验与替换；不在主线程做阻塞 I/O |
| 通知与提示 | `notification_center.py`、`result_notice.py`、`user_notice.py`、`notice_diagnostics.py` | 通知生命周期；不持有账号内容 |
| 图像与缓存 | `images.py`、`image_cache.py`、`room_images.py`、`avatar_widgets.py`、`folder_icons.py` | 下载、缓存与裁切；界面只消费结果 |
| 画中画 | `picture_in_picture*.py`、`pip_*.py` | 复用已有播放格；不复制整套主界面 |
| 诊断与采集 | `*_diagnostics.py`、`responsiveness*.py`、`on_demand_diagnostics.py`、`diagnostic_*.py` | 轻量记录按入口启用，完整专项按需启动；有界记录，采集开销与路径变化见专项说明 |
| 数据与文件 | `config.py`、`data_paths.py`、`image_cache.py`、`file_ops.py` | 数据根、迁移与原子替换 |

## 6. 状态所有权与生命周期规则

- **单一状态来源**：房间、排列、每个格子的音量/静音/画质归 `MainWindow` 与格子对象；拆分出的控制器
  只持有自己的会话状态，不复制宿主状态。
- **Qt 父子关系**：明确 QObject 的持有者、父对象及销毁边界；控制器可引用仍有效的宿主，迟到回调不得访问已销毁对象。线程和定时器在宿主退出前停止。
- **异步回调**：取流、图片、状态轮询都可能在窗口关闭后到达；回调进入界面前检查 `_closing` 或所属对象是否仍有效。
- **播放器生命周期**：`TilePlayer` 由格子宿主创建和释放；换台、清格、布局变化时优先复用播放器核心，
  只有解码或宿主身份变化才重建。原生视频子窗口的几何由 `video_surface.py` 跟随 Qt 遮罩。
- **配置写入**：正常保存走 `config.save`；独立设置进程只回传变化字段，取消不应用。退出时保存当前状态，
  不在多个模块各自写配置文件。

## 7. 关键数据流

**播放**：`StreamPlayback` 解析房间与流地址（B 站内置，其他平台经插件）→ 取流线程返回结果 →
`MainWindow` 选择/复用 `TilePlayer` → libmpv 原生窗口嵌入格子 → `video_surface` 与浮层跟随几何 →
状态回传格子与侧栏。失败进入重试/冻结恢复；录制起始可复用已解析的流地址，画质锁定或录制重连可能重新解析来源。FFmpeg 录制使用独立连接，不共享播放器的下载连接。

**弹幕**：`DanmakuLifecycle` 按房间复用连接（B 站使用 blivedm，其他平台由插件的 `danmaku_client` 提供）→ 过滤与屏蔽 → 弹幕面板或画面弹幕渲染 →
Super Chat 单独存储与展示。发送能力由插件实现，本体只调用接口。

**录制**：`CaptureControl` 决定开始/停止、即时回放范围和画质锁定 → `RecordingManager` 启动 FFmpeg
子进程并记录会话与片段 → 完成后交给回放/插件服务。录制会话与播放器分别管理，退出时由宿主协调收尾。

**设置**：设置窗口在独立进程渲染，宿主传入配置快照；保存时只回传变化字段，宿主应用并写配置。
宿主页（外观、插件、更新）仍由主进程提供，通过原生窗口容器嵌入。环境变量 `DDM_SETTINGS_PROCESS=0`
可关闭独立进程，便于隔离排查。

**插件**：`PluginManager` 扫描 `plugins_user/<ID>/plugin.py`，注册事件、平台、格子菜单、发送和皮肤能力；
装载/卸载在 GUI 线程，普通 Python 回调异常由管理器捕获；同进程的阻塞或原生库故障不受此机制隔离。插件凭据以快照和代次传递，账号事件不携带明文密钥。

**更新**：检查（`release_repository` / `online`）→ 下载并校验 SHA-256（`verified_download`）→ 暂存 →
退出后由更新助手替换 → 失败保留原程序。插件更新与本体更新相互独立。
插件商店由 `plugin_catalog_api` 从官方仓库正式 Release ZIP 发现候选，沿用 `plugin_packages` 验证包结构并只读清单，不执行候选代码；该模块负责元数据缓存与兼容判定，不维护插件 ID 白名单。

## 8. 扩展点

| 扩展 | 入口 | 约束 |
| --- | --- | --- |
| 平台与互动插件 | `docs/plugins.md`、`plugins_user/_template_platform` | 只依赖公开宿主 API；不导入宿主内部模块 |
| 皮肤与分区美化 | `ddm/skin_parts.py`、`docs/features/skins.md` | 使用声明式外观槽；不替换宿主控件 |
| 诊断采集 | `ddm/diagnostic_session.py`、`dev/checks/` | 普通入口保留轻量日志，完整采集按需、有界、脱敏；方法与开销见[卡顿采集](../development/responsiveness-capture.md) |
| 布局与直播间组合 | `ddm/layouts.py`、`room_presets.py` | 保存结构要有版本兼容和旧配置回退 |

## 9. 修改时先看哪里

| 想改的内容 | 先读 | 首先改 |
| --- | --- | --- |
| 窗口/布局/全屏 | [窗口缩放性能](../features/resize-performance.md)、`docs/development/ui-components.md` | `window_layout.py`、`wall_layout.py` |
| 播放/取流/解码 | `docs/bug-cases.md` 中播放类案例、`stream_playback.py` 文档字符串 | `stream_playback.py`、`player.py` |
| 弹幕/SC | `docs/development/testing.md` 对应小节 | `danmaku_*` 或 `super_chat_*` |
| 设置页 | `docs/development/ui-components.md`、`settings_control.py` | `settings_*.py` |
| 录制/回放 | `docs/plugins.md` 录制服务章节 | `capture_control.py`、`recording*.py` |
| 插件接口 | `docs/plugins.md`、`plugin_types.py` | 先加能力检查，再改宿主 |
| 外观/主题 | `docs/features/appearance-design.md`、`docs/features/skins.md` | `theme.py`、`skin_*` |

## 10. 详细模块职责

画面墙边框组件与拖动会话由 `ddm/wall_border.py` 维护：`WallBorderInteraction` 以画面墙为QObject父对象，统一持有悬停、拖动、待处理位置与32ms合并定时器；预览仍是画面墙的直接Qt子控件，格子边框仍归原格子。WallGrid保留布局/比例/格子状态与旧方法及只读诊断别名，不重复保存活动拖动状态。

直播间组合的快照、保存、重命名、删除和恢复由 `ddm/room_preset_control.py` 的 `RoomPresetController` 协调；校验/比较留在 `room_presets.py`，卡片/管理交互留在 `room_presets_ui.py`。主窗口保留旧方法委托，仍是配置集合、活动组合、恢复事务标志、退役格子及播放器/录制服务的唯一状态所有者，控制器不另存副本。

更新协调由 `ddm/app_updates.py` 的 `AppUpdates` 管理：启动软件/插件检查、结果回填、已读筛选、红点及通知；在线协议、任务和页面仍在 `online`/`online_ui`。主窗口唯一持有任务、检查标志、候选版本、启动定时器和通知，任务Qt父对象及连接的旧回调不变，关闭时仍由主窗口中断和等待。旧方法保留薄委托，控制器仅引用宿主。

设置协调由 `ddm/settings_control.py` 的 `SettingsControl` 维护普通/独立设置入口、预览上下文、页面连接与保存应用流程；`settings_process`/`settings_host` 继续维护进程通信和嵌入宿主页。主窗口唯一持有配置、进程、宿主页、更新页及退出状态，旧方法保留薄委托；三个涉及对话框类型的方法由主窗口传入原 `SettingsDialog` 工厂，保留既有替换入口，协调器不反向导入主窗口。

`settings_wheel.py` 负责 Windows 跨进程嵌入边界的纵向滚轮投递：宿主端转交真实子控件，设置子进程端经 `host-wheel` 消息转交宿主，页面滚动和输入控件规则仍归 `SettingsInputFocus`。原生过滤器以对应嵌入 QWidget 为 Qt 父对象，随父对象销毁移除；隐藏区域和弹出菜单不拦截。屏幕物理坐标按嵌入窗口原生边界及当前 DPI 转为页面局部坐标。

窗口方向与布局协调由 `ddm/window_layout.py` 的 `WindowLayout` 维护排布、方向布局记忆、显式布局选择、扩容清空隐藏房间、缩容开播优先和窗口限位；主窗口保留旧委托、方向检测/事件入口，唯一持有方向与布局记忆及Qt控件。墙的布局模型、比例与边框拖动仍在原模块，原生窗口父对象不变。

设置页实现按职责由 `settings_general`、`settings_notifications`、`settings_shortcuts`、`settings_danmaku`、`settings_recording`、`settings_plugins`、`settings_appearance` 维护；`shortcut_actions` 唯一定义快捷键契约。`dialogs.py` 保留设置窗口协调与旧导出，按原顺序装入同一Qt类；旧编解码编辑工厂使用一次按需兼容导入，旧插件页工厂仍由设置窗口解析，不复制控件状态。

添加房间、关注导入及共享文件夹选择逻辑由 `ddm/room_dialogs.py` 维护，账号窗口/主窗口直接依赖该模块，旧 `ddm.dialogs` 仍导出相同类和辅助函数。设置进程从 `shortcut_actions` 读取同一份快捷键契约。

关注文件夹编辑器、智能文件夹显示副本和标题按钮由 `ddm/sidebar_folders.py` 维护；`sidebar_cards` 和 `widgets` 保留同类兼容导出，侧栏内部直接使用职责模块。显示副本沿用原卡片及同一room对象，预览定时器仍是副本的Qt子对象，模型/关注集合仍归侧栏。

播放请求与应用由 `ddm/stream_playback.py` 的 `StreamPlayback` 维护逐格启动、画质策略、取流回调、播放器接线及失败分支。窗口唯一持有播放器、解析器代次集合、录制/重试和Qt子对象；旧入口委托并传入原解析器/播放器工厂，保留既有替换契约。回调仍经窗口入口动态路由，不反向导入主窗口，不新增定时器或复制状态。

单格编码/解码设置协调由 `ddm/codec_control.py` 的 `CodecControl` 维护继承值、重取流决策、编码保留回写、实际状态和对话框接线。窗口唯一持有codec_overrides所属格子、原解析器/播放器及对话框映射，旧工厂由主窗口传入，Qt父对象和迟到结果检查保持；设置页控件、协议和解码实现不迁移。

关注文件夹协调由 `ddm/sidebar_folder_control.py` 的 `SidebarFolderControl` 维护创建/归类/默认/智能副本、标题拖动和分组条目；筛选由 `ddm/sidebar_filter.py` 的 `SidebarFilter` 维护搜索、折叠/开播过滤及可见条目。Sidebar唯一持有文件夹、归属、卡片/标题缓存、选择和拖动状态，旧方法继续委托；对话框/标题/副本的旧工厂由Sidebar传入，Qt父对象及动画参数不变，不新增计时器或复制状态。`follow_folders`继续维护纯数据规则，`sidebar_folders`继续维护控件本体。 批量展开／折叠与实际折叠判断仍归该控制器；Sidebar唯一持有临时搜索自动展开策略，普通持久化状态仍使用原文件夹collapsed字段；筛选栏按钮、管理菜单及可配置快捷键均委托同一批量入口，单次刷新和保存，不复制房间或文件夹状态。

关注栏多选由 `ddm/sidebar_selection.py` 的 `SidebarSelection` 维护批量选择、Ctrl/Shift选择、拖动分组与删除信号；顺序由 `ddm/sidebar_sort.py` 的 `SidebarSort` 维护过滤落点换算、组内换位、置顶、文件夹排序及常看缓存协调。Sidebar唯一持有选择/锚点、卡片顺序、配置和WatchHistory，旧Qt入口保留薄委托；排序菜单的QActionGroup仍归菜单，实际卡片/定时器归属不变。计分模型仍在watch_history，拖放会话仍在sidebar_drag。

关注栏账号展示/菜单协调由 `ddm/sidebar_account_control.py` 的 `SidebarAccountControl` 维护，登录/退出仍向宿主既有信号派发；原菜单/账号行工厂由Sidebar传入，延迟登录保留Sidebar的Qt上下文。横竖布局、借用控件、账号形状和收起/展开由 `ddm/sidebar_presentation.py` 的 `SidebarPresentation` 维护，Sidebar仍唯一持有所有控件/布局/状态。控件身份、父子迁移、滚动约束及收起异常收尾沿用原行为，Qt虚方法和旧入口留在Sidebar。

Sidebar卡片集合和显示同步由 `ddm/sidebar_items.py` 维护，指针命中/拖动展示由 `ddm/sidebar_interaction.py` 维护；布局选择器协调复用SidebarPresentation。Sidebar保留组装、Qt事件和旧委托，卡片/预览计时器/拖放会话仍由原Qt宿主持有。

播放格职责：`tile_widgets.py` 保留 Qt 宿主、组装与事件；`tile_state.py` 维护媒体状态/画质/音频展示，`tile_controls.py` 协调控制条交互，`tile_presentation.py` 排列浮层与原生遮罩，`tile_context_menu.py` 构建运行时菜单。状态、信号、定时器与子控件仍只由 Tile 持有。

主窗口协调：`app_accounts.py` 账号与关注导入；`app_shortcuts.py` 快捷键绑定；`fullscreen_control.py` 全屏业务；`app_notices.py` 用户通知。播放状态、房间管理、录制源刷新、弹幕消息和设置应用分别归并至原有 StreamPlayback、RoomPlacement、CaptureControl、DanmakuLifecycle、SettingsControl。MainWindow 保留组装、Qt 事件、状态快照与关闭收尾；旧方法继续薄委托，异步任务/Qt 父对象/共享映射仍归窗口。

SC 职责：`super_chat_model.py` 为无 Qt/网络依赖的数据归一化、过期和排序；`super_chat_api.py` 为 B 站快照协议/工作线程；`super_chat_presentation.py` 为布局、预览、头像和绘制；`super_chat_widgets.py` 为弹幕面板卡片，`video_super_chat.py` 为画面 SC 浮层。`super_chat.py` 保留旧导出，滚动画面弹幕继续由 VideoDanmaku 负责。

小窗职责：`pip_geometry.py` 合成几何；`pip_preview.py` 布局预览；`pip_picker.py` 房间选择；`pip_window.py` 原生浮窗及控制。`picture_in_picture.py` 保留原有播放格借用/归还与业务状态，不复制播放器；旧类名兼容导出保持身份。

在线界面职责：`online_tasks.py` 工作线程与页面关闭后的退役清理；`plugin_downloads.py` 由主窗口持有插件下载／安装任务和状态，设置关闭后继续；`download_progress.py` 采样字节和速度，`update_progress_ui.py` 在通知、更新页和插件卡片显示进度及完成反馈，`ui/progress.py` 提供主题进度条。`plugin_store_ui.py` 插件商店；`plugin_details_ui.py` 卡片内详情展开和文本自适应高度，由卡片拥有并随外层列表滚动，复用原卡片底部操作组；`plugin_card_layout.py` 按筛选后顺序将卡片分入等宽独立列，分别计算高度，展开只推动本列；`app_update_ui.py` 软件更新页；`update_notice.py` 更新提示与标记；`result_notice.py` 用户结果通知；`update_offers.py` 版本提示数据。`update_errors.py` 将在线任务异常分类为可读失败原因，`update_progress_ui.py` 在原操作行显示换行反馈；关闭更新浮层仅标已读，通知中心保留恢复同一任务的入口。`online_ui.py` 保留旧导出和已有任务/通知替换入口，退役集合只保留一份。

B 站职责：`bili.py` 统一持有 HTTP 接口、凭据和协议参数；`bili_workers.py` 持有六种 Qt 取流/查询工作线程。`room_input.py` 提取分享文本及房间／个人主页身份，`bili_profile.py` 通过无账号公开接口将 UID 查询为真实房间号；查询只在现有 `InfoResolver` 工作线程执行，不持有配置或界面状态。工作线程在调用时读取原 API 模块，未复制凭据或函数引用，旧类导出与测试替换入口保持。

画面墙职责：`wall_geometry.py` 自动列数计算；`wall_layout.py` 格子几何、预设/角点比例、边框比例应用与缩放收敛；`wall_presentation.py` 全屏/小窗/侧栏动画期间的原生呈现。WallGrid 保留容器、格子与弹幕分区接线、Qt 事件，所有比例/定时器状态仍归 WallGrid，拖边会话继续归 WallBorderInteraction。

录制职责：`recording_process.py` 为 Windows 后台进程/Job Object；`recording_output.py` 为 FFmpeg 参数与容器/路径；`recording_session.py` 为每路会话数据与分段簿记；`recording_replay.py` 为租约、回放保留和导出。RecordingManager 保留编码器/取流/子进程轮询与关闭协调；会话、租约、导出和定时器仍只有一份。

插件职责：`plugin_types.py` 为公开协议/平台数据/上下文；`plugin_manifest.py` 为目录身份和元数据验证；`plugin_packages.py` 为安装、移除和目录清单。PluginManager 继续管理装载、事件分发与注册，凭据、控件、工作区和通知仍复用既有独立模块。旧插件 API 导出和单例注册表不变。

皮肤编辑职责：`skin_controls.py` 为共享素材控件/文件名显示；`skin_part_settings.py` 为分区外观编辑与预览；`skin_settings.py` 保留全局背景/遮罩控件和旧导出。分区对话框按需构造全局控件，避免互相提前导入，皮肤素材/预览/应用继续复用原有独立模块。

弹幕呈现职责：`danmaku_format.py` 为富文本/勋章格式；`danmaku_document.py` 为文档、表情和有界历史；`danmaku_scrolling.py` 为跟随及滚动位置；面板保留 Qt 控件和事件。`video_danmaku_raster.py` 为异步光栅资源，`video_danmaku_surface.py` 为原生/Quick 表面接线；VideoDanmaku 继续负责弹幕准入、轨道与时钟，SC 画笔归 video_super_chat，旧静态入口保留。

其他边界：`image_workers.py` 为图片缓存/下载工作线程，路径和缓存代次仍由 images API 持有；`account_workers.py` 为关注账号解析线程；`live_danmaku_protocol.py` 为三站只读弹幕编解码，连接/重连仍由 LiveDanmakuClient 负责；`add_room_dialog.py` 为添加房间，`room_dialogs.py` 为关注导入，文件夹动作归 `room_folder_controls.py`；`skin_assets.py` 为素材验证/导入，`skin_background.py` 为背景表面，SkinController 仍在 skins；`settings_worker.py` 为独立设置进程界面，SettingsProcess 保留宿主 QProcess 传输和公共协议入口。

登录边界：`bili_login_worker.py`、`oauth_worker.py`、`platform_follow_worker.py` 分别持有扫码、OAuth、平台关注协议工作线程；原 login/oauth_login/platform_login 保留具体登录界面及旧工厂。`platform_profiles.py` 统一持有浏览器 profile 注册表与退出清理，原模块只是同一字典的兼容引用。

房间细分：`room_catalog.py` 管关注目录、异步添加/删除与平台启停；`room_navigation.py` 管房间输入、主页识别和浏览器入口；`watch_history_sampling.py` 将可见播放状态采样交给既有 WatchHistory。RoomPlacement 保留格子放置/互换与旧方法委托，catalog/navigation 只引用同一窗口。`room_configuration.py` 管配置中的房间整理、平台挂起恢复与启动占位数据，config 保留路径、读写、设置定义及兼容导出。

SC 展示细分：`super_chat_layout.py` 为测量/位置/画笔原语，`super_chat_animation.py` 为运行时展开/折叠期限，`super_chat_avatar.py` 为头像资源与绘制，`super_chat_preview.py` 为设置预览与位置编辑。原 super_chat_presentation 保留兼容导出，项目内部按实际职责导入，QObject/定时器父对象不变。

关注栏呈现细分：`sidebar_orientation.py` 管横竖布局与借用控件，`sidebar_collapse.py` 管收起/展开协调，`sidebar_layout_picker.py` 管布局选择器；账号形状/显隐归既有 SidebarAccountControl，焦点交互归 SidebarInteraction。SidebarPresentation 保留兼容委托及外观行同步，控件、动画、计时器、状态全部仍归 Sidebar。

响应采集细分：`responsiveness_probe.py` 为通用心跳、调用计时、进程计数和有界堆栈；`folder_motion_capture.py` 为文件夹动画证据；`theme_capture.py` 为主题及其动画证据。responsiveness 保留通用安装协调与旧导出，旧监测替换点在调用时解析；原 Probe/采样线程、上限、输出字段和隐私规则不变。

在线协议细分：`release_repository.py` 为官方仓库 HTTP/ETag/清单与产物校验；`app_release_api.py` 为本体版本及发布说明；`plugin_catalog_api.py` 从正式 Release ZIP 清单发现插件，负责兼容性和持久缓存，复用安装器验证结构而不执行插件；`verified_download.py` 为取消/大小/hash校验/有限重试下载。online 保留公开 API 导出及既有替换点，不再维护插件 ID 白名单，缓存状态仍由调用者传入。

### 诊断中心与崩溃证据

- `ddm/settings_diagnostics.py`：设置内诊断表单、采集状态及手动导出反馈。
- `ddm/diagnostic_export.py`：QProcess 导出/现场采集协调、临时请求与取消清理；复用独立工具后端。
- `ddm/native_diagnostics.py`：Qt导入前安装原生采集、组件状态与转储开关。
- `ddm/qt_lifecycle.py`：关键对象生命周期的有界记录，不持有QObject。
- `tools/native_diagnostics/capture.cpp`：原生未处理异常通知DLL和独立栈/可选转储进程；`dev/build_native_diagnostics.cmd` 构建。
- `tools/diagnostics/CommandLine.cs`：固定JSON请求的无界面入口；WinForms和设置页共用 `Collector.cs`。
- `dev/native_diagnostics_fixture.cpp`、`dev/selfcheck_native_diagnostics.py`：隔离受控崩溃、正常退出、栈与转储回归。
- `dev/selfcheck_settings_diagnostics.py`：临时安装目录中的设置页、实际导出、取消及生命周期回归。


画中画的六格视频/弹幕组合由 `ddm/pip_composition.py` 维护无状态的格位规则：读取既有辅格弹幕绑定，不持有或复制Qt控件和可变配置。控制器协调选择和宽高比，预览与墙的画中画呈现共用格位；弹幕面板、消息文档及来源继续由原PaneDanmaku/WallGrid持有。

头像绘制、圆形裁切与关注头像条集中在 `ddm/avatar_widgets.py`，不依赖主窗口、播放器或 `ddm/widgets.py`。`widgets.py` 保留原组件名的导入兼容；通知和提示组件直接引用头像模块。关注栏拖拽会话由 `ddm/sidebar_drag.py` 管理，排序、归类和播放仍使用原有业务接口。播放恢复调度集中在 `ddm/playback_recovery.py`，独立持有重连与冻结恢复状态及定时器；主窗口负责播放器操作、界面和插件事件，并保留原有内部入口的委托。房间拖入、换格和保留播放器的格子互换策略集中在 `ddm/room_placement.py`，不导入 Qt 或播放器；主窗口保留原入口委托，继续提供播放、录制和界面服务。

开播提醒在可见画面墙满员时，通过 `ddm/wall_replacement.py` 选择替换目标；选择、取消和鼠标事件属于 UI 层，实际换房复用 `ddm/room_placement.py` 的播放与录制协调。

未决问题的显式专项入口由 `ddm/diagnostic_session.py` 统一安装；通知、弹幕数值运动和原生拖放采集分别位于 `notice_diagnostics.py`、`danmaku_diagnostics.py`、`drag_diagnostics.py`，原 `dev/diagnose_*` 保留兼容入口。独立诊断工具只在点击专项启动按钮后启动主软件，生成包时仅收集白名单已有日志，不自动采集或上传。

直播状态和人数轮询的请求协调、完成回调及状态落地集中在 `ddm/room_status.py`；主窗口保留原入口，按调用时的构造器创建轮询线程，并继续持有 Qt 线程引用和关闭流程，兼容既有平台与检查替身。

房间头像、封面和横幅的加载协调及界面回填集中在 `ddm/room_images.py`；主窗口保留原入口和调用时加载器构造器，继续持有线程引用及退出等待。缓存读写与下载仍由 `ddm/images.py` 实现，图片协调器不负责账号头像和播放器。

录制开关、即时回放范围与额度、录制前画质锁定/恢复及录制计时集中在 `ddm/capture_control.py`；主窗口保留原方法入口，继续持有会话、待开始任务、画质记录和退出流程。FFmpeg 执行仍在 `ddm/recording.py`，录制源解析及通知入口保留在主窗口。

画面墙右键的格子类型、多个弹幕栏及来源绑定由 `ddm/pane_danmaku.py` 管理，关联跟随画面换位，并随布局与直播间组合保存。`ddm/pane_source_picker.py` 管理信号图标左侧的头像来源条、从右向左展开／收起、溢出滚动和缓存头像更新。

弹幕连接共享、按需订阅及连接/SC 快照线程退役集中在 `ddm/danmaku_lifecycle.py`。主窗口保留旧入口与回调、按调用时构造器创建线程，继续拥有 Qt 对象、连接状态和退出等待；消息分发、账号凭据与 SC 展示策略保持原归属。

播放状态浮标（LIVE/时长/标题/加载提示/暂停图标）集中在 `ddm/playback_badges.py`，只依赖 Qt、主题与 `BadgeSurface`，不依赖播放器、Tile、WallGrid 或 Sidebar。`PauseIndicator` 是静态透明图形，保留 Tile 原有状态驱动与鼠标穿透。`ddm/widgets.py` 兼容导出旧类名、尺寸常量与字体辅助入口；加载动画生命周期不变。

多画面画中画由 `ddm/picture_in_picture.py` 管理全局入口、选流与独立小窗，WallGrid复用原播放格及共享弹幕层。说明见 `docs/features/picture-in-picture.md`，隔离回归为 `dev/selfcheck_picture_in_picture.py`。

矩形表面的连续圆角几何集中在 `ddm/corner_geometry.py`，无 QWidget、播放器或主题依赖；`ddm/continuous_corners.py` 读取原 QSS 的底色、描边、半径及状态并绘制表面，原控件继续处理文字、输入和布局。自绘图片与原生视频遮罩复用相同路径，系统窗口外框仍由 Windows 控制。

播放控制按钮及音量弹窗集中在 `ddm/playback_controls.py`，依赖 Qt、主题、动效和默认音量，不导入播放器或 `widgets`。`DanmakuSettingsButton` 按主题颜色绘制线条齿轮，避免 emoji 字体产生彩色图案。`ddm.ui` 按需从此模块提供原有按钮，`widgets` 保留旧类及绘制辅助函数的兼容导出；播放状态、格子信号连接与弹窗管理仍由原宿主负责，刷新动画仍以按钮为父对象。

省略标签与工具条图标按钮分别在 `ddm/ui/labels.py`、`ddm/ui/toolbar.py` 维护，`ddm.ui` 按需导入；`widgets` 在原定义位置兼容导出同一类，保留原 Qt 子类加载顺序，`_repolish` 从共享辅助模块兼容导出。基础控件不依赖画面墙、播放器或主窗口，Qt 父子归属与信号行为沿用原实现。

`ddm/widgets.py` 仅保留兼容导出，项目内部直接导入职责模块。弹幕/SC展示在 `ddm/danmaku_widgets.py`，账号行在 `ddm/account_widgets.py`，关注卡片/文件夹/列表在 `ddm/sidebar_item.py`、`sidebar_thumbnail.py`、`sidebar_folders.py`、`sidebar_list.py`，开播动画在 `live_alert.py`，`sidebar_cards.py` 仅作兼容导出，侧栏协调在 `ddm/sidebar_widgets.py`，单格播放UI在 `ddm/tile_widgets.py`，画面墙与分区几何在 `ddm/wall_widgets.py`，布局选择在 `ddm/layout_picker.py`；共有常量和绘制辅助在 `ddm/widget_support.py`。旧类、常量和辅助函数仍是同一对象。布局选择与格子到画面墙的类型判断按需导入，避免模块导入循环；Qt父子关系、信号和播放器/连接/账号的状态所有权沿用原实现。

侧栏的全局功能轨和关注管理入口位于 `ddm/sidebar_navigation.py`；插件入口的搜索、固定及受限尺寸面板由 `ddm/workspace_controls.py` 管理，复用原插件动作。关注排序、分组与拖放仍由原有组件负责。

网页登录职责：`ddm/account_browser.py`只管理本应用临时浏览器与回环控制连接；`ddm/browser_account_worker.py`处理取消、身份确认和关注读取；`ddm/browser_account_dialog.py`负责交互、加密保存和会话接线。平台接口解析留在独立插件，OAuth仍由原模块负责。浏览器只在用户发起登录且保存会话不可用时启动，结束或取消后释放，不读取个人浏览器资料。

`plugin_replacements.py`负责组合包向独立平台包的声明迁移、设置继承与装载优先级；`plugin_types.PluginContext`只暴露平台是否已接管的查询。平台协议、缓存与互动请求仍属于插件，不在迁移层复制。

## 相关文档

- [架构文档索引](README.md)
- [仓库文件分类清单](../repository-map.md)
- [开发文档规范](../standards/documentation.md)
- [验证指南](../development/testing.md)
- [插件接口](../plugins.md)
