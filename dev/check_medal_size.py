"""Render the chat panel and check medal alignment and image resolution."""
import argparse
import os
from pathlib import Path
import sys
from unittest.mock import patch

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QColor, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DDM_NO_SAVE', '1')

from ddm import theme
from ddm.danmaku_widgets import DanmakuPanel


MEDALS = (
    ('绿冻', '7', '#184f48'),
    ('满皇', '21', '#f5c542'),
    ('茶水间', '1000', '#122a74'),
    ('非常长的粉丝牌名字', '3', '#651c7b'),
)
NAME_COLOR = '#00a1d6'
MESSAGE_COLOR = '#e6e9ee'


def bounds(image, color, *, left=0, top=0, bottom=None):
    target = QColor(color)
    hits = []
    for y in range(top, image.height() if bottom is None else min(bottom, image.height())):
        for x in range(left, image.width()):
            pixel = image.pixelColor(x, y)
            if all(abs(a - b) <= 8 for a, b in zip(pixel.getRgb()[:3], target.getRgb()[:3])):
                hits.append((x, y))
    assert hits, color
    return (min(x for x, _ in hits), min(y for _, y in hits),
            max(x for x, _ in hits), max(y for _, y in hits))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path)
    args = parser.parse_args()
    app = QApplication([])
    theme.apply('dark')
    panel = DanmakuPanel()
    panel.setAttribute(Qt.WA_ShowWithoutActivating)
    panel.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    panel.move(-10000, -10000)
    panel.resize(520, 280)
    panel.show()
    panel.apply_style('', 17)
    for name, level, color in MEDALS:
        panel.add_event({'uname': '新事旧', 'color': NAME_COLOR, 'text': '发言测试',
                         'medal': {'name': name, 'level': level, 'color': color}})
    app.processEvents()
    shot = panel.body.viewport().grab()
    if args.snapshot is not None:
        assert panel.grab().save(str(args.snapshot))
    image, dpr = shot.toImage(), shot.devicePixelRatioF()
    document = panel.body.document()
    block = document.firstBlock()
    heights = []
    for _, _, color in MEDALS:
        _, top, right, bottom = bounds(image, color)
        heights.append(bottom - top + 1)
        midpoint = (top + bottom) / 2
        padding = round(10 * dpr)
        for ink in (NAME_COLOR, MESSAGE_COLOR):
            _, ink_top, _, ink_bottom = bounds(image, ink, left=right + 1,
                                              top=max(0, top - padding), bottom=bottom + padding)
            difference = abs(midpoint - (ink_top + ink_bottom) / 2)
            assert difference <= 3 * dpr, (color, ink, difference / dpr)
        fmt = block.begin().fragment().charFormat().toImageFormat()
        assert fmt.verticalAlignment() == QTextCharFormat.AlignMiddle
        badge = document.resource(QTextDocument.ImageResource, QUrl(fmt.name()))
        assert badge.devicePixelRatioF() == dpr
        assert abs(badge.width() - fmt.width() * dpr) <= 1
        assert abs(badge.height() - fmt.height() * dpr) <= 1
        block = block.next()
    assert max(heights) - min(heights) <= 1, heights
    medal_count = len(panel._images)
    new_dpr = 2 if dpr != 2 else 1.5
    with patch.object(panel.body.viewport(), 'devicePixelRatioF', return_value=new_dpr):
        app.sendEvent(panel, QEvent(QEvent.DevicePixelRatioChange))
        app.processEvents()
        for url, badge in panel._images.items():
            assert badge.devicePixelRatioF() == new_dpr
            assert document.resource(QTextDocument.ImageResource, QUrl(url)).devicePixelRatioF() == new_dpr
    assert len(panel._images) == medal_count and document.blockCount() == len(MEDALS)
    panel.close()
    print(f'PASS: centered fan medals and DPI-matched text at {dpr:g}×')


if __name__ == '__main__':
    main()
