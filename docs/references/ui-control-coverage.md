# DD 监控室实装控件核对清单

> 类型：设计 ｜ 状态：草案 ｜ 适用版本：当前开发版 ｜ 更新：2026-11-20 ｜ 读者：维护者、贡献者

从 [控件图鉴](ui-control-library.html) 的顶部分组进入。总览每类一张卡，78 个实装场景可在相应详情中切换。每个场景都有源码位置、参数面板和两套主题的 Windows Qt 截图。表里的 `#control-…` 直接打开对应场景的详情。

逐项记录包含本轮对照的控件结构、绘制或交互。详情面板可固定查看悬停、按下、键盘焦点和禁用，选中、展开、静音等持续状态通过操作相应控件查看。用「重置预览」恢复默认外观。

核对以 DD 监控室本体和宿主提供的插件管理界面为边界。同一组件在多个界面复用时，选一个实际入口作代表。页头、头像、面板、滚动和绘制部件在对应组合里核对。图鉴以本地样例数据演示，参数作用于当前网页。系统窗口外壳、平台登录网页、第三方插件私有界面和实际媒体输出属于各自宿主的验收范围。

## 逐项清单

### 设置页

| 试样 | 软件入口 | 可核对的操作或表现 | 源码 | 详情标识 | 实装外观与状态核对记录 |
| --- | --- | --- | --- | --- | --- |
| 全部展开后的收起方式 | 常规 › 关注与预览 | 收起全部关注文件夹，或恢复本次全部展开前的状态。 | [settings_general.py](../../ddm/settings_general.py) | `#control-collapse` | 共同底板、两段选中块和恢复原状反馈。 |
| 关注列表刷新间隔 | 常规 › 关注与预览 | 用加减按钮或数字输入调整轮询间隔，范围为 1–30 分钟。 | [settings_general.py](../../ddm/settings_general.py) | `#control-interval` | 一体底板、数字与单位、加减控件及 1–30 分钟边界。 |
| 关注栏直播预览 | 常规 › 关注与预览 | 开启后，在关注栏的直播间上悬停会显示播放预览。 | [settings_general.py](../../ddm/settings_general.py) | `#control-preview` | 即时状态、默认 320 毫秒的弹簧滑动、滑块随速度轻微拉伸、键盘切换。 |
| 新建格子的初始音量 | 常规 › 播放与声音 | 设置新建播放格使用的默认音量。 | [settings_general.py](../../ddm/settings_general.py) | `#control-initial-volume` | 实装滑轨位置、白色滑块和独立数值列。 |
| 直播源格式 | 常规 › 编解码 | 选择直播流编码偏好，可选 H.264、HEVC 和 AV1。 | [settings_general.py](../../ddm/settings_general.py) | `#control-codec` | 三段底板、当前编码高亮、切换反馈。 |
| 本机解码方式 | 常规 › 编解码 | 选择本机处理视频的方式，自动解码会优先使用可用的硬件。 | [settings_general.py](../../ddm/settings_general.py) | `#control-decoder` | 闭合边框、箭头、圆角下拉、悬停及当前项、键盘确认和取消。 |
| 界面主题 | 外观 › 主题 | 切换深色、浅色或跟随系统，此处会同步改变图鉴的预览主题。 | [settings_appearance.py](../../ddm/settings_appearance.py) | `#control-theme` | 深色、浅色与跟随系统共用底板和选中块。 |
| 主题色 | 外观 › 主题 | 在默认主题色与预设颜色间切换，详情可直接调任意强调色。 | [settings_appearance.py](../../ddm/settings_appearance.py) | `#control-palette` | 默认按钮、实装色点、选中色标和悬停反馈。 |

### 播放格

