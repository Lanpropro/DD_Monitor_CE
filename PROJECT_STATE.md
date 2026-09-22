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
- `idea.txt`：待做清单，现为 7 条 —— 1 发送弹幕 / 2 录像（含单格独立录制方案）/
  3 接别的直播平台 / 4 自定义布局 / 5 正在播放的卡片要能一眼看出来 /
  6 右键卡片用默认浏览器打开直播间 / 7 全局音量·画质按钮。
  （原第 8 条「修复搜索栏」已完成，按约定从清单里删掉了。）
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

本次任务（关闭/启动提速，`DDMCE-20260920-SPEEDUP-01`）已完成：

- `cee6160` 关闭提速：`closeEvent()` 最开头先 `self.hide()`，窗口 ~2 ms 内消失
  （`[关闭]` 日志量化），随后照旧收尾释放播放器；`selfcheck_close_release.py` 钉住
  「先隐藏窗口」。
- `89d8d95` 启动提速：`build_rooms()` 不再启动时同步逐个拉房间（单个超时 10 秒），
  改成只造占位条目、窗口立刻出现，真实信息由 `refresh_status()` 后台批量补齐
  （侧栏/画面格补主播名+标题+直播时长）。新增 `dev/selfcheck_startup.py`。
- `2aa1a0e` 启动量化：`main()` 打印 `[启动]` 各阶段耗时（日志时间戳）。
- `f1f866c` 减占用：设置里关掉「悬停预览」时不再建第二个 libvlc 实例。
- `222a3d5` 修崩溃：用户最新日志（13:38 段）里 `[预览音频] mute=-1 …` 之后
  `access violation` —— 悬停预览（silent）对 `--no-audio` 实例（没有 aout）调
  `audio_set_track` / `set_mute` / `set_volume` / `get_*` 触发。改成 silent 播放器
  完全不再碰 libvlc 音频接口（`--no-audio` 已保证静音），新增
  `dev/selfcheck_preview_audio.py` 钉住。
- 自检现状：全量 29 项里 28 项稳定通过；`selfcheck_plugins.py` 因本机沙箱限制
  `tempfile.mkdtemp`（建出的目录 ACL 拒绝写子目录）无法运行，与本任务改动无关。
  未推送、未更新 Release 附件、未碰 `utils/config.json`。

用户实测反馈的后续修复（同一会话，均未推送）：

- 秒切后音量条跟着画面走（`739dcb9c` 起就有的老毛病）：`_hot_swap()` 只换了
  `tile.room` 和播放器，没刷新音量条控件 —— 画面换了、声音也对了，但条子还停在
  原位。新增 `Tile.sync_audio_ui()` 在换位后按各自状态重画（不触发信号），
  `dev/selfcheck_settings_status.py` 钉住。
- 取消一个格子的静音，却把别的格子（含布局缩小后已隐藏的格子）一起解除了静音：
  隐藏的格子只是 `setVisible(False)`、幕后仍在播放，而换位时
  `muted/volume/audio_channel` 没跟着画面走。现在 `_sync_tile_playback()` 会把
  没上墙的格子真的停掉（换布局时顺带启动新上墙的），`_hot_swap()` 把音量、静音、
  声道一起跟着画面走。
- 启动时对所有已在播的房间弹「开播了」：`build_rooms()` 改成占位条目之后，
  第一次状态刷新被当成了「离线 → 开播」。用 `room["live_known"]` 抑制首轮
  （只有真的离线转开播才提示），`dev/selfcheck_startup.py` §3b 钉住。
- 关注栏拖动时不能自动滚动、拖动中滚轮无效：`RoomListBox.auto_scroll()` 改按
  **视口**边缘滚动（原来错用内容高度，往下永远不触发）；拖动期间的滚轮用临时
  `WH_MOUSE_LL` 钩子接管（`ddm/mouse_hook.py`，只读、不吞事件），因为 Qt 的
  `QDrag::exec()` 走 Windows OLE `DoDragDrop`，拖动中滚轮事件根本到不了控件。
  新增 `dev/selfcheck_drag_scroll.py`、`dev/selfcheck_drag_wheel.py`。
- 封面慢 / 未开播没封面（本次）：以前只在状态刷新拿到 URL 后才下载封面，而未开播
  的房间接口压根不给封面（实测 `rooms_status` 对未开播房间返回空 `cover_url`），
  所以启动时卡片空着、主播没开播就没图。现在除按 URL 缓存外再按**房间号**留一份
  （`cache/covers/room/<房间号>.png`），`load_cached_covers()` 在窗口出现后
  120 ms 就把上次那张顶上，不必等状态轮询；封面同时改走 B 站 CDN 缩放后缀
  （`@412w_232h.webp`，实测原图 52.8 KB → 8.1 KB），取不到会自动退回原图。
  新增 `dev/selfcheck_cover_cache.py`。
