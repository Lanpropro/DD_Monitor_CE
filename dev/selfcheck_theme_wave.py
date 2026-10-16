"""Theme wave endpoints, reversal, media holes, cancellation and reduced motion."""
import os
from pathlib import Path
import platform
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
platform._wmi_query = lambda *a: (_ for _ in ()).throw(OSError('Isolated test'))
from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPalette
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from ddm import app as app_module, motion, theme
from ddm.theme_transition import wave_path, ui_snapshot
from ddm.dialogs import SettingsDialog
from dev.selfcheck_tile_fullscreen import SilentPoller


def main():
    app = QApplication([])
    errors = []
    original_hook = sys.excepthook
    def capture(kind, value, traceback):
        errors.append(value)
        original_hook(kind, value, traceback)
    sys.excepthook = capture
    app_module.StatusPoller = app_module.StatsPoller = SilentPoller
    room = dict(room_id='990000', uname='Wave test', live=False)
    with patch('PySide6.QtCore.QTimer.singleShot'):
        window = app_module.MainWindow([room], [dict(room)], layout_id='corner',
            state={'plugins_enabled': [], 'settings': {'auto_update': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    window.resize(1280, 720)
    window.show()
    QTest.qWait(60)
    width, height = window.width(), window.height()
    assert not wave_path(0, width, height).contains(QPoint(width//2, height//2))
    assert wave_path(1, width, height).contains(QPoint(width-1, height-1))
    surface = window.wall.tiles[0].video
    center = surface.mapTo(window, surface.rect().center())
    snapshot = ui_snapshot(window).toImage()
    ratio = snapshot.devicePixelRatio()
    assert snapshot.pixelColor(round(center.x()*ratio), round(center.y()*ratio)).alpha() == 255, 'Empty tiles must participate in the wave, not switch instantly'
    window.wall.tiles[0]._player_active = True
    playing_snapshot = ui_snapshot(window).toImage()
    assert playing_snapshot.pixelColor(round(center.x()*ratio), round(center.y()*ratio)).alpha() == 0, 'Playing video must remain uncovered'
    window.wall.tiles[0]._player_active = False
    handles = [int(tile.video.winId()) for tile in window.wall.tiles]
    with patch.object(motion, 'enabled', return_value=True):
        with patch.object(app, 'setStyleSheet', side_effect=AssertionError('Theme switch must not re-polish the global stylesheet')), patch('ddm.theme_transition.ui_snapshot', wraps=ui_snapshot) as grab:
            window.set_appearance('light')
            assert grab.call_count == 1, 'A normal switch needs only its old UI snapshot'
        transition = window._theme_transition
        assert transition.animation.duration() == 360
        assert transition.overlays and transition.animation.state() == QAbstractAnimation.Running
        QTest.qWait(40)
        assert transition.overlays, 'Theme wave cancelled during normal painting'
        assert window.wall.grid.spacing() == 8
        transition.animation.setCurrentTime(motion.THEME_WAVE_MS//2)
        progress = transition.progress
        assert 0 < progress < 1
        overlay = transition.overlays[0]
        reset_palette = QPalette(app.palette())
        reset_palette.setColor(QPalette.Window, QColor('#101114'))
        app.setPalette(reset_palette)
        assert transition.overlays[0] is overlay and transition.progress == progress, 'External palette refresh must not cancel or restart the reveal'
        origin = window.sidebar.appearance_button.mapTo(window, QPoint())
        assert overlay.origin == origin, 'Origin must be the button top-left, not the window edge or click centre'
        early = wave_path(.1, width, height, origin)
        assert early.contains(origin + QPoint(1, 1))
        assert not early.contains(QPoint(width-1, height-1))
        assert wave_path(1, width, height, origin).contains(QPoint(width-1, height-1))
        assert overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
        assert overlay.windowFlags() & Qt.WindowTransparentForInput
        output = ROOT / 'work/appearance-delivery'
        output.mkdir(parents=True, exist_ok=True)
        assert overlay.grab().save(str(output / 'wave-half.png'))
        visible = ui_snapshot(window)
        painter = QPainter(visible)
        painter.drawPixmap(0, 0, overlay.grab())
        painter.end()
        window.set_appearance('dark')
        assert transition.overlays[0].snapshot.toImage() == visible.toImage(), 'Interruption must preserve the visible frame'
        assert transition.progress == 0.0, 'New colour must flow from the button'
        assert transition.animation.endValue() == 1.0
        window.set_appearance('light')
        assert transition.progress == 0.0 and transition.animation.endValue() == 1.0
        transition.animation.setCurrentTime(transition.animation.duration())
        assert not transition.overlays and transition.animation.state() == QAbstractAnimation.Stopped
        assert theme.is_light() and window.settings['appearance_mode'] == 'light'
        for _ in range(5):
            QTest.qWait(30)
            assert theme.is_light() and not transition.overlays, 'Settled light theme must not revive a dark snapshot'
            footer = window.wall.tiles[0].bottom.grab().toImage()
            scale = footer.devicePixelRatio()
            assert footer.pixelColor(round(20*scale), round(5*scale)).name() == '#f0f3f8', 'Light footer must keep its rendered colour after switching'
        assert handles == [int(tile.video.winId()) for tile in window.wall.tiles]
        with patch('PySide6.QtCore.QTimer.singleShot'):
            dialog = SettingsDialog(window.settings, window.shortcuts, window)
        dialog.nav.setCurrentRow(1)
        dialog.appearanceChanged.connect(window.set_appearance)
        with patch.object(motion, 'enabled', return_value=False):
            dialog.show()
            QTest.qWait(40)
        dialog.appearance_page.buttons['dark'].click()
        assert len(transition.overlays) == 2, 'Main and settings windows should both transition'
        button_origin = dialog.appearance_page.buttons['dark'].mapToGlobal(QPoint())
        assert all(o.origin == o.parentWidget().mapFromGlobal(button_origin) for o in transition.overlays)
        QTest.qWait(40)
        assert len(transition.overlays) == 2
        dialog.reject()
        assert not transition.overlays, 'Closing settings should release all its transition snapshots'
        window.set_appearance('light')
        transition.finish()
        window.set_appearance('dark')
        assert transition.overlays
        assert window.wall.grid.spacing() == 8
        window.resize(1300, 740)
        app.processEvents()
        assert not transition.overlays, 'Resize must release snapshot windows'
        window.set_appearance('light')
        assert transition.overlays
        app.sendEvent(window, QEvent(QEvent.DevicePixelRatioChange))
        assert not transition.overlays, 'DPI change must release snapshots'
        window.set_appearance('dark')
        window.set_appearance('light')
        assert transition.overlays
        theme.apply('dark')
        assert not transition.overlays, 'External/system change must cancel stale snapshots'
        app.sendEvent(window, QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier))
        window.set_appearance('light')
        assert not transition.overlays and theme.is_light(), 'Keyboard action should switch immediately'
        QTest.mouseClick(window.sidebar.appearance_button, Qt.LeftButton)
        assert transition.overlays
        overlay = transition.overlays[0]
        origin = window.sidebar.appearance_button.mapTo(window, QPoint())
        assert overlay.origin == origin
        # Inspect the actual overlay pixels after the sidebar click. Points on
        # the same vertical line must reveal at different times, unlike a sweep.
        overlay.reveal(.25)
        frame = overlay.grab().toImage()
        scale = frame.devicePixelRatio()
        x = window.wall.tiles[0].video.mapTo(window, QPoint()).x() + 40
        near = QPoint(x, origin.y() + 30)
        far = QPoint(x, window.height() - 120)
        assert frame.pixelColor(round(near.x()*scale), round(near.y()*scale)).alpha() == 0
        assert frame.pixelColor(round(far.x()*scale), round(far.y()*scale)).alpha() == 255, 'The lower empty tile must retain the old theme until the circular wave reaches it'
    with patch.object(motion, 'enabled', return_value=False):
        window.set_appearance('light')
        assert not transition.overlays and theme.is_light()
    with patch.object(motion, 'enabled', return_value=True):
        window.set_appearance('dark')
        assert transition.overlays
        window.close()
        assert not transition.overlays, 'Close must leave no floating overlay'
    app.processEvents()
    assert not errors, errors
    print('PASS: wave endpoints, live-video holes, continuous interrupted snapshots, input passthrough, resize/close/system cancellation, keyboard/reduced-motion fallback and stable video HWNDs')


if __name__ == '__main__':
    main()
