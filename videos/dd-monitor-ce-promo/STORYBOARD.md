---
format: 1920x1080
duration: 63s
message: "十六路直播，不必开十六个窗口"
arc: Demo Loop（钩子 → 产品 → 演示循环 ×N → 宣言 → 行动）
audience: 同时追好几个直播间的 B 站用户
mode: collaborative
music: driving electronic, punchy four-on-the-floor kick, syncopated bass, 129 BPM
---

# DD监控室CE — 63 秒产品宣传片（v2 定稿）

本文件是 `SCRIPT-v2.md` 的装配版（timing 权威来源）。16 拍一条连续流程：
从第 3 拍起，同一个窗口从单画面一路变到左右两分 / 四分 / 九分 / 1+5 / 弹幕 / 竖屏，
再回到横屏聚焦关注栏、分屏做左右声道、演一次重连，宣言卡 + 墙滚动 + logo 收尾。

- 画幅 / 帧率：1920×1080 / 24fps；总长 **63.0 秒 / 16 拍**。
- 无口播 / 无配音 / 无口播字幕；色场法规见 `STYLE-CHECK.md`，文案以 `SCRIPT-v2.md` 为准。
- 一切软件画面来自真实录屏（`assets/rec-*.mp4`），一个像素不用 DOM 重画。

## Frame 01 — 墙面在播 + 标题

- scene: 黑场。1+5 画面墙已经在播（真实录屏），主标题从上方压下来，副标题随其后。开场即给结论。
- onscreen: "十六路直播，不必开十六个窗口" / "DD监控室CE 专为 DD 设计的多窗口监控工具"
- duration: 3.5s
- transition_in: cut
- field: field-black
- status: built
- src: compositions/frames/01-wall-build.html
- focal: assets/rec-wall-build.mp4
- sfx: pop（墙面节奏音）, whoosh-cinematic（标题落定）

## Frame 02 — 标题落定

- scene: 暗场。第一行逐词、第二行瞬时替换，副标题最后淡入；墙压暗到 0.28 退成底，落定后完全静止。
- onscreen: "十六路直播，不必开十六个窗口" / "DD监控室CE 专为 DD 设计的多窗口监控工具"
- duration: 5.5s
- transition_in: blur-crossfade
- field: field-dark
- status: built
- src: compositions/frames/02-title.html
- focal: assets/rec-wall-build.mp4
- sfx: whoosh-short（字替）, impact-bass-1（落定）

## Frame 03 — 想怎么看，就怎么排

- scene: B 站蓝满场。单窗口播放 + 一次模拟点击动效（光标点布局按钮、菜单弹出）→ 窗口裂成左右两分。
- onscreen: "想怎么看，就怎么排" / "平分布局"
- duration: 4s
- transition_in: zoom-through
- field: field-blue
- status: built
- src: compositions/frames/03-layout-1to2.html
- focal: assets/rec-layout-1to2.mp4
- sfx: click-soft（点击）, whoosh-short（分裂）

## Frame 04 — 四分

- scene: 承接 03。左右两分 → 四分（先后两刀）。承接，不加新标题。
- duration: 3s
- transition_in: crossfade
- field: field-blue
- status: built
- src: compositions/frames/04-layout-1to4.html
- focal: assets/rec-layout-1to4.mp4
- sfx: click-soft（两刀）

## Frame 05 — 九路同屏

- scene: 四分 → 九分，九格全亮；chip 4→6→9 逐级走。
- onscreen: "九路同屏，一眼看全" / "单画面 两分 四分 六分 九分"
- duration: 3s
- transition_in: crossfade
- field: field-blue
- status: built
- src: compositions/frames/05-layout-9grid.html
- focal: assets/rec-layout-9grid.mp4
- sfx: click-soft（chip 逐级）, whoosh-short（九格铺满）

## Frame 06 — 主画面不动，小画面环绕

- scene: 九分 → 1+5：主画面钉死左上，五小依次归位。
- onscreen: "主画面不动，小画面环绕" / "1 + 5 主画面加五小"
- duration: 3.5s
- transition_in: push-slide LEFT
- field: field-blue
- status: built
- src: compositions/frames/06-layout-bigplus.html
- focal: assets/rec-layout-bigplus.mp4
- sfx: pop（五小归位，一声一格）

## Frame 07 — 弹幕跟着主画面走

- scene: 在 1+5 上换成同布局弹幕版（主画面 + 1 小 + 弹幕）；镜头推近弹幕格给聚焦，弹幕一直滚。
- onscreen: "弹幕跟着主画面走" / "1 + 1 + 弹幕"
- duration: 5.5s
- transition_in: push-slide LEFT
- field: field-blue
- status: built
- src: compositions/frames/07-layout-danmaku.html
- focal: assets/rec-layout-danmaku.mp4
- sfx: click-soft（chip 换形）, whoosh-short（弹幕格成形）

