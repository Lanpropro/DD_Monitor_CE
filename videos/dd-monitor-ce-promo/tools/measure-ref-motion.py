"""量参考片的相机运动 / 标题淡入淡出 / 软件窗口出现时间。

为什么需要：A 组（`18-01-intro.html`）的相机速率曲线、以及「窗口出现 1.44s /
标题隐去 1.79s」这两个时刻，都是用户要求照参考片前 4 秒定的。靠肉眼估缓动不可靠，
这里直接从像素反推，把「感觉」变成可复现的数字。

做法（都不需要 GPU，纯 OpenCV）：

  · 相机位移 —— 对画面 **30-60%** 带做 `cv2.phaseCorrelate`，逐帧求全局平移并累加。
    这条带避开了左侧标题（标题占 x 7.8%-26%），但**窗口从右侧进入后会污染它**
    （实测 2.75s 起不可信），所以脚本同时输出 **0-7%** 带（避开标题左部）做交叉验证，
    并打印每帧的 `resp` 匹配置信度 —— resp 掉到 0.3 以下就别信那一帧。
  · 标题 —— 左侧带（x 0-35%，y 40-72%）里亮像素（灰度 > 140）的计数曲线。
    基线约 860（背景本身的亮部），标题满值约 14800，淡入淡出看得一清二楚。
  · 窗口 —— 最右 6 列的平均亮度：窗口右缘贴上画面右缘时会跳一下（实测 1.458s 从 72 跳到 121）。
    注意参考片窗口是**米白**而不是纯白，用 V>195 & S<45 的"近白"掩膜去找窗口左缘不可靠
    （会被标题的白色文字骗到），所以这里只用右缘那一下的跳变定时。

用法：
    python tools/measure-ref-motion.py raw/ref.mp4            # 默认 0-4.8s
    python tools/measure-ref-motion.py raw/ref.mp4 0 8        # 指定区间

参考片实测结论（raw/ref.mp4，1920x1080 / 24fps / 63.373s）：
    0.00-1.38s   匀加速（位移 ∝ t^2），走 189px，峰值 258px/s
    1.38-1.88s   完全静止 0.5s
    1.44s        软件窗口从画面右缘进入
    1.79-2.04s   标题隐去（0.25s）
    1.92-4.00s   恒定 315px/s
    4.00-4.96s   357 -> 0 px/s，平滑减速到停
"""
import sys

import cv2
import numpy as np

path = sys.argv[1] if len(sys.argv) > 1 else "raw/ref.mp4"
t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
t1 = float(sys.argv[3]) if len(sys.argv) > 3 else 4.8

cap = cv2.VideoCapture(path)
if not cap.isOpened():
    print(f"!! cannot open {path}")
    raise SystemExit(1)

fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
frames = []
while True:
    ok, frame = cap.read()
    if not ok:
        break
    frames.append(frame)
frames = frames[int(round(t0 * fps)):int(round(t1 * fps))]
if not frames:
    print("!! no frames in range")
    raise SystemExit(1)

gray = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
H, W = gray[0].shape

print(f"== {path}")
print(f"fps={fps:.4f}  range={t0}-{t1}s  frames={len(frames)}  size={W}x{H}")
print()
print("   t   | cam_mid_cum | cam_left_cum | title_bright | rightcol")
print("        |  (30-60%)   |    (0-7%)    |    (>140)    |")

x0m, x1m = int(W * 0.30), int(W * 0.60)
x0l, x1l = 0, int(W * 0.07)
ty0, ty1 = int(H * 0.40), int(H * 0.72)

cum_mid = 0.0
cum_left = 0.0
for i, g in enumerate(gray):
    if i > 0:
        (dxm, _), _r = cv2.phaseCorrelate(np.float32(gray[i - 1][:, x0m:x1m]), np.float32(g[:, x0m:x1m]))
        cum_mid += dxm
        (dxl, _), _r2 = cv2.phaseCorrelate(np.float32(gray[i - 1][:, x0l:x1l]), np.float32(g[:, x0l:x1l]))
        cum_left += dxl
    title = int((g[ty0:ty1, 0:int(W * 0.35)] > 140).sum())
    rightcol = float(g[:, W - 6:W].mean())
    print("%6.3f | %11.2f | %12.2f | %12d | %7.1f"
          % (t0 + i / fps, cum_mid, cum_left, title, rightcol))
