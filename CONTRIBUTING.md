# 开发与贡献

## 分支和目录

日常开发以 `develop` 为基线，`main` 保存经整体验证后接收的主线代码。
版本标签（如 `v0.4`）和 GitHub Releases 标识正式发布版本；分支上的进度不表示已经发布了同版本的 EXE。

| 分支 | 用途 |
| --- | --- |
| `main` | 从 `develop` 接收准备发布的改动 |
| `develop` | 汇总功能、修复和日常维护，进行整体验证 |
| `function/<名称>` | 从 `develop` 创建的一项功能或修复 |
| `release/<版本>` | 保留发布标签对应的源码基线，不承载日常开发 |
| `archive/<名称>` | 保留旧方案或整理前的历史，不作为新任务基线 |

日常开发和人工验收统一使用仓库根目录 `run.cmd`。特殊项目确需隔离时才使用独立 worktree；测试结束后，必须将完成的功能集成回根目录，再从 `run.cmd` 复测。独立入口通过不代表日常开发版已经包含该功能。

发布从根目录当前已提交的完整开发源码构建，包含当时完成的全部功能，不再另外挑选修复组合。配置、账号、缓存、日志、录制和本机插件安装副本不进入发布包；插件仍按独立仓库发布。开发入口与打包使用同一固定版本的 Qt 依赖，当前为 PySide6 6.9.3。

分支是同一仓库中的代码历史，不是文件夹。先检查当前目录与分支：

```powershell
git status --short --branch
git branch --show-current
git worktree list
```

- 维护者的小型文档或注释修改可以直接在 `develop` 完成、验证、提交，不强制创建 PR 或 Draft PR。
- 一项独立功能或修复使用 `function/<名称>`，如 `function/emoticon-tabs`。
- 功能、修复和外部贡献通过 PR 提交到 `develop`。未完成时可使用 Draft；准备好审查后使用普通 PR。
- 同一功能的相关修复、样式调整和验收反馈优先追加到尚未合入的原 PR；不要为每次微调新建 PR，独立需求再拆分。
- 准备发布时，验证完整的 `develop`，再通过 PR 合入 `main`；已有面向 `main` 的 PR 先检查依赖与差异，再决定是否调整目标。
- PR 模板区分日常贡献与发布；创建时核对 GitHub 的 base，日常贡献选择 `develop`，发布选择 `main`。
- 特殊项目使用独立 worktree 和分支时，不覆盖日常配置；完成后集成回根目录并清理临时入口。
- 合并后的功能分支可在确认不再被 worktree 使用后删除；备份和未合并成果先保留。

## 日常开发

1. 先检查未提交内容。工作区未归类清楚时，不切换分支或拉取合并。
2. 同步 `develop`，在干净的工作区开始小修改，或从它创建 `function/<名称>`。
3. 修改一项内容，补充相关测试，并执行与改动对应的验证。
4. 检查差异，按文件或交互式暂存，创建一个能独立说明的提交。
5. 结束开发前再次检查状态，说明剩余文件属于源码、未完成内容还是本机资料。

```powershell
git switch develop
git pull --ff-only origin develop
git switch -c function/emoticon-tabs

git add -p
# 新增文件需要明确指定路径添加。
git diff --cached
git diff --cached --check
git commit -m "fix(sidebar): correct selection marker position"
```

提交前缀可使用 `feat:`、`fix:`、`perf:`、`test:`、`docs:`、`chore:`。
未完成工作可在功能分支保存为 `wip:`；提交是保存进度，发布需要单独验收。

## 尝试与提交整理

- 开发中可以多次提交保存进度；合入 `develop` 时通常用 Squash and merge，将最终成果汇总成一个清晰的提交。
- 完全放弃的尝试可以关闭 PR、删除对应功能分支，无需合入开发主线。删除前确认没有需要保留的未提交内容或 worktree。
- 未推送的个人功能分支可以整理提交；已推送但未合并的个人功能分支，先确认无人基于它开发并保留备份，再用 `--force-with-lease` 更新。
- 已进入 `main` 或 `develop` 的历史保留；撤销代码使用 `git revert`，不通过删除共享提交撤销功能。
- 版本对照快照整理前保留原提交引用或 bundle，并核对整理前后的代码树一致，保留贡献者与来源记录。

## PR 集成

- 描述目的、修改范围、相关问题、验证命令和已知限制；界面修改提供截图或复现步骤。
- PR 依赖另一个 PR 时，在描述中写明顺序，依赖解决前保持 Draft。
- 集成时核对作者的最新提交 SHA；本地曾经 cherry-pick 某一版本，不代表已经包含后续更新。
- 在测试分支或 worktree 中验证组合后的代码，保留贡献者信息与原 PR 链接。
- 独立功能通常使用 squash merge；需要保留多个提交或处理分支历史时逐项决定，不强制改写已共享历史。
- 不强推 `main` 或 `develop`，不以整树覆盖的方式忽略远端改动，也不自动关闭仍未完成核对的 PR。

## 验证范围

