---
workflow: product-launch-video
flow: automation
storyboard: yes
message: "十六路直播，不必开十六个窗口"
destination: bilibili
aspect: 1920x1080
language: zh
audience: 同时追好几个直播间的 B 站用户
length: 60s
angle: 布局系统当主角 —— 画面墙自己会动
narration: no
voice: none
style_preset: cobalt-grid
---

## Intent

给「DD监控室CE」做一支 60 秒宣传片。DD监控室CE 是一个 Windows 桌面工具，
把最多 16 路 B 站直播间塞进同一个画面墙，并且有一套很厚的布局系统
（横屏平分布局 / 大带小 / 弹幕布局，外加一整套竖屏预设，拖窗口换方向还会
按「能放几路」自动接上最相似的布局）。

这是一支**产品展示片**，不是概念片：片子要让人 60 秒内看懂"同时盯很多个直播间"
这件事已经被一屏解决了。调性对齐参考片（`Video_reference/` 里那支 LauncherX
启动器宣传片）——干净、克制、大字号中文标题 + 软件窗口演示，白场暗场交替，
纯 BGM 无口播。

**核心决定：产品本身就是主角。** 参考片全程没有实拍，软件画面全是窗口截图在动；
而本项目要走得更实——**软件真实运行的录屏**。所以片子的骨架是"画面墙自己会动"：
逐格亮起 → 布局变形 → 拖成竖屏 → 弹幕滚动 → 每格单独调音。装饰越少越好，
让真实界面占满注意力。

## Assets

- `capture/assets/overview1_Landscape_mode.png` — 3840×2160 横屏平分布局真机截图，
  左主画面 + 右侧两小 + 下排三格，侧栏关注列表可见。全片主力 hero，可大幅 punch-in。
- `capture/assets/overview2_Landscape_mode.png` — 3840×2160 横屏弹幕布局真机截图，
  弹幕面板里能看到粉丝牌、表情、屏蔽词。弹幕段落的主画面。
- `capture/assets/overview1_Portrait_Mode.png` — 1600×2559 竖屏布局真机截图。
- `capture/assets/portrait-current.png` / `portrait-bar.png` — 竖屏形态与顶部横栏特写。
- `capture/extracted/tokens.json` — 品牌令牌，取自软件本体 `ddm/theme.py`（真实来源，
  不是记忆里的配色）；含 `colorStats`，按真机截图里各色实际占的面积与用途标注。
- **待补：屏幕录制母版**（主显示器全屏 4K30，NVENC）。等直播间开播后录，产物进 `assets/`。

## Customizations

- **真实录屏优先于截图运镜**：这是本片的定制点，也是它和参考片最大的分野。
  录制母版固定为主显示器全屏 3840×2160 @30fps，成片时按窗口区域裁切。
- **左右声道路由的可视化**：软件可以把每一路单独路由到左声道/右声道，这是别家没有的
  功能，值得一个独立节拍，用声音波形跑向左右来表现。
- **横屏拖成竖屏的连续过程**：不是切一个竖屏截图，而是拍下窗口从横变竖、布局自动
  接上最相似预设的完整过程。用程序改窗口尺寸触发（`ddm/app.py:368` 的 `resizeEvent`，
  和手动拖动是同一条代码路径）。
- **字体不做联网下载**：Microsoft YaHei UI / Microsoft YaHei / Segoe UI 都是 Windows
  系统自带字体，避免任何授权问题。

## Notes

- 片尾**不加**"画面来自公开直播间"的版权说明（用户明确选择保持干净）。
- 设计系统是**严格双色**（Cobalt Grid 的 doctrine）：暗底 `#222428` + 近白字 `#f1f2f5`，
  B 站蓝 `#00a1d6` 是唯一的第二色。B 站粉 `#fb7299` **不进设计系统**，
  只在真实录屏里自然出现（直播徽标、弹幕点）。
- **禁止事项**：不做假的软件界面（一切软件画面必须来自真实截图或真实录屏）；
  不做幻灯片式的一格一换；不做无意义的环境动效；不加发光描边。
- 参考片：`Video_reference/来看看最新的_MC_启动器___LauncherX.29543304125.mp4`
  （1920×1080 / 24fps / 63.4 秒 / 纯 BGM）。已加入 `.gitignore`，不进版本库。
- 软件本体没有 logo 文件（只有 `favicon.ico`），片尾用字体排出字标，不硬造 logo。
- 录制依赖直播间在线：**录屏素材不可复现**，直播间下播就补不回来，因此要一次性
  录足一池原始素材再从里面剪，而不是缺哪段补哪段。
- 录制期间鼠标不能被碰，窗口一偏那条素材就废。
