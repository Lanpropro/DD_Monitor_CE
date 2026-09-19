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
  参考片靠一张巨型版本号卡片贯穿全片（下载页、反馈页又回来），本项目用 chip 做同一件事：
  它在 03–06 每一拍出现，在 14 摊成一整面阵列回收。它把七个分散的场景缝成一支片子。
- **场景色场（一帧只用一种，平面不加纹理）**：
  `field-black #0d0e10`（开场、片尾）· `field-dark #222428`（竖屏、重连、插件）·
  `field-blue #00a1d6`（**布局系统整段 03–06**）· `field-light #f1f2f5`（细节段 08–11、宣言 14）。
- **Brand（来自真实来源，不是记忆）**：`ddm/theme.py`。
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
  前面的节奏越密，这一拍越值钱。
- **真实来源声明**：所有软件画面来自软件真实运行（录屏）或软件真机截图（`docs/`）。
  片中出现的直播间、用户名、弹幕均来自真实公开直播间，**照实呈现，不做虚构**。

## Frame 01 — 墙面亮起

- scene: 黑场。16 个格子在黑暗里逐格亮起，每一格接进一路真实直播；弹幕细线横向划过。镜头全程极缓推近，一镜到底不切。
- onscreen: （无字——这一拍只给画面）
- duration: 6s
- poster: 5s
- transition_in: cut
- field: field-black
- status: outline
- src: compositions/frames/01-wall-ignite.html
- type: hook
- persuasion: Show-don't-tell proof
- beat: 好奇
- blueprint: zoom-out-workspace-reveal
- asset_candidates: assets/rec-wall-build.mp4 — 从空布局开始、主播逐个进墙、格子逐格亮起的真实录屏

narrativeRole: 用参考片同样的手法开场——先给一个 6 秒的氛围长镜头，不给任何信息。"本该很乱却自己排得整整齐齐"的秩序感就是钩子。
keyMessage: 这场面是一个窗口，不是十六个。

## Frame 02 — 标题

- scene: 墙面压暗退到背景。标题块居中打出：重磅主标题在上、副标题在下，块内做 2–3 次极快的字替（参考片 6.75–9.6s 那次标题爆发）。落定后停住。
- onscreen: "十六路直播，不必开十六个窗口" / "DD监控室CE 专为 B 站直播设计的多窗口监控工具"
- duration: 4.5s
- poster: 4s
- transition_in: blur-crossfade
- field: field-dark
- status: outline
- src: compositions/frames/02-title.html
- type: product_intro
- persuasion: Future pacing
- beat: 清晰
- blueprint: kinetic-type-beats
- asset_candidates: assets/rec-wall-build.mp4 — 同一条素材压暗当作底

narrativeRole: 在第 2 拍把结论说完（reverse iceberg：先给价值，后面全是举证），并给产品命名。参考片在同一个位置做的是密集快切，本拍照做。
keyMessage: 十六路 = 一个窗口。

## Frame 03 — 想怎么看，就怎么排

- scene: B 站蓝满场，平面无纹理。左下角布局图 chip 从"单格"变成"四分"；右侧窗口里的画面同步被切开重排。标题块居中在上。
- onscreen: "想怎么看，就怎么排" / "平分布局"
- duration: 3.5s
- poster: 3s
- transition_in: zoom-through
- field: field-blue
- prop: 布局图 chip —— 单格 → 四分
- status: outline
- src: compositions/frames/03-layout-1to4.html
- type: feature_showcase
- persuasion: Friction reduction
- beat: 掌控
- blueprint: grid-card-assemble
- asset_candidates: assets/rec-layout-1to4.mp4 — 切「布局预设」菜单、单画面变四分的真实录屏

narrativeRole: 把"布局系统"这个核心卖点用一次真实的形态变化讲清楚——不是菜单截图，是墙真的变了。蓝色场是参考片那种"换场换色"的节拍器。
keyMessage: 排布是免费的，不是一个高级功能。

