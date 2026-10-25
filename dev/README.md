# 开发目录

| 位置 | 用途 |
| --- | --- |
| [run-checks.cmd](run-checks.cmd)、[run_checks.py](run_checks.py) | 统一验证入口，默认仅运行仓库检查 |
| [checks/](checks/README.md) | 全部专项脚本的功能索引、已审查的执行套件与子进程引导 |
| [benchmarks/](benchmarks/README.md) | 弹幕性能测量；结果不等同于桌面最终呈现帧率 |
| [tools/](tools/README.md) | 品牌资源生成、插件发布目录生成工具 |
| `selfcheck_*.py`、`check_*.py` | 软件专项回归及诊断；暂保留现有路径，兼容相互导入 |
| [build_release.ps1](build_release.ps1)、[build_windows_version.py](build_windows_version.py)、[pyi_rth_pyside6_paths.py](pyi_rth_pyside6_paths.py) | 发布构建、Windows 版本资源和打包运行时钩子 |
| [build_setup.py](build_setup.py)、[check_setup_install.py](check_setup_install.py) | DDMonitorSetup 安装器构建与隔离生命周期验证，见[卸载范围](../docs/development/windows-installer.md) |
| [build_program_inventory.py](build_program_inventory.py) | 从历史EXE包生成路径/大小/SHA-256清单，或为最终便携目录生成当前程序清单，见[更新清理](../docs/online-updates.md) |
| [fetch_mpv.py](fetch_mpv.py) | 获取并校验播放运行库 |
| [build_match_sync.py](build_match_sync.py)、[check_release_package.py](check_release_package.py) | 插件打包与发布包检查 |
| [screens.py](screens.py)、`repro_*.py` | 显示器信息和特定问题复现；日常启动使用根目录 run.cmd |

目录中还可能存在被 Git 忽略的本机预览或宣传脚本；它们不在源码清单和批量套件内。

## 常用命令

从仓库根目录执行：

```powershell
dev\run-checks.cmd
dev\run-checks.cmd --list
dev\run-checks.cmd --suite offline
dev\run-checks.cmd --script selfcheck_emoticon_tabs
```

Windows 包装器优先使用仓库 `.venv`，其次使用相邻的 `DD_Monitor-venv`，也可回退到 PATH 中的 Python。其他环境直接使用当前 Python：

```powershell
python dev/run_checks.py --suite repository
```

分类与适用条件见[验证指南](../docs/development/testing.md)。

本机目录与旧运行库的恢复方法见[工作区维护](../docs/development/workspace-maintenance.md)。

## 独立设置进程原型

开发版的 `run.cmd` 和 `run-console.cmd` 已启用独立设置进程，使用本目录原有配置与插件直接测试。
直接执行 `python main.py` 时，需先设置 `$env:DDM_SETTINGS_PROCESS='1'`。
程序启动一秒后异步预热一个设置进程，点击关注栏设置时发送配置快照；保存只将变化的字段交回主程序，取消不应用。
不设该环境变量时沿用原入口。源码运行需要开发依赖与 libmpv；现有旧 EXE 不支持新增的 `--settings-worker`，需另行构建才能验证打包行为。

常规、弹幕、录制、通知和快捷键页面复用原控件。外观、插件和软件更新仍在主程序窗口打开；切换前可保存、放弃或取消当前改动。
独立窗口不阻止操作主程序，因此主程序可继续播放；修改解码或录制等设置后，保存应用仍按原逻辑执行，可能影响正在使用的功能。
子进程使用临时配置目录，不读取账号或加载用户插件，关闭主程序时退出。

验证命令：

```powershell
python dev/checks/bootstrap.py dev/selfcheck_settings_process.py
python dev/check_settings_process_playback.py --help
```

前者验证保存、取消、窗口切换、失败重试、退出与 GUI 隔离；后者用本地双路合成媒体对照画面间隔、音频欠供和时钟年龄。
合成媒体及 Qt 定时器测试不能替代真实直播与打包 EXE 的人工验收。

Windows 每次打开或再次点击设置时，宿主向握手返回的实际工作进程 PID 授予前台权限；预热本身不激活窗口。
已有窗口最小化时先恢复，再请求系统前台，保持未保存的编辑；不设置永久置顶。
原生前台检查可使用 `QT_QPA_PLATFORM=windows` 运行 `dev/selfcheck_settings_process.py --native-focus`。
该项会显示合成窗口并临时移动和恢复光标，只点击核对过句柄的空白测试窗口；普通后台回归不运行此项。