| 试样 | 软件入口 | 可核对的操作或表现 | 源码 | 详情标识 | 实装外观与状态核对记录 |
| --- | --- | --- | --- | --- | --- |
| 暂停／继续 | 底部信息条 | 切换当前播放格的暂停状态，再点一次继续。 | [tile_widgets.py](../../ddm/tile_widgets.py) | `#control-pause` | 暂停双竖线、继续三角形、底栏悬停反色。 |
| 格子音量 | 底部信息条 · 宽格子 | 点击扬声器静音或取消静音，也可以拖动滑块独立调整音量。 | [tile_widgets.py](../../ddm/tile_widgets.py) | `#control-volume` | 扬声器及声道图标、静音与拖动恢复、数值和滑轨。 |
| 画面弹幕／观看设置 | 底部信息条 | 左侧开关控制画面弹幕，齿轮打开弹幕观看设置。 | [tile_widgets.py](../../ddm/tile_widgets.py) | `#control-danmaku` | 弹字勾选、独立齿轮、五个滑块及两项复选。 |
| 录制 | 底部信息条 | 在开始和停止录制之间切换，浏览器样例会显示当前状态。 | [tile_widgets.py](../../ddm/tile_widgets.py) | `#control-record` | 空闲实拍标识和红色录制状态，停止后回到空闲。 |
| 全屏 | 底部信息条 | 切换进入与退出全屏的按钮状态。 | [tile_widgets.py](../../ddm/tile_widgets.py) | `#control-fullscreen` | 底栏小图标、悬停和进入／退出反馈。 |
| 画质 | 悬停时 · 右上角 | 选择单路直播的画质。直播中的可选档位由平台提供。 | [tile_widgets.py](../../ddm/tile_widgets.py) | `#control-quality` | 右上角胶囊及画质菜单的勾选、键盘和悬停。 |
| 重新连接 | 悬停时 · 右上角 | 重新连接这一路，试用区会依次呈现连接中与已连接。 | [tile_widgets.py](../../ddm/tile_widgets.py) | `#control-reconnect` | 弧形双箭头、进行中高亮及临时禁用。 |
| 关闭这一路 | 悬停时 · 右上角 | 关闭当前播放格。试用区可再次点击恢复样例。 | [tile_widgets.py](../../ddm/tile_widgets.py) | `#control-close` | 右上角小圆按钮及关闭后的网页恢复入口。 |

### 设置与工具

| 试样 | 软件入口 | 可核对的操作或表现 | 源码 | 详情标识 | 实装外观与状态核对记录 |
| --- | --- | --- | --- | --- | --- |
| 刷新统计 | 数据与存储 › 图片缓存 | 重新统计缓存用量。这里返回模拟结果。 | [cache_settings.py](../../ddm/cache_settings.py) | `#control-cache-action` | 圆头刷新按钮、统计中禁用和完成提示。 |
| 下载进度 | 软件更新 › 下载 | 拖动示例控制条可查看进度条在不同数值下的绘制。 | [update_progress_ui.py](../../ddm/update_progress_ui.py) | `#control-update-progress` | 圆角进度填充，网页滑杆用于改变演示数值。 |
| 插件详情展开条 | 插件 › 插件商店 | 展开插件卡片的说明和作者信息。 | [plugin_store_ui.py](../../ddm/plugin_store_ui.py) | `#control-plugin-disclosure` | 详情条右箭头、展开方向和内容区。 |
| 弹幕字体 | 弹幕 › 弹幕字体与记录 | 输入字体名称后选择。试样使用几种 Windows 本地字体。 | [settings_danmaku.py](../../ddm/settings_danmaku.py) | `#control-danmaku-font` | 字体下拉、搜索区域、当前项和选取反馈。 |
| 弹幕颜色 | 播放格 › 弹幕观看设置 | 在 RGB 滑块、数值和 HEX 之间同步，确认后应用。 | [ui/color_dialog.py](../../ddm/ui/color_dialog.py) | `#control-danmaku-color` | 色样和色值、RGB／HEX 联动、确认与取消。 |
| 弹幕缩放曲线 | 弹幕 › 画面弹幕缩放 | 拖动节点调整比例。720 px 对应 100%，保持固定。 | [ui/scale_curve.py](../../ddm/ui/scale_curve.py) | `#control-scale-curve` | 坐标网格、固定基准点、节点拖动和重置。 |
| 插件页签 | 插件 › 已安装／插件商店 | 在已安装与插件商店之间切换。 | [settings_plugins.py](../../ddm/settings_plugins.py) | `#control-plugin-tabs` | 分开的圆头页签和当前页签轮廓。 |
| 设置分类与页头 | 设置 › 左侧分类 | 切换分类，查看页面标题、说明和分组面板。 | [settings_navigation.py](../../ddm/settings_navigation.py) | `#control-settings-nav` | 搜索框、分类导航、页头及内容卡片层级。 |

