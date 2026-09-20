# 录屏会话 · 当前状态与下一步

更新时间：**长素材已录到第一条**（画面可用，声音待确认）
素材目录：`videos/dd-monitor-ce-promo/raw/`

## 现在的状态（先看这段）

`raw/take.mp4` —— **一条 239 秒的连续长素材，画面已验证可用**：

- HEVC + AAC，3840×2160，239.0 秒，288MB；逐事件表 `raw/take-events.json`（64 步全中）。
- 画面抽查（`raw/frames/` 的联系表）：空墙 → 单格 → 四分 → 九分 → 1+5 → 弹幕布局
  → 横→竖→横（竖屏那一瞬窗口在屏幕中央，两侧露桌面）→ 反回九分，
  各状态都真实出现。**唯一瑕疵**：竖屏那几十秒窗口只有屏幕中部一条，
  成片里必须裁到窗口区域（本来就是按窗口裁的，问题不大）。
- **声音是空的（-91dB 全程）**：录之前按进程静音是对的，但计划里"要出声"那一拍
  没能把它放出来。原因已定位：`mute-app.py` 是按**进程名**找音频会话的，
  实测会同时命中多个 pythonw 会话（有的 MUTED 有的 unmuted），
  解静音可能落到别的会话上。**下一轮修法**：驱动器里改成按
  **进程 ID**（读窗口的 PID）挑会话，而不是按名字。
- 因此：如果成片这两拍（分镜 10/11）本来就要听直播的人声/音乐，
  这条素材的声音不能直接用；如果只要"音量条/静音图标"的画面变化（不需要真声音），
  这条已经够用。

## 已确认的决策

**改用"一条连续长素材"**，不再切成七八个独立片段。理由：

1. 全片的 spine 是「同一个窗口」——分镜里写死了。一条连续素材天然满足；切成多段再拼，
   接缝处窗口位置/内容会跳。
2. 布局那一段（分镜 03–06）本来就是「1→4→9→1+5→弹幕」的连续演化，不切最有说服力。
3. 真实感更强：这是一次真实使用过程，不是"一个功能演示一段"。

剪辑时从**同一条** `raw/take.mp4` 里取时间窗，喂给各拍。

## 各拍该从 take.mp4 的哪一段取（照着 take-events.json 划的窗）

| 拍 | 素材 | 取窗（秒） |
| --- | --- | --- |
| 01 墙面亮起 / 02 标题底 / 12 重连 | `rec-wall-build` | 4–12（空墙→第一格亮）或 42–66（逐格填满九分） |
| 03 单画面→四分 | `rec-layout-1to4` | 13–18 |
| 04 九分 | `rec-layout-9grid` | 37–42 与 66–70 |
| 05 大带小 1+5 | `rec-layout-bigplus` | 72–84 |
| 06 弹幕进墙 | `rec-layout-danmaku` | 88–96 与 96–110（弹幕在滚） |
| 07 拖成竖屏 | `rec-portrait-flip` | 112–132（竖→横连续过程在里面） |
| 08 弹幕面板特写 | `rec-danmaku-panel` | 96–110（弹幕格那半屏，4K 母版可推近） |
| 09 关注列表 | `rec-follow-list` | 141–165（四次悬停，每次停 5 秒） |
| 10 单格音量/静音 | `rec-tile-audio` | 175–192（音量按钮左键两次） |
| 11 左右声道 | `rec-channel-route` | 200–222（只播左→只播右→默认） |

## 已到手的素材

| 文件 | 说明 |
| --- | --- |
| `raw/take.mp4` | **239 秒连续长素材**，3840×2160，HEVC+AAC。画面已验证；声音全程 -91dB（见上） |
| `raw/take-events.json` | 64 步动作时刻表（每步的秒数 + 命中控件名），剪辑按它取窗 |
| `raw/session4.mp4` | 187.5MB，93 秒，7 个布局状态命中（可用，但覆盖不了关注悬停以外的细节） |

## 仍缺的镜头与已定位到的触发方式

