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

`function/v0.4.1` 是本次整理得到的 **0.4.1（未发布）** 对照快照，内容已在主线历史中，不需要再次合并。软件内版本号暂未修改；后续任务从最新 `develop` 创建自己的分支。

分支是同一仓库中的代码历史，不是文件夹。先检查当前目录与分支：

```powershell
git status --short --branch
git branch --show-current
git worktree list
```

- 维护者的小型文档或注释修改可以直接在 `develop` 完成、验证、提交，不强制创建 PR 或 Draft PR。
- 一项独立功能或修复使用 `function/<名称>`，如 `function/emoticon-tabs`。
- 功能、修复和外部贡献通过 PR 提交到 `develop`。未完成时可使用 Draft；准备好审查后使用普通 PR。
- 准备发布时，验证完整的 `develop`，再通过 PR 合入 `main`；已有面向 `main` 的 PR 先检查依赖与差异，再决定是否调整目标。
- PR 模板区分日常贡献与发布；创建时核对 GitHub 的 base，日常贡献选择 `develop`，发布选择 `main`。
- 多项任务同时进行时，使用独立 worktree 和分支；不要让测试目录与日常开发目录互相覆盖。
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

GitHub Actions 执行以上基础检查。这些检查不能替代功能、原生播放和真实直播验收。

使用 `python dev/run_checks.py --list` 查看已审查的测试套件。完整命令、依赖与全部专项脚本的分类入口见[验证指南](docs/development/testing.md)。新增测试同步更新分类索引；确认隔离条件后再纳入批量套件。

涉及界面、账号或播放的专项检查应使用独立测试数据，通常设置：

```powershell
$env:DDM_NO_SAVE = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
```

需要原生 Windows 视频窗口时使用 `QT_QPA_PLATFORM=windows`。
真实直播、音频听感、高 DPI 和跨屏检查单独列出；未执行或未通过的项目明确说明。
测试不向公开直播间自动发送消息，不使用真实 Cookie 作为测试数据。

## 本机资料与发布

- `utils/`、缓存、账号、皮肤、安装中的插件和插件更新备份只保留在本机，不进入源码提交。
- 插件源码在独立插件仓库维护；本机安装副本被忽略不代表其改动已经备份或提交。
- `work/` 保存临时 worktree、构建文件和本机备份；这些内容不进入发布包。
- 打包前检查 `git status`、提交与版本号，按确定的 commit 构建；正式发布给该 commit 打版本标签。
- 发布说明记录源码 SHA、依赖或插件版本及验收范围。不要将开发目录里遗留的 EXE 当作最新构建。
