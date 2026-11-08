# 共用界面组件

统一调用入口为 `ddm.ui`。先检查这里和下表，再使用 Qt 原生控件或补充真正缺少的组件；颜色、字号、圆角和间距继续由 `ddm.theme` 管理，不在各页面另建配色表。

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
| `ElidedLabel`、`BarIconButton` | 省略文字、工具条按钮 | `ddm/widgets.py` |
| `continuous_path` | 矩形表面的连续圆角路径；保留圆形、胶囊及明确的直角 | `ddm/corner_geometry.py` |
| `ScaleCurveControl` | SC / 弹幕可拖动控制点的缩放曲线与比例示例 | `ddm/ui/scale_curve.py`；计算规则见 `ddm/viewport_scale.py` |

原有组件通过统一入口导出同一个类/函数对象，仍在原模块维护，不复制实现。原导入路径继续有效。播放器相关组件保留原有宿主、信号、原生窗口和生命周期要求，不是脱离业务上下文的通用播放框架。

`ddm.ui` 按需加载头像、动效和播放控件；导入基础按钮/标签或上述播放控制按钮不会装载 `widgets`、播放器、主窗口或网页登录模块。播放按钮和音量弹窗集中在 `ddm/playback_controls.py`；`widgets` 保留原类及绘制辅助函数的兼容导出，刷新动画仍归按钮所有，音量弹窗仍归调用方持有。`ElidedLabel`、`BarIconButton` 目前仍由 `widgets` 维护。使用明确的导入名称，避免 `from ddm.ui import *` 将全部组件一起载入。

## 播放界面设置与验收

设置分类导航采用关注栏风格，在 `ddm/settings_navigation.py` 维护：基础偏好、观看与互动、系统与扩展三组，分类名称支持中文／拼音搜索。完整分类栏宽 224 px，鼠标在右侧内容区连续停留至少两秒后收成 58 px 图标栏；移回图标栏展开。收起清空分类筛选，保持全部分类与更新红点可访问。页面顺序、懒创建、配置与取消语义保持原有接口。

指针检测仅在设置窗口显示时运行，失焦、移出窗口、弹出菜单、按住鼠标拖动会重置停留时间；键盘操作立即展开并暂停自动收起，移动鼠标后恢复。过渡复用现有曲线，200 ms，可从当前宽度反向，关闭系统动画时直接切换；隐藏／关闭停止检测，销毁时同时释放定时器。人工验收时在右侧停留两秒、移回左侧、拖动曲线和使用 Tab／方向键，再切换窗口与关闭重开核对这些边界。

SC 和画面弹幕使用控制点曲线：横轴为画面高度 0–1440 px，纵轴为相对手动大小的比例 10%–200%，720 px / 100% 为固定基准。拖动节点调整，拖动线条新增节点，右键或 Delete 删除选中的中间节点；端点仅上下移动。超过 1440 px 使用最右端比例。设置 → 弹幕中分别编辑，格内观看设置也提供同一曲线，并沿用全局／逐格独立设置。已有缩放强度转换为初始曲线；没有曲线数据时继续使用旧强度计算。SC 布局仍受容器宽高及消息数量限制，比例示例不代表拥挤时的最终大小。

设置 → 托盘行为 → 画面右键菜单左右并排：左侧为菜单缩略图，直接拖动功能行排序；右侧勾选功能并实时更新预览。仍支持上移／下移与恢复默认。插件扩展按一组参与排序；全屏及画中画继续隐藏不适用的菜单项。

从根目录运行 `run.cmd --check-ui-polish` 可检查透明边缘、底栏背景、历史消息按钮、缩放与菜单配置。真实界面人工验收步骤：

1. 在 100%、125%、150% 系统缩放下悬停播放格，检查 LIVE／标题胶囊边缘和底栏按钮蓝色背景；切换深浅主题后仍应平滑。
2. 滚动弹幕到历史位置，等待新消息和表情图片刷新；“回到底部”按钮应一直固定在可见区域，点击后恢复跟随并隐藏。
3. 在 SC／弹幕曲线上拖动一个节点，在线上新增节点并右键删除；改变格子大小，核对文字变化、保存重开、曲线重置，以及弹幕独立设置与全局设置。
4. 在托盘行为页右侧取消一个菜单功能，在左侧缩略图上将另一项拖到顶部；保存后打开画面右键菜单，检查可见项、顺序、点击功能及恢复默认。

### 设置内容布局

`ddm/settings_layout.py` 仅负责设置卡片和响应式排列，控件、信号和保存仍由各页面持有。设置默认宽 1200、高 800，受当前屏幕可用范围限制；右侧内容区达到 760 px 时两列排列，否则上下堆叠。常规、弹幕、录制、通知、快捷键和嵌入式分区样式复用原控件分组；SC 曲线与位置预览并排。需要完整宽度的内容跨列，底部保存按钮固定在滚动区外。

常规页原 grid 和隐藏平台标识 anchor 保留，兼容已发布插件的插入、保存、取消和重置。不得以复制控件或另建状态副本实现布局切换。

人工验收：从根目录 `run.cmd` 打开设置，检查宽窗口各卡片并排；缩到 760 px 宽时应改为上下排列并能滚动到末项。修改音量、SC 曲线、录制目录、快捷键及菜单顺序，切换页面和窗口宽度后值应保持；分别验证取消、保存重开和当前页重置。外观页左右预览与选项应联动，插件平台标识应仍可保存。自动几何回归通过不代表人工验收完成。

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

功能轨使用 34×34 按钮和 6px 间隔；顶部和底部各组间的弹性空白继续用于分组。皮肤或控件的原半径与颜色仍生效，不统一改成同一个半径。

```powershell
python dev/run_checks.py --script selfcheck_ui_components
run.cmd --check-continuous-corners
run.cmd --check-playback-controls
run.cmd --check-image-cache
```

组件专项验证轻量导入、原对象身份、旧导入兼容、按钮信号/禁用/归属、标题/说明样式与旧设置入口、实际页面采用共用控件及主题切换；使用离屏 Qt、临时数据，不读取用户账号、不联网。播放按钮专项另检查音量滚轮上下限、声道提示、暂停/方向/弹幕开关、刷新动画显隐与销毁、多缩放绘制；这些回归不代表实际直播性能验收。