| 镜头 | 触发 | 代码位置 |
| --- | --- | --- |
| 弹幕布局（1+1+弹幕） | 布局菜单里切到「弹幕布局」标签页再选卡片 | picker 标签页窗口内约 (236,1538)，**卡片坐标未量** |
| 单格音量 / 静音 | **左键**点格子底栏的音量按钮 | `widgets.py:3949` `VolumeButton(size=26)` 加进 `bottom_layout`；左键 `_toggle_mute` |
| 左/右声道路由 | **右键**点同一个音量按钮 | `widgets.py:2141` `contextMenuEvent`；按钮上画 `L`/`R` 指示 |
| 断流重连 | 不好演，分镜里已决定用界面特写 + 字幕带过 | — |

## 录制顺序（按分镜拍序走一遍）

```
1. 空墙起步 → 逐格亮起         (01)
2. 布局：单画面 → 四分 → 九分  (03–04)
3. 大带小 1+5                  (05)
4. 弹幕布局 1+1+弹幕           (06)
5. 拖成竖屏 → 回横屏           (07)
6. 弹幕面板推进                (08)
7. 关注列表悬停/置顶/拖动        (09)
8. 单格音量 → 静音             (10)   ← 这两拍保持有声
9. 左/右声道切换               (11)   ← 这两拍保持有声
```

**机器约束**（都已实测，写进 `tools/record-session.ps1` 注释）：

- 系统缩放 150%：逻辑 1920×1080 → 物理 2880×1620
- 软件启动几秒后会恢复 `saveGeometry` 的最大化状态，把刚摆好的尺寸顶掉
  → 等它恢复完再摆；**每次开菜单前重新摆回 2880×1620**，否则菜单坐标失效
- 软件会自己挪窗口位置 → 点击/悬停一律「实时查窗口矩形 + 窗口内相对坐标」
- 桌面其他窗口会盖住软件、模拟点击会打偏 → 录制期间常驻 `HWND_TOPMOST`；
  `resize` 之后要补一次（`Front()` 结尾会摘掉）
- dshow 无回环设备 → 声音走 `tools/loopback-rec.py`（soundcard 的 WASAPI 回环）
- 软件的画面墙格子显示「已静音」但实际仍出声（实测：关掉软件回环从 -32dB 掉到 -91dB）
  → 需要它安静时用 `tools/mute-app.py` 按进程静音；需要有声时 `unmute`
- PS 5.1 按 ANSI 读无 BOM 的 `.ps1` → 脚本必须带 UTF-8 BOM，**每次编辑后要补回**
- **合成鼠标在这个环境里被挡**（见下节）→ 录制不能靠 `mouse_event`

## 坐标口径（实测钉死，别再凭直觉改）

1. `tools/measure-ui.py` 量的「窗口内坐标」= Qt `mapToGlobal` 的差（客户区原点口径）；
   `record-session.ps1` 用 `GetWindowRect` 左上角 + 窗口内坐标，两个同口径。
2. Qt 的 `mapToGlobal` 给的就是**屏幕物理像素**（缩放 150% 时**不要**再乘 1.5 ——
   乘了会整整偏 1.5 倍，表现是「动作都做了、一个都没点中」；这个坑踩了两轮）。
3. 布局预设按钮：窗口内 **(95, 967)**（实测尺寸 166×36 @ 窗口内 12,949）。
   弹层弹在它**上方**：窗口内 y ≈ 635–971，所以点按钮那一下（y=967）不会被弹层吃掉；
   弹层里的卡片坐标见 `raw/ui-metrics.json` 的 `picker.groups`。
4. 右键菜单弹在光标处，菜单项偏移见 `ui-metrics.json` 的 `menus`；
   格子的音量/声道菜单是 **Tile** 的菜单（右键冒泡到格子），不是按钮自己的。
5. 复算工具：`tools/diagnose-clicks.py`（用 `QApplication.widgetAt` 反查命中）、
   `tools/measure-frame-map.py`、`tools/measure-picker-rect.py`。

## 关键阻塞：合成鼠标在本环境点不动窗口

实测（`tools/check-synth-input.py` + `tools/check-qt-inject.py`）：

| 手段 | 结果 |
| --- | --- |
| `SetCursorPos` + `mouse_event` | 光标到位、窗口前台，但按钮**收不到点击**（自建小窗口也一样） |
| `PostMessageW` WM_LBUTTONDOWN/UP | 同样收不到 |
| `QTest.mouseClick`（进程内） | **有效**（clicked 信号来了） |
| `QTest` 按下/移动/松开 | **有效**（拖动事件按序到达） |
| `QApplication.sendEvent(QMouseEvent)` | **有效** |

