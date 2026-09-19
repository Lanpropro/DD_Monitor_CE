---
format: 1920x1080
duration: 60s
message: "十六路直播，不必开十六个窗口"
arc: Demo Loop（钩子 → 产品 → 演示循环 ×N → 宣言 → 行动）
audience: 同时追好几个直播间的 B 站用户
mode: collaborative
music: driving electronic, punchy four-on-the-floor kick, syncopated bass, 129 BPM
---

# DD监控室CE — 60 秒产品宣传片

## 决策（先定这些，再谈每一格）

- **Message**：十六路直播，不必开十六个窗口。
- **Audience / Arc**：说给「同时追好几个直播间的人」听。弧线是 Demo Loop：
  先用一面真实亮起来的画面墙把人钉住，第二拍就把结论说完，之后每一段都是在给这个结论举证。
- **Format**：1920×1080 / 24fps / 目标 60 秒 / **无口播、无配音** / 有 BGM / 中文字幕卡。
- **风格目标（最高优先级）**：**贴着参考片**。参考片实测——一场一景；平均镜头 ≈2.4s；
  开头一个 6.75s 纯氛围长镜头；6.75–9.6s 一次密集快切（标题爆发）；之后每段功能 3–6s；
  场景在暖色影棚 / 大色块卡片 / 白底窗口 / 深色极光 / 纯品牌色 / 黑场之间交替。
  本片照这个节奏排。详见 `frame.md` 的「参考片对齐」一节。
- **Spine（贯穿全片的那个东西）**：**布局图 chip** —— 软件自己的布局缩略图线框小方块。
  参考片靠一张巨型版本号卡片贯穿全片，本项目用 chip 做同一件事：它在 03–06 每一拍出现，
  在 14 摊成一整面阵列回收。
- **场景色场（一帧只用一种，平面不加纹理）**：
  `field-black #0d0e10`（开场、片尾）· `field-dark #222428`（竖屏、重连、插件）·
  `field-blue #00a1d6`（**布局系统整段 03–06**）· `field-light #f1f2f5`（细节段 08–11、宣言 14）。
- **Brand（来自真实来源，不是记忆）**：`ddm/theme.py` + `assets/logo.svg`。
  地面 `#222428`、次表面 `#303338`、字 `#f1f2f5`、B 站蓝 `#00a1d6`；
  字体 Microsoft YaHei UI / Microsoft YaHei / Segoe UI（系统自带，不联网下载）。
- **排版**：居中的重磅主标题 `headline` 4.6cqw/700 + 居中副标题 2.1cqw/600/字距 0.16em。
  副标题里的并列项**用空格分隔**，不堆顿号。
- **Bans（本片的"不许"）**：
  - **不许画假的软件界面**——一切软件画面必须来自真机截图或真实录屏，一个像素都不许用 DOM 重画。
  - **不许用 cobalt-grid 的招牌原子**——方格纸底纹、上下细线、像素故障块、QR 块，参考片里一个都没有。
  - 不许一格一换的幻灯片节奏；不许没有信息的环境动效；不许发光描边；不许玻璃拟态。
  - 不许把 B 站粉 `#fb7299` 拿来做设计色——它只在真实录屏里自然出现。
  - **两个具体的动效病**：*幻灯片*（每一拍都是一张新卡片）和*屏保*（在动，但什么都没说）。
- **Held frame（刻意不动的那一拍）**：**Frame 14**。全片唯一一次让画面停住、只留一句宣言。
- **真实来源声明**：所有软件画面来自软件真实运行（录屏）或软件真机截图（`docs/`）。
  片中出现的直播间、用户名、弹幕均来自真实公开直播间，**照实呈现，不做虚构**。

## Video direction（全片共享，逐拍只写增量）

- **Palette**：色场取自 `frame.md`，一帧只用一种。字色按色场取——暗场/黑场用 `#f1f2f5`，
  **蓝场用 `#0d1114`**（深字压亮底，对比度更高），白场用 `#101114`。
  B 站蓝 `#00a1d6` 是全片唯一的强调色；**唯一的例外是片尾 logo**，它自带
  `#00a1d6 → #756bf2 → #fb7299` 的青紫粉渐变——那是官方品牌资产的真实颜色，按原样使用。
  粉色不进入设计系统。
- **Type**：居中的重磅主标题 + 居中副标题。并列项用空格分隔。
- **Motion grammar**：默认 `power3` 长尾缓动，**平顺压过弹跳**，不用 `back.out` / `bounce.out` / `elastic.out`。
  **本片没有口播**，所以"揭示节奏"挂两个 cue：**屏幕上的文案行**和**录屏里那个动作本身**——
  每一件东西在它对应的文案出现时才进场，揭示铺在该拍的后 ~50%，绝不前置堆叠。
- **Idle budget / 静止分配**：三拍是刻意的静止——**01**（墙亮完就停住）、
  **07**（竖屏转完停住）、**14**（整拍就是一次静止的阅读，全片唯一的真静止）。
  其余各拍都是"揭示完就停"，只在必要处保留唯一一种"活着"：
  弹幕自己在滚（06/08）——那是**主体在做自己的事**，不是装饰性呼吸。
- **Negative list**：不许幻灯片（前置堆完就冻住）；不许屏保（各元素各飘各的）；
  不许懒呼吸；不许后半段慢推慢摇；不许方格纸/细线/像素故障/QR 块；
  不许画假界面；不许发光描边；不许玻璃拟态。
