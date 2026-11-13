# 架构总览

> 类型：架构 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-14 ｜ 读者：贡献者、维护者

本页说明软件本体如何组成：有哪些进程、代码分几层、状态由谁持有、一次播放或一次设置保存经过哪些模块。
文件级清单见[仓库文件分类清单](../repository-map.md)，单条功能的交互细节见对应设计文档。

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

## 2. 进程与运行形态

| 进程 | 启动方式 | 职责 | 退出 |
| --- | --- | --- | --- |
| 主界面进程 | `run.cmd` → `pythonw main.py`，或打包后的 `DD监控室CE.exe` | Qt 主窗口、播放器、弹幕、录制、插件、更新 | 关闭窗口或托盘退出 |
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

- 职责模块不导入 `ddm/app.py`、`ddm/dialogs.py`、`ddm/widgets.py`；需要宿主能力时通过构造参数、
  回调或 signal 传入，避免反向依赖和导入循环。
- 基础控件不依赖画面墙、播放器或主窗口；主题令牌集中在 `ddm/theme.py`，不在页面里另建配色表。
- `ddm/widgets.py` 只保留兼容导出，项目内部直接导入职责模块；兼容导出必须指向同一对象，不复制类。
- 新代码按功能职责分块；聚合入口（`app.py`、`widgets.py`）只做协调和兼容，不继续堆实现。

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
| 诊断与采集 | `*_diagnostics.py`、`responsiveness*.py`、`on_demand_diagnostics.py`、`diagnostic_*.py` | 默认关闭、按需采集、有界记录；不改变播放行为 |
| 数据与文件 | `config.py`、`data_paths.py`、`image_cache.py`、`file_ops.py` | 数据根、迁移与原子替换 |

## 6. 状态所有权与生命周期规则

- **单一状态来源**：房间、排列、每个格子的音量/静音/画质归 `MainWindow` 与格子对象；拆分出的控制器
  只持有自己的会话状态，不复制宿主状态。
- **Qt 父子关系**：谁创建谁持有；跨模块传递的 QObject 不长期保存引用，线程和定时器在宿主退出前停止。
- **异步回调**：取流、图片、状态轮询都可能在窗口关闭后到达；回调进入界面前检查 `_closing` 或所属对象是否仍有效。
- **播放器生命周期**：`TilePlayer` 由格子宿主创建和释放；换台、清格、布局变化时优先复用播放器核心，
  只有解码或宿主身份变化才重建。原生视频子窗口的几何由 `video_surface.py` 跟随 Qt 遮罩。
- **配置写入**：正常保存走 `config.save`；独立设置进程只回传变化字段，取消不应用。退出时保存当前状态，
  不在多个模块各自写配置文件。

## 7. 关键数据流

**播放**：`StreamPlayback` 解析房间与流地址（B 站内置，其他平台经插件）→ 取流线程返回结果 →
`MainWindow` 选择/复用 `TilePlayer` → libmpv 原生窗口嵌入格子 → `video_surface` 与浮层跟随几何 →
状态回传格子与侧栏。失败进入重试/冻结恢复，录制使用同一流地址，不二次取流。

**弹幕**：`DanmakuLifecycle` 按房间复用连接（blivedm 协议）→ 过滤与屏蔽 → 弹幕面板或画面弹幕渲染 →
Super Chat 单独存储与展示。发送能力由插件实现，本体只调用接口。

**录制**：`CaptureControl` 决定开始/停止、即时回放范围和画质锁定 → `RecordingManager` 启动 FFmpeg
子进程并记录会话与片段 → 完成后交给回放/插件服务。录制失败不能阻塞播放与退出。

**设置**：设置窗口在独立进程渲染，宿主传入配置快照；保存时只回传变化字段，宿主应用并写配置。
宿主页（外观、插件、更新）仍由主进程提供，通过原生窗口容器嵌入。环境变量 `DDM_SETTINGS_PROCESS=0`
可关闭独立进程，便于隔离排查。

**插件**：`PluginManager` 扫描 `plugins_user/<ID>/plugin.py`，注册事件、平台、格子菜单、发送和皮肤能力；
装载/卸载在 GUI 线程，异常被隔离在插件边界内。插件凭据以快照和代次传递，事件不携带明文密钥。

**更新**：检查（`release_repository` / `online`）→ 下载并校验 SHA-256（`verified_download`）→ 暂存 →
退出后由更新助手替换 → 失败保留原程序。插件更新与本体更新相互独立。

## 8. 扩展点

| 扩展 | 入口 | 约束 |
| --- | --- | --- |
| 平台与互动插件 | `docs/plugins.md`、`plugins_user/_template_platform` | 只依赖公开宿主 API；不导入宿主内部模块 |
| 皮肤与分区美化 | `ddm/skin_parts.py`、`docs/skins.md` | 使用声明式外观槽；不替换宿主控件 |
| 诊断采集 | `ddm/diagnostic_session.py`、`dev/checks/` | 默认关闭、有界、脱敏，不改变正常路径 |
| 布局与直播间组合 | `ddm/layouts.py`、`room_presets.py` | 保存结构要有版本兼容和旧配置回退 |

## 9. 修改时先看哪里

| 想改的内容 | 先读 | 首先改 |
| --- | --- | --- |
| 窗口/布局/全屏 | [窗口缩放性能](../resize-performance.md)、`docs/development/ui-components.md` | `window_layout.py`、`wall_layout.py` |
| 播放/取流/解码 | `docs/bug-cases.md` 中播放类案例、`stream_playback.py` 文档字符串 | `stream_playback.py`、`player.py` |
| 弹幕/SC | `docs/development/testing.md` 对应小节 | `danmaku_*` 或 `super_chat_*` |
| 设置页 | `docs/development/ui-components.md`、`settings_control.py` | `settings_*.py` |
| 录制/回放 | `docs/plugins.md` 录制服务章节 | `capture_control.py`、`recording*.py` |
| 插件接口 | `docs/plugins.md`、`plugin_types.py` | 先加能力检查，再改宿主 |
| 外观/主题 | `docs/appearance-design.md`、`docs/skins.md` | `theme.py`、`skin_*` |

## 相关文档

- [架构文档索引](README.md)
- [仓库文件分类清单](../repository-map.md)
- [开发文档规范](../standards/documentation.md)
- [验证指南](../development/testing.md)
- [插件接口](../plugins.md)
