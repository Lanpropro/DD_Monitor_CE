# 宣传片封面

用户确认v5成片后要求制作封面。采用深灰、青蓝和近白，与成片视觉一致；以多平台Apex同屏及CS2比赛解说画面为参考，构成有轻微透视的两块软件窗口。

- 文件：`videos/dd-monitor-ce-plugins-promo/covers/dd-monitor-ce-cover-v1.png`。
- 规格：1672×941，近16:9，RGB、不透明PNG，2091114 bytes。
- 文案：“DD监控室CE”“多平台同屏 · 比赛双解说”“一起看，更尽兴。”。
- 生成方式：内置图像生成工具；参考当前工程9.5秒国内画面、42.35秒精彩画面及61.125秒片尾Logo。不添加性能承诺或占位文字。
- 图为生成式宣传视觉，软件窗口依照真实截图重构，细小UI文字不作为准确功能说明。
- 原始生成文件：`C:/Users/Lan/.codex/generated_images/01a11758-8cca-7382-a41f-0a33ba0d0491/exec-b0990d43-4eee-46b7-a90c-cc96bf972be2.png`；原图原样复制到工程。
- 验证：人工核对主文案、Logo、排版与480px缩略图可读性；`python -m unittest dev.test_promo_cover -v` 检查尺寸比例、PNG各块CRC和完整像素数据。

不修改已确认视频、时间轴或音频。

## 柔和版（v2）

用户反馈第一版视觉过于锐利。以第一版为编辑参考，用内置图像生成工具减弱发光边框、去除硬斜线与地面反射、减少窗口透视，将标题改为正向排版，副标题改为柔和灰青蓝；保留原文案、Logo识别及两块软件画面的主题。

输出 `videos/dd-monitor-ce-plugins-promo/covers/dd-monitor-ce-cover-v2.png`，原封面保留。原始生成文件 `C:/Users/Lan/.codex/generated_images/01a11758-8cca-7382-a41f-0a33ba0d0491/exec-63ea29eb-1cb5-4c66-aba2-57443a351b25.png`，原样复制到工程。沿用封面文件验证，并同时检查两个版本。