- **Caption band**：本片**没有口播也没有字幕**，所以下沿 ~17% **不预留**。
  窗口 mockup 刻意跑出下沿裁切——这是参考片的固定手法。
- **Camera**：每拍最多一次缓慢推近或漂移，**后半段不再二次推**。

## Frame 01 — 墙面亮起

- scene: 黑场。16 个格子在黑暗里逐格亮起，每一格接进一路真实直播；弹幕细线横向划过。镜头全程极缓推近，一镜到底不切。
- onscreen: （无字——这一拍只给画面）
- duration: 6s
- poster: 5s
- transition_in: cut
- field: field-black
- status: built
- src: compositions/frames/01-wall-ignite.html
- type: hook
- persuasion: Show-don't-tell proof
- beat: 好奇
- blueprint: zoom-out-workspace-reveal (Adapt)
- focal: assets/rec-wall-build.mp4
- roles: rec-wall-build = cutout（唯一主体，占画面 ~86% 宽，下沿裁切）
- asset_candidates: assets/rec-wall-build.mp4 — 从空布局开始、主播逐个进墙、格子逐格亮起的真实录屏
- sfx: pop（格子逐格亮起，每格一声，密度递增）, whoosh-cinematic（结尾整墙亮完那一下）, riser（0–3s 极轻的底）
- handoff_out: element = 画面墙窗口 · rect left 7cqw / right 7cqw / top 16cqw / bottom −6cqw · scale 1.04 · opacity 1 · motion 极缓推近（scale 1.00→1.04，全程）

Adapt：保留 zoom-out-workspace-reveal 的"先给看不懂的东西、再让它自己解释自己"的签名动作，
把"工作台"换成真实录屏的画面墙；不加任何字，靠格子逐格亮起的秩序感本身当钩子。

narrativeRole: 用参考片同样的手法开场——先给一个 6 秒的氛围长镜头，不给任何信息。"本该很乱却自己排得整整齐齐"的秩序感就是钩子。
keyMessage: 这场面是一个窗口，不是十六个。

Scene 1 (0.0–2.0s)：全黑，只有画面墙的窗口边框隐约可见（占 ~86% 宽，上沿在 16cqw，下沿被裁）。
窗口内 16 格里最左上 3 格先亮，**pop** 一声一格，间隔 ~0.4s。极缓推近从 t=0 就在跑（scale 1.00→1.04 铺满整拍，后半段不再加推）。
Scene 2 (2.0–4.4s)：亮起的顺序按行推进（左→右、上→下），越到后面越密（0.4s → 0.22s → 0.12s），
弹幕细线开始在已亮的格子里横向划过。这一窗不出现任何文字。
Scene 3 (4.4–6.0s)：最后一格亮起时 **whoosh-cinematic** 落地，整面墙完整；镜头停在 scale 1.04。
**这就是本拍的 held read——墙亮完就停住，不动、不呼吸**（静比乱动好）。

## Frame 02 — 标题

- scene: 墙面压暗退到背景。标题块居中打出：重磅主标题在上、副标题在下，块内做 2–3 次极快的字替（参考片 6.75–9.6s 那次标题爆发）。落定后停住。
- onscreen: "十六路直播，不必开十六个窗口" / "DD监控室CE 专为 DD 设计的多窗口监控工具"
- duration: 4.5s
- poster: 4s
- transition_in: blur-crossfade
- field: field-dark
- status: built
- src: compositions/frames/02-title.html
- type: product_intro
- persuasion: Future pacing
- beat: 清晰
- blueprint: kinetic-type-beats (Adapt)
- focal: assets/rec-wall-build.mp4
- roles: rec-wall-build = background（全幅铺底，压暗到 opacity 0.28 并加一层暗罩）
- asset_candidates: assets/rec-wall-build.mp4 — 同一条素材压暗当作底
- sfx: whoosh-short（每次字替一下）, impact-bass-1（主标题落定）
- handoff_in: element = 画面墙窗口 · rect left 7cqw / right 7cqw / top 16cqw / bottom −6cqw · scale 1.04 · opacity 1 → 0.28（入场 0.45s 内压暗）· motion 停（本拍窗口不动，只压暗）

Adapt：保留 kinetic-type-beats 的"字替就是节拍"签名，把口播换成字幕卡——
主标题分两行、副标题一行，共三次落字，每次间隔由 **whoosh-short** 断句。

narrativeRole: 在第 2 拍把结论说完（reverse iceberg：先给价值，后面全是举证），并给产品命名。参考片在同一个位置做的是密集快切，本拍照做。
keyMessage: 十六路 = 一个窗口。

Scene 1 (6.0–7.4s)：handoff 进来的墙在 0.45s 内压暗到 0.28 并轻微降饱和；主标题第一行
"十六路直播，"以 **per-word staggered reveal**（`dynamic-content-sequencing`）逐词落定，居中、占画面宽 ~62%。
Scene 2 (7.4–8.8s)：第二行"不必开十六个窗口"以 **hard-cut / flash word-swap**（`discrete-text-sequence`）
换掉第一行——不是淡入，是**瞬时替换**，配 **whoosh-short**。这是参考片那次标题爆发的复刻。
Scene 3 (8.8–10.5s)：副标题"DD监控室CE 专为 DD 设计的多窗口监控工具"在第二行下方淡入（字距 0.16em），
**impact-bass-1** 落在主标题最终定格那一下。落定后**完全静止**读 1.0s，窗口与文字都不再动。

