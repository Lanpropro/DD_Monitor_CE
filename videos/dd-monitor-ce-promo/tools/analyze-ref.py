"""把参考片拆成**可读的数据**（不是我"看"图，而是测量）。

为什么不用 motion-web 的 measure_frames.py：
它把 PNG 写到系统 temp（`tempfile.mkdtemp()`），在本沙箱里被拒，报 I/O error。
这里全程只读视频、只往 stdout 写，不落任何临时文件。

用法：
    python tools/analyze-ref.py raw/ref.mp4
输出：
    · 基本参数
    · 场景切换点（HSV 直方图 BHATTACHARYYA 距离 > 阈值）
    · 每秒的 RGB 均值 / 亮度 / 十六进制 —— 用来读"明暗节奏"和"色场切换"
    · 每段场景的主色（k-means，k=3）
"""
import sys

import cv2
import numpy as np

path = sys.argv[1] if len(sys.argv) > 1 else "raw/ref.mp4"
CUT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.32

cap = cv2.VideoCapture(path)
if not cap.isOpened():
    print(f"!! 打不开 {path}")
    raise SystemExit(1)

fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
dur = total / fps if fps else 0.0
print(f"== {path}")
print(f"fps={fps:.3f}  frames={total}  duration={dur:.2f}s")

step = max(1, int(round(fps / 10)))  # 10 Hz 采样
prev_hist = None
cuts = []
samples = []  # (t, (r,g,b), lum)

i = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    if i % step == 0:
        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        t = i / fps
        if prev_hist is not None:
            d = float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
            if d > CUT:
                cuts.append((round(t, 2), round(d, 3)))
        prev_hist = hist

        b, g, r = (float(v) for v in small.mean(axis=(0, 1)))
        lum = int(0.299 * r + 0.587 * g + 0.114 * b)
        samples.append((round(t, 2), (int(r), int(g), int(b)), lum))
    i += 1
cap.release()

print(f"\n== scene cuts (hist distance > {CUT}): {len(cuts)}")
for t, d in cuts:
    print(f"   t={t:6.2f}s   d={d}")

# 把时间轴按切点切成段，报每段时长 + 主色
bounds = [0.0] + [t for t, _ in cuts] + [round(dur, 2)]
cap2 = cv2.VideoCapture(path)
print("\n== segments ==")
print(f"   {'#':>2}  {'in':>7}  {'out':>7}  {'len':>6}   dominant colours")
for idx in range(len(bounds) - 1):
    a, b = bounds[idx], bounds[idx + 1]
    if b - a < 0.25:
        continue
    cap2.set(cv2.CAP_PROP_POS_MSEC, (a + (b - a) * 0.5) * 1000.0)
    ok, fr = cap2.read()
    if not ok:
        continue
    sm = cv2.resize(fr, (160, 90), interpolation=cv2.INTER_AREA)
    data = sm.reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _, labels, centers = cv2.kmeans(data, 3, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=3)
    order = np.argsort(-counts)
    cols = []
    for k in order:
        bb, gg, rr = centers[k]
        pct = 100.0 * counts[k] / counts.sum()
        cols.append(f"#{int(rr):02x}{int(gg):02x}{int(bb):02x} {pct:4.1f}%")
    print(f"   {idx:>2}  {a:>7.2f}  {b:>7.2f}  {b-a:>6.2f}   " + "  ".join(cols))
cap2.release()

print("\n== luminance timeline (每 0.5s, 读明暗节奏) ==")
line = ""
for t, _rgb, lum in samples:
    ch = " .:-=+*#%@"
    line += ch[min(9, int(lum / 26))]
    if len(line) == 120:
        print("   " + line)
        line = ""
if line:
    print("   " + line)
print("   (每字符 0.1s；' '=最暗 ≈0  '@'=最亮 ≈255)")
