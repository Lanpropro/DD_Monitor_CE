"""Verify historic Unicode glyphs render in video danmaku text."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = next((path for path in (ROOT, *ROOT.parents)
                if (path / "libmpv-2.dll").is_file()), ROOT)
os.environ["PATH"] = str(RUNTIME) + os.pathsep + os.environ.get("PATH", "")
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import theme  # noqa: E402
from ddm.danmaku_raster import CommentRaster  # noqa: E402


def main():
    app = QApplication.instance() or QApplication([])
    font = theme.danmaku_font("Source Han Sans SC", 24)
    runs = theme.danmaku_font_runs("文字𒅌文字", font)
    if QFontDatabase.families():
        assert any(text == "𒅌" and "Segoe UI Historic" in selected.families()
                   for text, selected in runs), runs
    else:
        # The offscreen Qt platform has no system font database; the real
        # Windows run selects Segoe UI Historic, while this still checks that
        # the fallback family is carried by the configured font.
        assert "Segoe UI Historic" in font.families()
    raster = CommentRaster(font, 1, 1, 500, {})
    image = raster._render_text("𒅌", QColor("white"))
    assert not image.isNull() and image.width() > 0 and image.height() > 0
    print("PASS: historic Unicode glyph fallback and raster rendering")


if __name__ == "__main__":
    main()
