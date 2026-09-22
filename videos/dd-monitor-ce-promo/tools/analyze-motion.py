"""量出参考片的**相机运动曲线**（不是"看"画面，是测量）。

为什么需要：用户反馈"移动过程有点掉帧"，要求参考片里的速率和曲线。
靠肉眼猜缓动不可靠，这里直接从帧间位移反推速度曲线。

做法：把每帧缩到 480 宽转灰度，用 cv2.phaseCorrelate 求相邻帧的全局平移，
累加成位移曲线，再求导得到速度；位移按 1920/480 换算回原始尺度。

用法：
    python tools/analyze-motion.py raw/ref.mp4            # 全片概览
    python tools/analyze-motion.py raw/ref.mp4 0 8        # 只看 0-8s（含每帧明细）
"""
import sys

import cv2
import numpy as np

path = sys.argv[1] if len(sys.argv) > 1 else "raw/ref.mp4"
win0 = float(sys.argv[2]) if len(sys.argv) > 2 else -1.0
win1 = float(sys.argv[3]) if len(sys.argv) > 3 else -1.0

cap = cv2.VideoCapture(path)
if not cap.isOpened():
    print(f"!! 打不开 {path}")
    raise SystemExit(1)

fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
dur = total / fps if fps else 0.0
W = 480
print(f"== {path}")
print(f"fps={fps:.3f}  frames={total}  duration={dur:.2f}s")

prev = None
samples = []  # (t, dx, dy, resp)
idx = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    t = idx / fps
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    scale = W / g.shape[1]
    g = cv2.resize(g, (W, int(round(g.shape[0] * scale))))
    g = np.float32(g)
    if prev is not None and prev.shape == g.shape:
        (dx, dy), resp = cv2.phaseCorrelate(prev, g)
        samples.append((t, dx / scale, dy / scale, resp))
    prev = g
    idx += 1
cap.release()

if not samples:
    print("!! 没有采到帧")
    raise SystemExit(1)

arr = np.array(samples)  # t, dx, dy, resp
t = arr[:, 0]
dx = arr[:, 1]
resp = arr[:, 3]

# 响应低的帧（场景切换 / 无纹理）不可信，速度记 0 但不参与统计
trust = resp >= 0.08

# ---------- 概览：每 0.5s 的速度 ----------
print("\n== 全片运动概览（每 0.5s 的平均速度，px/s @1920）")
print("   · = 水平右移   ·= 水平左移")
bucket = 0.5
n = int(np.ceil(dur / bucket))
for b in range(n):
    lo, hi = b * bucket, (b + 1) * bucket
    m = (t >= lo) & (t < hi) & trust
    if not m.any():
        print(f"  {lo:6.2f}s  {'':>12}  (无有效帧)")
        continue
    vx = dx[m].sum() / bucket
    vy = arr[m, 2].sum() / bucket
    speed = abs(vx)
    bar = ("+" if vx >= 0 else "-") * min(60, int(speed / 40))
    print(f"  {lo:6.2f}s  vx={vx:8.1f} px/s  vy={vy:7.1f}  {bar}")

# ---------- 找出"持续单方向移动"的段落 ----------
print("\n== 连续单方向运动段落（|vx| 连续 >= 3 帧超过 60px/s）")
run_start = None
run_dx = 0.0
for i in range(len(t)):
    fast = trust[i] and abs(dx[i]) * fps > 60
    same_dir = run_dx == 0 or (dx[i] * run_dx > 0)
    if fast and same_dir:
        if run_start is None:
            run_start = t[i]
            run_dx = dx[i]
        run_dx += dx[i]
    else:
        if run_start is not None and t[i] - run_start >= 0.25:
            seg = (t >= run_start) & (t <= t[i]) & trust
            d = dx[seg].sum()
            print(f"  {run_start:6.2f} → {t[i]:6.2f}s  ({t[i]-run_start:5.2f}s)  "
                  f"位移 {d:8.1f}px  平均 {d/(t[i]-run_start):7.1f} px/s")
        run_start = None
        run_dx = 0.0

# ---------- 明细：窗口内逐帧速度 + 累积位移 ----------
if win0 >= 0:
    print(f"\n== {win0}-{win1}s 逐帧明细（每 {max(1,int(round(fps/12)))} 帧一行）")
    print("     t      dx(px)   vx(px/s)   cum(px)   resp   速度条")
    step = max(1, int(round(fps / 12)))
    m = (t >= win0) & (t <= win1)
    sub = arr[m]
    cum = 0.0
    for k in range(0, len(sub), step):
        tt, ddx, _, rr = sub[k]
        cum += sub[max(0, k - step + 1):k + 1, 1].sum()
        v = ddx * fps
        bar = "#" * min(50, int(abs(v) / 25))
        print(f"  {tt:6.2f}  {ddx:8.2f}  {v:9.1f}  {cum:9.1f}   {rr:5.2f}  {bar}")
    # 拟合：把累积位移归一化，看它像哪条缓动
    print(f"\n== {win0}-{win1}s 累积位移的归一化形状（用于反推缓动）")
    cum_all = np.cumsum(sub[:, 1])
    if abs(cum_all[-1]) > 1:
        norm = cum_all / cum_all[-1]
        print("     p(时间进度)  ->  s(位移进度)   与 linear 的差")
        for p in [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]:
            k = min(len(norm) - 1, int(round(p * (len(norm) - 1))))
            print(f"     {p:5.2f}      ->  {norm[k]:6.3f}        {norm[k]-p:+.3f}")