也就是说：`record-session.ps1` 那条「系统级鼠标」的路在这个沙箱里走不通；
上一轮 `session4.mp4` 能用，是用户自己动手点的鼠标。

**已按 A 落地**：`tools/drive-take.py` 在软件进程里驱动动作，`tools/shoot-take.ps1`
一条命令录完（画面 + 声音 + 动作 + 合流）。B 那条（手动操作）留给以后要"最真实
鼠标轨迹"的镜头。

### 驱动器的两条实测规则

- **按控件身份选目标，不按像素碰运气**：格子几何随布局变（1x1 时 tile0 是
  1625×1011、九分时 536×332），动作计划里写 `target`（控件名）/`pick`（类别）。
- **菜单项直接 `trigger()`**：QTest 往 QMenu 上打点击不生效（实测点了声道没变）。
  菜单照样弹出来、光标照样停在那一项上，成片里看不出区别。
- 菜单里有个**文字为空**的自定义控件项（音量滑条）：匹配菜单文字时
  **空文字永远不算命中**，且只允许"目标文字被包含"（精确优先），不做反向包含。

## 常用命令

```powershell
# 起点准备（备份 / 空墙+单画面 / 录完还原）—— 改配置前必须先退出软件
powershell -File tools/prep-take.ps1 backup|empty|restore|show

# 录一条连续长素材（ddagrab 画面 + WASAPI 回环声音 + 进程内动作 + 合流）
powershell -File tools/shoot-take.ps1
# 产物：raw/take.mp4（成片素材）、raw/take-events.json（每步的秒数，剪辑取窗用）

# 只驱动动作、先验证（不录画面）
python tools/drive-take.py --plan tools/take-plan.json --mode picker --lead 2
python tools/drive-take.py --plan tools/test-plan-picker.json --mode picker   # 布局弹层
python tools/drive-take.py --plan tools/test-plan-tile.json --mode tile       # 音量/声道

# 量控件坐标（写 raw/ui-metrics.json：卡片、音量按钮、菜单项偏移）
python tools/measure-ui.py

# 按计划坐标"真点"并核对命中（不需要人看截图，直接查控件状态）
python tools/diagnose-clicks.py

# 逐步截图核对（注意：Qt::Popup 抓不进 GDI 截图，只能看主窗口变化）
powershell -File tools/verify-clicks.ps1 -PlanFile tools/verify-plan.json -Launch

# 按进程静音/解静音软件的音频会话
python tools/mute-app.py python mute|unmute|status

# 组装成片（唯一正确入口：先 restore 视频再 assemble，否则视频会被吞掉、全片黑屏）
node tools/assemble.mjs . "C:\Users\Lan\.agents\skills\product-launch-video"

# 渲染
npx hyperframes render --skill=product-launch-video --quality high -f 24 --output renders/video.mp4
```

## 本轮已就位的东西

- `tools/take-plan.json` —— **一条连续长素材**的完整动作计划（0–228 秒，按分镜拍序走：
  空墙 → 逐格亮起 → 单画面 → 四分 → 九分 → 1+5 → 弹幕布局 → 竖屏 → 回横屏 →
  关注列表悬停 → 九分 → 单格音量/静音 → 左/右声道 → 归位）。
  两声"要出声"的拍由计划里的 `mute` 动作控制（`unmute` / `mute`）。
- `tools/prep-take.ps1` —— 起点/还原配置（空墙 1 格 + 单画面），关注列表 32 个保住。
- `tools/drive-take.py` + `tools/shoot-take.ps1` —— 进程内动作驱动 + 一键录制。
- `tools/measure-ui.py` —— 把所有要点的控件坐标一次量全（含弹层三栏、右键菜单、
  「画质/声道」子菜单偏移、单格音量按钮、关注条目、坐标口径自检）。
- `raw/ui-metrics.json` —— 上面那份实测数据（好让坐标能复算）。

## 注意

- `raw/` 与 `work/` 都已在 .gitignore 里，不进版本库。
- 成片目前用的 `assets/rec-*.mp4` **仍是占位片段**（真机截图生成的推镜），
  尚未换成真实录屏。
- 已知的成片缺陷（与录屏无关，下一轮处理）：
  - 被提升的视频绘制在帧 DOM 之上 → 帧 03 的切分线、帧 09 的标注在成片里不可见
  - 帧 01 的窗口推近与视频不同步（视频无法跟随帧内缩放）

