import cv2, numpy as np, glob, os

# 量每张卡片素材的"灰色边"边界：逐列/逐行统计低饱和（灰）像素占比。
for f in sorted(glob.glob("assets/rec/card-*.png")):
    img = cv2.imread(f)
    h, w = img.shape[:2]
    b, g, r = cv2.split(img.astype(np.int16))
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = (mx - mn) < 14                     # 低饱和 = 灰
    lum = (0.299 * r + 0.587 * g + 0.114 * b)
    colG = sat.mean(axis=0)                  # 每列灰像素比例
    rowG = sat.mean(axis=1)
    # 从左右两端找第一条"不是整列灰"的列
    def edge(arr, lo, hi, step):
        i = lo
        while (i < hi) if step > 0 else (i > hi):
            if arr[i] < 0.85:
                return i
            i += step
        return None
    left = edge(colG, 0, w, 1)
    right = edge(colG, w - 1, 0, -1)
    top = edge(rowG, 0, h, 1)
    bot = edge(rowG, h - 1, 0, -1)
    print("%-14s %dx%d  content x %s..%s (w=%s)   y %s..%s (h=%s)   left/right gray cols=%s/%s"
          % (os.path.basename(f), w, h, left, right,
             (right - left + 1) if (left is not None and right is not None) else "?",
             top, bot,
             (bot - top + 1) if (top is not None and bot is not None) else "?",
             (right if right else 0), (w - 1 - left if left is not None else 0)))

# 再看首尾若干列的灰占比，确认灰边到底多宽
f = "assets/rec/card-1.png"
img = cv2.imread(f).astype(np.int16)
b, g, r = cv2.split(img)
sat = ((np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)) < 14)
colG = sat.mean(axis=0)
print("\ncard-1.png 每列灰占比（前 20 / 后 20）:")
print("  head:", " ".join("%.2f" % v for v in colG[:20]))
print("  tail:", " ".join("%.2f" % v for v in colG[-20:]))
