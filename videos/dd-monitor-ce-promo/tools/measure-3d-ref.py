import cv2, numpy as np, sys

p = sys.argv[1] if len(sys.argv) > 1 else "renders/_user-3d-ref.png"
img = cv2.imread(p)
H, W = img.shape[:2]
print("ref image %dx%d" % (W, H))

gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
# 卡片与背景都是灰，用梯度找边
edges = cv2.Canny(gray, 12, 40)
print("canny edges px:", int((edges > 0).sum()))

lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=60, minLineLength=120, maxLineGap=8)
segs = []
if lines is not None:
    for l in lines:
        x1, y1, x2, y2 = l[0]
        length = float(np.hypot(x2 - x1, y2 - y1))
        ang = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if ang < -90:
            ang += 180
        if ang > 90:
            ang -= 180
        segs.append((length, ang, x1, y1, x2, y2))

segs.sort(reverse=True)
print("\ntop 18 longest straight segments (length, angle deg from horizontal, endpoints):")
for length, ang, x1, y1, x2, y2 in segs[:18]:
    kind = "VERT" if abs(abs(ang) - 90) < 12 else ("HORIZ" if abs(ang) < 12 else "DIAG")
    print("  len=%6.1f  ang=%+7.2f deg  %-5s  (%4d,%4d)-(%4d,%4d)" % (length, ang, kind, x1, y1, x2, y2))

# 亮度剖面：沿几行/几列看跳变位置，定位卡片边界
lum = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(float)
print("\nrow mean luminance at several rows:")
for y in range(20, H, max(1, H // 12)):
    row = lum[y]
    print("  y=%4d  min=%6.1f max=%6.1f  left=%6.1f mid=%6.1f right=%6.1f"
          % (y, row.min(), row.max(), row[:W // 6].mean(), row[W // 2 - 40:W // 2 + 40].mean(), row[-W // 6:].mean()))
print("\ncolumn mean luminance at several cols:")
for x in range(10, W, max(1, W // 12)):
    col = lum[:, x]
    print("  x=%4d  min=%6.1f max=%6.1f  top=%6.1f mid=%6.1f bot=%6.1f"
          % (x, col.min(), col.max(), col[:H // 6].mean(), col[H // 2 - 40:H // 2 + 40].mean(), col[-H // 6:].mean()))