## Frame 03 — 想怎么看，就怎么排

- scene: B 站蓝满场，平面无纹理。左下角布局图 chip 从"单格"变成"四分"；右侧窗口里的画面同步被切开重排。标题块居中在上。
- onscreen: "想怎么看，就怎么排" / "平分布局"
- duration: 3.5s
- poster: 3s
- transition_in: zoom-through
- field: field-blue
- prop: 布局图 chip —— 单格 → 四分
- status: built
- src: compositions/frames/03-layout-1to4.html
- type: feature_showcase
- persuasion: Friction reduction
- beat: 掌控
- blueprint: grid-card-assemble (Adapt)
- focal: assets/rec-layout-1to4.mp4
- roles: rec-layout-1to4 = cutout（窗口主体，右侧 52cqw 宽，下沿裁切）; 布局图 chip = supporting（左下 15cqw 见方）
- asset_candidates: assets/rec-layout-1to4.mp4 — 切「布局预设」菜单、单画面变四分的真实录屏
- sfx: whoosh-short（切分那一下）, click-soft（chip 换形）
- handoff_out: element = 窗口 + chip · 窗口 rect right 5cqw / width 52cqw / top 31cqw / bottom −7cqw · chip rect left 5cqw / top 36cqw / 15cqw 见方 · 两者 scale 1 · opacity 1 · motion 停（下一拍靠内部布局变化，不动外框）

Adapt：保留 grid-card-assemble 的"格子自己拼起来"签名，但拼的不是卡片墙，
而是**同一个窗口内部被切开重排**——签名动作落在"四分"成形那一下。

narrativeRole: 把"布局系统"这个核心卖点用一次真实的形态变化讲清楚——不是菜单截图，是墙真的变了。蓝色场是参考片那种"换场换色"的节拍器。
keyMessage: 排布是免费的，不是一个高级功能。

Scene 1 (10.5–11.3s)：**zoom-through** 进场，蓝场整面铺开（平面，无纹理无渐变）。
标题块居中在上（`pad-top` 位），chip 先以单格状态落在左下角——**先只有它，窗口还没进**。
Scene 2 (11.3–12.6s)：文案行"想怎么看，就怎么排"落定（`dynamic-content-sequencing`，逐词）。
窗口从右下滑入并就位（**spring-pop-entrance**，长尾平顺不弹），里面是单画面；
chip 同步被 **click-soft** 点亮，从 1 格切成 4 格。
Scene 3 (12.6–14.0s)：窗口内部真正切开重排成四分（这是录屏里的真实动作，
**per-word 式的顺序重排**——先后两刀，不要一次到位），副标题"平分布局"最后落定。
落定即静止，窗口与 chip 都不再动。

## Frame 04 — 九路同屏

- scene: 同一个蓝场，chip 从四分继续走到九分；窗口里九路画面同时铺满。镜头轻微推近再停。
- onscreen: "九路同屏，一眼看全" / "单画面 两分 四分 六分 九分"
- duration: 3.5s
- poster: 3s
- transition_in: crossfade
- field: field-blue
- prop: 布局图 chip —— 四分 → 九分
- status: built
- src: compositions/frames/04-layout-9grid.html
- type: feature_showcase
- persuasion: Value stacking
- beat: 满足
- blueprint: device-surface-showcase (Adapt)
- focal: assets/rec-layout-9grid.mp4
- roles: rec-layout-9grid = cutout（窗口主体，位置尺寸与 03 完全一致）; 布局图 chip = supporting
- asset_candidates: assets/rec-layout-9grid.mp4 — 切到九分平分布局的真实录屏
- sfx: click-soft（chip 进到九分）, whoosh-short（九格铺满）
- handoff_in: element = 窗口 + chip · 窗口 rect right 5cqw / width 52cqw / top 31cqw / bottom −7cqw · chip rect left 5cqw / top 36cqw / 15cqw 见方 · 两者 scale 1 · opacity 1 · motion 停（承接 03 的收尾状态，外框一个像素不动）
- handoff_out: 同 handoff_in（交给 05 时外框仍不动）

Adapt：device-surface-showcase 的签名是"功能在它真实的界面里被使用"——本拍保留它，
把"使用"压缩成一次纯粹的形态推进：四分→九分，全部发生在窗口内部。

narrativeRole: 把平分布局的整个梯度一次性摊开，证明"多变"是真的一整套而不是两三个。
keyMessage: 平分布局有从一到九的完整梯度。

Scene 1 (14.0–14.8s)：**crossfade** 进来时窗口与 chip 保持 03 的收尾状态，一个像素不动——
这是 handoff 的意义所在。文案行"九路同屏，一眼看全"落定。
Scene 2 (14.8–16.2s)：chip 的格数从 4 逐级跳到 9（4→6→9，每级 **click-soft** 一下），
窗口内部同步从四分推进到九分。**一次只走一级**，不要一帧到位。
Scene 3 (16.2–17.5s)：九格铺满时 **whoosh-short** 落地，镜头做本拍唯一一次轻微推近
（scale 1.00→1.03，前段完成）；副标题"单画面 两分 四分 六分 九分"以 0.16em 字距铺在标题下。
推完停住，后半段不再推。