### 关注与导航

| 试样 | 软件入口 | 可核对的操作或表现 | 源码 | 详情标识 | 实装外观与状态核对记录 |
| --- | --- | --- | --- | --- | --- |
| 收起／展开关注栏 | 关注栏 › 顶部 | 横屏下点击在「«」和「»」之间切换。 | [sidebar_widgets.py](../../ddm/sidebar_widgets.py) | `#control-sidebar-toggle` | 透明底和箭头轮换，接受键盘焦点。 |
| 关注直播筛选 | 关注栏 › 全部／直播中 | 切换全部直播间与直播中的关注项。 | [sidebar_navigation.py](../../ddm/sidebar_navigation.py) | `#control-sidebar-filter` | 实装图标结构、粉色直播点和选择底色。 |
| 多选管理按钮 | 竖屏关注栏 › 工具栏 | 在横栏中开始或结束多选管理。 | [sidebar_widgets.py](../../ddm/sidebar_widgets.py) | `#control-sidebar-multi` | 叠层勾选图标和进入／退出多选反馈。 |
| 关注头像条 | 竖屏关注栏 › 收起后的头像条 | 点头像选择示例直播间。粉点表示直播中，圆弧表示置顶。 | [avatar_widgets.py](../../ddm/avatar_widgets.py) | `#control-avatar-strip` | 圆头像、直播点、置顶弧和选择操作。 |
| 关注管理菜单 | 关注栏 › 关注管理 | 打开多选、刷新、展开收起和分组排序选项。 | [sidebar_navigation.py](../../ddm/sidebar_navigation.py) | `#control-sidebar-menu` | 菜单行、分组、子菜单和选择反馈。 |
| 长标题省略 | 插件商店 › 插件名称 | 悬停查看完整标题，调整预览宽度可观察省略。 | [plugin_store_ui.py](../../ddm/plugin_store_ui.py) | `#control-elided-title` | 单行截断、完整标题提示及宽度影响。 |

### 添加与关注