基础仓库检查仅依赖 Python 和 Git，不联网、不读取个人配置：

```powershell
python dev/run_checks.py --suite repository
python -m compileall -q ddm blivedm main.py
git diff --check
```

GitHub Actions 执行以上基础检查，以及 `python dev/run_checks.py --suite smoke --timeout 120` 的离屏核心功能检查。smoke 使用开发依赖和 libmpv；CI 按 `ddm/assets/licenses/libmpv-SOURCE.json` 下载运行库并校验压缩包及 DLL 的 SHA256。这些检查不能替代原生播放和真实直播验收。

使用 `python dev/run_checks.py --list` 查看已审查的测试套件。完整命令、依赖与全部专项脚本的分类入口见[验证指南](docs/development/testing.md)。新增测试同步更新分类索引；确认隔离条件后再纳入批量套件。

涉及界面、账号或播放的专项检查应使用独立测试数据，通常设置：

```powershell
$env:DDM_NO_SAVE = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
```

需要原生 Windows 视频窗口时使用 `QT_QPA_PLATFORM=windows`。
真实直播、音频听感、高 DPI 和跨屏检查单独列出；未执行或未通过的项目明确说明。
测试不向公开直播间自动发送消息，不使用真实 Cookie 作为测试数据。

### 改动区域 → 必跑测试

所有改动先运行 `repository` 套件、源码编译和 `git diff --check`。下表为在此基础上的最低要求；跨区域改动取并集。CI 自动运行 repository 和 smoke，其他专项由贡献者执行并在 PR 记录结果。

| 改动区域 | 必跑功能检查 | 额外验收条件 |
| --- | --- | --- |
| 设置、设置保存与默认值 | `python dev/run_checks.py --script selfcheck_general_settings` | 修改具体页面时补充该页专项；检查打开、切换、保存、取消与重置 |
| 通知、开播提醒、快捷键入口 | `python dev/run_checks.py --script selfcheck_main_notices` | 手动检查点击、关闭、遮挡及连续通知 |
| 关注排序、常看记录 | `python dev/run_checks.py --script selfcheck_frequent_sort`；`python dev/run_checks.py --script selfcheck_sort_manager` | 检查启用／停用、置顶、普通及智能文件夹、手动刷新和重启恢复；悬停不计次 |
| 布局、格子数量与状态恢复 | `python dev/run_checks.py --script selfcheck_layout_16`；`python dev/run_checks.py --script selfcheck_layout_growth_empty` | 拖拽、全屏或方向相关改动还需 `--suite native` 及实际播放验收 |
| 弹幕发送、凭据快照与协议 | `python dev/run_checks.py --script selfcheck_bili_plugin_boundary`；发送协议在独立插件仓执行对应专项；连接改动另跑 `--script selfcheck_danmaku_connection` | 使用替身或本机服务，不向真实直播间发送测试消息 |
| 弹幕绘制、浮层和控件 | `python dev/run_checks.py --script selfcheck_video_danmaku`；`python dev/run_checks.py --script selfcheck_video_danmaku_controls` | Quick 渲染或透明窗口改动另跑 native 套件并检查高 DPI |
| 插件接口、事件和装载 | `python dev/run_checks.py --script selfcheck_plugin_contract` | 安装／更新／启用交互需按插件主题索引选择专项，使用临时插件目录 |
| 播放器、解码与原生窗口 | `python dev/run_checks.py --suite native` | 实际播放、音频听感及跨屏检查，必要时显式运行 live 单项 |
| 录制、回放与退出收尾 | `python dev/selfcheck_recording.py`；`python dev/selfcheck_recording_shutdown.py` | 需 FFmpeg；隔离输出，核对生成文件、分段、回放和停止行为 |
| CI、测试入口和工作流文档 | `python dev/selfcheck_check_runner.py`；`python dev/selfcheck_project_workflow.py` | 修改 smoke 选项或依赖时运行完整 smoke，并确认远端 CI |

未登记的专项先核对[分类索引](dev/checks/README.md)，确认不会读取真实账号配置、加载安装中的插件或产生外部写入后再执行。测试结果写明命令、退出码和未覆盖范围，不能以 smoke 通过代替改动区域的专项验收。

## 本机资料与发布

- `utils/`、缓存、账号、皮肤、安装中的插件和插件更新备份只保留在本机，不进入源码提交。
- 插件归属见[源码、模板与安装副本边界](docs/plugins.md#源码模板与安装副本的边界)：`plugins_user/_match_sync` 和 `_template_platform` 在本仓库跟踪；国内／海外平台插件在独立插件仓库维护。`plugins_user/match_sync` 等本机安装副本被忽略不代表其改动已经备份或提交。修改应落实到所属源码、验证并提交，再重新打包安装。
- `work/` 保存临时 worktree、构建文件和本机备份；这些内容不进入发布包。
- 打包前检查 `git status`、提交与版本号，按确定的 commit 构建；正式发布给该 commit 打版本标签。
- 发布说明记录源码 SHA、依赖或插件版本及验收范围。不要将开发目录里遗留的 EXE 当作最新构建。
