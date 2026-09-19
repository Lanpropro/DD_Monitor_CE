# DD Monitor CE 项目状态

更新时间：2026-09-20（Asia/Hong_Kong）
项目目录：`F:\CodexAppManager\Code\DD_Monitor_CE`（仅本机路径）
远程仓库：`https://github.com/Lanpropro/DD_Monitor_CE`
当前分支：`main`
交接编号：`DDMCE-20260920-SPEEDUP-01`

## 当前目标（2026-09-20 登记）

用户要求：**优化代码，并让软件的关闭、启动更快** —— 现状是关闭时能肉眼看到
「一格一格把直播窗口拆掉」，然后窗口才消失。同时要求：**先做好备份，出问题能回到
最新可用版本**。

完成标准：

- 点关闭后窗口立刻消失，不再逐格可见地拆播放器；启动耗时同样有改善（以日志时间戳为准）。
- 每次改动都有对应 Git commit；新增或更新自检；交付前全部自检通过（根目录 `AGENTS.md`）。
- 保留可回滚版本（见下「版本与备份」）。
- 交付时说明「怎么验证」。

## 版本与备份（回滚用）

- **最新可用版本 = `5f7c1e6`**（`fix(freeze): 画面卡死检测不再截图`），也就是
  `origin/main`。该提交状态下：27/27 自检通过、`results\` 已出包并实测启动正常。
- 备份动作（2026-09-20 已完成）：
  - Git 标签 `backup-20260920-5f7c1e6`（**已推送**到 origin，指向上面的提交）。
    回滚：`git checkout backup-20260920-5f7c1e6`（或 `git switch -c hotfix backup-…`）。
  - 本地 exe 包备份：`results\backup\DDMonitorCE-v0.1-exe-5f7c1e6.zip`（240.7 MB，
    与当时 `results\DDMonitorCE-v0.1-exe.zip` 哈希一致）。
  - GitHub Release `v0.1` 的附件 `DDMonitorCE-v0.1-exe.zip` 仍在（本会话**没有**更新它）。
- **并发状态（重要）**：本地 `main` 比 `origin/main` 超前 5 个提交
  （`5f7c1e6..32ea784`），全部是**宣传片工程**（`videos/dd-monitor-ce-promo/`）；
  已确认这段时间**没有碰** `ddm/`、`dev/`、`main.py`、`requirements.txt`。
  工作区里还有宣传片工程的未提交改动／删除（`videos/…/.media/...`）。
  这些都不是本任务的改动：**不要 `git add -A`、不要提交或推送它们**，也不要
  `git push origin main`（会把别人未完成的宣传片提交一起推上去）。

## 权威资料

- `HANDOFF-PORTRAIT.md`：竖屏/顶部横栏、布局对映等决策与踩坑历史（E/D/C 编号表）。
- `idea.txt`：待做清单（第 6 条「交换画面秒切」已完成并删除；其余 1–8 条仍在）。
- `dev/selfcheck_*.py`：**27 个自检就是事实上的验收标准**；跑法见 `dev/run-checks.cmd`
  （离屏、`DDM_NO_SAVE=1`、`PYTHON_VLC_LIB_PATH=<仓库>\libvlc.dll`）。
- `logs/ddm-*.log`：运行日志；卡死/硬崩会自动写入 `[卡死]`（各线程调用栈）与
  `[崩溃]`（faulthandler）段，是排查用户侧问题的第一手材料。
- `dev/build_release.ps1`：出包脚本（默认输出 `results\`）；改动后必须保持 UTF-8 **BOM**。

## 决定与限制（本会话新增，均为用户已确认）

- 第一次启动的默认布局 = **1 主画面 + 5 小环绕**（`layouts.FIRST_LAYOUT = "corner"`）。
- 快捷键：`M` = 静音鼠标所在那一路；`Alt+M` = 只保留鼠标所在那一路的声音。
- 悬停预览**永远静音**：预览用独立的 libvlc 实例（`--aout=adummy --no-audio`）+
  `:avcodec-hw=none`，播放后再把音频轨关掉。
- 交换画面「秒切」= **两个格子换位置**（`WallGrid.tiles` 对调 + relayout），
  **不搬播放器、不碰 `set_hwnd`** —— 实测搬播放器会让画面不跟手，并让 VLC 冒出
  独立悬浮窗（会在 Alt+Tab 里出现）。
- 画面卡死检测**不再用 `video_take_snapshot`**（用户机器上正卡在它里面 7 秒 + 访问违例），
  改成读 `libvlc_media_get_stats` 的 decoded_video / displayed_pictures。
- 选了另一个方向的布局时，**窗口本身也变成那个方向**（含取消最大化）；布局菜单三栏
  （普通/弹幕/竖屏）都列出来。
- 鼠标命中格子的判断不用 `QApplication.widgetAt`（画面是 VLC 原生窗口，认不出来），
  改成光标坐标与格子矩形比。
- 老规矩仍然有效：**未经用户明确要求不更新 Release 附件**；`utils/config.json`
  是用户数据（含凭据），不读不写不提交；只用显式路径 `git add`。

## 进展与运行状态

已完成并验证：

- 上述全部改动均已提交并推送；`origin/main` = `5f7c1e6`。
- 最后一次全量自检：**27/27 通过**（`work\checks\*.log` 留有每项输出）。
- `results\` 已重打并验证：exe 包 624 MB；`DDMonitorCE-v0.1-exe.zip` 与
  `DD监控室CE-v0.1-exe.zip` 各 240.7 MB（哈希一致）；新 exe 启动日志为
  `[VLC] libvlc 3.0.12 Vetinari 硬件解码=开` / `[方向] 横屏 布局=corner` /
  `[崩溃] 崩溃转储已开启（faulthandler）`，交付目录里 logs/cache/utils/插件运行目录均已清空。
- 用户侧曾报的三个问题都已定位并修复（预览出声、预览卡死/悬浮窗、切换画布失效）；
  最新一次用户反馈（2026-09-20 两份日志）指向 `video_take_snapshot`，已按上面的方式改掉。

未开始：

- **关闭/启动提速**（本次任务的主体），尚未动代码。

## 接续动作

第一步（关闭提速），已核实的线索：

- `ddm/app.py` 的 `MainWindow.closeEvent()`：`players = list(self.players.values())`
  之后逐个 `player.release()`；`TilePlayer.release()` 里依次做 `player.stop()`、
  `player.set_hwnd(0)`、`player.release()` —— 这几步都是阻塞的 libvlc 调用（每格
  上百毫秒量级），而且都在主线程上，所以用户看到「一格一格关掉」。
  `closeEvent` 里还有 `self._wait_background()`（最多等 2.5 秒）与 `config.save()`。
- `ddm/app.py` 的 `main()`：`code = app.exec()` 之后才 `os._exit(code)`。
- 建议做法（待验证，不要照抄）：`closeEvent` **最开头先 `self.hide()`**（窗口立刻消失，
  用户不再看到逐格拆），再按现有顺序收尾；必要时先把各格 `video` 子窗口隐藏/摘掉画面，
  最后统一释放播放器。改动要有量化依据（用日志时间戳量关闭耗时，别凭感觉）。

验收方法：

- 手感：点关闭后窗口立刻消失。
- `dev/run-checks.cmd`（27 项）全绿；为「closeEvent 先隐藏窗口」补一条自检钉住。
- 出包：`dev/build_release.ps1` 通过（含 20 秒实跑校验 + `[方向]` 日志）。

不要重走的路（已验证无效或有副作用）：

- 用 `QThread.terminate()` 收掉取流线程（会造成线程本地存储损坏、主线程卡死）。
- 正在播时把播放器 `set_hwnd` 到别的窗口、或「关视频轨再重建」来搬画面
  （画面不跟手，还会让 VLC 冒出独立悬浮窗）。
- 用 `video_take_snapshot` 做画面指纹（用户机器上卡 7 秒 + 访问违例）。

## 交接登记

- 交接编号：`DDMCE-20260920-SPEEDUP-01`
- 源任务编号：未提供
- 用户确认范围：完整交接 —— 保存材料，并在本项目**新建接手任务继续**（用户先输入「执行交接」，再明确「新建 然后交接」）。
- 接手任务编号：`04f970d1-51c9-4d9e-93fd-7e16028b80cf`
- 交接实现方式：本宿主（DeepSeek Harness）**没有** Codex 的 `list_projects` / `create_thread` / `navigate_to_codex_page` 等接口；用等价能力执行 —— 在本会话内新建一个**独立上下文、不带本对话历史**的接续任务（正是交接要求的形态），先做只读核验轮，再由源对话发出继续指令、移交修改权。用户若想换成独立的界面会话，可用本页「接续动作」前那段可复制开场白自行新建。
- 交接状态：已创建，等待接手核验（源对话在核验通过前不推进业务、不交出修改权）

---

# 上一份交接记录（2026-09-17，声道任务 → 竖屏适配，原样保留）

> 以下内容是 2026-09-17 那次交接登记的原文，属于当时那个任务的事实快照。
> 其中的 `HEAD`/`origin/main` 早已过时（见本页顶部的版本与备份），保留仅为追溯。

## 当前目标（2026-09-17）

等待另一个 Agent 完成竖屏适配修改；完成后先只读检查其最新提交与工作区，确认没有并发写入风险，再审查和验证竖屏适配。未经用户新指令，不主动推送远程仓库。

完成标准：

- 明确区分已提交成果、未提交并发修改和本任务自己的改动。
- 竖屏适配由负责该部分的 Agent 收拢后，再进行代码审查和相关测试。
- 后续每次修改均遵守根目录 `AGENTS.md`：有对应 Git commit，更新或补充测试，并在交付前验证。
- 每次修改后告诉用户如何验证；完成软件修改后自动重启验证。

## 已完成并确认（2026-09-17）

### 每格独立左右声道路由

- 提交：`91dd8ea feat(audio): route each tile to left or right output`
- 用户已经实际确认任务完成。
- `ddm/audio_output.py` 将每个直播的立体声混合为完整单声道，然后只送入物理左输出或右输出，避免 VLC 原生“左/右声道”仅选择源轨而丢失内容。
- `ddm/player.py` 通过 libVLC PCM 回调为每个播放格子建立独立输出；默认模式仍保持普通立体声。
- `requirements.txt` 新增 `sounddevice`；当前软件虚拟环境为 `F:\CodexAppManager\Code\DD_Monitor-venv`。
- 自动测试：`dev/selfcheck_audio_routing.py`。
- 已通过：语法检查、PCM 路由、静音生命周期、真实 VLC 解码回调、`dev/selfcheck_volume_channel.py` 的菜单／运行时重应用／持久化检查。
- 软件已在提交后重启，进程曾为 PID 21376，启动日志未发现 `[音频输出]`、`PortAudioError` 等错误；PID 只代表当时状态，恢复时应重新核实。

## 当前版本与并发状态（2026-09-17）

接手核验时：`HEAD` 为 `0274e18 docs: prepare handoff continuation`，`origin/main` 为 `46e9c26 fix(portrait): 横向卡片条 + 回横屏左栏恢复 + 主画面不再被压扁`；当前分支 `main` 较远端超前 4 个文档提交。工作区没有已跟踪文件改动，但仍有以下未跟踪竖屏原型文件：

- `dev/mock_portrait.py`
- `dev/portrait_mock.html`

因此竖屏适配尚未视为完全收拢，接手任务保持只读等待，暂不进入业务审查或测试。

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

## 决定与限制（2026-09-17）

- 用户确认：同时使用 Codex 与 DeepSeek Harness 开发本项目。
- 用户确认：声道任务结束后先等待另一个 Agent 的竖屏适配修改。
- 用户确认：不自动上传／推送，只有用户明确要求时才推送。
- 项目规则：每次修改必须有对应 commit，并更新或补充相关测试，交付前验证通过。
- 并发原则：先辨认文件归属；只暂存本任务明确修改的路径，不能用清理命令处理他人的未提交工作。

## 接续动作（2026-09-17）

已完成接手核验：当前仍有未跟踪竖屏原型文件，故停止业务写入并等待负责 Agent 收拢。收拢后重新核对 `HEAD`、`origin/main`、`git status --short --branch` 和 `git log -5 --oneline --decorate`，再阅读竖屏相关差异并运行针对性测试；未经新授权不推送。

## 交接登记（2026-09-17）

- 交接编号：`DDMCE-20260917-PORTRAIT-CONTINUE-01`
- 源任务编号：未提供
- 用户确认范围：保存当前进度，在同一项目原目录新建任务并继续；当前继续范围为等待、核对并在竖屏适配收拢后审查验证。
- 接手任务编号：`01a0affe-9021-7391-ba8c-a828e9801df4`
- 交接状态：已接手