## Frame 05 — 大带小

- scene: 蓝场。chip 换成 **1+5** 的线框（主画面占 2×2，余下五格是小画面）；窗口里主画面钉死在左上不动，五路小画面依次归位环绕。
- onscreen: "主画面不动，小画面环绕" / "1 + 5 主画面加五小"
- duration: 3.5s
- poster: 3s
- transition_in: push-slide LEFT
- field: field-blue
- prop: 布局图 chip —— 1 大 + 5 小（主画面那格高亮）
- status: built
- src: compositions/frames/05-layout-bigplus.html
- type: feature_showcase
- persuasion: Show-don't-tell proof
- beat: 秩序感
- blueprint: fixed-anchor-cycle (Adapt)
- focal: assets/rec-layout-bigplus.mp4
- roles: rec-layout-bigplus = cutout（窗口主体，位置尺寸与 03/04 完全一致）; 布局图 chip = supporting
- asset_candidates: assets/rec-layout-bigplus.mp4 — 切「主画面 + 5 小环绕」（1+5）的真实录屏
- sfx: pop（五路小画面逐个归位，一声一格）, click-soft（chip 换成 1+5）
- handoff_in: element = 窗口 + chip · rect 与 03/04 完全一致 · scale 1 · opacity 1 · motion 停
- handoff_out: 同 handoff_in（交给 06 时外框仍不动）

Adapt：fixed-anchor-cycle 的签名是"一个锚点钉死不动，周围的词在换"。
本拍把"词"换成"五路小画面"——**主画面就是那个锚**，它不动是这一拍全部的说服力。

narrativeRole: 证明布局不只是等分格子——有主次。主画面钉住不动是这一拍的全部说服力。
keyMessage: 有主有次，不是一律等分。

Scene 1 (17.5–18.3s)：**push-slide LEFT** 推进来，窗口与 chip 承接 04 的状态。
chip 被 **click-soft** 换成 1+5 线框（主画面那格亮起）；窗口里主画面就位到左上、占 2×2，
**它的位置从这一刻起到本拍结束一个像素都不动**。
Scene 2 (18.3–19.7s)：五路小画面**依次归位**（**pop** 一声一格，顺序左→右），
文案行"主画面不动，小画面环绕"在它们归位的同时逐词落定——揭示铺在后半段，不前置。
Scene 3 (19.7–21.0s)：副标题"1 + 5 主画面加五小"落定，五小归位完毕。
停住读约 1.0s——锚点与环绕都静止，本拍不做任何相机运动。

## Frame 06 — 弹幕进墙

- scene: 蓝场收尾。chip 换成 **1+1+弹幕**（主画面 / 一路小画面 / 弹幕面板）；窗口右侧上格是一路小画面、下格是弹幕面板，弹幕自下而上滚。
- onscreen: "弹幕跟着主画面走" / "1 + 1 + 弹幕"
- duration: 3.5s
- poster: 3s
- transition_in: push-slide LEFT
- field: field-blue
- prop: 布局图 chip —— 1 大 + 1 小 + 弹幕
- status: built
- src: compositions/frames/06-layout-danmaku.html
- type: feature_showcase
- persuasion: Friction reduction
- beat: 沉浸
- blueprint: device-surface-showcase (Adapt)
- focal: assets/rec-layout-danmaku.mp4
- roles: rec-layout-danmaku = cutout（窗口主体，位置尺寸与 03–05 完全一致）; 布局图 chip = supporting
- asset_candidates: assets/rec-layout-danmaku.mp4 — 切「主画面 + 1 小 + 弹幕」（1+1+弹幕）并让弹幕滚动的真实录屏
- sfx: click-soft（chip 换形）, whoosh-short（弹幕格成形）, typing（弹幕滚动的极轻底噪）
- handoff_in: element = 窗口 + chip · rect 与 03–05 完全一致 · scale 1 · opacity 1 · motion 停
- handoff_out: element = 窗口 + chip · rect 同上 · scale 1 · opacity 1 · motion 停（本拍后蓝色整段收束，下一拍换暗场，不做跨帧延续）

Adapt：device-surface-showcase 的签名不变；本拍是蓝色布局段的收束，
把"弹幕是墙里的一格"这件事用 1+1+弹幕 这个真实排布证完。

narrativeRole: 弹幕不是外挂窗口，是画面墙里的一格——解决了"看直播还要另开一个弹幕页"的老麻烦。1+1+弹幕这个排布也顺手证明了：弹幕格和视频格是可以共存的，不是二选一。这一拍结束，蓝色的布局整段收束。
keyMessage: 弹幕是墙的一部分。

Scene 1 (21.0–21.8s)：**push-slide LEFT** 推进来，窗口与 chip 仍承接上一拍。
chip 换成 1+1+弹幕 线框（**click-soft**）；窗口右侧上格先落成一路小画面。
Scene 2 (21.8–23.2s)：下格的弹幕面板成形（**whoosh-short**），弹幕开始自下而上滚。
**这是全片唯一允许的持续性运动**——因为它是主体在做自己的事（弹幕本来就在滚），
不是装饰性呼吸。文案行"弹幕跟着主画面走"在这一窗落定。
Scene 3 (23.2–24.5s)：副标题"1 + 1 + 弹幕"落定；弹幕继续滚到本拍结束（它不停）。
除此之外画面完全静止——这是蓝色整段的收尾。