| 试样 | 软件入口 | 可核对的操作或表现 | 源码 | 详情标识 | 实装外观与状态核对记录 |
| --- | --- | --- | --- | --- | --- |
| 关注搜索框 | 关注栏 › 搜索主播／房间号 | 输入中文、拼音或房间号，查看结果与空态。 | [room_add_followed.py](../../ddm/room_add_followed.py) | `#control-room-search` | 搜索框、占位文字、有输入时显示的命中和空态。 |
| 批量添加直播间 | 关注栏 › 添加与导入 | 每行一个房间号或直播间链接。选择文件夹后试用数量与错误反馈。 | [room_add_panel.py](../../ddm/room_add_panel.py) | `#control-room-add` | 行内带描边面板、关闭与导入按钮、文件夹和计数主按钮。 |
| 关注直播间选择器 | 添加直播间 › 从关注列表选择 | 搜索关注项、筛选直播中并选择一项。 | [room_add_followed.py](../../ddm/room_add_followed.py) | `#control-room-picker` | 搜索与直播中复选并列、文件夹标题、两列头像卡片。 |
| 导入关注列表 | 添加与导入 › 导入关注 | 核对复选、已关注禁用和导入数量。 | [follow_import_ui.py](../../ddm/follow_import_ui.py) | `#control-follow-import` | 头像、状态副标题、右侧勾选和已关注禁用。 |
| 关注卡片多选 | 关注列表 › 多选管理 | 选择卡片，查看主播标题和开播状态。在详情拖动把手试用排序。 | [sidebar_item.py](../../ddm/sidebar_item.py) | `#control-follow-card` | 卡片层级、选择标记、直播牌，以及快速改向时的弹簧让位。 |
| 关注文件夹标题 | 关注列表 › 文件夹 | 展开或收起文件夹，也可进入行内重命名。 | [sidebar_folders.py](../../ddm/sidebar_folders.py) | `#control-folder-head` | 圆头文件夹标题、文件夹图标、展开和行内改名。 |
| 文件夹名称与图标 | 关注列表 › 新建／编辑文件夹 | 填写名称、选择颜色，确认后立即显示。 | [folder_icons.py](../../ddm/folder_icons.py) | `#control-folder-edit` | 当前图标、内置图标网格、色点、保存和恢复操作。 |
| 功能中心 | 侧栏 › 功能中心 | 搜索功能、切换固定状态，或打开插件管理入口。 | [workspace_controls.py](../../ddm/workspace_controls.py) | `#control-function-hub` | 搜索浮层、结果数量、条目与固定图标。 |
| 账号行与账号菜单 | 关注栏底部 › 账号 | 打开账号操作菜单。示例使用虚构账号。 | [account_widgets.py](../../ddm/account_widgets.py) | `#control-account-menu` | 头像、账号名、ID、平台标识及账号菜单。 |
| 智能分组规则 | 关注管理 › 新建智能文件夹 | 组合来源文件夹、开播状态、平台条件和排序。 | [sidebar_folders.py](../../ddm/sidebar_folders.py) | `#control-smart-folder` | 名称、来源多选、显示规则、开播、排序和平台复选。 |
| 登录平台选择 | 关注栏 › 登录 | 切换宿主平台按钮，核对选择反馈。 | [account_dialog.py](../../ddm/account_dialog.py) | `#control-account-platform` | 实装平台图标、圆头按钮、已选平台。 |

### 画面墙与播放

