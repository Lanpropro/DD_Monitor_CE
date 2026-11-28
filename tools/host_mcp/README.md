# 软件本体 MCP

Windows 本体通过当前用户的本地诊断管道处理请求。MCP 客户端通过标准输入输出启动本目录的 `server.py`，Python 3.11+ 环境按 `requirements.txt` 安装 MCP SDK。本体继续从根目录 `run.cmd` 启动。更新前已打开的本体需正常退出再启动才能加载新协议。

在仓库根目录用 PowerShell 注册本机服务，`$python` 指向安装了 SDK 的解释器。

```powershell
codex mcp add dd-monitor-host -- $python (Resolve-Path tools/host_mcp/server.py).Path
```

先调用 `list_instances` 取得 PID，后续每次调用都显式指定同一个 PID。旧实例也可能出现在管道列表中，用 `get_state` 核对是否支持本体协议。

| 工具 | 用途 |
| --- | --- |
| `list_settings_pages` | 返回当前本体的设置分类 ID 和名称。 |
| `get_settings_state` | 返回设置窗口类型（local、worker 或 closed）、可见性和实际选中的分类。 |
| `open_settings_page` | 按分类 ID 打开或切页。默认走侧栏设置入口。传入 `entry="monitor", page="streamer_defaults"` 可走主播监控面板的设置请求。 |
| `close_settings` | 通过设置窗口原有的关闭流程收起窗口。 |
| `get_state` | 读取布局、横竖屏、画中画和从 1 开始的墙内格位。playing 统计墙内播放器状态为 playing 且未暂停的路数。 |
| `capture_diagnostics` | 在指定 PID 的运行中本体采集斗鱼取流、全屏、通知关闭、播放、文件夹、拖放或功能栏高亮。 |
| `capture_wall_buffers` | 从指定格号（1 起算）起，异步观察最多 4 格。播放样本的 slot 为 0 起算，properties 中的 cache-forward-bytes、cache-total-bytes 分别为 libmpv 的前向及总封包缓存字节数。属性缺失表示未取得数据。 |
| `remove_wall_slots`、`undo_wall_removal` | 将所选格位作为一次操作移除，画面墙仍匹配时可撤回至原位。目标中包含录制格或空格时整批拒绝。 |
| `list_startup_diagnostics` | 列出当前源码目录可用的启动专项。 |
| `prepare_startup_diagnostics` | 为当前源码目录登记一次启动采集。 |
| `measure_sidebar_interactions` | 指定 PID，在 1–60 秒内观察关注栏卡片拖动、放下或取消，以及横向或纵向滚动。默认采集 30 秒。 |
| `set_pip_picker_visible` | 通过侧栏按钮打开组合画中画面板，或收起面板。返回实际可见状态和同步处理耗时。 |
| `list_layouts` | 列出内置和已保存的布局 ID。 |
| `set_layout` | 使用布局菜单的处理函数应用指定 ID。选择另一方向的布局会切换横竖屏。 |
| `open_picture_in_picture` | 将指定格位列表的已有画面放入浮窗。 |
| `close_picture_in_picture` | 关闭当前画中画。 |
| `remove_wall_slot` | 通过移除面板移除单个格位，可在面板撤回。录制中、待录制和画中画活动时会拒绝移除。 |

设置打开和关闭返回 `accepted` 后，轮询 `get_settings_state` 可确认完成。分类回读反映导航选中状态，首帧耗时需结合绘制采样。画面墙修改工具返回操作后的状态和同步处理毫秒数。手动选择布局后也可以从 `get_state.last_layout_change` 读取最近一次布局回调的起止布局、完成时间和耗时。画面呈现、异步播放恢复仍需对照实机。请求超时后先重新读取本体状态。

使用 `capture_diagnostics(pid, mode, seconds)` 时，在调用等待期间按平时的方式操作软件。每个进程同一时间接受一次采集，超时或客户端断开后停止采集。

