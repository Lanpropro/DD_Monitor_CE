"""Cross-process settings clipping; isolated data and screen-off native windows."""
import json
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
                QTimer.singleShot(150, self.step)
            QTimer.singleShot(30, report)

    def show(dialog):
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
        command = (sys.executable, [str(Path(__file__).resolve()), '--worker'])
        try:
            with patch.object(settings_process, 'worker_command', return_value=command), \
                    patch.object(settings_process, '_allow_foreground'):
                for ending in ('cancel', 'crash', 'stop'):
                    messages.clear()
                    client.open(config.DEFAULT_SETTINGS, {})
                    previous = None
                    for stage in ('shown', 'moved', 'resized', 'hidden', 'restored', 'minimized', 'normal'):
                        wait(app, lambda: any(m.get('stage') == stage for m in messages))
                        expected = next(m['rect'] for m in messages if m.get('stage') == stage)
                        assert client.occlusion == (QRect(*expected) if expected else QRect()), stage
                        origin = window.wall.mapToGlobal(QPoint())
                        if expected:
                            centre = client.occlusion.center() - origin
                            assert window.wall.rect().contains(centre)
                            assert not layer.window.mask().contains(centre), stage
                            if previous is not None:
                                assert client.occlusion != previous, stage
                            previous = QRect(client.occlusion) if stage in ('shown', 'moved') else None
                        else:
                            assert layer.window.mask().contains(window.wall.rect().center()), stage
                    # Fullscreen uses a different canvas origin; retain the same hole.
                    tile = window.wall.tiles[0]
                    tile.setGeometry(20, 30, 1400, 1000)
                    layer.set_presentation_window(tile)
                    layer.show()
                    centre = client.occlusion.center() - tile.mapToGlobal(QPoint())
                    assert not layer.window.mask().contains(centre)
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
                    assert layer.window.mask().contains(window.wall.rect().center()), ending
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)
            window.close()
            app.processEvents()
    print('PASS: cross-process settings mask follows show/move/resize/hide/minimize, fullscreen, reopen and termination')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
