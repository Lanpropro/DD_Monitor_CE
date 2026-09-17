# DD Monitor CE 项目状态

更新时间：2026-09-17（Asia/Hong_Kong）
项目目录：`F:\\CodexAppManager\\Code\\DD_Monitor_CE`（仅本机路径）
远程仓库：`https://github.com/Lanpropro/DD_Monitor_CE`
当前分支：`main`

## 当前目标

等待另一个 Agent 完成竖屏适配修改；完成后先只读检查其最新提交与工作区，确认没有并发写入风险，再审查和验证竖屏适配。未经用户新指令，不主动推送远程仓库。

完成标准：

- 明确区分已提交成果、未提交并发修改和本任务自己的改动。
- 竖屏适配由负责该部分的 Agent 收拢后，再进行代码审查和相关测试。
- 后续每次修改均遵守根目录 `AGENTS.md`：有对应 Git commit，更新或补充测试，并在交付前验证。
- 每次修改后告诉用户如何验证；完成软件修改后自动重启验证。

## 已完成并确认

### 每格独立左右声道路由

- 提交：`91dd8ea feat(audio): route each tile to left or right output`
- 用户已经实际确认任务完成。
- `ddm/audio_output.py` 将每个直播的立体声混合为完整单声道，然后只送入物理左输出或右输出，避免 VLC 原生“左/右声道”仅选择源轨而丢失内容。
- `ddm/player.py` 通过 libVLC PCM 回调为每个播放格子建立独立输出；默认模式仍保持普通立体声。
- `requirements.txt` 新增 `sounddevice`；当前软件虚拟环境为 `F:\\CodexAppManager\\Code\\DD_Monitor-venv`。
- 自动测试：`dev/selfcheck_audio_routing.py`。
- 已通过：语法检查、PCM 路由、静音生命周期、真实 VLC 解码回调、`dev/selfcheck_volume_channel.py` 的菜单／运行时重应用／持久化检查。
- 软件已在提交后重启，进程曾为 PID 21376，启动日志未发现 `[音频输出]`、`PortAudioError` 等错误；PID 只代表当时状态，恢复时应重新核实。

## 当前版本与并发状态

保存材料时的 HEAD：`55a2520 fix(portrait): 修一批竖屏实机问题`，且 `origin/main` 同步指向该提交。其之前包括：

- `ec68ba9 fix(portrait): 顶部横栏收起时只留头像排`
- `d23affc test: 自检跟上「竖屏布局」这一栏`
- `7d489c0 feat(portrait): 竖屏布局 + 顶部横栏`
- `91dd8ea feat(audio): route each tile to left or right output`

保存时另一个 Agent 正在处理的未提交文件：

- `ddm/app.py`
- `ddm/widgets.py`
- `dev/selfcheck_portrait.py`
- `dev/_probe_controls.py`（未跟踪）
- `dev/_probe_strip_render.py`（未跟踪）
- `dev/mock_portrait.py`（未跟踪）
- `dev/portrait_mock.html`（未跟踪）

这些内容不是声道任务遗留，也未由源任务暂存。接手时必须重新运行 `git status --short --branch` 和 `git log -5 --oneline --decorate`；不要覆盖、暂存或提交仍属于另一个 Agent 的文件。

## 决定与限制

- 用户确认：同时使用 Codex 与 DeepSeek Harness 开发本项目。
- 用户确认：声道任务结束后先等待另一个 Agent 的竖屏适配修改。
- 用户确认：不自动上传／推送，只有用户明确要求时才推送。
- 项目规则：每次修改必须有对应 commit，并更新或补充相关测试，交付前验证通过。
- 并发原则：先辨认文件归属；只暂存本任务明确修改的路径，不能用清理命令处理他人的未提交工作。

## 接续动作

第一步只读执行：核对当前 `HEAD`、`origin/main`、工作区状态和另一个 Agent 的竖屏修改是否已经收拢。若上述文件仍有未提交改动，停止业务写入并报告仍在等待；若已经提交且工作区稳定，再阅读竖屏相关差异、运行其针对性测试，并向用户报告审查结果与手动验证方法。未经新授权不推送。