- 横屏切到竖屏逛一圈再切回来，横屏的布局被改掉（用户报的「布局被改了」）：
  `layouts.counterpart()` 是**按容量就近折算**的，横屏「主画面 + 5 小环绕」和
  「六分」都是 6 路，从竖屏折回来平手取到排在前面那个（六分）—— 新用户默认就是
  corner，一转就变六分。现在 `_apply_orientation()` 把「切走之前在用的那套」记在
  原方向名下（`_layout_by_orientation`），切回来优先还原；只有本次会话第一次进
  某个方向时才按容量折算（保住上一轮修的「进竖屏要跟着横屏走」）。另外
  `_on_layout_changed()` 在转窗口前先把用户选的那套挂成 `_pending_layout`，
  否则刚选的会被还原逻辑顶掉。新增 `dev/selfcheck_orientation_layout.py`（6 节）。
- 搜索栏（`idea.txt` 原第 8 条）从纯摆设变成能用：按主播名 / 房间号 / 直播间
  标题过滤，大小写不敏感，空格分开的多个词要全中。做法是给 `NavItem` 加
  `filtered_out`，`RoomListBox.relayout()` 直接跳过被过滤的条目 —— **不能靠
  `setVisible` 来过滤**，因为 relayout 每摆一张卡都会把它重新显示出来。过滤只藏
  不排：条目顺序、置顶、多选态都不动，`Sidebar.resort()`（状态刷新的出口）里先
  重算标记再摆位置，所以刷新之后过滤依然生效。列表一条不剩时在列表位置摆一句
  提示（`RoomListBox.empty_hint`，样式 `#FilterHint`），计数写成
  「露出来几路 / 一共几路」；竖屏顶部那排头像也跟着过滤。回车把焦点交给列表，
  Esc 等价于点清空按钮，进多选态会自动清掉搜索（免得批量删掉看不见的条目）。
  新增 `dev/selfcheck_search.py`（10 节）。注意 `QShortcut` 在 Qt6 属于
  `QtGui` 而不是 `QtWidgets`。
- 音量曲线从 VLC 的三次方改成**线性**（用户反馈「音量条调节很难受」）：三次方
  曲线下 50% 只有约 12.5% 音量、30% 只有约 2.7%，声音全堆在最后 20~30%，前面拖了
  没反应、后面突然响。现在原生输出路径在 `_apply_volume` 里先把滑块值取**立方根**
  再交给 `libvlc_audio_set_volume`（`linear_to_vlc_volume`），抵消 VLC 内部的三次方；
  PCM 回调路径（仅左/仅右）的 `apply_volume_s16_stereo` 直接乘 `v/100`。两条路径
  最终都是「滑块值/100」的线性增益。用 `work/probe_volume_curve.py` 实测确认过：
  `libvlc_audio_set_volume` 对回调样本**完全不起作用**（volume 从 10 到 100，回调
  峰值都是满幅），所以手动曲线是回调路径的唯一曲线，不存在双重三次方。
- 竖屏窄格子里控制条错位（用户截图）：`_layout_areas()` 以前在「LIVE 浮标 +
  控制条」放不下第一行时，把控制条**折到第二行**（y = 8 + BADGE_HEIGHT + 6 = 38）
  —— 竖屏小格子普遍 282 宽，必然触发：按钮跑出右上角，还压住画面中间的状态文字
  （「连接失败」）。而且判定浮标要不要收窄时只算了浮标自己
  （`width < full_width() + 20`），**没把控制条的宽度算进去**，明明两者加起来
  放不下却判定成放得下。现在反过来：控制条永远钉在右上角（y=8），空间不够让
  **浮标**让位（`_sync_stream_badge()`：先收起人数，再整个收起来；浮标的宽度和
  显隐**只由它一个地方决定** —— 以前散在四处各设各的，漏一处就会出现「放不下却
  还露着」压住控制条）。新增
  `dev/selfcheck_tile_overlay.py`，钉住「控制条在右上角 / 不压信息条 / 不溢出 /
  不压浮标」。
- 静音串台 + 声道归属（用户报「开这格的静音，旁边那格声音也不对了，标志却还
  亮着」）：音量 / 静音 / 声道 / 画质这几个回调都用 `_tile_of(room_id)` **反查**
  格子。同一个直播间占了两个格子时（配置里存重了、或同一张卡片被拖上两次），
  反查只会命中列表里第一个 —— 静音因此下发给了另一格，操作的那一格反倒还在出声，
  而标志画在自己身上照样亮着。探针实测复现后改成用**信号来源**定位
  （`_sender_tile()`，这些信号都是直接连接的），反查只留作兜底。顺带修一处：
  `Tile.set_room()` 换台时原来用新房间的 `audio_channel` 覆盖格子，会把用户调好的
  「只播左 / 只播右」丢掉 —— 声道和音量 / 静音一样属于格子，现在写回格子自己那份。
  新增 `dev/selfcheck_audio_owner.py`（4 节）。
