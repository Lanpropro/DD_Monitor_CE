"""把预览图整理成便于查看的尺寸：整体缩略 + 侧栏细节裁切。"""
import os

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview")


def save_scaled(source: QImage, path: str, width: int) -> None:
    scaled = source.scaledToWidth(width, Qt.SmoothTransformation)
    scaled.save(path, "PNG")
    print(f"{os.path.basename(path)}: {scaled.width()}x{scaled.height()}")


def save_crop(source: QImage, path: str, rect: QRect) -> None:
    source.copy(rect).save(path, "PNG")
    print(f"{os.path.basename(path)}: {rect.width()}x{rect.height()}")


def main() -> None:
    main_image = QImage(os.path.join(OUT, "wall_2560x1440.png"))
    print(f"主屏原图: {main_image.width()}x{main_image.height()}")
    save_scaled(main_image, os.path.join(OUT, "view_main.png"), 1800)
    # 侧栏 + 第一格（含单窗口控制条，1.5 倍缩放下的物理像素）
    save_crop(main_image, os.path.join(OUT, "view_detail.png"), QRect(0, 0, 1500, 840))

    focus = QImage(os.path.join(OUT, "wall_focus.png"))
    save_scaled(focus, os.path.join(OUT, "view_focus.png"), 1800)

    rail = QImage(os.path.join(OUT, "wall_sidebar_rail.png"))
    save_scaled(rail, os.path.join(OUT, "view_rail.png"), 1800)

    portrait = QImage(os.path.join(OUT, "wall_914x1463.png"))
    print(f"副屏原图: {portrait.width()}x{portrait.height()}")
    save_scaled(portrait, os.path.join(OUT, "view_portrait.png"), 700)


if __name__ == "__main__":
    main()