## Frame 07 — 拖成竖的

- scene: 换回暗场。同一个窗口从 16:9 连续变成 9:16：先是窗口边框在动，然后内部布局重排、侧栏变成顶部横栏。一镜到底，不切。
- onscreen: "拖成竖的，它自己接上" / "按能放几路 自动对映最相似的预设"
- duration: 5.5s
- poster: 4.5s
- transition_in: zoom-through
- field: field-dark
- status: built
- src: compositions/frames/07-portrait-flip.html
- type: feature_showcase
- persuasion: Friction reduction
- beat: 惊喜 → 省心
- blueprint: panel-edit-live-sync (Adapt)
- focal: assets/rec-portrait-flip.mp4
- roles: rec-portrait-flip = cutout（唯一主体，右侧竖屏窗口，宽 22.5cqw、上下贯通）
- asset_candidates: assets/rec-portrait-flip.mp4 — 窗口从横屏连续变成竖屏、布局自动切换的真实录屏
- sfx: whoosh-cinematic（拖动的起手）, riser（布局重排那一下的 0.6s 抬升）, impact-bass-1（接上预设落定）
- handoff_out: element = 竖屏窗口 · rect right 8cqw / width 22.5cqw / top 9cqw / bottom −6cqw · scale 1 · opacity 1 · motion 停（转完停住，下一拍换白场，不做跨帧延续）

Adapt：panel-edit-live-sync 的签名是"一个动作 → 另一处立刻应答"的双联句（做 X，Y 就应）。
本拍保留它，把"拖数值/选单位"换成"拖窗口形状 → 布局自己接上"，**一镜到底不许切**。

narrativeRole: 全片最有说服力的一拍，也是别家没有的一拍：改方向不是"重排一遍"，是"它自己接上"。一镜到底不许切，切了这拍就不成立了。
keyMessage: 连拖窗口这件事它都想到了。

Scene 1 (24.5–26.2s)：**zoom-through** 进暗场。窗口以横屏 16:9 出现（右偏，宽 22.5cqw），
标题块居左在上。文案行"拖成竖的，它自己接上"逐词落定；**whoosh-cinematic** 起手。
Scene 2 (26.2–28.6s)：窗口边框开始连续变窄变高（**这一窗就是那个动作本身**，不要切），
内部布局随之重排：侧栏消失、顶部横栏出现、主画面按 16:9 占满宽度。
**riser** 在重排那一下抬 0.6s；这是全片最长的一次连续运动，**绝不许切**。
Scene 3 (28.6–30.0s)：窗口停在 9:16，**impact-bass-1** 落地，副标题"按能放几路 自动对映最相似的预设"落定。
**转完即停**——这是本拍的 held read，窗口不再动、不再呼吸、不做二次推。

## Frame 08 — 弹幕面板

- scene: 换到近白场，暗字。窗口推近到弹幕格：粉丝牌徽章、B 站表情、屏蔽词过滤后的干净弹幕流依次被点出。
- onscreen: "粉丝牌 表情 屏蔽词" / "字体字号可调"
- duration: 3.5s
- poster: 3s
- transition_in: zoom-through
- field: field-light
- status: built
- src: compositions/frames/08-danmaku-panel.html
- type: feature_showcase
- persuasion: Feature-to-benefit translation
- beat: 舒适
- blueprint: cursor-ui-demo (Adapt)
- focal: assets/rec-danmaku-panel.mp4
- roles: rec-danmaku-panel = cutout（窗口居中，左右各 14cqw，下沿裁切）
- asset_candidates: assets/rec-danmaku-panel.mp4 — punch-in 到弹幕格的特写录屏
- sfx: whoosh-short（推近）, click-soft ×3（粉丝牌 / 表情 / 屏蔽词各一下）

Adapt：cursor-ui-demo 的签名是"一个具体动作在真实界面里发生"。
本拍保留它，把"多步工作流"换成"同一处三次点名"——**不出现假光标**（不许画假界面的一部分）。

narrativeRole: 上一拍说"弹幕在墙里"，这一拍证明弹幕本身也是认真做的，不是塞了个文本框。近白场把细节衬出来。
keyMessage: 弹幕面板是按 B 站生态做的。

Scene 1 (30.0–30.9s)：**zoom-through** 进近白场。窗口居中（左右各 14cqw，下沿被裁），
镜头推近到弹幕格那一块；标题块居中在上。文案行"粉丝牌 表情 屏蔽词"落定。
Scene 2 (30.9–32.3s)：三处被**依次点名**——粉丝牌徽章、B 站表情、屏蔽词过滤后的干净弹幕流，
每处一次 **click-soft**，顺序揭示、不齐发；被点名的那一处做极轻的一次 **keyword glow**
（`asr-keyword-glow`），其余保持不动。
Scene 3 (32.3–33.5s)：副标题"字体字号可调"落定；三处高亮回到常态。
**停住**——不再推近、不呼吸。

## Frame 09 — 关注列表