| 模式 | 现场操作与记录 |
| --- | --- |
| `douyu` | 播放或重载出问题的斗鱼房间。在原有连接上记录播放、取流与恢复事件，以及定时播放器状态。详情在 `logs/douyu-on-demand.jsonl`，另有同名的 `-responsiveness.jsonl` 心跳日志。 |
| `fullscreen` | 对目标直播格进入或退出全屏。记录过渡阶段、键盘消息延迟、布局、控制栏与播放器观察值。详情在 `logs/fullscreen-on-demand.jsonl`。 |
| `notices` | 点击当前通知的关闭按钮或通知列表的删除按钮。记录按钮、动画、定时器、窗口可见状态等。详情在 `logs/on-demand.jsonl`。 |
| `folders` | 立即读取当前文件夹和卡片几何。 |
| `drag` | 尝试拖放一张卡片。完成一次操作或等待最多 60 秒。 |
| `playback` | 观察最多四路播放器及缓存、进度等数据，默认 60 秒。 |
| `dock-hover` | 将鼠标划过功能栏，在最长 60 秒内记录指针和高亮状态。 |

斗鱼、全屏和通知默认 30 秒，与播放模式都支持 1–60 秒。在结果的 `specialty-start` 中可以找到日志名和会话标识；通用播放的记录在结果里，也可按会话查 `logs/on-demand.jsonl`。

## 需要从启动开始的采集

先调用 `list_startup_diagnostics` 核对模式，再调用 `prepare_startup_diagnostics(mode)`。保存返回的 `request_id`，正常退出旧实例，用同一个源码目录的根 `run.cmd` 启动。在新 PID 的 `get_state.startup_diagnostics` 核对模式和编号，随后复现并正常退出。请求在十分钟内供下一次启动领取一次，新请求会替换此前未领取的请求。MCP 不自动关闭或启动软件。

| 模式 | 采集内容 |
| --- | --- |
| `window-resize` / `window-dpi-profile` | 跨屏、窗口缩放和布局阶段，后一项额外采集 DPI 消息的函数耗时。 |
| `settings-scroll` / `settings-performance` | 设置滚轮投递或页面创建和保存耗时，覆盖主进程和新启动的设置进程。 |
| `responsiveness` / `responsiveness-profile` / `folders` / `theme` | 启动和滚动、完整响应性、文件夹动画或主题切换。 |
| `fullscreen-input` / `control-swap` / `wall-replacement` / `tiles` | 全屏输入、控件交换、画面替换或启动布局与格子悬浮栏。 |
| `sc` / `danmaku` / `danmaku-motion` | SC 绘制与拖动，或弹幕运动。部分专项可用 Ctrl+Alt+F8 标记现场。 |
| `drag` / `notices` / `fullscreen` / `dock-hover` | 同类运行中采集之外，可保留从启动开始的专项记录。 |
| `douyu` / `douyu-deep` / `live-elapsed` | 取流与 mpv 生命周期、经本机转发器的逐包实验或直播时长状态。斗鱼深度实验会改变连接路径。 |
| `match-d3d11` / `match-d3d11-quick` / `development-hang` | 源码和本机依赖就绪时才列出，用于二路渲染对照或外部卡死采集。 |

采样开始后可按平时的速度滚动关注栏，再拖动一张卡片。按 Esc 可取消拖动。返回值包含卡片拖影生成、启动、落点更新、放下和清理的调用次数与最大耗时，以及滚动期间可见封面的刷新耗时。横纵轴分别记录滚动次数、首末位置变化之间的时长和最大变化间隔。滚动间隔受输入节奏影响。判断界面停顿可看 `heartbeat` 中 16 毫秒主线程定时器的实际间隔及达到 50、250 毫秒的次数。拖动、滚动（含末次输入后 250 毫秒）、两者同时发生与空闲分别计数。原始报告写入本机 `logs/on-demand.jsonl`，可按返回的 session 查找。

`slow_intervals` 按活动保存最慢的三个 ≥50 毫秒心跳。每段最多八次主线程 Python 调用位置采样，只代表采样瞬间。通过侧栏打开组合画中画时，`phases` 记录构造、候选卡、布局、显示等阶段（嵌套耗时不可相加），`picker_first_paint_ms` 从进入打开函数计至面板第一次 paintEvent 返回。

根目录 `run.cmd --check-host-mcp` 验证隔离窗口及本地管道。将环境变量 `DDM_MCP_PYTHON` 指向安装了本目录依赖的 Python 后执行同一命令，还会启动独立 stdio 服务和 SDK 客户端验证全部工具。

在 `measure_sidebar_interactions` 采样期间从画中画返回主墙，`pip-return` 记录整墙返回回调耗时，子项分别记录挂回主窗口布局、恢复格位布局、显示画面墙、同步浮层和激活主窗。并行播放的独立小墙使用另一条返回路径。