| 试样 | 软件入口 | 可核对的操作或表现 | 源码 | 详情标识 | 实装外观与状态核对记录 |
| --- | --- | --- | --- | --- | --- |
| 画面墙布局预设 | 画面墙 › 布局预设 | 选择布局卡片，比较格子排列和选中态。 | [layout_picker.py](../../ddm/layout_picker.py) | `#control-layout-picker` | 标题与当前方案、三类页签、布局缩略格和默认比例。 |
| 保存直播间组合 | 布局预设 › 我的组合 | 输入组合名并试用保存、取消及反馈。 | [room_presets_ui.py](../../ddm/room_presets_ui.py) | `#control-room-preset` | 行内命名表单、键盘确认／取消及保存反馈。 |
| 移除画面选择 | 画面墙 › 清空画面墙 | 选择未开播或全部直播，移除后可撤回。 | [wall_removal.py](../../ddm/wall_removal.py) | `#control-wall-remove` | 带当前布局的面板、选择范围、数量、移除及撤回。 |
| 画面墙全局设置 | 画面墙 › 全局设置 | 调整全局音量、画质、画面弹幕和弹幕浮窗。 | [wall_quick_settings.py](../../ddm/wall_quick_settings.py) | `#control-wall-quick` | 统一底板和四行参数，滑块与画质、弹幕开关联动。 |
| 画中画组合预览 | 画中画 › 选择画面组合 | 调整列数、选择主画面，或拖到高亮位置换位。 | [pip_preview.py](../../ddm/pip_preview.py) | `#control-pip-composer` | 组合格子、主画面状态、落点高亮、可中断的弹簧吸附。 |
| 画中画工具栏 | 画中画 › 悬停工具栏 | 检查组合、调整位置、置顶、返回和关闭的反馈。 | [pip_window.py](../../ddm/pip_window.py) | `#control-pip-tools` | 实装五个圆形工具位和置顶／位置切换。 |
| 画中画单路音量 | 画中画 › 多路音量 | 查看主播名，切换静音并调整音量。 | [picture_in_picture_audio.py](../../ddm/picture_in_picture_audio.py) | `#control-pip-audio` | 主播头像、声道图标、静音、滑块及百分比。 |
| 窄格音量浮层 | 播放格 › 窄幅底栏 | 悬停或点击扬声器，试用竖向滑块。 | [playback_controls.py](../../ddm/playback_controls.py) | `#control-volume-popup` | 窄格按钮、悬停弹层和纵向滑块。 |
| 连接与播放状态 | 播放格 › 画面叠层 | 切换连接、缓冲、播放与暂停，查看状态提示。 | [playback_badges.py](../../ddm/playback_badges.py) | `#control-stream-state` | 紧凑状态胶囊和连接、缓冲、失败等文字。 |
| 直播流信息 | 播放格 › 右键菜单 | 打开弹窗，选择或复制示例编解码信息。 | [stream_info.py](../../ddm/stream_info.py) | `#control-stream-info` | 实装信息字段、两列排版和关窗动作。 |
| 字幕浮动工具栏 | 播放格 › 字幕位置工具 | 切换字幕内容、增减字号、复位和锁定。 | [caption_toolbar.py](../../ddm/caption_toolbar.py) | `#control-caption-tools` | 紧凑工具条及字幕、字号、复位和锁定动作。 |
| 弹幕格消息与工具 | 画面墙 › 弹幕格 | 切换跟随、返回底部、调字号和输入示例。 | [danmaku_widgets.py](../../ddm/danmaku_widgets.py) | `#control-danmaku-panel` | 消息面板、粉点标题、字号滑块和跟随操作。 |
| 醒目留言卡片 | 弹幕格 › 醒目留言 | 展开或收起内容，关闭后可恢复示例。 | [super_chat_widgets.py](../../ddm/super_chat_widgets.py) | `#control-super-chat` | 浅色头部、价格、深蓝正文、折叠关闭和示例恢复。 |
| 弹幕来源选择 | 弹幕格 › 关联画面 | 展开头像列表，切换关联的画面。 | [pane_source_picker.py](../../ddm/pane_source_picker.py) | `#control-danmaku-source` | 弹幕栏、来源头像与已选来源反馈。 |
| 单条弹幕工具条 | 弹幕消息 › 右键 | 查看复制、复读和屏蔽动作，试样使用本地文本。 | [danmaku_actions.py](../../ddm/danmaku_actions.py) | `#control-comment-actions` | 消息右键浮层、横排动作和取消。 |
| 弹幕浮窗与收回 | 弹幕格 › 浮动窗口 | 浮出弹幕面板，再用占位按钮收回。 | [danmaku_float_window.py](../../ddm/danmaku_float_window.py) | `#control-danmaku-float` | 浮窗面板和收回入口，系统级拖拽保留原生验收。 |
| 字幕位置与大小 | 字幕工具 › 宿主位置预览 | 拖动或用方向键移动字幕，调整大小，双击复位。 | [caption_preview.py](../../ddm/caption_preview.py) | `#control-caption-placement` | 双语字幕、虚线区域、拖动与键盘移动、双击复位。 |

### 系统与设置