## Frame 08 — 拖成竖的，它自己接上

- scene: 暗场。窗口 16:9 连续变 9:16，自动接上对映预设，一镜到底。
- onscreen: "拖成竖的，它自己接上" / "按能放几路 自动对映最相似的预设"
- duration: 5.5s
- transition_in: zoom-through
- field: field-dark
- status: built
- src: compositions/frames/08-portrait-flip.html
- focal: assets/rec-portrait-flip.mp4
- sfx: whoosh-cinematic（起手）, riser（重排）, impact-bass-1（落定）

## Frame 09 — 竖屏滑出

- scene: 竖屏窗口横向滑出画面，匀速干脆，走干净。承接，不加字。
- duration: 2s
- transition_in: cut
- field: field-dark
- status: built
- src: compositions/frames/09-portrait-slideout.html
- focal: assets/rec-portrait-slideout.mp4
- sfx: whoosh-short（滑出）

## Frame 10 — 切回 1+5

- scene: 一记硬切回横屏 1+5（形态同 06）。无字。
- duration: 1s
- transition_in: cut
- field: field-dark
- status: built
- src: compositions/frames/10-layout-cutback.html
- focal: assets/rec-layout-bigplus.mp4

## Frame 11 — 悬停就能预览

- scene: 近白场。放大聚焦左侧关注栏一个在播直播间：真实悬停 → 封面预览卡弹出。
- onscreen: "悬停就能预览" / "开播提醒 置顶 拖动排序 导入关注"
- duration: 3.5s
- transition_in: push-slide LEFT
- field: field-light
- status: built
- src: compositions/frames/11-follow-list.html
- focal: assets/rec-follow-list.mp4
- sfx: click-soft（悬停）, pop（预览卡）

## Frame 12 — 这一路放左边 这一路放右边

- scene: 近白场。左右两个画面（两个不同直播间）：左路只播左声道、右路只播右声道；两侧声波左先右后，停峰值保形。
- onscreen: "这一路放左边 这一路放右边" / "每路独立左右声道路由"
- duration: 6s
- transition_in: push-slide LEFT
- field: field-light
- status: built
- src: compositions/frames/12-channel-route.html
- focal: assets/rec-channel-route.mp4
- sfx: whoosh-short（进）, ping（左落）, ping（右落）

## Frame 13 — 断了自己连回来

- scene: 接 12 分屏：其中一路黑掉、角标转琥珀「重连中…」→ 自己回来（不真演断流，字幕带过）。
- onscreen: "断了自己连回来" / "断流重连 画面卡死检测"
- duration: 3s
- transition_in: crossfade
- field: field-dark
- status: built
- src: compositions/frames/13-reconnect.html
- focal: assets/rec-channel-route.mp4
- sfx: error（断掉）, riser（重连中）, chime（回来）

## Frame 14 — 把多个窗口，收成一个

- scene: 近白场。全片唯一"只有字"的一拍：一行居中大字，落定后完全静止。与开场首尾呼应。
- onscreen: "把多个窗口，收成一个"
- duration: 3.5s
- transition_in: zoom-through
- field: field-light
- status: built
- src: compositions/frames/14-manifesto.html
- sfx: impact-bass-2（落定，轻）

## Frame 15 — 墙纵向滚动

- scene: 硬切回软件：画面墙纵向滚动（从下往上，画框里始终露出 2–3 行在播格子），滚到尽头整体极缓压暗。
- duration: 5s
- transition_in: cut
- field: field-dark
- status: built
- src: compositions/frames/15-wall-scroll.html
- focal: assets/rec-wall-scroll.mp4
- sfx: whoosh-short（滚动起）

## Frame 16 — logo 拼装

- scene: 收黑 → 官方 logo 拼装（三层窗格描边 → D 字标扫出 → CE 亮 → 青紫粉缝合线合上），定格后下方淡入字标。
- onscreen: "DD监控室CE"
- duration: 5.5s
- transition_in: crossfade
- field: field-black
- status: built
- src: compositions/frames/16-logo.html
- focal: assets/logo.svg
- sfx: whoosh-short（窗格走笔）, riser（D 扫出）, chime（CE 亮）, whoosh-cinematic（缝合线）

## 时长核算

3.5 + 5.5 + 4 + 3 + 3 + 3.5 + 5.5 + 5.5 + 2 + 1 + 3.5 + 6 + 3 + 3.5 + 5 + 5.5 = **63.0 秒**（16 拍）
