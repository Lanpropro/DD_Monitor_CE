"""量粉丝牌渲染出来的实际尺寸：名字长短、等级位数不同时，高度必须一致。"""
import os
import sys

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.widgets import DanmakuPanel  # noqa: E402

# (名字, 等级, 颜色) —— 覆盖短名/长名、一位数/四位数等级、深色/浅色底
MEDALS = [
    ("绿冻", "7", "#5c7cfa"),
    ("满皇", "21", "#f5c542"),
    ("茶水间", "1000", "#8d8366"),
    ("非常长的粉丝牌名字", "3", "#e36ea7"),
]


def pixels_of(image, color: str) -> list[tuple[int, int]]:
    """找出这个颜色的像素坐标（粉丝牌是实心色块）。"""
    target = theme.mix(color, "#ffffff", 0.0).lstrip("#")
    red, green, blue = (int(target[index:index + 2], 16) for index in (0, 2, 4))
    hits = []
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if (abs(pixel.red() - red) <= 6 and abs(pixel.green() - green) <= 6
                    and abs(pixel.blue() - blue) <= 6):
                hits.append((x, y))
    return hits


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    panel = DanmakuPanel()
    panel.resize(460, 320)
    panel.show()
    panel.apply_style("", 13)
    for name, level, color in MEDALS:
        panel.add_event({"kind": "danmaku", "uname": f"{name}家的小号", "text": "测试弹幕",
                         "medal": {"name": name, "level": level, "color": color}})
    for _ in range(4):
        app.processEvents()

    panel.grab().save(os.path.join(REPO, "work", "preview", "medal_sizes.png"), "PNG")
    image = panel.grab().toImage()

    heights, tops = [], []
    for name, level, color in MEDALS:
        hits = pixels_of(image, color)
        if not hits:
            print(f"  {name}{level}: 没找到色块")
            return 1
        xs = [x for x, _ in hits]
        ys = [y for _, y in hits]
        height = max(ys) - min(ys) + 1
        widths = max(xs) - min(xs) + 1
        heights.append(height)
        tops.append(min(ys))
        print(f"  {name}{level:<5} 色块 {widths}x{height}  顶部 y={min(ys)}")

    print(f"\n高度：{heights}（应当全相同）")
    print(f"顶部 y：{tops}（应当全相同：同一行对齐）")
    ok = len(set(heights)) == 1 and len(set(tops)) == 1
    print("结论：" + ("统一" if ok else "不统一"))
    print("截图：work/preview/medal_sizes.png")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