| 试样 | 软件入口 | 可核对的操作或表现 | 源码 | 详情标识 | 实装外观与状态核对记录 |
| --- | --- | --- | --- | --- | --- |
| 快捷键录入 | 设置 › 快捷键 | 聚焦录入框，按组合键，再试禁用与恢复默认。 | [settings_shortcuts.py](../../ddm/settings_shortcuts.py) | `#control-shortcut-edit` | 键序列输入、清除图标、启用和恢复。 |
| 设置窗口标题栏 | 设置 › 窗口顶部 | 核对标题与关闭按钮，点击可恢复示例。 | [settings_window.py](../../ddm/settings_window.py) | `#control-settings-caption` | 设置标题、靠右圆形关闭键和页面恢复入口。 |
| 关窗去向选择 | 主窗口 › 关闭 | 选择隐藏到托盘或退出，并试用记住选择。 | [system_tray.py](../../ddm/system_tray.py) | `#control-close-choice` | 说明段、底部记住复选、托盘主按钮、退出次按钮。 |
| 缓存分类环图 | 数据与存储 › 图片缓存 | 点击分类环图或复选框，再试模拟清理。 | [cache_settings.py](../../ddm/cache_settings.py) | `#control-cache-pie` | 环图颜色、中心总量、扇区选中变暗及复选交互。 |
| 本地背景图库 | 外观 › 背景素材 | 选中默认背景或导入本地预览。图片只用于当前网页。 | [skin_gallery.py](../../ddm/skin_gallery.py) | `#control-skin-library` | 默认背景卡、导入卡、选中边框和本地素材预览。 |
| 屏蔽用户列表 | 弹幕 › 屏蔽用户 | 添加数字 UID，选择一项再移除。 | [settings_danmaku_blocking.py](../../ddm/settings_danmaku_blocking.py) | `#control-blocked-users` | 列表位置、平台选择、UID 输入及添加／移除。 |
| 音量均衡响应图 | 常规 › 音量均衡 | 修改响应参数，观察示例曲线。 | [audio_normalization_ui.py](../../ddm/audio_normalization_ui.py) | `#control-audio-response` | 实装图表的网格、增益刻度及三枚可调节点。 |
| 右键菜单顺序 | 常规 › 播放格菜单 | 拖动条目或用按钮调整顺序，切换是否显示。 | [tile_menu.py](../../ddm/tile_menu.py) | `#control-menu-order` | 拖动手柄、开关、行拖放和键盘重排。 |
| 通知中心与未读 | 侧栏 › 通知 | 打开通知、标记已读或清空示例记录。 | [notification_center.py](../../ddm/notification_center.py) | `#control-notices` | 通知标题和计数、已读标记、通知条和清空反馈。 |
| 版本更新提示 | 画面墙 › 更新提醒 | 试用查看更新、关闭和恢复提醒。 | [update_notice.py](../../ddm/update_notice.py) | `#control-update-notice` | 项目图标、标题及说明、右上关闭与主操作。 |
| 托盘布局示意 | 托盘菜单 › 布局预览 | 点击布局示意查看恢复窗口的反馈。 | [tray_preview.py](../../ddm/tray_preview.py) | `#control-tray-layout` | 两类颜色块和图例，点击后展示恢复反馈。 |
| 录制保存目录 | 设置 › 录制 | 编辑路径，或用浏览入口切换示例目录。 | [settings_recording.py](../../ddm/settings_recording.py) | `#control-record-path` | 路径与浏览入口同行，网页试用示例路径。 |
| 诊断图片与导出 | 设置 › 诊断与反馈 | 添加或移除示例附件，试用导出反馈。 | [settings_diagnostics.py](../../ddm/settings_diagnostics.py) | `#control-diagnostic-form` | 附件列表、添加／移除和导出反馈。 |
| 删除插件确认 | 设置 › 已安装插件 | 检查确认与取消的焦点、颜色和反馈。 | [settings_plugins.py](../../ddm/settings_plugins.py) | `#control-plugin-remove` | 标题与重启提示、取消默认焦点和删除主按钮。 |
| 主题自定义值 | 外观 › 主题 | 试填 HEX 色值，切换字体与字号。 | [settings_theme_editor.py](../../ddm/settings_theme_editor.py) | `#control-theme-editor` | 实装色点、HEX、自定义字体和字号，保留预览反馈。 |
| 界面分区预览 | 外观 › 界面美化 | 切换场景，选中分区并改变底色。 | [skin_preview.py](../../ddm/skin_preview.py) | `#control-skin-parts` | 完整界面缩略图、分区轮廓、场景、当前区域和区域着色。 |
| 开播通知模糊预览 | 通知 › 开播提醒 | 开关封面，调整模糊程度。 | [settings_notifications.py](../../ddm/settings_notifications.py) | `#control-notice-blur` | 封面图层、提示文字、封面开关与模糊变化。 |
| 主播独立设置卡 | 主播设置 › 主播卡片 | 切换整组与单个主播，展开后试调画质和音量。 | [settings_streamer_profiles.py](../../ddm/settings_streamer_profiles.py) | `#control-streamer-profile` | 叠放头像、展开箭头、三项摘要、组及单人设置。 |
| 首次启动须知 | 首次启动 › 用户须知 | 滚动阅读示例，确认后查看反馈。 | [user_notice.py](../../ddm/user_notice.py) | `#control-startup-notice` | 须知正文、内部滚动和右下确认按钮。 |
| 视觉效果与设置布局 | 外观 › 视觉效果 | 试用毛玻璃底色、阴影、分段滑动和单／双列布局。 | [settings_material_editor.py](../../ddm/settings_material_editor.py) | `#control-settings-material` | 设置卡片、参数可见条件、列数和指示器动效。 |

