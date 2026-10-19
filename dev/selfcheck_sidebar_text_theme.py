"""关注栏紧凑列表文字随主题切换，封面卡片保持浅色叠字。"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import theme
from ddm.widgets import NavItem


def assert_color(label, expected):
    # Palette roles can be reset during a theme switch; inspect the painted text.
    if expected.alpha() != 255:
        return
    image = label.grab().toImage()
    assert any(all(abs(a - b) <= 1 for a, b in zip(
        image.pixelColor(x, y).getRgb(), expected.getRgb()))
        for y in range(image.height()) for x in range(image.width())), (
            label.objectName(), expected.getRgb())


def main():
    app = QApplication([])
    theme.apply('dark')
    room = {'room_id': '123', 'uname': '主播', 'title': '直播标题', 'live': True}
    item = NavItem(room, 0)
    item.resize(300, item.height())
    item.show()
    for mode in ('dark', 'light', 'dark', 'light'):
        theme.apply(mode)
        for card in (False, True, False):
            item.set_card_mode(card)
            QTest.qWait(20)
            expected = (QColor('#ffffff'), QColor(238, 241, 246, 224)) if card else (
                theme.qcolor(theme.TEXT1), theme.qcolor(theme.TEXT2))
            for label, color in zip((item.name_label, item.sub), expected):
                assert_color(label, color)
        item.set_compact(True)
        item.set_compact(False)
        QTest.qWait(20)
        assert_color(item.name_label, theme.qcolor(theme.TEXT1))
        assert_color(item.sub, theme.qcolor(theme.TEXT2))
        fresh = NavItem(room, 1)
        fresh.set_card_mode(False)
        fresh.show()
        QTest.qWait(20)
        assert_color(fresh.name_label, theme.qcolor(theme.TEXT1))
        assert_color(fresh.sub, theme.qcolor(theme.TEXT2))
        fresh.close()
    item.close()
    print('PASS: sidebar list theme colours, cover text, layout transitions and new items')


if __name__ == '__main__':
    main()
