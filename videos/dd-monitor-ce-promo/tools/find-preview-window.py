"""在 4K 预览帧的左侧关注栏里找出「展开的卡片预览小窗」的 bbox。

判据：小窗是一整块有内容的矩形（直播画面），
- 行方向：在卡片横向范围内 std 高（有画面）且持续 ~130px；
- 列方向：在窗口纵向范围内 std 高。
普通列表卡高度只有 ~95px 且大部分是深色背景，靠"内容行段的高度 + 平均 std"区分。

用法：python tools/find-preview-window.py <frame.png> [x0 x1 y0 y1]
"""
import cv2, numpy as np, sys, os

p = sys.argv[1]
x0, x1, y0, y1 = (int(v) for v in (sys.argv[2:6] if len(sys.argv) >= 6 else (0, 360, 60, 1400)))
img = cv2.imread(p)
if img is None:
    print("cannot read", p); sys.exit(1)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
print("%s  %dx%d   ROI x %d..%d y %d..%d" % (os.path.basename(p), img.shape[1], img.shape[0], x0, x1, y0, y1))

band = gray[y0:y1, x0:x1]
rowstd = band.std(axis=1)
thr = max(6.0, float(np.percentile(rowstd, 60)))
runs, cur = [], None
for i, v in enumerate(rowstd):
    if v > thr:
        cur = [i, i] if cur is None else [cur[0], i]
    else:
        if cur is not None and cur[1] - cur[0] >= 25:
            runs.append(cur)
        cur = None
if cur is not None and cur[1] - cur[0] >= 25:
    runs.append(cur)

print("  content bands (std > %.1f, len>=25):" % thr)
for a, b in runs:
    ya, yb = y0 + a, y0 + b
    seg = gray[ya:yb + 1, x0:x1]
    colstd = seg.std(axis=0)
    cols = np.where(colstd > max(6.0, np.percentile(colstd, 55)))[0]
    xa = x0 + int(cols.min()) if cols.size else x0
    xb = x0 + int(cols.max()) if cols.size else x1
    print("    y %4d..%-4d  h=%3d   x %4d..%-4d  w=%3d   mean=%.1f  std=%.1f"
          % (ya, yb, yb - ya + 1, xa, xb, xb - xa + 1, seg.mean(), seg.std()))