## 复用与运行边界

| 范围 | 对照方式 |
| --- | --- |
| 公共 `ddm.ui` 入口 | 设置分类样例包含页头、标题、说明、切页和分组表面。关注头像条包含头像、圆裁和置顶标记。分段、开关、步进、字号和进度各用实际入口作代表。独立的 `step_button` 保留在公开兼容目录。 |
| 快捷键、筛选、列表 | 常用单行、长文、数值、搜索、多选、只读和禁用分别由快捷键、设置、添加直播间、导入关注、屏蔽名单与诊断附件样例覆盖。搜索使用少量本地中英文与拼音样例。 |
| 自绘图形 | 缓存环图、音量均衡和弹幕缩放曲线、托盘和画中画的布局图、直播状态、醒目留言以及通知在相应区域核对。拖动换格、动态视频、透明合成和系统托盘的实际组合仍由原生场景验收。 |
| 对话框与菜单 | 文件夹、画质、弹幕、关注菜单、选色、账号、关闭窗口、直播流信息和删除确认分别有试样。账号资料使用示例，目录和删除操作在网页里模拟。 |
| 全屏栏、拖放与浮窗 | 全屏沿用播放格的操作与图标。原生视频层上的全屏命中、跨格拖放预览、独立窗口的位置和缩放，需要在实装环境中验收。网页可试局部拖动、画面选择和浮窗收回。 |
| 实装截图 | 使用当前 Windows Qt 控件类，以临时数据和本地资源渲染。复杂页面展示可辨识的代表区域，例如录制目录行和诊断附件区。三份图像按深／浅两列组织。 |

## 验证入口

- [首批 Qt 对照](ui-control-library-qt.png)、[设置与导航 Qt 对照](ui-control-library-qt-extra.png)、[本体专用组合 Qt 对照](ui-control-library-qt-application.png)。
- 当前源码重新取样了 78 项 Windows Qt 深浅色默认外观。可进入相应状态的代表控件另取了悬停、焦点、按下、选中和禁用样张。连接标牌等展示结果的部件按其实际反馈核对。
- 本机和离线页面均用 Chromium 核对 78 项与两套主题。检查覆盖总览操作、详情状态、参数调整及重置、桌面和 390 px 窄屏。组合中的持久状态按对应入口试用。
- 网页复现了控件的结构和反馈，复用了项目的图标素材和颜色规范。系统窗口、原生视频、DPI、Qt 连续圆角与 Windows 实时合成仍需在软件中验收。