- scene: 白场。镜头拉到左侧关注列表：鼠标悬停弹出封面预览缩略卡，然后是置顶徽标和拖动排序的位移。
- onscreen: "悬停就能预览" / "开播提醒 置顶 拖动排序 导入关注"
- duration: 3.5s
- poster: 3s
- transition_in: push-slide LEFT
- field: field-light
- status: built
- src: compositions/frames/09-follow-list.html
- type: feature_showcase
- persuasion: Friction reduction
- beat: 省心
- blueprint: device-surface-showcase (Adapt)
- focal: assets/rec-follow-list.mp4
- roles: rec-follow-list = cutout（窗口居中，左右各 6cqw，下沿裁切）
- asset_candidates: assets/rec-follow-list.mp4 — 悬停预览 + 拖动排序的真实录屏
- sfx: click-soft（悬停）, pop（预览卡弹出）, whoosh-short（拖动排序那一下）

Adapt：device-surface-showcase 的签名"在真实界面里被使用"不变；
把"使用"落成三个可辨认的动作：悬停 → 预览卡弹出 → 置顶/重排。

narrativeRole: 证明"从关注到上墙"这条路是通的——片子到这里才把"内容从哪来"补上。
keyMessage: 关注列表直接就是素材库。

Scene 1 (33.5–34.3s)：**push-slide LEFT** 进白场。窗口居中、下沿裁切，镜头偏左一点落在关注列表。
标题块居左在上。文案行"悬停就能预览"落定。
Scene 2 (34.3–35.8s)：鼠标停在某一项上（**这是一次真实悬停的录屏，不许画假光标**），
封面预览缩略卡以 **spring-pop-entrance** 弹出（**pop**），随后置顶徽标亮起。
Scene 3 (35.8–37.0s)：拖动排序发生一次位移（**whoosh-short**），副标题
"开播提醒 置顶 拖动排序 导入关注"落定。**停住**读后半拍。

## Frame 10 — 每一路，单独调

- scene: 白场。某一格的底部控制条展开：音量滑杆、静音、画质依次亮起；同时另外八格保持不受影响。
- onscreen: "每一路 单独调" / "音量 静音 画质"
- duration: 3.5s
- poster: 3s
- transition_in: crossfade
- field: field-light
- status: built
- src: compositions/frames/10-tile-audio.html
- type: benefit_highlight
- persuasion: Feature-to-benefit translation
- beat: 掌控
- blueprint: cursor-ui-demo (Adapt)
- focal: assets/rec-tile-audio.mp4
- roles: rec-tile-audio = cutout（窗口居中，左右各 10cqw，下沿裁切）
- asset_candidates: assets/rec-tile-audio.mp4 — 打开单格音量/静音/画质菜单的真实录屏
- sfx: click-soft（展开控制条）, ping（音量）, click-soft（静音）, pop（画质）

Adapt：cursor-ui-demo 不变；把"多步流程"换成**一处展开、三项依次点名**，
并强调"其余八格不受影响"——那是这一拍的价值所在。

narrativeRole: 多路同屏最容易崩的就是"声音怎么办"，这一拍直接回答它。
keyMessage: 十六路不是一个整体，是十六个独立的路。

Scene 1 (37.0–37.8s)：**crossfade** 进白场。窗口居中，标题块居中在上。
文案行"每一路 单独调"落定。
Scene 2 (37.8–39.2s)：某一格的底部控制条展开（**click-soft**），
音量滑杆、静音、画质三项**依次亮起**（ping / click-soft / pop），每项一次、顺序揭示。
其余八格在这一窗里**始终不动**——静止就是论据。
Scene 3 (39.2–40.5s)：副标题"音量 静音 画质"落定，控制条保持在展开态。
停住，不做相机运动。

## Frame 11 — 这一路放左边

- scene: 白场竖向一分为二：左半屏只有一路画面、声波跑向左；右半屏另一路、声波跑向右。中间一条细线把声道分开，两侧完全对称。
- onscreen: "这一路放左边 这一路放右边" / "每路独立左右声道路由"
- duration: 3.5s
- poster: 3s
- transition_in: push-slide LEFT
- field: field-light
- status: built
- src: compositions/frames/11-channel-route.html
- type: benefit_highlight
- persuasion: Show-don't-tell proof
- beat: 意外 → 满足
- blueprint: comparison-split (Reproduce)
- focal: assets/rec-channel-route.mp4
- roles: rec-channel-route = cutout（唯一素材，左右各切一半镜像使用，构成对称）
- asset_candidates: assets/rec-channel-route.mp4 — 音量菜单里切「左声道 / 右声道」的真实录屏
- sfx: whoosh-short（进）, ping（左声道落）, ping（右声道落，音高不同）

Reproduce：comparison-split 的签名就是"两个对等的东西并置，用对称说话"——
本拍完全照它的形状来：两侧等大、等距、镜像，中间一条分割线。

narrativeRole: 这是本项目独有、别人抄不动的功能，必须给独立一拍。用对称的画面把"左/右"变成可看的东西。
keyMessage: 声音的去向是可控的。

Scene 1 (40.5–41.3s)：**push-slide LEFT** 进白场。两侧窗口对位就位（左右镜像、等大等距），
中间一条竖线分开。**先只有窗，声波还没有。** 文案行"这一路放左边 这一路放右边"落定。
Scene 2 (41.3–42.7s)：左侧声波先起（**ping**，`stat-bars-and-fills` 的条形填充，
从中心线向左递进），右侧在 ~0.5s 后应答（**ping**，音高不同，向右递进）——
**这个先后差就是这一拍的意思**：两路声音各有各的去向。
Scene 3 (42.7–44.0s)：副标题"每路独立左右声道路由"落定；两侧声波停在峰值并**保形不动**
（不要循环滚动——那是屏保）。停住读半拍。

