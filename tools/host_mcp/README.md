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
| `list_layouts` | 列出内置和已保存的布局 ID。 |
| `set_layout` | 使用布局菜单的处理函数应用指定 ID。选择另一方向的布局会切换横竖屏。 |
| `open_picture_in_picture` | 将指定格位列表的已有画面放入浮窗。 |
| `close_picture_in_picture` | 关闭当前画中画。 |
| `remove_wall_slot` | 通过移除面板移除单个格位，可在面板撤回。录制中、待录制和画中画活动时会拒绝移除。 |

设置打开和关闭返回 `accepted` 后，轮询 `get_settings_state` 可确认完成。分类回读反映导航选中状态，首帧耗时需结合绘制采样。画面墙修改工具返回操作后的状态和同步处理毫秒数。手动选择布局后也可以从 `get_state.last_layout_change` 读取最近一次布局回调的起止布局、完成时间和耗时。画面呈现、异步播放恢复仍需对照实机。请求超时后先重新读取本体状态。

根目录 `run.cmd --check-host-mcp` 验证隔离窗口及本地管道。将环境变量 `DDM_MCP_PYTHON` 指向安装了本目录依赖的 Python 后执行同一命令，还会启动独立 stdio 服务和 SDK 客户端验证全部工具。
