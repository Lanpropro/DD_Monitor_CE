import cv2, numpy as np, sys

# 原始卡片长图：8 张卡片竖排，实测周期 192px、卡高 182px、起点 y=26。
# 逐行方差找"间隔行"（纯色）与"卡片行"（有内容），据此定每张卡的上下边界。
p = sys.argv[1] if len(sys.argv) > 1 else r"../../Video_reference/卡片截图_自行裁剪.png"
# cv2.imread 在 Windows 上读不了非 ASCII 路径，用 fromfile + imdecode
img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
if img is None:
    print("cannot read", p); sys.exit(1)
h, w = img.shape[:2]
print("source %dx%d" % (w, h))

gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
rowstd = gray.std(axis=1)
rowmean = gray.mean(axis=1)
print("\nrows with low std (plain rows, std<3):")
runs = []
cur = None
for y in range(h):
    if rowstd[y] < 3.0:
        if cur is None:
            cur = [y, y, float(rowmean[y])]
        else:
            cur[1] = y
    else:
        if cur is not None:
            runs.append(cur); cur = None
if cur is not None:
    runs.append(cur)
for a, b, m in runs:
    print("  y %4d..%-4d  h=%3d  mean=%.1f" % (a, b, b - a + 1, m))

# 也报告每 192px 周期附近的边界细节
print("\nrow std / mean around expected card boundaries (cycle 192, start 26):")
for i in range(8):
    top = 26 + i * 192
    for y in range(max(0, top - 6), min(h, top + 8)):
        print("   card%d  y=%4d  std=%6.2f  mean=%6.1f" % (i + 1, y, rowstd[y], rowmean[y]))
    bot = top + 182
    for y in range(max(0, bot - 8), min(h, bot + 6)):
        print("   card%d  y=%4d  std=%6.2f  mean=%6.1f  (bottom)" % (i + 1, y, rowstd[y], rowmean[y]))
    print()
