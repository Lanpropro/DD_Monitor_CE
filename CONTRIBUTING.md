# 开发与贡献

## 分支和目录

当前主要开发分支是 `main`，版本标签（如 `v0.4`）和 GitHub Releases 标识正式发布版本。
`main` 上的开发进度不表示已经发布了同版本的 EXE。

分支是同一仓库中的代码历史，不是文件夹。先检查当前目录与分支：

```powershell
git status --short --branch
git branch --show-current
git worktree list
```

- 维护者的小修改可以直接在 `main` 完成、验证、提交，不强制创建 Draft PR。
- 一项独立功能或修复使用 `function/<名称>`，如 `function/emoticon-tabs`。
- 外部贡献通过 PR 提交到 `main`。未完成时可使用 Draft；准备好审查后使用普通 PR。
- 多项任务同时进行时，使用独立 worktree 和分支；不要让测试目录与日常开发目录互相覆盖。
- 合并后的功能分支可在确认不再被 worktree 使用后删除；备份和未合并成果先保留。

## 日常开发

1. 先检查未提交内容。工作区未归类清楚时，不切换分支或拉取合并。
2. 在干净且已同步的 `main` 上开始小修改，或创建 `function/<名称>`。
3. 修改一项内容，补充相关测试，并执行与改动对应的验证。
4. 检查差异，按文件或交互式暂存，创建一个能独立说明的提交。
5. 结束开发前再次检查状态，说明剩余文件属于源码、未完成内容还是本机资料。

```powershell
git add -p
# 新增文件需要明确指定路径添加。
git diff --cached
git diff --cached --check
git commit -m "fix(sidebar): correct selection marker position"
```

提交前缀可使用 `feat:`、`fix:`、`perf:`、`test:`、`docs:`、`chore:`。
未完成工作可在功能分支保存为 `wip:`；提交是保存进度，发布需要单独验收。

## PR 集成

- 描述目的、修改范围、相关问题、验证命令和已知限制；界面修改提供截图或复现步骤。
- PR 依赖另一个 PR 时，在描述中写明顺序，依赖解决前保持 Draft。
- 集成时核对作者的最新提交 SHA；本地曾经 cherry-pick 某一版本，不代表已经包含后续更新。
- 在测试分支或 worktree 中验证组合后的代码，保留贡献者信息与原 PR 链接。
- 独立功能通常使用 squash merge；需要保留多个提交或处理分支历史时逐项决定，不强制改写已共享历史。
- 不强推 `main`，不以整树覆盖的方式忽略远端改动，也不自动关闭仍未完成核对的 PR。

## 验证范围

基础仓库检查仅依赖 Python 和 Git，不联网、不读取个人配置：

```powershell
python -m unittest dev.selfcheck_repository_files dev.selfcheck_project_workflow
python -m compileall -q ddm blivedm main.py
git diff --check
```

GitHub Actions 执行以上基础检查。这些检查不能替代功能、原生播放和真实直播验收。

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
