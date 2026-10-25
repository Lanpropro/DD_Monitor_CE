# 本机工作区维护

## 已核对的目录归属

| 位置 | 归属与处理 |
| --- | --- |
| `ddm/`、`blivedm/`、`assets/` | 已跟踪的软件代码与资源 |
| `dev/`、`docs/` | 开发维护工具、检查与文档，按各自索引使用 |
| `website-prototype/` | 独立网站原型，单独维护任务范围 |
| `libmpv-2.dll` | 当前播放运行库，保留在应用查找位置；由 `dev/fetch_mpv.py` 校验获取 |
| `plugins_user/` | 模板、开发源码与本机安装副本混合存放；安装副本的改动应在独立插件仓库追踪 |
| `utils/`、`cache/`、`logs/`、`recordings/` | 本机配置、账号、缓存、日志和录像；保持现有读取路径与 Git 忽略规则 |
| `work/` | 临时工作树、构建依赖、回归日志和恢复备份；按子项目处理 |
| `results/` | 发布成品、最终视频/封面及随附的来源和校验文件；不存放测试日志、素材、备份或验收入口 |
| `work/test-artifacts/` | 按二路插件、设置进程、本体验证和导出校验分类的本机测试资料；迁移清单记录原路径与目标路径 |
| `videos/`、`Video_reference/`、`raw/` | 独立宣传工程、参考与原始素材，按素材项目管理 |
| `_perf_tmp/`、`ddm_plugins_dd3l0oxq/` | 2026-10-19 检查时无文件；来源或工具复用条件尚未确认，保留 |

分类时只检查配置、媒体和素材目录的入口及必要文件元数据，不读取真实账号或媒体内容。

测试输出默认写入 `work/checks/` 或 `work/test-artifacts/<任务>/`，最终安装包和成片才复制到 `results/`。
`results/` 保留最新正式版本的发布目录；旧版发布目录归档为同名 ZIP，核对文件清单及内容一致后再删除原目录。需要旧版文件时解压到 `work/` 使用，不长期恢复为成品目录中的文件夹。此规则不处理宣传片、插件等其他成品，也不改变已发布的 GitHub Release。
本机历史资料迁移记录在 `work/test-artifacts/relocation-20261025.json`；二路合成视频位于
`work/test-artifacts/match-sync/match-input-fixtures/`。旧独立修复版已经集成回根目录，日常测试统一使用 `run.cmd`。旧报告中的 `results/` 路径按清单查找，不再维护长期验收入口。

## 本机旧 VLC 归档

2026-10-19，确认当前主程序、依赖清单和跟踪中的二路插件不再导入 VLC，且本机没有进程加载 `libvlc.dll` 或 `libvlccore.dll` 后，将以下三个入口移动到本机忽略目录：

```text
work/archive/legacy-vlc-20261019/
├── libvlc.dll
├── libvlccore.dll
├── plugins/       # 原 VLC 模块，210 个文件
└── manifest.json # 原位置、类型与大小
```

归档共约 82.5 MB，文件完整保留。当前 libmpv 运行库仍在根目录。本机归档不进入 Git，也不随源码或发布包上传。开发重启脚本已使用与 `run.cmd` 相同的 Quick 开关，不再设置旧 VLC 路径。

若需要运行历史 VLC 版本，可从仓库根目录恢复完整三项；先退出对应播放器，并确认目标位置没有同名新文件：

```powershell
$taskArchive = Join-Path (Get-Location).Path 'work/archive/legacy-vlc-20261019'
foreach ($taskName in @('libvlc.dll', 'libvlccore.dll', 'plugins')) {
    if (Test-Path -LiteralPath $taskName) { throw "目标已存在：$taskName" }
}
foreach ($taskName in @('libvlc.dll', 'libvlccore.dll', 'plugins')) {
    Move-Item -LiteralPath (Join-Path $taskArchive $taskName) -Destination (Get-Location).Path
}
```

归档用于本机恢复；其他开发者需要历史运行库时，应使用对应版本的依赖来源，不能依赖这台电脑的归档路径。

## 自动检查纳入标准

- 配置读写使用独立临时目录或明确的替身，不能只依赖 `DDM_NO_SAVE=1` 来假定不会读取真实配置。
- 离屏套件只允许本机测试服务。入口使用 Python 审计事件阻止外部 DNS 查询和 socket 连接；被脚本捕获的违规请求也会使最终结果失败。这不替代对 Qt WebEngine、原生库和子进程网络行为的源码审查。
- `os._exit(0)` 会跳过正常清理，不允许出现在已注册的自动套件脚本中。强退脚本继续单独审查，不能将其退出码当成生命周期验证通过。
- 依赖真实媒体、发布包、登录或显示器条件的诊断单独记录，未确认条件前不批量执行。

本轮审查中，`selfcheck_live_alert.py`、`selfcheck_live_alert_sort.py`、`selfcheck_layout_none.py`、`selfcheck_settings_status.py` 含强退调用，继续保留为单项诊断；`selfcheck_bili_2k_live.py` 明确依赖本机登录状态，也不纳入无账号的真实直播套件。

执行方法见[验证指南](testing.md)，完整脚本索引见[专项检查分类](../../dev/checks/README.md)。

## 本轮验证范围（2026-10-19）

- 仓库套件 8 项、离屏套件 30 项、Windows 原生套件 7 项通过。
- 公开直播间 `5279` 的真实弹幕运动、三次最大化还原和加载提示层检查通过；未使用账号或发送弹幕。
- 房间 `6` 曾在 40 秒内没有收到可渲染弹幕；房间 `21144080` 曾触发还原后黑屏断言，加入起播基线后该房间三轮还原复测通过。此前单次黑屏的原因尚未确定；失败日志与成功日志均保留在本机 `work/checks/`，不能将某个直播间通过解释为所有房间稳定性均已验证。
- 实播还原脚本现在先确认真实弹幕和还原前的视频画面，再检查还原结果，以区分前置条件与还原阶段失败。
