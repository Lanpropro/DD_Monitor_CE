"""量左侧关注栏里「展开的预览小窗」的精确上下边界。

思路：小窗是一块比卡片背景亮的矩形。取小窗的横向范围（避开左侧头像区），
逐行求平均亮度，找亮度抬升/回落的跳变位置。

用法：python tools/window-bounds.py <frame.png> <x0> <x1> <y0> <y1>
"""
import cv2, numpy as np, sys, os

p, x0, x1, y0, y1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
img = cv2.imread(p)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
band = gray[y0:y1, x0:x1]
rows = band.mean(axis=1)

base = float(np.percentile(rows, 10))       # 卡片背景亮度
hi = float(np.percentile(rows, 95))
thr = base + (hi - base) * 0.35
print("%s  x %d..%d  y %d..%d   base=%.1f  hi=%.1f  thr=%.1f"
      % (os.path.basename(p), x0, x1, y0, y1, base, hi, thr))

inside, start = False, None
for i, v in enumerate(rows):
    y = y0 + i
    if not inside and v > thr:
        inside, start = True, y
    elif inside and v <= thr:
        if y - start >= 60:
            print("   window  y %4d..%-4d  h=%3d   (row mean %.1f -> %.1f)"
                  % (start, y - 1, y - start, rows[start - y0], rows[max(0, y - 1 - y0)]))
        inside = False
if inside and (y1 - start) >= 60:
    print("   window  y %4d..%-4d  h=%3d   (reaches ROI bottom)" % (start, y1 - 1, y1 - start))
print("   row mean profile (every 8px):")
print("   " + "  ".join("%d:%.0f" % (y0 + i, rows[i]) for i in range(0, len(rows), 8)))