## Frame 04 — 九路同屏

- scene: 同一个蓝场，chip 从四分继续走到九分；窗口里九路画面同时铺满。镜头轻微推近再停。
- onscreen: "九路同屏，一眼看全" / "单画面 两分 四分 六分 九分"
- duration: 3.5s
- poster: 3s
- transition_in: crossfade
- field: field-blue
- prop: 布局图 chip —— 四分 → 九分
- status: outline
- src: compositions/frames/04-layout-9grid.html
- type: feature_showcase
- persuasion: Value stacking
- beat: 满足
- blueprint: device-surface-showcase
- asset_candidates: assets/rec-layout-9grid.mp4 — 切到九分平分布局的真实录屏

narrativeRole: 把平分布局的整个梯度一次性摊开，证明"多变"是真的一整套而不是两三个。
keyMessage: 平分布局有从一到九的完整梯度。

## Frame 05 — 大带小

- scene: 蓝场。chip 换成"一大五小"的线框；窗口里主画面钉死在左侧不动，右侧五路小画面依次归位环绕。
- onscreen: "主画面不动，小画面环绕" / "主画面 加 2 3 4 5 小"
- duration: 3.5s
- poster: 3s
- transition_in: push-slide LEFT
- field: field-blue
- prop: 布局图 chip —— 一大五小（主画面位置高亮）
- status: outline
- src: compositions/frames/05-layout-bigplus.html
- type: feature_showcase
- persuasion: Show-don't-tell proof
- beat: 秩序感
- blueprint: fixed-anchor-cycle
- asset_candidates: assets/rec-layout-bigplus.mp4 — 切「主画面 + 5 小环绕」的真实录屏

narrativeRole: 证明布局不只是等分格子——有主次。主画面钉住不动是这一拍的全部说服力。
keyMessage: 有主有次，不是一律等分。

## Frame 06 — 弹幕进墙

- scene: 蓝场收尾。chip 换成"主画面 + 弹幕"；窗口右侧一整格变成弹幕面板，弹幕从下往上滚动，其余格子继续播。
- onscreen: "弹幕跟着主画面走" / "弹幕布局"
- duration: 3.5s
- poster: 3s
- transition_in: push-slide LEFT
- field: field-blue
- prop: 布局图 chip —— 主画面 + 右侧弹幕格
- status: outline
- src: compositions/frames/06-layout-danmaku.html
- type: feature_showcase
- persuasion: Friction reduction
- beat: 沉浸
- blueprint: device-surface-showcase
- asset_candidates: assets/rec-layout-danmaku.mp4 — 切「主画面 + 弹幕」并让弹幕滚动的真实录屏

narrativeRole: 弹幕不是外挂窗口，是画面墙里的一格——解决了"看直播还要另开一个弹幕页"的老麻烦。这一拍结束，蓝色的布局整段收束。
keyMessage: 弹幕是墙的一部分。

## Frame 07 — 拖成竖的

- scene: 换回暗场。同一个窗口从 16:9 连续变成 9:16：先是窗口边框在动，然后内部布局重排、侧栏变成顶部横栏。一镜到底，不切。
- onscreen: "拖成竖的，它自己接上" / "按能放几路 自动对映最相似的预设"
- duration: 5.5s
- poster: 4.5s
- transition_in: zoom-through
- field: field-dark
- status: outline
- src: compositions/frames/07-portrait-flip.html
- type: feature_showcase
- persuasion: Friction reduction
- beat: 惊喜 → 省心
- blueprint: panel-edit-live-sync
- asset_candidates: assets/rec-portrait-flip.mp4 — 窗口从横屏连续变成竖屏、布局自动切换的真实录屏

narrativeRole: 全片最有说服力的一拍，也是别家没有的一拍：改方向不是"重排一遍"，是"它自己接上"。一镜到底不许切，切了就不成立了。
keyMessage: 连拖窗口这件事它都想到了。

