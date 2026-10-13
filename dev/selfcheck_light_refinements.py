"""Light tiles, account controls, pink add-room action and direct settings opening."""
import os
from pathlib import Path
import platform
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
platform._wmi_query = lambda *a: (_ for _ in ()).throw(OSError('Isolated test'))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import app as module, motion, theme
from ddm.dialogs import SettingsDialog
from ddm.widgets import _icon_color
from dev.selfcheck_tile_fullscreen import SilentPoller


def sample(widget, point):
    image = widget.grab().toImage()
    dpr = image.devicePixelRatio()
    return image.pixelColor(round(point.x()*dpr), round(point.y()*dpr))


def main():
    app = QApplication([])
    module.StatusPoller = module.StatsPoller = SilentPoller
    with patch('PySide6.QtCore.QTimer.singleShot'):
        window = module.MainWindow([], [], layout_id='1x1',
            state={'plugins_enabled': [], 'settings': {'auto_update': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    window.resize(1280, 800)
    window.show()
    window.sidebar.logoutRequested.disconnect(window.logout)
    account = window.sidebar.account_row
    account.set_account('浅色测试用户', uid='123456')
    clicks = []
    account.logoutClicked.connect(lambda: clicks.append(True))
    tile = window.wall.tiles[0]
    hwnd = int(tile.video.winId())
    with patch.object(motion, 'enabled', return_value=False):
        for mode in ('light', 'dark', 'light'):
            window.set_appearance(mode)
            QTest.qWait(50)
            if mode == 'light':
                assert sample(tile.video, QPoint(20, tile.video.height()//2)) == QColor('#F4F6F9')
                point = tile.bottom.mapTo(window, QPoint(5, tile.bottom.height()//2))
                assert sample(window, point) == QColor('#F4F6F9')
                button = window.sidebar.add_button
                assert sample(button, QPoint(20, button.height()//2)) == QColor('#FB7299')
                assert account.name.palette().color(QPalette.WindowText) == QColor('#202630')
                assert _icon_color(tile.pause_button) == theme.qcolor(theme.TEXT2)
                logout = account.logout_button
                assert logout.width() >= logout.fontMetrics().horizontalAdvance(logout.text()) + 16
                assert logout.height() >= logout.fontMetrics().height() + 6
                assert logout.geometry().right() < account.width()
            else:
                assert sample(tile.video, QPoint(20, tile.video.height()//2)) == QColor(theme.TILE_BG)
                assert sample(window.sidebar.add_button, QPoint(20, window.sidebar.add_button.height()//2)) == QColor(theme.ACCENT)
            assert int(tile.video.winId()) == hwnd
        QTest.mouseClick(account.logout_button, Qt.LeftButton)
        assert clicks == [True]
        with patch('PySide6.QtCore.QTimer.singleShot'):
            settings = SettingsDialog(window.settings, window.shortcuts, window)
        settings.setAttribute(Qt.WA_ShowWithoutActivating)
        settings.move(-10000, -10000)
        settings.show()
        assert not hasattr(settings, '_entrance')
        position = settings.pos()
        QTest.qWait(200)
        assert settings.pos() == position
        visible = [w for w in app.topLevelWidgets() if w.isVisible()]
        assert set(visible) == {window, settings}, 'Settings must not show an intermediate top-level window'
        settings.reject()
    output = ROOT / 'work/appearance-delivery'
    output.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(output / 'light-refined.png'))
    window.close()
    print('PASS: light tile/footer, pink add-room button, readable account, enclosed clickable logout, direct settings and stable HWND')


if __name__ == '__main__':
    main()
