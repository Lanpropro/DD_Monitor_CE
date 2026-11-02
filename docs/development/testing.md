# 验证指南

所有命令均从仓库根目录执行。默认入口只运行仓库检查，不遍历所有专项脚本。

日常功能和人工验收统一使用根目录 `run.cmd`。特殊项目可隔离测试，完成后必须集成回根目录并在该入口复测；自动回归仍使用合成数据、临时配置和离屏窗口。开发入口与冻结包统一使用 PySide6 6.11.2。

## 执行分类

| 套件 | 依赖与行为 | 命令 |
| --- | --- | --- |
| `repository` | Python 标准库和 Git；不导入 Qt，不读取账号，不联网 | `python dev/run_checks.py` |
| `smoke` | 开发依赖和 libmpv；离屏核心功能检查，使用合成数据与本机服务 | `python dev/run_checks.py --suite smoke --timeout 120` |
| `offline` | 开发依赖；离屏 Qt、替身接口或本机 HTTP/WebSocket 服务，不访问真实直播 | `python dev/run_checks.py --suite offline` |
| `native` | Windows、开发依赖、libmpv；部分项目需 FFmpeg，会创建原生窗口 | `python dev/run_checks.py --suite native` |
| `live` | Windows、运行库和网络；显式指定公开开播房间，只读接收 | 使用下方单项命令 |

`offline` 是已核对隔离条件的回归子集，`native` 也是明确列出的原生检查子集；均不表示仓库全部相关测试。其余历史脚本按功能列入[完整索引](../../dev/checks/README.md)，需要先检查脚本依赖、测试数据和隔离条件，再单独运行或加入套件。不能根据文件名中的 `live` 判断它是否使用真实网络。

离屏进程会阻止 Python 层的外部 DNS 查询和 socket 连接，只允许回环地址；即使脚本捕获该异常，最终结果仍失败。Qt WebEngine、原生库和子进程仍需逐项审查。套件脚本不能使用 `os._exit` 绕过清理；具体纳入标准与本机归档见[工作区维护](workspace-maintenance.md)。

## 单项与真实直播

```powershell
python dev/run_checks.py --list
python dev/run_checks.py --script selfcheck_preview_scroll
python dev/run_checks.py --script check_live_restore -- 6
python dev/run_checks.py --script check_live_danmaku_motion -- --room 6 --backend animator
```

房间 `6` 仅为命令示例，执行前确认目标正在开播。真实直播检查必须显式选择单项并传入参数，不能隐式批量执行；以上两项不加载个人登录配置、不发送真实弹幕。

Windows 也可将 `python dev/run_checks.py` 换为 `dev\run-checks.cmd`。入口使用当前 Python 的解释器执行子进程，设置 `DDM_NO_SAVE=1`；离屏与原生图形后端按分类选择。每个脚本的退出码和异常保留在日志中；Windows 引导保持 MTA 资源至 Qt 清理结束。

## 结果与新增检查

侧栏收起／展开回归与本地播放：

```powershell
python dev/run_checks.py --script selfcheck_sidebar_performance --timeout 120
python dev/run_checks.py --script selfcheck_sidebar_performance --timeout 120 -- --layout dm_main3 --players 3 --quick
python dev/run_checks.py --script selfcheck_sidebar_performance --timeout 120 -- --layout dm_main3 --players 3 --quick --burst
python dev/run_checks.py --script selfcheck_sidebar_performance -- --layout dm_main3 --players 3 --quick --size 2300 1250
```

默认使用 60 张合成封面和 16 格原生窗口，检查动画期间播放格子尺寸稳定、Quick 层只移动位置、结束后恢复重绘与布局、反向点击、切方向、隐藏、全屏及计时器清理。输出准备／收尾耗时、宽度更新间隔和 CPU 时间，这些回调不代表 DWM 最终呈现帧率。可选播放器参数需要 FFmpeg，只生成本地测试视频，不读取账号或访问真实直播；`--quick` 使用实际共享弹幕层。人工仍需确认动画期间视频画面、浮层和皮肤的视觉表现。

`--players` 同时设置合成房间和真实播放中的格子状态；配合 `--quick` 注入本地合成弹幕，确保共享层确实创建。`--size` 指定测试窗口的 Qt 逻辑尺寸，便于复查大窗口下填满画面后的收尾开销。收尾在布局、格子顺序、全屏目标和弹幕格均未变化时只更新几何；发生结构变化仍完整重排。离屏主窗口检查另覆盖这一分支、连点和异常后的重绘恢复。