## Frame 08 — 弹幕面板

- scene: 换到近白场，暗字。窗口推近到弹幕格：粉丝牌徽章、B 站表情、屏蔽词过滤后的干净弹幕流依次被点出。
- onscreen: "粉丝牌 表情 屏蔽词" / "字体字号可调"
- duration: 3.5s
- poster: 3s
- transition_in: zoom-through
- field: field-light
- status: outline
- src: compositions/frames/08-danmaku-panel.html
- type: feature_showcase
- persuasion: Feature-to-benefit translation
- beat: 舒适
- blueprint: cursor-ui-demo
- asset_candidates: assets/rec-danmaku-panel.mp4 — punch-in 到弹幕格的特写录屏

narrativeRole: 上一拍说"弹幕在墙里"，这一拍证明弹幕本身也是认真做的，不是塞了个文本框。近白场把细节衬出来。
keyMessage: 弹幕面板是按 B 站生态做的。

## Frame 09 — 关注列表

- scene: 白场。镜头拉到左侧关注列表：鼠标悬停弹出封面预览缩略卡，然后是置顶徽标和拖动排序的位移。
- onscreen: "悬停就能预览" / "开播提醒 置顶 拖动排序 导入关注"
- duration: 3.5s
- poster: 3s
- transition_in: push-slide LEFT
- field: field-light
- status: outline
- src: compositions/frames/09-follow-list.html
- type: feature_showcase
- persuasion: Friction reduction
- beat: 省心
- blueprint: device-surface-showcase
- asset_candidates: assets/rec-follow-list.mp4 — 悬停预览 + 拖动排序的真实录屏

narrativeRole: 证明"从关注到上墙"这条路是通的——片子到这里才把"内容从哪来"补上。
keyMessage: 关注列表直接就是素材库。

## Frame 10 — 每一路，单独调

- scene: 白场。某一格的底部控制条展开：音量滑杆、静音、画质依次亮起；同时另外八格保持不受影响。
- onscreen: "每一路 单独调" / "音量 静音 画质"
- duration: 3.5s
- poster: 3s
- transition_in: crossfade
- field: field-light
- status: outline
- src: compositions/frames/10-tile-audio.html
- type: benefit_highlight
- persuasion: Feature-to-benefit translation
- beat: 掌控
- blueprint: cursor-ui-demo
- asset_candidates: assets/rec-tile-audio.mp4 — 打开单格音量/静音/画质菜单的真实录屏

narrativeRole: 多路同屏最容易崩的就是"声音怎么办"，这一拍直接回答它。
keyMessage: 十六路不是一个整体，是十六个独立的路。

## Frame 11 — 这一路放左边

- scene: 白场竖向一分为二：左半屏只有一路画面、声波跑向左；右半屏另一路、声波跑向右。中间一条细线把声道分开，两侧完全对称。
- onscreen: "这一路放左边 这一路放右边" / "每路独立左右声道路由"
- duration: 3.5s
- poster: 3s
- transition_in: push-slide LEFT
- field: field-light
- status: outline
- src: compositions/frames/11-channel-route.html
- type: benefit_highlight
- persuasion: Show-don't-tell proof
- beat: 意外 → 满足
- blueprint: comparison-split
- asset_candidates: assets/rec-channel-route.mp4 — 音量菜单里切「左声道 / 右声道」的真实录屏

narrativeRole: 这是本项目独有、别人抄不动的功能，必须给独立一拍。用对称的画面把"左/右"变成可看的东西。
keyMessage: 声音的去向是可控的。

## Frame 12 — 断了自己连回来

