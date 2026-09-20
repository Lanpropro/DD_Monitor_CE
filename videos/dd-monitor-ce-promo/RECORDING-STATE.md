# 录屏会话 · 当前状态与下一步

更新时间：录制阶段（未完成）
素材目录：`videos/dd-monitor-ce-promo/raw/`

## 已确认的决策

**改用"一条连续长素材"**，不再切成七八个独立片段。理由：

1. 全片的 spine 是「同一个窗口」——分镜里写死了。一条连续素材天然满足；切成多段再拼，
   接缝处窗口位置/内容会跳。
2. 布局那一段（分镜 03–06）本来就是「1→4→9→1+5→弹幕」的连续演化，不切最有说服力。
3. 真实感更强：这是一次真实使用过程，不是"一个功能演示一段"。

剪辑时从**同一条** `raw/take.mp4` 里取时间窗，喂给各拍。

## 已到手的素材

| 文件 | 说明 |
| --- | --- |
| `raw/session4.mp4` | 187.5MB，3840×2160，全程最大化，HEVC+AAC，93 秒。逐帧验证 7 个状态命中：单画面 / 四分 / 九分 / 1+5 / 六分 / 竖屏 / 回横屏 + 关注栏 4 次悬停（各停 4 秒）。**这条可以用**，但缺下面「仍缺的镜头」 |

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
  → 等它恢复完再摆；**每次开菜单前重新最大化**，否则菜单坐标失效
- 软件会自己挪窗口位置 → 点击/悬停一律「实时查窗口矩形 + 窗口内相对坐标」
- 桌面其他窗口会盖住软件、模拟点击会打偏 → 录制期间常驻 `HWND_TOPMOST`；
  `resize` 之后要补一次（`Front()` 结尾会摘掉）
- dshow 无回环设备 → 声音走 `tools/loopback-rec.py`（soundcard 的 WASAPI 回环）
- 软件的画面墙格子显示「已静音」但实际仍出声（实测：关掉软件回环从 -32dB 掉到 -91dB）
  → 需要它安静时用 `tools/mute-app.py` 按进程静音；需要有声时 `unmute`
- PS 5.1 按 ANSI 读无 BOM 的 `.ps1` → 脚本必须带 UTF-8 BOM，**每次编辑后要补回**

## 常用命令

```powershell
# 录制（动作计划 + 回环录音 + 合流）
powershell -NoProfile -ExecutionPolicy Bypass -File tools/record-session.ps1 `
  -PlanFile tools/action-plan.json -OutFile raw/take.mp4

# 按进程静音/解静音软件的音频会话
python tools/mute-app.py python mute|unmute|status

# 组装成片（唯一正确入口：先 restore 视频再 assemble，否则视频会被吞掉、全片黑屏）
node tools/assemble.mjs . "C:\Users\Lan\.agents\skills\product-launch-video"

# 渲染
npx hyperframes render --skill=product-launch-video --quality high -f 24 --output renders/video.mp4
```

## 注意

- `raw/` 与 `work/` 都已在 .gitignore 里，不进版本库。
- 成片目前用的 `assets/rec-*.mp4` **仍是占位片段**（真机截图生成的推镜），
  尚未换成真实录屏。
- 已知的成片缺陷（与录屏无关，下一轮处理）：
  - 被提升的视频绘制在帧 DOM 之上 → 帧 03 的切分线、帧 09 的标注在成片里不可见
  - 帧 01 的窗口推近与视频不同步（视频无法跟随帧内缩放）
