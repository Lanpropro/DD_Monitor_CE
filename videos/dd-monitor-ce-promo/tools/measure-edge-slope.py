import cv2, numpy as np, sys

# 裁出「卡片上边缘」区域并放大，方便肉眼比斜率方向；同时用竖直梯度拟合斜率。
jobs = [
    ("renders/v3-03-queue-check.png", (10, 950, 455, 560), "renders/_edge-mine.png"),
    ("renders/_user-3d-ref.png", (40, 820, 40, 150), "renders/_edge-ref-user.png"),
    ("renders/_ref-t195.png", (80, 700, 540, 660), "renders/_edge-ref-film.png"),
]

def fit_slope(gray, x0, x1, y0, y1):
    g = cv2.GaussianBlur(gray, (5, 5), 0).astype(np.float32)
    # 竖直方向梯度（Sobel y）
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    xs, ys = [], []
    for x in range(x0, x1, 4):
        col = np.abs(gy[y0:y1, x])
        if col.size == 0:
            continue
        i = int(np.argmax(col))
        if col[i] < 8:
            continue
        xs.append(x)
        ys.append(y0 + i)
    if len(xs) < 20:
        return None
    xs = np.array(xs, float); ys = np.array(ys, float)
    A = np.vstack([xs, np.ones_like(xs)]).T
    k, b = np.linalg.lstsq(A, ys, rcond=None)[0]
    return k, b, len(xs)

for path, (x0, x1, y0, y1), out in jobs:
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    r = fit_slope(gray, x0, x1, y0, y1)
    name = path.split("/")[-1]
    if r is None:
        print("%-26s ROI x %d..%d y %d..%d  -> 拟合失败" % (name, x0, x1, y0, y1))
        continue
    k, b, n = r
    ang = np.degrees(np.arctan(k))
    print("%-26s ROI x %4d..%4d y %4d..%4d  n=%3d  斜率 %+0.4f  = %+0.2f deg  (%s)"
          % (name, x0, x1, y0, y1, n, k, ang,
             "右端更低" if k > 0 else "右端更高"))
    crop = img[y0:y1, x0:x1]
    big = cv2.resize(crop, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(out, big)
    print("      -> %s  (%dx%d)" % (out, big.shape[1], big.shape[0]))
