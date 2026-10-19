# 开发目录

| 位置 | 用途 |
| --- | --- |
| [run-checks.cmd](run-checks.cmd)、[run_checks.py](run_checks.py) | 统一验证入口，默认仅运行仓库检查 |
| [checks/](checks/README.md) | 全部专项脚本的功能索引、已审查的执行套件与子进程引导 |
| [benchmarks/](benchmarks/README.md) | 弹幕性能测量；结果不等同于桌面最终呈现帧率 |
| [tools/](tools/README.md) | 品牌资源生成、插件发布目录生成工具 |
| `selfcheck_*.py`、`check_*.py` | 软件专项回归及诊断；暂保留现有路径，兼容相互导入 |
| [build_release.ps1](build_release.ps1)、[build_windows_version.py](build_windows_version.py)、[pyi_rth_pyside6_paths.py](pyi_rth_pyside6_paths.py) | 发布构建、Windows 版本资源和打包运行时钩子 |
| [fetch_mpv.py](fetch_mpv.py) | 获取并校验播放运行库 |
| [build_match_sync.py](build_match_sync.py)、[check_release_package.py](check_release_package.py) | 插件打包与发布包检查 |
| [restart-client.ps1](restart-client.ps1)、[screens.py](screens.py)、`repro_*.py` | 重启、显示器信息和特定问题复现；单独使用 |

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
