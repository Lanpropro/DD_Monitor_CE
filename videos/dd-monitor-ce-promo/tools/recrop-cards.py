"""从 Video_reference/卡片截图_自行裁剪.png 重裁 8 张卡片。

实测（tools/measure-card-rows.py，逐行 std 找纯色间隔行）：
  源图 321x1561，卡片内容 **x 12..308（297 宽）**
  第一张内容起点 **y 13**，两张之间是 **21 行纯色背景**（#1F1F1F），
  所以周期 **195**、卡高 **174**。
之前用的 crop 是 `321x182 起点 26 周期 192` —— 每张卡底部therefore带着 21 行灰边，
这就是"下方还有灰边"的来源。

输出：297x174 按 Lanczos4 放大到目标尺寸（默认 760x445，与卡片框 1:1），
再做一次轻度 unsharp（sigma 1.2 / amount 0.6）—— 源分辨率就 297 宽，
放大 3 倍必然发虚，只能靠这一步把边缘拉回来一点。
"""
import cv2, numpy as np, os, sys

SRC = r"F:\CodexAppManager\Code\DD_Monitor_CE\Video_reference\卡片截图_自行裁剪.png"
OUT_DIR = r"F:\CodexAppManager\Code\DD_Monitor_CE\videos\dd-monitor-ce-promo\assets\rec"

X, W = 12, 297
Y0, CYC, H = 13, 195, 174
TW, TH = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (760, 445)

img = cv2.imdecode(np.fromfile(SRC, dtype=np.uint8), cv2.IMREAD_COLOR)
print("source %dx%d" % (img.shape[1], img.shape[0]))

for i in range(8):
    y = Y0 + i * CYC
    card = img[y:y + H, X:X + W]
    assert card.shape[:2] == (H, W), "card %d wrong shape %s" % (i + 1, card.shape)
    big = cv2.resize(card, (TW, TH), interpolation=cv2.INTER_LANCZOS4)
    blur = cv2.GaussianBlur(big, (0, 0), 1.2)
    sharp = cv2.addWeighted(big, 1.6, blur, -0.6, 0)
    out = os.path.join(OUT_DIR, "card-%d.png" % (i + 1))
    cv2.imwrite(out, sharp)
    print("card-%d.png  crop y %d..%d (x %d..%d) -> %dx%d  %d bytes"
          % (i + 1, y, y + H - 1, X, X + W - 1, TW, TH, os.path.getsize(out)))
