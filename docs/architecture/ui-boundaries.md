# 界面组件与宿主边界

> 类型：架构 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-15 ｜ 读者：贡献者、维护者

本页说明共用控件和业务界面的职责、状态归属及兼容边界。选用控件与调用示例见[共用界面组件](../development/ui-components.md)；其他领域的详细职责见[架构总览](overview.md#10-详细模块职责)。

## 共用入口与业务宿主

`ddm.ui` 按需导出同一个已存在的类或函数对象，不复制控件实现；基础控件仍在 `ddm/ui/`，头像、播放按钮及通用动效仍由各自维护模块实现。公共入口不持有播放器、账号、设置值或窗口状态。业务界面按实际需要导入具体职责模块，旧调用方继续使用兼容导出。

| 职责 | 维护模块 | 状态归属 |
| --- | --- | --- |
| 弹幕面板、文档、阅读位置与 SC 卡片 | `danmaku_widgets`、`danmaku_document`、`danmaku_scrolling`、`super_chat_widgets` | 面板持有消息、图片加载器和 Qt 子控件；连接与快照由宿主协调 |
| 账号行与菜单绘制 | `account_widgets` | 登录、账号存储和刷新线程仍归账号业务 |
| 关注卡片、缩略图、文件夹与列表 | `sidebar_item`、`sidebar_thumbnail`、`sidebar_folders`、`sidebar_list` | 卡片、预览播放器和动画仍归原对象；Sidebar 管理集合、排序和拖动会话 |
| 单格视频、浮层与播放控制 | `tile_widgets`、`playback_controls` | Tile 持有控件、信号与定时器；播放器和取流生命周期由原宿主协调 |
| 画面墙、分区与边框拖动 | `wall_widgets`、`wall_border` | WallGrid 持有布局与比例；WallBorderInteraction 持有一次拖边会话和合并定时器 |
| 设置页控件与外壳 | `settings_*`、`settings_window`、`settings_host` | 页面持有草稿控件，主窗口持有配置与应用状态；宿主和工作进程沿用原 HWND／Qt 父子关系 |
| 布局选择器与共享绘制辅助 | `layout_picker`、`widget_support` | 只提供选择信号或绘制辅助，不接管窗口和播放器状态 |

## 状态与兼容规则

- MainWindow 唯一持有播放器与解析器映射、任务代次、设置、录制和关停状态；Sidebar、Tile、WallGrid 继续持有各自 Qt 子控件和定时器。协调器引用宿主，不保存第二套可变状态。
- 浮动小窗借用原播放格，退出时按原路径归还。画面墙拖边预览不改变视频格几何，松手才应用最终比例；预览和计时器随原 Qt 父对象清理。
- `widgets`、`sidebar_cards`、`dialogs`、`online_ui`、`super_chat` 等旧出口保留类身份与实际调用方需要的工厂替换点。Qt 回调签名、父对象、继承关系、懒加载和关闭顺序在结构拆分时保持。
- `theme` 管颜色与字体令牌；`motion` 管通用动效及系统动画开关。业务按钮的图形、动画和状态一起复用，尚未拆成通用图标资源。
- 结构拆分本身不表示性能改善；实际流畅度要结合真实软件中的操作和对应采集证据判断。

## 设置界面的职责

设置页由各 `settings_*` 模块维护控件和草稿；`settings_layout`、`settings_navigation` 负责排列与分类入口，`settings_material`、`SettingsSurface` 和主题令牌负责共用表面。`SettingsControl` 处理打开、保存应用和关闭协调，`settings_autosave` 持有单个自动保存定时器及在途增量；确认基线在成功回执后更新。独立设置进程通过 `settings_host` 和既有协议与主窗口同步，不复制配置所有权。

`ToggleSwitch`、`SegmentedControl`、`StepperControl` 和 `SelectControl` 的 Qt 值仍是唯一状态来源。键盘、程序设值、快速反向和系统关闭动画时的处理留在控件自身；页面只提供业务字段和保存接线。画面墙、弹幕、皮肤与插件页面分别持有自己的交互数据，不能为统一外观而迁入基础控件库。

## 维护与追溯

新增组件前先检查[组件目录](../development/ui-components.md#组件目录)和现有主题、动效实现；新增的公开入口同步目录、职责和对应专项检查。较长宿主模块的保留依据、六处后续职责细分、设置材质和拖动等详细实施过程见[历史组件记录](../archive/ui-components-202611.md)。当前领域模块的逐项归属以[架构总览](overview.md#10-详细模块职责)为准。
