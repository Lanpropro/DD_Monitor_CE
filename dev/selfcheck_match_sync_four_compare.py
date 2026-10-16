"""Four horizontal comparisons and bounded settings/audio work, without live streams."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import app as app_module, plugins, theme
from ddm.dialogs import SettingsDialog
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, FakeDevice, jpeg
from dev.selfcheck_settings_status import SilentPoller
from plugins_user._match_sync import viewer as module


class BufferedSink:
    def __init__(self, *_args):
        self.stateChanged = Mock()
        self.played = 0

    def setBufferSize(self, size):
        self.capacity = self.free = size

    def start(self):
        return FakeDevice(self)

    def bytesFree(self):
        return self.free

    def processedUSecs(self):
        return self.played * 1_000_000 // module.RATE

    def consume(self, frames):
        assert self.capacity - self.free >= frames * 4, 'GUI pause exhausted the audio queue'
        self.free += frames * 4
        self.played += frames

    def stop(self):
        pass

    def deleteLater(self):
        pass


def main():
    app = QApplication([])
    theme.apply('dark')
    with tempfile.TemporaryDirectory() as root:
        manager = plugins.PluginManager(plugins_dir=root)
        with patch('ddm.dialogs.PluginSettingsPage', side_effect=AssertionError('Unopened plugin page was constructed')), \
                patch('ddm.online_ui.AppUpdatePage', side_effect=AssertionError('Unopened update page was constructed')):
            dialog = SettingsDialog({'danmaku_font_size': 27, 'auto_update': True}, {'mute': 'Ctrl+M'}, plugin_manager=manager)
        assert not dialog._loaded_pages
        with patch.object(dialog, '_page', side_effect=AssertionError('Save instantiated an unopened page')):
            started = time.perf_counter()
            assert dialog.settings()['danmaku_font_size'] == 27
            assert dialog.settings()['auto_update'] is True
            assert dialog.shortcuts()['mute'] == 'Ctrl+M'
            dialog.confirm_button.click()
            elapsed = (time.perf_counter() - started) * 1000
        assert elapsed < 100 and not dialog._loaded_pages, elapsed
        dialog = SettingsDialog({'danmaku_font_size': 27}, {}, plugin_manager=manager)
        dialog.danmaku_page.size_spin.setValue(31)
        assert dialog.settings()['danmaku_font_size'] == 31
        assert set(dialog._loaded_pages) == {2}
        dialog.close()
        dialog = SettingsDialog({}, {}, plugin_manager=manager)
        pages = []
        dialog.pageCreated.connect(lambda index, page: pages.append(index))
        dialog.nav.setCurrentRow(5)
        assert pages == [5] and set(dialog._loaded_pages) == {5}
        dialog.nav.setCurrentRow(6)
        dialog.nav.setCurrentRow(5)
        assert pages == [5, 6] and set(dialog._loaded_pages) == {5, 6}
        dialog.close()
        print(f'PASS: settings save preserves unopened pages and custom keys without building controls ({elapsed:.1f}ms)')

    with patch.object(app_module, 'StatusPoller', SilentPoller), \
            patch.object(app_module, 'StatsPoller', SilentPoller), patch.object(app_module.QTimer, 'singleShot'):
        window = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'auto_update': False}})
    try:
        with patch.object(SettingsDialog, 'exec', return_value=SettingsDialog.Accepted), \
                patch.object(window, '_sync_platform_rooms') as sync, \
                patch.object(window, 'refresh_skin') as skin:
            assert window.open_settings()
            sync.assert_not_called()
            skin.assert_not_called()
        with patch.object(SettingsDialog, 'exec', return_value=SettingsDialog.Accepted), \
                patch.object(SettingsDialog, 'enabled_plugins', return_value={'test'}), \
                patch.object(window, '_sync_platform_rooms') as sync:
            assert window.open_settings()
            sync.assert_called_once()
        def install_platform():
            window.plugins._platform_owner['test_platform'] = 'test'
            return SettingsDialog.Accepted
        with patch.object(SettingsDialog, 'exec', side_effect=install_platform), \
                patch.object(window, '_sync_platform_rooms') as sync:
            assert window.open_settings()
            sync.assert_called_once()
        print('PASS: unchanged settings skip room rebuilding; enable/install changes still synchronize platforms')
    finally:
        window.close()

    with tempfile.TemporaryDirectory() as root, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), 'four'), {})
        try:
            viewer.resize(1600, 900)
            viewer.show()
            for key in ('1', '2', '3', '4', '5'):
                viewer.add_room(key)
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            viewer.audio.clock = lambda: 100
            image = jpeg()
            for row in viewer.rows.values():
                for stamp in range(80, 121):
                    row.decoder.history.append(stamp, image)
            viewer.show_comparison('3')
            panel = viewer.comparison_panel
            app.processEvents()
            assert panel.shown_rooms == ('1', '3') and panel.target.isVisible()
            viewer.remove_room('5')
            viewer.render()
            app.processEvents()
            assert panel.shown_rooms == ('1', '2', '3', '4') and panel.target.isHidden()
            for width in (1600, 680):
                viewer.resize(width, 900)
                panel.setMaximumWidth(width)
                app.processEvents()
                viewer.render()
                app.processEvents()
                cards = [panel.cards[key][0] for key in panel.shown_rooms]
                assert all(card.isVisible() and card.width() >= 200 for card in cards)
                if width == 680:
                    assert panel.findChild(module.QScrollArea).horizontalScrollBar().maximum() > 0
                output = Path(__file__).resolve().parents[1] / "work"
                output.mkdir(exist_ok=True)
                panel.grab().save(str(output / f"match-sync-four-compare-{width}.png"))
                assert len({card.y() for card in cards}) == 1
                assert all(left.geometry().right() < right.x() for left, right in zip(cards, cards[1:]))
            assert panel.cards['1'][2].image == viewer.canvas.image
            viewer.select_main('3')
            viewer.render()
            assert panel.shown_rooms == ('3', '1', '2', '4')
            viewer.select_main('1')
            viewer.render()
            readers = []
            for row in viewer.rows.values():
                reader = row.decoder.pictures = Mock()
                readers.append(reader)
            viewer._configure_picture_budget()
            assert all(reader.configure.call_args.kwargs['active'] for reader in readers)
            assert sum(reader.configure.call_args.args[0] for reader in readers) <= 384 * 1024 * 1024
            panel.close_button.click()
            viewer._configure_picture_budget()
            assert readers[0].configure.call_args.kwargs['active']
            assert all(not reader.configure.call_args.kwargs['active'] for reader in readers[1:])
            print('PASS: four horizontal cards, narrow-window scrolling, five-room selector and bounded preview memory')
        finally:
            viewer.close()
            host.close()
            app.processEvents()

    # Exercise the output owner's startup and PCM/clock with deterministic consumption.
    host = QWidget()
    host.running = True
    host.rows = {}
    host.shifts = lambda: {}
    host.playback_rate = 1
    host.relative_rates = {}
    host.sync_waiting = False
    pump = module.AudioPump(host)
    output = Mock()
    output.id.return_value = b'test'
    output.isNull.return_value = False
    output.isFormatSupported.return_value = True
    with patch.object(module, 'QAudioSink', BufferedSink):
        pump.anchor = time.monotonic()
        feed = module.AudioFeed(pump, output, module.QAudioFormat())
        feed.start()
        feed.timer.stop()
        pump.fill()
        pump.fill()
        before = pump.clock()
        pump.sink.consume(round(module.RATE * .12))
        assert abs(pump.clock() - before - .12) < .00001
        pump.fill()
        feed.stop()
        pump.stop()
    host.close()
    print('PASS: 120ms GUI pause retains queued audio; media clock follows actual device consumption')


if __name__ == '__main__':
    main()
