# 验证指南

所有命令均从仓库根目录执行。默认入口只运行仓库检查，不遍历所有专项脚本。

## 执行分类

| 套件 | 依赖与行为 | 命令 |
| --- | --- | --- |
| `repository` | Python 标准库和 Git；不导入 Qt，不读取账号，不联网 | `python dev/run_checks.py` |
| `offline` | 开发依赖；离屏 Qt、替身接口或本机 HTTP/WebSocket 服务，不访问真实直播 | `python dev/run_checks.py --suite offline` |
| `native` | Windows、开发依赖、libmpv；部分项目需 FFmpeg，会创建原生窗口 | `python dev/run_checks.py --suite native` |
| `live` | Windows、运行库和网络；显式指定公开开播房间，只读接收 | 使用下方单项命令 |

`offline` 是已核对隔离条件的回归子集，`native` 也是明确列出的原生检查子集；均不表示仓库全部相关测试。其余历史脚本按功能列入[完整索引](../../dev/checks/README.md)，需要先检查脚本依赖、测试数据和隔离条件，再单独运行或加入套件。不能根据文件名中的 `live` 判断它是否使用真实网络。

## 单项与真实直播

```powershell
python dev/run_checks.py --list
python dev/run_checks.py --script selfcheck_emoticon_tabs
python dev/run_checks.py --script check_live_restore -- 6
python dev/run_checks.py --script check_live_danmaku_motion -- --room 6 --backend animator
```

房间 `6` 仅为命令示例，执行前确认目标正在开播。真实直播检查必须显式选择单项并传入参数，不能隐式批量执行；以上两项不加载个人登录配置、不发送真实弹幕。

Windows 也可将 `python dev/run_checks.py` 换为 `dev\run-checks.cmd`。入口使用当前 Python 的解释器执行子进程，设置 `DDM_NO_SAVE=1`；离屏与原生图形后端按分类选择。每个脚本的退出码和异常保留在日志中；Windows 引导保持 MTA 资源至 Qt 清理结束。

## 结果与新增检查

- 日志与 `summary.json` 写入忽略目录 `work/checks/<时间>/`。
- 所有选中项目完成后，任一失败或超时均返回退出码 `1`；参数错误返回 `2`，全部通过返回 `0`。
- 单项默认超时 300 秒，可用 `--timeout` 调整。遇到失败先查看对应日志，不以“执行结束”判断通过。
- 新增脚本先更新完整索引；核对真实配置、网络、窗口和依赖后，才将其加入 `dev/checks/suites.json`。
- 涉及发弹幕的自动回归使用替身或本机服务。真实账号、跨屏操作、声音听感等需要独立人工验收。
- CI 运行 `repository` 套件及应用源码编译；它不代表软件功能、播放和真实直播验收全部通过。

## 工具与历史记录

性能测量见[性能工具](../../dev/benchmarks/README.md)，资源生成见[辅助工具](../../dev/tools/README.md)。发布构建入口继续使用 `dev/build_release.ps1`。

PR 测试和整理过程的历史记录位于 [archive/](../archive/README.md)，版本说明位于 [releases/](../releases/RELEASE-v0.4.md)。