`--burst` 分别以 40 ms、200 ms 间隔连续切换 12 次，断言整轮只做一次昂贵收尾并正确恢复最终宽度、卡片样式和重绘。连点时只更新动画目标；宽度运动结束后保留 80 ms 的反向切换窗口，再统一结算。显式不播放动画、隐藏或切方向时立即结算，不等待该窗口。

关注栏应用内拖拽回归：

```powershell
python dev/run_checks.py --script selfcheck_drag_lifecycle
python dev/run_checks.py --script selfcheck_folder_drag
python dev/run_checks.py --script selfcheck_folder_card_drag
python dev/run_checks.py --script selfcheck_drag_wheel --timeout 120
```

前三项使用合成关注数据，覆盖排序、文件夹、多选、智能副本与头像、滚轮、移动合并、松手、取消和异常清理。最后一项需要 Windows、libmpv 与 FFmpeg，在真实视频子窗口上连续执行 60 次合成鼠标拖放，断言捕获释放、落点高亮及视频持续播放，报告抓起耗时、UI 心跳和进程 CPU 时间；不证明真实桌面下所有输入均已验收。需另测实际鼠标时可追加 `-- --physical`；该模式需要交互桌面，只在确认命中自身测试窗口后注入鼠标消息，并恢复指针。高 DPI、跨屏与 Alt+Tab 仍需人工验收。

连续拖动的跟手测量可追加 `-- --motion`：在视频区和列表区持续注入合成移动，统计拖影窗口位置更新频率、间隔、落点检查次数、CPU 时间和视频丢帧。拖影使用精确定时器按所在屏幕刷新率更新，跨屏后调整；排序与落点检查保持 16 ms 节流。位置回调频率不是 DWM 最终呈现帧率，不能用 UI 心跳代替拖影流畅度。

预览播放器初始化回归与对照测量：

```powershell
python dev/run_checks.py --script selfcheck_mpv --timeout 120 -- --preview-startup
```

需要 Windows、libmpv 和 PATH 中的 FFmpeg。临时生成本地视频，对照立即创建输出与预览按需创建输出的初始化耗时、播放调用耗时和 10 ms UI 心跳最大间隔；启动期间不轮询 mpv 同步属性，避免测量自身引入等待。随后验证实际播放进度、GPU 输出、核心复用、未播放取消、起播中取消和重复释放。不读取账号或访问真实直播。性能数字仅代表本机合成场景，不设跨机器耗时门槛，也不表示原生拖放问题已全部解决。

临时菜单与背景主题订阅的对象回收检查：

```powershell
.\run.cmd --check-widget-lifetime
```

该离屏专项不读取账号、不加载插件、不播放媒体。真实 Qt 右键和画质菜单各进退 30 次后，格子下菜单与滑条数量必须回到初始值，临时菜单的 Python 弱引用也必须清空；音量、画质及插件菜单回调仍有效，执行异常时同样回收。创建并销毁 20 个背景层后，弱引用应全部清空，主题信号不再访问已销毁控件。检查已加入 `smoke` / `offline`，验证对象生命周期，不代表真实直播长期内存或 GPU 内存均无泄漏。

从根目录普通 `run.cmd` 重启后，可对同一格子反复打开／取消右键和画质菜单，再调整音量、选择画质，确认菜单能正常关闭、操作各生效一次；切换深浅色并打开设置，背景及主题应正常刷新。若需比较长期资源走势，使用 `run.cmd --diagnose-responsiveness`，保持相同直播、布局、插件负载，预热后分组操作并等待回稳，比较 `logs/responsiveness.jsonl` 的私有内存、句柄及播放器数量。对象回收不要求进程工作集立即回到启动值；背景层销毁后的回调问题由专项自动检查验证，不以重启进程后的内存下降代替。

原生视频浮层的内存回归：

```powershell
python dev/run_checks.py --script selfcheck_badge_memory
```

使用真实 Windows 原生徽标和左右圆角窗口，在深浅主题下完成 2,400 次 alpha 上传，
确认上传成功且 GC 后保留的 Python 内存低于 512 KiB。窗口在屏幕外创建，
不打开媒体、不加载插件或账号配置；此检查用于捕获反复重绘时创建 ctypes 类型导致的持续积累。

