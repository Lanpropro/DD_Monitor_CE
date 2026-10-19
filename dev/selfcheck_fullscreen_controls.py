"""Offline fullscreen bar animation, interruption, settings and corner alpha."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, theme
from ddm.dialogs import GeneralSettingsPage
from ddm.widgets import TimeBadge
from dev.selfcheck_tile_fullscreen import SilentPoller


def main():
    app = QApplication([])
    badge = TimeBadge()
    refreshed = []
    badge.refresh_theme = lambda: refreshed.append(True)
    badge.event(QEvent(QEvent.Type.Show))
    badge.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not refreshed, 'Destroyed badges must cancel queued theme refreshes'
    app_module.StatusPoller = app_module.StatsPoller = SilentPoller
    room = {'room_id': '1000', 'uname': 'Fixture', 'live': False}
    with patch('ddm.app.QTimer.singleShot'):
        window = app_module.MainWindow([room], [dict(room)], layout_id='1x1',
            state={'plugins_enabled': [], 'settings': {'auto_update': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    window.resize(900, 650)
    window.show()
    window.isActiveWindow = lambda: True
    tile = window.wall.tiles[0]
    cursor = window._fullscreen_cursor
    try:
        for mode in ('dark', 'light'):
            theme.apply(mode)
            app.processEvents()
            for corner in tile.video_corners:
                image = QImage(24, 24, QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(2)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                corner._render_badge(painter)
                painter.end()
                assert any(0 < image.pixelColor(x, y).alpha() < 255
                           for y in range(24) for x in range(24)), 'Missing antialiased pixels'
                outside_x = 23 if corner.right else 0
                assert image.pixelColor(outside_x, 0).alpha() == 0, 'Corner backing covers skin background'
                assert image.pixelColor(12, 12).alpha() == 0, 'Corner backing covers video interior'
                if app.platformName() == 'windows':
                    QTest.qWait(30)
                    assert corner._alpha_uploaded, 'Corner must use per-pixel alpha in both themes'
            assert all(corner.isVisible() for corner in tile.video_corners)
        window._fullscreen_tile = tile
        window.wall.set_fullscreen_tile(tile)
        app.processEvents()
        assert all(not corner.isVisible() for corner in tile.video_corners)
        geometry = tile.video.geometry()
        assert geometry.height() == tile.height(), 'Fullscreen video must fill the bottom too'
        normal_y = tile.bottom.y()
        point = tile.video.mapToGlobal(tile.video.rect().center())
        with patch('ddm.fullscreen_cursor.QCursor.pos', return_value=point), \
                patch('ddm.motion.enabled', return_value=True):
            cursor.start()
            cursor._last_move = 0
            cursor.update_cursor()
            assert cursor.hidden
            QTest.qWait(60)
            assert normal_y < tile.bottom.y() < tile.height(), 'Bar must slide down'
            halfway = tile.bottom.y()
            cursor._position = point - QPoint(1, 0)
            cursor.update_cursor()
            assert not cursor.hidden and abs(tile.bottom.y() - halfway) <= 1, 'Reversal jumped'
            QTest.qWait(220)
            assert tile.bottom.y() == normal_y and tile.bottom.isVisible()
            assert tile.video.geometry() == geometry, 'Animation resized native video'
            cursor._last_move = 0
            cursor.update_cursor()
            QTest.qWait(220)
            assert cursor.hidden and not tile.bottom.isVisible()
            window.settings['fullscreen_auto_hide_controls'] = False
            cursor.update_cursor()
            QTest.qWait(220)
            assert tile.bottom.isVisible() and tile.bottom.y() == normal_y, 'Switch-off must restore bar'
            assert tile.video.geometry() == geometry
            with patch.object(QApplication, 'activePopupWidget', return_value=object()):
                cursor.update_cursor()
                assert not cursor.hidden, 'Menu must restore controls and cursor'
            window.settings['fullscreen_auto_hide_controls'] = True
            with patch('ddm.motion.enabled', return_value=False):
                cursor._last_move = 0
                cursor.update_cursor()
                assert not tile.bottom.isVisible(), 'Reduced motion must hide immediately'
                cursor.stop()
                assert tile.bottom.isVisible(), 'Reduced motion must restore immediately'
            outside = tile.mapToGlobal(QPoint(tile.width() + 100, tile.height() // 2))
            with patch('ddm.fullscreen_cursor.QCursor.pos', return_value=outside):
                cursor.update_cursor()
                QTest.qWait(220)
                assert not tile.bottom.isVisible() and not tile.controls.isVisible(), 'Leaving the screen must hide both bars'
                assert not cursor.hidden and QApplication.overrideCursor() is None, 'Other monitor cursor must stay visible'
                cursor.update_cursor()
                assert tile._bar_animation.state() == QAbstractAnimation.Stopped, 'Outside polling must not restart the slide'
                window.settings['fullscreen_auto_hide_controls'] = False
                cursor.update_cursor()
                QTest.qWait(220)
                assert tile.bottom.isVisible(), 'Leaving must respect the auto-hide switch'
                window.settings['fullscreen_auto_hide_controls'] = True
                cursor.update_cursor()
                QTest.qWait(220)
            cursor.update_cursor()
            QTest.qWait(220)
            assert tile.bottom.isVisible() and tile.controls.isVisible(), 'Returning must restore both bars'
            cursor._last_move = 0
            cursor.update_cursor()
            QTest.qWait(220)
            assert cursor.hidden
            with patch('ddm.fullscreen_cursor.QCursor.pos', return_value=outside):
                cursor.update_cursor()
                assert not cursor.hidden and QApplication.overrideCursor() is None, 'Leaving from idle must release the cursor'
            cursor.stop()
        window._fullscreen_tile = None
        window.wall.set_fullscreen_tile(None)
        assert tile._bar_progress == 0 and tile.bottom.isVisible()
        assert all(corner.isVisible() for corner in tile.video_corners)
        page = GeneralSettingsPage({'fullscreen_auto_hide_controls': False})
        assert not page.values()['fullscreen_auto_hide_controls']
        page.reset()
        assert page.values()['fullscreen_auto_hide_controls']
        assert window.current_state()['settings']['fullscreen_auto_hide_controls']
        page.close()
    finally:
        cursor.stop()
        window.close()
        app.processEvents()
    print('PASS: corner alpha, fullscreen slide, reversal, screen exit/return, cursor visibility, switch and cleanup')


if __name__ == '__main__':
    main()
