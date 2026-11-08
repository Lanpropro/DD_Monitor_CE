"""Native settings occlusion and clipping fallback; isolated screen-off windows."""
import json
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ['DDM_QTQUICK_DANMAKU'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, QProcess, QRect, QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from ddm import config, settings_process
from dev.selfcheck_settings_process import wait


def worker():
    from ddm import dialogs

    class FixtureDialog(dialogs.SettingsDialog):
        def showEvent(self, event):
            super().showEvent(event)
            if not hasattr(self, 'steps'):
                self.steps = iter(('shown', 'moved', 'resized', 'hidden', 'restored',
                                   'minimized', 'normal'))
                QTimer.singleShot(100, self.step)

        def step(self):
            stage = next(self.steps, None)
            if stage is None:
                return
            if stage == 'moved':
                self.move(self.pos() + QPoint(80, 50))
            elif stage == 'resized':
                self.resize(self.width() + 50, self.height() + 40)
            elif stage == 'hidden':
                self.hide()
            elif stage == 'restored':
                self.show()
            elif stage == 'minimized':
                self.showMinimized()
            elif stage == 'normal':
                self.showNormal()

            def report():
                rect = list(self.frameGeometry().getRect()) if self.isVisible() and not self.isMinimized() else []
                print(settings_process.PREFIX + json.dumps(
                    {'kind': 'fixture', 'stage': stage, 'rect': rect}), flush=True)
            QTimer.singleShot(30, report)

    def show(dialog):
        if hasattr(dialog, 'steps'):
            dialog.step()  # Host acknowledges each phase after native assertions.
            return
        dialog.setAttribute(Qt.WA_ShowWithoutActivating)
        dialog.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        dialog.setGeometry(-9900, -9900, 980, 720)
        dialog.show()

    dialogs.SettingsDialog = FixtureDialog
    settings_process._activate_dialog = show
    return settings_process.run_worker()


def main():
    if '--worker' in sys.argv:
        return worker()
    from ddm import app as host, plugins
    from ddm.video_danmaku_quick import QuickDanmakuLayer
    from dev.selfcheck_tile_fullscreen import SilentPoller
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    user32 = ctypes.windll.user32
    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HRGN)
    gdi32 = ctypes.windll.gdi32
    gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
    gdi32.CreateRectRgn.restype = wintypes.HRGN
    gdi32.PtInRegion.argtypes = (wintypes.HRGN, ctypes.c_int, ctypes.c_int)
    gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)

    def above(first, second):
        current = second
        while current:
            current = user32.GetWindow(current, 3)  # GW_HWNDPREV
            if current == first:
                return True
        return False

    def native_mask_covers_settings(layer, client, expected=True):
        overlay = wintypes.RECT()
        assert user32.GetWindowRect(int(layer.window.winId()), ctypes.byref(overlay))
        # The mask is submitted in logical window coordinates; GetWindowRgn
        # reports physical client coordinates, including for screen-off windows.
        point = layer.window.mapFromGlobal(client.occlusion.center())
        scale = layer.window.devicePixelRatio()
        x, y = round(point.x() * scale), round(point.y() * scale)
        assert 0 <= x < overlay.right - overlay.left
        assert 0 <= y < overlay.bottom - overlay.top
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        try:
            assert user32.GetWindowRgn(int(layer.window.winId()), region)
            actual = bool(gdi32.PtInRegion(region, x, y))
            assert actual == expected, (actual, expected, x, y, scale)
        finally:
            gdi32.DeleteObject(region)
    with tempfile.TemporaryDirectory() as temporary, \
            patch.object(config, 'REPO', temporary), \
            patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')), \
            patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(Path(temporary) / 'plugins')), \
            patch.object(host, 'StatusPoller', SilentPoller), \
            patch.object(host, 'StatsPoller', SilentPoller), \
            patch.object(QuickDanmakuLayer, '_set_layered', QuickDanmakuLayer._set_layered
                         if app.platformName() == 'windows' else lambda self: None):
        with patch.object(host.QTimer, 'singleShot'):
            window = host.MainWindow([], [], layout_id='1x1', state={
                'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        window.setGeometry(-10000, -10000, 1500, 1100)
        window.show()
        layer = window.wall.ensure_quick_danmaku_layer()
        assert layer is not None
        group = layer.create_group(0, 0, window.wall.width(), window.wall.height())
        image = QImage(80, 30, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.white)
        layer.add(group, image, 300, 200, 80, 30)
        client = window._get_settings_process()
        messages = []
        client.received.connect(messages.append)
        awaiting_window = []
        client.occlusionChanged.connect(lambda: awaiting_window.append(not layer.window.isVisible())
            if client.visible and not client.closing and not getattr(client, 'window_hwnd', 0) else None)
        command = (sys.executable, [str(Path(__file__).resolve()), '--worker'])
        try:
            with patch.object(settings_process, 'worker_command', return_value=command), \
                    patch.object(settings_process, '_allow_foreground'):
                # Exiting an unused prewarmed process must not touch a layer
                # whose QWidget parent may already be undergoing destruction.
                warm_client = settings_process.SettingsProcess()
                warm_changes = []
                warm_client.occlusionChanged.connect(lambda: warm_changes.append(True))
                try:
                    warm_client.warm()
                    wait(app, lambda: warm_client.ready)
                    assert warm_client.finish()
                    assert not warm_changes, 'Unused worker shutdown must not invalidate overlays'
                finally:
                    warm_client.finish()
                for ending in ('cancel', 'crash', 'stop'):
                    messages.clear()
                    awaiting_window.clear()
                    client.open(config.DEFAULT_SETTINGS, {})
                    wait(app, lambda: client.visible)
                    assert awaiting_window and all(awaiting_window), 'Pending HWND must suppress Quick synchronously'
                    if not getattr(client, 'window_hwnd', 0):
                        assert not layer.window.isVisible(), 'Wait for the settings HWND before showing/raising Quick'
                    previous = None
                    for stage in ('shown', 'moved', 'resized', 'hidden', 'restored', 'minimized', 'normal'):
                        wait(app, lambda: any(m.get('stage') == stage for m in messages))
                        expected = next(m['rect'] for m in messages if m.get('stage') == stage)
                        wait(app, lambda: client.occlusion == (QRect(*expected) if expected else QRect()))
                        assert client.occlusion == (QRect(*expected) if expected else QRect()), stage
                        origin = window.wall.mapToGlobal(QPoint())
                        if expected:
                            assert client.window_hwnd, 'Settings must publish its HWND for native ordering'
                            assert user32.GetWindow(client.window_hwnd, 4) == int(window.winId())
                            assert layer.window.isVisible()
                            with patch.object(user32, 'SetWindowPos', wraps=user32.SetWindowPos) as position:
                                for _ in range(3):
                                    layer.raise_()
                                    app.processEvents()
                                    assert above(client.window_hwnd, int(layer.window.winId())), stage
                            assert position.called, 'Real Quick raises must explicitly stay below settings'
                            assert all(int(call.args[1]) == client.window_hwnd for call in position.call_args_list)
                            assert not user32.GetWindowLongW(client.window_hwnd, -20) & 8
                            centre = client.occlusion.center() - origin
                            assert window.wall.rect().contains(centre)
                            assert layer.window.mask().contains(centre), \
                                'Native ordering must avoid a delayed settings-shaped hole'
                            native_mask_covers_settings(layer, client)
                            with patch.object(user32, 'SetWindowPos', return_value=0):
                                assert not client.stack_overlay_below(layer.window)
                                assert layer._update_occlusion()
                                assert not layer.window.mask().contains(centre), \
                                    'Failed native ordering must retain the clipping fallback'
                                native_mask_covers_settings(layer, client, False)
                            layer.show()
                            # A delayed cross-process rectangle must not leave a hole
                            # where settings was before its latest native move.
                            with patch.object(client, 'occlusion', client.occlusion.translated(70, 40)):
                                layer.show()
                                assert layer.window.mask().contains(centre)
                                assert above(client.window_hwnd, int(layer.window.winId()))
                            if previous is not None:
                                assert client.occlusion != previous, stage
                            previous = QRect(client.occlusion) if stage in ('shown', 'moved') else None
                        else:
                            assert layer.window.mask().contains(window.wall.rect().center()), stage
                        client._send({'kind': 'focus'})
                    # A rebuilt swap chain must restore the relative Z order too.
                    layer._restore_surface()
                    app.processEvents()
                    assert above(client.window_hwnd, int(layer.window.winId()))
                    native_mask_covers_settings(layer, client)
                    # Fullscreen uses a different canvas origin; retain native ordering.
                    tile = window.wall.tiles[0]
                    tile.setGeometry(20, 30, 1400, 1000)
                    layer.set_presentation_window(tile)
                    layer.show()
                    wait(app, lambda: not layer.window._move_regions)
                    centre = client.occlusion.center() - tile.mapToGlobal(QPoint())
                    assert layer.window.mask().contains(centre)
                    assert above(client.window_hwnd, int(layer.window.winId()))
                    layer.set_presentation_window(None)
                    if ending == 'cancel':
                        client._send({'kind': 'host-cancel'})
                        wait(app, lambda: not client.visible)
                    elif ending == 'crash':
                        client.process.kill()
                        wait(app, lambda: client.process.state() == QProcess.NotRunning)
                    else:
                        client.stop()
                        wait(app, lambda: client.process.state() == QProcess.NotRunning)
                    assert client.occlusion.isEmpty(), ending
                    assert client.window_hwnd == 0, ending
                    assert layer.window.mask().contains(window.wall.rect().center()), ending
                    assert layer.window.isVisible(), ending
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)
            window.close()
            app.processEvents()
    print('PASS: native settings occlusion avoids delayed holes; clipping fallback, fullscreen, reopen and termination preserved')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