## Frame 12 — 断了自己连回来

- scene: 换回暗场。某一格黑掉，角标变成重连中的琥珀色；2 秒后画面自己回来，角标恢复。全程没有人工操作。
- onscreen: "断了自己连回来" / "断流重连 画面卡死检测"
- duration: 3.5s
- poster: 3s
- transition_in: crossfade
- field: field-dark
- status: built
- src: compositions/frames/12-reconnect.html
- type: benefit_highlight
- persuasion: Risk reversal
- beat: 安心
- blueprint: kinetic-type-beats (Adapt)
- focal: assets/rec-wall-build.mp4
- roles: rec-wall-build = cutout（窗口居中，左右各 12cqw，下沿裁切；取其中一格做重连状态）
- asset_candidates: assets/rec-wall-build.mp4 — 画面墙素材，取某一格做重连状态的表现
- sfx: error（那一格断掉）, riser（重连中 1.2s 的抬升）, chime（自己连回来）

Adapt：kinetic-type-beats 的签名"字就是节拍"保留，但本拍真正的节拍在**那格画面**上：
断开 → 等待 → 回来，三步各配一声。

narrativeRole: 长时间挂机的人最怕的就是半夜某一路悄悄死了——这一拍把那个担心直接消掉。暗场是这一拍成立的前提。
keyMessage: 不用一直盯着它有没有掉。

Scene 1 (44.0–44.9s)：**crossfade** 进暗场。窗口居中、下沿裁切，标题块居中在上。
文案行"断了自己连回来"落定；与此同时其中一格**断掉**（黑），角标转琥珀色"重连中…"（**error**）。
Scene 2 (44.9–46.1s)：等待——**riser** 抬 1.2s，那一格保持黑，角标保持琥珀色。
其余八格继续正常播（静止的对照，不动）。这一窗**什么都不揭示**，就是让等待被感觉到。
Scene 3 (46.1–47.5s)：那一格**自己回来**（**chime**），角标恢复常态；
副标题"断流重连 画面卡死检测"落定。停住——不做相机运动。

## Frame 13 — 想加功能，写个插件

- scene: 暗场。淡入到安静的界面特写：`plugins_user/` 目录结构 + 一个真实插件例子 `danmaku_log`。左边一个极简的线性图标。
- onscreen: "本体不带的功能 插件带" / "plugins_user/名字/plugin.py"
- duration: 3.5s
- poster: 3s
- transition_in: blur-crossfade
- field: field-dark
- status: built
- src: compositions/frames/13-plugins.html
- type: feature_showcase
- persuasion: Authority by association
- beat: 信任
- blueprint: device-surface-showcase (Adapt)
- focal: assets/overview2_Landscape_mode.png
- roles: overview2 = background（全幅铺底，压暗到 opacity 0.22）; 目录树面板 = cutout（居中，左右各 14cqw）
- asset_candidates: assets/overview2_Landscape_mode.png — 真机截图，用作压暗的背景层
- sfx: typing（目录树逐行展开）, click-soft（两个插件目录名点亮）

Adapt：device-surface-showcase 的签名不变；把"真实界面"从软件窗口换成
**软件真实存在的插件目录结构**（`plugins_user/` 下两个真实目录名），逐行展开。

narrativeRole: 说明这个工具是可扩展的、不是封死的——对象是愿意折腾的那部分用户。
keyMessage: 边界是可以自己往外推的。

Scene 1 (47.5–48.4s)：**blur-crossfade** 进暗场。真机截图压暗到 0.22 铺底，
目录树面板居中，标题块居中在上。文案行"本体不带的功能 插件带"落定。
Scene 2 (48.4–49.8s)：目录树**逐行展开**（**typing** 底噪），
`danmaku_log/` 与 `_template_platform/` 两个真实目录名先后点亮（**click-soft**）。
顺序揭示，不齐发。
Scene 3 (49.8–51.0s)：副标题"plugins_user/名字/plugin.py"落定。停住——本拍不做相机运动。

## Frame 14 — 收成一个

- scene: 近白场，暗字。**全片唯一停住不动的一拍**：标题块居中，右下角把 03–06 用过的布局图 chip 摊成一整面阵列（12 个），全部静止。没有任何位移。
- onscreen: "把十六个窗口，收成一个" / "Windows 开源免费 LGPL-2.1"
- duration: 4.5s
- poster: 4.5s
- transition_in: zoom-through
- field: field-light
- prop: 布局图 chip —— 回收：03–06 出现过的 chip 全部摊成阵列
- status: built
- src: compositions/frames/14-manifesto.html
- type: branding
- persuasion: Negative contrast
- beat: 平静
- blueprint: titlecard-reveal (Adapt)
- focal: assets/overview1_Landscape_mode.png
- roles: overview1 = supporting（缩到 ~12cqw 的缩略图，退到右下，作为 chip 阵列的"实物对照"）; chip 阵列 = cutout（12 个布局图，主视觉）
- asset_candidates: assets/overview1_Landscape_mode.png — 横屏平分布局真机截图，作为右下角的缩略图来源
- sfx: chime（chip 阵列成形的最后一下）, impact-bass-2（宣言落定，轻）