- 自检现状：全量 **37 项里 36 项通过**，唯一失败的仍是 `selfcheck_plugins.py`
  （原因同上，与本轮改动无关）。未推送、未更新 Release 附件、未碰
  `utils/config.json`。
- 跑自检的正确姿势（踩过的坑）：照 `dev\run-checks.cmd` 原样跑 —— 只设
  `DDM_NO_SAVE=1`、`PYTHON_VLC_LIB_PATH`、`PYTHONIOENCODING=utf-8`，
  **不要自己加 `QT_QPA_PLATFORM=offscreen`**。只有
  `selfcheck_audio_routing.py` / `build_brand_assets.py` 自己用 `setdefault`
  设离屏；强行全局设会把虚拟屏压成 800x800，害得
  `selfcheck_live_alert` / `selfcheck_nav_layout` / `selfcheck_portrait` /
  `selfcheck_ui3` 在窗口几何和像素检测上误报失败。

## 接续动作

关闭/启动提速（`DDMCE-20260920-SPEEDUP-01`）和随后用户实测反馈的 7 个问题
（静音串台、秒切后音量条、隐藏格子仍在播、拖动自动滚动、拖动中滚轮、启动误弹
开播提示、封面慢/未开播没图）都已修完，全量自检 33 项 32 通过（唯一失败的
`selfcheck_plugins.py` 是本机沙箱限制）。**当前没有必须马上做的改动。**

接下来按 `idea.txt` 挑（8 条，用户自己排的队）。其中「8 修复搜索栏」卡点最少 ——
控件和样式都已经在 `ddm/widgets.py` / `ddm/theme.py` 里躺好了，只差过滤逻辑
（`ddm/app.py` 里一处 search 都没有）；插件接口的细节看 `docs/plugins.md`。

不要重走的路（已验证无效或有副作用）：

- 用 `QThread.terminate()` 收掉取流线程（会造成线程本地存储损坏、主线程卡死）。
- 正在播时把播放器 `set_hwnd` 到别的窗口、或「关视频轨再重建」来搬画面
  （画面不跟手，还会让 VLC 冒出独立悬浮窗）。
- 用 `video_take_snapshot` 做画面指纹（用户机器上卡 7 秒 + 访问违例）。

## 交接登记

- 交接编号：`DDMCE-20260920-SPEEDUP-01`
- 源任务编号：`session-00eec372-c207-4804-8d7d-19ae7610a913`（DSH 会话，仅本机）
- 用户确认范围：完整交接 —— 保存材料，并**在新对话里接手继续**（用户先输入「执行交接」→「新建 然后交接」→「新建新对话交接」）。
- 接手任务编号：**待用户在新对话中建立**。本宿主（DeepSeek Harness Desktop 0.9.0）没有创建界面会话的接口：`resources\app` 里没有 bin / CLI，只有 GUI 界面，也没有 Codex 那套 `create_thread` / `navigate_to_codex_page` 工具。因此**不擅自改 DSH 的会话存储去伪造一个会话**，改为交付可复制开场白（见下）。
- 已做的等价动作：在本会话内新建过一个**独立上下文、不带历史**的只读核验任务 `04f970d1-51c9-4d9e-93fd-7e16028b80cf`（只核对目录/HEAD/备份标签/并发状态/材料一致性）。它是核验员，**没有**拿到业务修改权；用户要的是新对话接手，所以业务工作**不要**交给它做，也不要在源会话里开工。
- 交接状态：材料已核对，等待用户在新对话中接手核验

## 新对话的入口（把下面整段贴进新对话的第一条消息）

    执行交接核验：项目 F:\CodexAppManager\Code\DD_Monitor_CE，交接来源 PROJECT_STATE.md 顶部的
    「当前目标（2026-09-20 登记）」与「交接登记」，交接编号 DDMCE-20260920-SPEEDUP-01。
    先只读核对：
      1) 目录/分支/HEAD，与 origin/main 的关系，备份标签 backup-20260920-5f7c1e6 是否存在；
      2) git diff --stat 5f7c1e6..HEAD -- ddm dev main.py requirements.txt 是否为空（应为空）；
      3) 并发状态：本地 main 上有别人的宣传片提交、工作区有别人的未提交改动，
         只 git add 显式路径，禁止 git add -A，禁止 git push origin main，
         不碰 utils/config.json，不更新 GitHub Release 附件；
      4) 本任务已确认的限制与「不要重走的路」（见 PROJECT_STATE.md）。
    返回：差异清单 + 你打算的第一步（一句话），本轮不要改业务文件。
    核验通过后按「接续动作」执行第一步：让关闭窗口瞬间完成（先在 closeEvent 最开头隐藏窗口，
    再收尾释放播放器），并用可量化依据说明关闭耗时；随后继续原目标（启动也更快），
    每次改动都要 commit + 自检，交付前 27 个自检全绿。

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