- 日志与 `summary.json` 写入忽略目录 `work/checks/<时间>/`。
- 所有选中项目完成后，任一失败或超时均返回退出码 `1`；参数错误返回 `2`，全部通过返回 `0`。
- 单项默认超时 300 秒，可用 `--timeout` 调整。遇到失败先查看对应日志，不以“执行结束”判断通过。
- 新增脚本先更新完整索引；核对真实配置、网络、窗口和依赖后，才将其加入 `dev/checks/suites.json`。
- 涉及发弹幕的自动回归使用替身或本机服务。真实账号、跨屏操作、声音听感等需要独立人工验收。
- CI 分别运行 `repository` 和 `smoke`，并编译应用源码。smoke 覆盖设置、通知、布局、关注排序、弹幕发送和插件接口；它不代表原生播放、视觉帧率和真实直播验收全部通过。
- smoke 与 offline 可共享脚本，但必须保持相同隔离模式；同一套件不允许重复脚本。新增 smoke 项目应先核对隔离条件、耗时和依赖，不把所有历史脚本直接纳入 CI。

## 工具与历史记录

性能测量见[性能工具](../../dev/benchmarks/README.md)，资源生成见[辅助工具](../../dev/tools/README.md)。发布构建入口继续使用 `dev/build_release.ps1`。

PR 测试和整理过程的历史记录位于 [archive/](../archive/README.md)，版本说明位于 [releases/](../releases/RELEASE-v0.4.md)。

## 账号菜单再次登录

```powershell
python dev/run_checks.py --script selfcheck_account_login_reopen --timeout 45
```

此原生检查使用真实 `QMenu.exec`、鼠标点击和平台登录窗口，在展开与收起侧栏各重复打开、取消两次；断言登录入口在菜单和鼠标回调返回后才执行。只使用合成账号与 `about:blank` 页面，禁用宿主轮询、启动更新和插件检查，不读取真实账号。外部进程超时也覆盖原生事件循环卡死。

## 久用卡顿的真实采集

`run.cmd --diagnose-responsiveness` 开启默认关闭的专项采集，步骤及字段说明见[真实复现采集](responsiveness-capture.md)。采集器回归不代表 BUG-070 已定位或性能改善。

2026-11-02 的真实侧栏展开/收起采样中，123 个关注条目下 `Sidebar.set_collapsed` 多次耗时约 200–373 ms，主线程栈反复落在 `Avatar.set_pixmap_image` 的样式设置。针对这条路径，头像已有透明样式时不重复设置，更新图片直接交给 QLabel，不先清空已有图片。`selfcheck_main_notices` 覆盖图片替换、尺寸切换、透明圆角及不重复设置样式/文本；这些断言仅为功能回归。展开黑区和实际响应改善仍需相同操作的真实对照采样确认，不能据此宣布 BUG-070 已解决。

头像修正后的真实对照仍出现黑块，侧栏切换约 103–363 ms，收尾栈还采到弹幕重排。经用户同意，左侧关注栏改为一次切换完整布局：暂停侧栏绘制，准备最终控件、宽度与可见封面，并统一调整播放区后再恢复显示；取消逐帧宽度动画和延迟收尾。`selfcheck_main_notices` 检查卡片/列表模式、连续切换、智能文件夹副本、隐藏恢复及异常时释放绘制；`selfcheck_sidebar_performance` 检查最终尺寸、无后续宽度变化、屏外封面和本地播放器，可用 `--background` 将原生测试窗口置于屏幕外。合成功能检查不作为真实流畅度证据。

人工对照：退出旧实例，从根目录 `run.cmd --diagnose-responsiveness` 重启；以相同关注数量和播放布局反复收起/展开。预期直接呈现头像栏或完整关注栏，不经历窄条封面拉伸；滚动后封面正常，播放与弹幕位置正确。若黑块或停顿仍出现，记录到秒的时间以及展开结束后是否残留，再核对新会话日志。

12:24 的真实函数明细（123 个关注）显示，每次切换有 123 次 `setParent`、约 370 次图片缩放，以及大量显隐/置顶事件。对应修正：空闲缩略图停止直接返回；头像在目标尺寸下一次完成裁切与圆环，不先重裁旧图；平台图标固定挂在条目上，用坐标定位到头像角落或展开位置，不再随模式切换换父级。回归覆盖图标显隐、横竖屏位置、头像透明角与圆环、预览提示清理和播放器停止。函数分析增加耗时；这些回归及合成测试不代表真实流畅度改善，仍需用户同场景录屏和明细对照。

12:40 录屏反馈明确允许右侧格子随后缩放，但要求左侧一次显示完整内容。切换收尾因此先恢复侧栏绘制并同步提交完整侧栏的绘制，再释放播放区尺寸保持；不增加固定等待或新的宽度动画。回归记录实际 `QEvent.Paint`，检查侧栏在最终宽度下的绘制先于播放区几何更新，并保留隐藏、原有绘制暂停、异常恢复和连续切换检查。该顺序检查覆盖 Qt 绘制调用，不等同于 Windows 桌面合成器实际呈现的录像验证。