Adapt：titlecard-reveal 的签名是"一两张近乎静止的卡，一次上滑交叉淡入，然后**保持不动**——
低运动量本身就是重点"。本拍完全照这个来，是全片的 held frame。

narrativeRole: 全片唯一静止的一拍，把前面所有演示压成一句结论，同时让贯穿全片的 chip 回收成阵列。前面的密度是这一拍的燃料。
keyMessage: 一切都在一个窗口里。

Scene 1 (51.0–52.0s)：**zoom-through** 进近白场。标题块居中。
文案行"把十六个窗口，收成一个"以一次**上滑交叉淡入**落定——只用这一个动作。
Scene 2 (52.0–53.0s)：12 个布局图 chip 在标题下方分两组落定（0.6s 内完成，**chime** 收尾），
右下角退出一张真机截图的缩略图作为实物对照（opacity 0.5）。
Scene 3 (53.0–55.5s)：副标题"Windows 开源免费 LGPL-2.1"落定。
**从这里到本拍结束，画面一个像素都不动**——不高亮、不呼吸、不推近。
全片唯一真正的静止，用前面的密度换来的 2.5 秒。

## Frame 15 — 片尾

- scene: 纯黑。**官方 logo 拼装成形**：三层错位的圆角窗格先逐层描边走笔画出（从最外那层开始），然后两个 D 字标从左往右扫出，接着 CE 亮起，最后中间那条青→紫→粉的渐变缝合线合上。定格后下方淡入仓库地址。
- onscreen: "DD监控室CE" / "github.com/Lanpropro/DD_Monitor_CE"
- duration: 4.5s
- poster: 4.5s
- transition_in: crossfade
- field: field-black
- prop: logo —— 三层错位窗格是"画面墙"的抽象，片尾用拼装把它和全片的布局母题接上
- status: built
- src: compositions/frames/15-outro.html
- type: cta
- persuasion: Risk reversal
- beat: 行动的冲动
- blueprint: logo-assemble-lockup (Reproduce)
- focal: assets/logo.svg
- roles: logo = cutout（唯一主体，居中 ~19cqw）; logo.png = background（降级备份，不参与构图）
- asset_candidates: assets/logo.svg — 官方 logo（三层错位窗格 + DD 字标 + CE + 青紫粉渐变缝）; assets/logo.png — 同款位图，作为降级备份
- sfx: whoosh-short（每层窗格走笔一下）, riser（D 扫出的 1.0s 抬升）, chime（CE 亮起）, whoosh-cinematic（缝合线合上）

Reproduce：logo-assemble-lockup 的签名就是"元素清场、logo 自己画进来"。
本拍照它的形状做，且用的是**官方 logo 的真实结构**（三层错位窗格 + DD 路径 + CE + 渐变缝），
不做任何重绘。

narrativeRole: 把"开源免费"和"去哪拿"两件事说完，落地成一个地址。logo 的三层错位窗格正是"多路画面墙"的抽象——用它收尾，等于把全片的布局母题在最后一拍点上句号。
keyMessage: 开源免费，GitHub 自取。

Scene 1 (55.5–56.7s)：**crossfade** 收黑。三层错位窗格**由外向内**逐层描边走笔画出
（**SVG self-draw**，`svg-path-draw`；每层一次 **whoosh-short**），这是拼装的第一步。
Scene 2 (56.7–58.2s)：两个 D 字标**从左往右扫出**（遮罩扫出，**riser** 抬 1.0s），
随后 CE 亮起（**chime**），最后中间那条青→紫→粉渐变缝合线合上（**whoosh-cinematic**）。
**logo 的渐变色按原样使用，不改。**
Scene 3 (58.2–60.0s)：logo 定格，下方淡入"DD监控室CE"字标与仓库地址。
**这是全片唯一允许有 exit 的一拍**——最后 0.4s 整体极缓压暗收尾。

## 时长核算

6.0 + 4.5 + 3.5 + 3.5 + 3.5 + 3.5 + 5.5 + 3.5 + 3.5 + 3.5 + 3.5 + 3.5 + 3.5 + 4.5 + 4.5 = **60.0 秒**（15 拍）

节奏核对（对齐参考片实测）：开场 6.0s 长镜头（参考 6.75s）→ 标题 4.5s 含内部快切
（参考 6.75–9.6s 的爆发）→ 中段每拍 3.5s（参考 3–6s）→ 竖屏 5.5s 作为次高潮
（参考在 23–33s 也放了最长的一段实拍）→ 宣言 4.5s 静止收 → 片尾 4.5s logo 拼装。

**静止分配**：01（墙亮完停住）、07（转完停住）、14（整拍静止）——三处刻意的呼吸点，
其余各拍"揭示完即停"。唯一持续的运动是 06/08 的弹幕，它是主体自身的行为，不是装饰。

## 素材库查询记录

设计前按流程查了 HyperFrames 注册表（`npx hyperframes catalog --query`），
"logo assemble reveal" / "app window device mockup" / "audio waveform equalizer bars" /
"aurora gradient animated background" / "folder file tree terminal" 五条查询全部返回空，
`npx hyperframes catalog --json`（无条件）返回 `[]`——**该 CLI 版本下注册表整体取不到条目**。
因此全部视觉手写，不依赖现成 block。已知悉并如实记录。
