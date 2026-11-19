# 共用界面组件

> 类型：指南 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-15 ｜ 读者：贡献者

## 本页导航

软件界面需要控件时，先从 `ddm.ui` 的[组件目录](#组件目录)选用，再考虑 Qt 原生控件或补充缺项；图标与动效先看[现有复用入口](#图标与动效复用入口)。接入方式见[调用示例](#调用示例)，业务组件的状态归属见[界面组件与宿主边界](../architecture/ui-boundaries.md)。颜色、字号、圆角和间距由 `ddm.theme` 管理，不在页面里另建样式常量。

## 搜索框统一约定

本体及独立插件所有用于查找列表、目录或选项的搜索框，都必须支持中文原文、英文、数字ID、拼音全拼及首字母；新建或修改搜索功能时同时补回归。弹幕发送、昵称/ID填写和URL输入属于内容录入，不应改变其值或做拼音转换。

复用 `ddm.search.matches_query(text, query)`：忽略大小写，多个以空白分隔的词按AND匹配，空查询显示全部；每个词沿用 `matches_text` 的原文、全拼和首字母匹配。只拼接原功能已经检索的字段，不扩大到账号私有数据，不改变类别/直播/日期筛选、排序或勾选状态。拼音缓存和固定依赖由宿主统一维护，不在各页面复制实现或联网下载词库。已有支持拼音的入口保持原匹配语义。

插件直接复用这一公开宿主模块；依赖该接口的插件须在配套说明中明确所需本体能力，不能在缺接口时静默退回普通文本搜索。测试覆盖中文、全拼、首字母、英文/ID混合、空查询、无匹配，以及原筛选和排序的叠加。

## 导读

先查组件目录与共用入口；状态归属、兼容边界和具体功能的验证说明见下文对应小节。

## 组件目录

| 组件 | 用途 | 原实现/维护位置 |
| --- | --- | --- |
| `ActionButton` | 设置页普通操作按钮，沿用 `IconButton` 样式 | `ddm/ui/basics.py` |
| `TitleLabel`、`HintLabel` | 设置标题、可换行说明，沿用 `SettingsTitle` / `SettingsHint` | `ddm/ui/basics.py` |
| `page_header` | 设置页标题加可选说明 | 从 dialogs 的 `_page_head` 集中提取；旧入口保持别名 |
| `step_button` | 原有 28×28 加减按钮，包含提示和点击回调 | 从 dialogs 的 `_step_button` 集中提取；旧入口保持别名 |
| `Avatar`、`RoomStrip`、`PinnedArc`、`circular_pixmap` | 头像、头像条、置顶标记、圆形图片 | `ddm/avatar_widgets.py` |
| `AnimatedDialog`、`AnimatedMenu` | 已有对话框和菜单的交互/动效 | `ddm/motion.py` |
| `ColorDialog` | 紧凑 RGB / HEX 选色与预览，确认时发出 `colorSelected`，复用现有主题和按钮 | `ddm/ui/color_dialog.py` |
| `SlidingTabs`、`SettingsStack` | 已有页签和设置页面切换 | `ddm/motion.py` |
| `TileButton`、`VolumeButton`、`RecordingButton` | 播放格按钮、音量、录制控件 | `ddm/playback_controls.py` |
| `SidebarToggleButton`、`PauseButton`、`RefreshButton`、`DanmakuToggleButton` | 已有侧栏/播放控制按钮 | `ddm/playback_controls.py` |
| `ElidedLabel`、`BarIconButton` | 省略文字、工具条按钮 | `ddm/ui/labels.py`、`ddm/ui/toolbar.py` |
| `NavigationButton` | 功能轨及弹出面板使用的图标按钮，统一悬停与键盘焦点反馈 | `ddm/sidebar_navigation.py` |
| `continuous_path` | 矩形表面的连续圆角路径；保留圆形、胶囊及明确的直角 | `ddm/corner_geometry.py` |
| `ScaleCurveControl` | SC / 弹幕可拖动控制点的缩放曲线与比例示例 | `ddm/ui/scale_curve.py`；计算规则见 `ddm/viewport_scale.py` |
| `ToggleSwitch` | 设置行右侧的开关，保留 Qt 点击、空格键、焦点及禁用语义 | `ddm/ui/selection.py`；`NotificationSwitch` 保留兼容子类 |
| `SegmentedControl` | 单选分段组，共用底板与选中块，支持方向键切换及禁用项 | `ddm/ui/selection.py`；`value()` / `setValue()` / `valueChanged` |
| `DisclosureButton` | 页内展开条，统一焦点、按下、圆角与箭头绘制 | `ddm/ui/disclosure.py`；Qt 持有勾选值，固定控件高度 |
| `SettingsSurface` | 设置卡片的半透明渐变、高光和静态背景模糊缓存 | `ddm/ui/settings_surface.py`；供分组、通知及插件卡片复用 |
| `SelectControl` | 选项较多时使用的紧凑下拉，Qt 负责选择模型、弹层定位和键盘操作 | `ddm/ui/select.py`；沿用 `QComboBox` 的数据与信号接口 |
| `FontSelectControl` | 共用下拉外观的字体选择 | `ddm/ui/select.py` |
| `StepperControl` | 将现有 Qt 数值编辑器与加减按钮组合成紧凑控件 | `ddm/ui/stepper.py` |
| `SettingsSlider`、`SettingsValueLabel` | 设置页定宽滑块和随文字调整宽度的数值标签 | `ddm/ui/slider.py` |
| `SettingsProgressBar` | 更新下载进度条，沿用主题色、轨道和连续圆角，保留 Qt 数值与可访问性接口 | `ddm/ui/progress.py` |

原有组件通过统一入口导出同一个类/函数对象，仍在原模块维护，不复制实现。原导入路径继续有效。播放器相关组件保留原有宿主、信号、原生窗口和生命周期要求，不是脱离业务上下文的通用播放框架。

选择控件的绘制集中在 `ddm/ui/selection.py`，尺寸由 `theme` 的开关令牌及 `CONTROL_HEIGHT` / `SEGMENT_*` 管理，颜色随深浅主题更新。`ToggleSwitch` 继承 `QCheckBox`，轨道和滑块由自身绘制；`SegmentedControl` 拥有一组互斥 `QAbstractButton`，Qt 选中状态是唯一值来源，`setValue` 不移动键盘焦点。两者标记 `customControlSurface`，通用圆角过滤器跳过这些控件的表面，避免额外复选指示器覆盖开关圆角；普通控件仍走原绘制路径。组件随 Qt 父控件销毁，不持有业务设置或创建定时器。常规与通知页共用开关，全局编解码的源格式接入分段组，原 `source_buttons` / `source_group` 仅为实际控件的兼容引用。

分段选中块使用渐变、上沿高光与轻投影表达微小高度差，底板使用凹槽明暗；这些是静态绘制，不改变按钮尺寸、状态或键盘行为。`SelectControl` 与 `FontSelectControl` 共用触发区和选项行绘制，列表沿用 Qt 弹层及父子生命周期，公共圆角与颜色跟随主题；弹层关闭或父控件销毁由 Qt 清理。全局解码方式接入下拉，并仅显示当前模式说明，展开选项不改变设置页几何尺寸。分段和下拉默认按内容宽度取尺寸，不随父布局横向铺满；编解码行将名称与控件分列，说明单独换行。其他按钮、输入框和滑块仍沿用原组件。

人工从根 `run.cmd` 检查常规与通知页开关左右端圆角、深浅色、鼠标／空格操作及禁用状态；展开编解码后检查源格式的凹槽底板、选中块高光、Tab／方向键，以及修改后自动保存。解码列表应在触发框附近显示，选择后收起，Esc 关闭列表，关闭设置后无残留列表；切换模式仅更新当前说明。100%／150%／200% 离屏回归和控件预览仅作为功能与绘制回归，实际系统缩放及真实界面仍待人工验收。

`ddm.ui` 按需加载头像、动效和播放控件；导入基础按钮/标签或上述播放控制按钮不会装载 `widgets`、播放器、主窗口或网页登录模块。播放按钮和音量弹窗集中在 `ddm/playback_controls.py`；`widgets` 保留原类及绘制辅助函数的兼容导出，刷新动画仍归按钮所有，音量弹窗仍归调用方持有。`ElidedLabel`、`BarIconButton` 由 `ddm/ui/labels.py`、`ddm/ui/toolbar.py` 维护，公共入口和旧 `widgets` 导出保持同一对象；导入它们也不会装载播放器或主窗口。使用明确的导入名称，避免 `from ddm.ui import *` 将全部组件一起载入。

## 图标与动效复用入口

| 需要的表现 | 先查看 | 适用边界 |
| --- | --- | --- |
| 播放格的暂停、刷新、音量、弹幕和录制图标 | `ddm.ui` 中的播放控制按钮；实现在 `ddm/playback_controls.py` | 连同按钮状态、信号和格子生命周期使用，尚无独立通用图标包 |
| 工具栏图标按钮 | `BarIconButton`、`NavigationButton` | 后者复用侧栏功能轨和功能中心的图标、状态反馈，供通知菜单等弹出面板使用 |
| 对话框、菜单和设置页切换动效 | `AnimatedDialog`、`AnimatedMenu`、`SlidingTabs`、`SettingsStack`；实现在 `ddm/motion.py` | 遵循系统动画开关，仍由原 Qt 宿主持有 |
| 设置开关、分段选项与数值步进反馈 | `ToggleSwitch`、`SegmentedControl`、`StepperControl` | 复用控件自身的状态和反馈，不在页面另建动画状态 |

这些是现有入口清单。哪些图标和动效的视觉效果适合进一步沉淀为跨页面组件，需盘点后由维护者选择；本页不把业务按钮的图形单独声明为已可复用素材。

## 调用示例

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout
from ddm.ui import ActionButton, HintLabel, page_header

page = QWidget()
layout = QVBoxLayout(page)
layout.addLayout(page_header('图片缓存', '选择需要清理的图片类别'))
status = HintLabel('尚未统计', page)
button = ActionButton('刷新统计', page)
button.clicked.connect(refresh_cache)  # 页面自己的业务函数
layout.addWidget(status)
layout.addWidget(button)
```

调用现有头像或菜单：

```python
from ddm.ui import Avatar, AnimatedMenu

# 使用原构造参数与信号；具体业务状态由页面提供。
# 两个名称分别指向 avatar_widgets.Avatar 与 motion.AnimatedMenu。
```

主题颜色直接读取当前主题，例如 `theme.ACCENT`（主题蓝）、`theme.SUCCESS`（现有绿色）。用 QPainter 绘制 `rgba(...)` 颜色时走 `theme.qcolor()`，不要将 CSS rgba 字符串直接传给 QColor。缓存饼图使用蓝/绿两类，灰色仅用于空状态、辅助文字和边界。

已接入：设置页公共页头和加减按钮、数据与存储页、图片缓存页。以后修改共用样式应修改 `theme.py`；组件行为在实际维护模块修改，并通过统一入口验证兼容性。业务页面如录制管理、账号窗口、缓存管理器仍各自维护，不整体搬入基础组件入口。

## 验证

矩形控件的底色与描边通过 `ddm/continuous_corners.py` 统一绘制，Qt 继续负责原有文字、输入、操作及布局。主题 QSS 仍是颜色、半径、状态和尺寸的来源；自绘卡片与图片裁切使用 `continuous_path`，不在各页面另造曲线。当前曲线是带连续曲率接点的近似外形，并非 Apple 私有路径的逐点复刻。圆形头像、状态圆点、胶囊和 Windows 系统窗口外框保持原形。

带控件类型的状态规则也沿用同名的圆角底板，例如 `QPushButton#IconButton:pressed` 沿用 `#IconButton` 的圆角。根圆角专项检查空画面格的实际添加按钮、主操作按钮、导航、外观、快捷键等控件在深浅主题下鼠标和空格按住时的四角像素、按下反馈及尺寸，并覆盖账号按钮的局部选中样式。人工从根 `run.cmd` 启动后，按住空画面格的“添加直播间”，确认按下反馈仍保留圆角。移出按钮再松开应取消，按钮内松开应打开添加界面。

功能轨使用 34×34 按钮和 6px 间隔；顶部和底部各组间的弹性空白继续用于分组。皮肤或控件的原半径与颜色仍生效，不统一改成同一个半径。

```powershell
python dev/run_checks.py --script selfcheck_ui_components
run.cmd --check-continuous-corners
run.cmd --check-playback-controls
run.cmd --check-image-cache
```

组件专项验证轻量导入、原对象身份、旧导入兼容、按钮信号/禁用/归属、标题/说明样式与旧设置入口、实际页面采用共用控件及主题切换；使用离屏 Qt、临时数据，不读取用户账号、不联网。播放按钮专项另检查音量滚轮上下限、声道提示、暂停/方向/弹幕开关、刷新动画显隐与销毁、多缩放绘制；这些回归不代表实际直播性能验收。

人工从根 `run.cmd` 核对深浅主题、系统关闭动画、悬停与键盘操作、100%／125%／150% 缩放，以及图标和动效在实际页面中的表现。外观页滚轮仍待真实验收，见 [BUG-072](../bug-cases.md#2026-11-15-外观页滚轮反馈)。各功能的旧实施细节及逐项验收记录见[历史组件记录](../archive/ui-components-202611.md)。