- scene: 换回暗场。某一格黑掉，角标变成重连中的琥珀色；2 秒后画面自己回来，角标恢复。全程没有人工操作。
- onscreen: "断了自己连回来" / "断流重连 画面卡死检测"
- duration: 3.5s
- poster: 3s
- transition_in: crossfade
- field: field-dark
- status: outline
- src: compositions/frames/12-reconnect.html
- type: benefit_highlight
- persuasion: Risk reversal
- beat: 安心
- blueprint: kinetic-type-beats
- asset_candidates: assets/rec-wall-build.mp4 — 画面墙素材，取某一格做重连状态的表现

narrativeRole: 长时间挂机的人最怕的就是半夜某一路悄悄死了——这一拍把那个担心直接消掉。暗场是这一拍成立的前提（黑掉的格子必须在暗底上才看得出来）。
keyMessage: 不用一直盯着它有没有掉。

## Frame 13 — 想加功能，写个插件

- scene: 暗场。淡入到安静的界面特写：`plugins_user/` 目录结构 + 一个真实插件例子 `danmaku_log`。左边一个极简的线性图标。
- onscreen: "本体不带的功能 插件带" / "plugins_user/名字/plugin.py"
- duration: 3.5s
- poster: 3s
- transition_in: blur-crossfade
- field: field-dark
- status: outline
- src: compositions/frames/13-plugins.html
- type: feature_showcase
- persuasion: Authority by association
- beat: 信任
- blueprint: device-surface-showcase
- asset_candidates: assets/overview2_Landscape_mode.png — 真机截图，用作背景层

narrativeRole: 说明这个工具是可扩展的、不是封死的——对象是愿意折腾的那部分用户。
keyMessage: 边界是可以自己往外推的。

## Frame 14 — 收成一个

- scene: 近白场，暗字。**全片唯一停住不动的一拍**：标题块居中，右下角把 03–06 用过的布局图 chip 摊成一整面阵列（大约十二个），全部静止。没有任何位移。
- onscreen: "把十六个窗口，收成一个" / "Windows 开源免费 LGPL-2.1"
- duration: 5s
- poster: 5s
- transition_in: zoom-through
- field: field-light
- prop: 布局图 chip —— 回收：03–06 出现过的 chip 全部摊成阵列
- status: outline
- src: compositions/frames/14-manifesto.html
- type: branding
- persuasion: Negative contrast
- beat: 平静
- blueprint: titlecard-reveal
- asset_candidates: assets/overview1_Landscape_mode.png — 横屏平分布局真机截图，作为缩略图来源

narrativeRole: 全片唯一静止的一拍，把前面所有演示压成一句结论，同时让贯穿全片的 chip 回收成阵列。前面的密度是这一拍的燃料。
keyMessage: 一切都在一个窗口里。

## Frame 15 — 片尾

- scene: 纯黑。字标从笔画组装成形，下面一行仓库地址，最后定格。
- onscreen: "DD监控室CE" / "github.com/Lanpropro/DD_Monitor_CE"
- duration: 4s
- poster: 4s
- transition_in: crossfade
- field: field-black
- status: outline
- src: compositions/frames/15-outro.html
- type: cta
- persuasion: Risk reversal
- beat: 行动的冲动
- blueprint: logo-assemble-lockup
- asset_candidates: （纯字体排版拍，不引用素材）

narrativeRole: 把"开源免费"和"去哪拿"两件事说完，落地成一个地址。
keyMessage: 开源免费，GitHub 自取。

## 时长核算

6.0 + 4.5 + 3.5 + 3.5 + 3.5 + 3.5 + 5.5 + 3.5 + 3.5 + 3.5 + 3.5 + 3.5 + 3.5 + 5.0 + 4.0 = **60.0 秒**（15 拍）

节奏核对（对齐参考片实测）：开场 6.0s 长镜头（参考 6.75s）→ 标题 4.5s 含内部快切
（参考 6.75–9.6s 的爆发）→ 中段每拍 3.5s（参考 3–6s）→ 竖屏 5.5s 作为次高潮
（参考在 23–33s 也放了最长的一段实拍）→ 宣言 5.0s 收 → 片尾 4.0s（参考最后 3.25s）。
