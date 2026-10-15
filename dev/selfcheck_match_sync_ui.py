"""Theme/settings responsiveness with 67 followed rooms and embedded match UI."""
import os
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
platform._wmi_query = lambda *a: (_ for _ in ()).throw(OSError('Isolated UI test'))
from PySide6.QtGui import QColor, QFontDatabase, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from ddm import app as module, motion, plugins, theme
from ddm.dialogs import SettingsDialog
from dev.selfcheck_tile_fullscreen import SilentPoller
from dev.selfcheck_match_sync import FakeDecoder, FakeChat
from plugins_user._match_sync import viewer as video
from plugins_user._match_sync.plugin import MatchSyncPlugin

app = QApplication([])
assert QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc') >= 0
module.StatusPoller = module.StatsPoller = SilentPoller
rooms = [dict(room_id=str(1000+i), uname='Fixture '+str(i), live=False, title='Fixture') for i in range(67)]
with patch('PySide6.QtCore.QTimer.singleShot'):
    window = module.MainWindow(rooms, [], layout_id='corner', state={'plugins_enabled': [], 'settings': {'auto_update': False}})
window.resize(1800, 1000)
window.show()
app.processEvents()
ctx = plugins.PluginContext(window.plugins, 'ui_profile')
with patch.object(video, 'Decoder', FakeDecoder), patch.object(video, 'Chat', FakeChat), \
        patch.object(video.AudioPump, 'start', lambda _: None):
    plugin = MatchSyncPlugin()
    plugin.on_load(ctx)
    plugin.button.setChecked(True)
    for room in rooms[:3]:
        plugin.viewer.add_room(room['room_id'], {'alias': room['uname']})
    plugin.viewer.render_timer.stop()
    plugin.viewer.match_timer.stop()
    app.processEvents()
    face = QPixmap(32, 32)
    face.fill(QColor('green'))
    window.sidebar._items[0].thumb.set_face(face)
    plugin.viewer.rows['1000'].refresh_avatar()
    assert not plugin.viewer.rows['1000'].avatar.pixmap().isNull()
    assert plugin.viewer.rows['1000'].alias.isHidden()
    for widget in ('audible', 'volume', 'channel', 'delay'):
        xs = [getattr(row, widget).x() for row in plugin.viewer.rows.values()]
        assert max(xs) - min(xs) <= 1, (widget, xs)
    styles = []
    original_style = QWidget.setStyleSheet
    def styled(widget, source):
        styles.append(widget)
        original_style(widget, source)
    with patch.object(QWidget, 'setStyleSheet', styled):
        for _ in range(10):
            plugin.viewer.refresh_appearance()
        assert not styles, 'Stable appearance must not repolish any control subtree'
    with patch.object(motion, 'enabled', return_value=False):
        start = time.perf_counter()
        window.set_appearance('light')
        theme_ms = (time.perf_counter()-start)*1000
        print('THEME_MS', theme_ms)
        assert theme_ms < 250
    start = time.perf_counter()
    dialog = SettingsDialog(window.settings, window.shortcuts, window, plugin_manager=window.plugins)
    dialog.show()
    app.processEvents()
    settings_ms = (time.perf_counter()-start)*1000
    print('SETTINGS_MS', settings_ms)
    assert settings_ms < 250
    assert dialog._loaded_pages == {}, 'Opening general settings must not build all other control pages'
    dialog.nav.setCurrentRow(2)
    assert set(dialog._loaded_pages) == {2} and dialog.stack.currentWidget() is dialog.danmaku_page
    page = dialog.danmaku_page
    page.size_spin.setValue(22)
    dialog.nav.setCurrentRow(1)
    assert set(dialog._loaded_pages) == {1, 2}
    dialog.nav.setCurrentRow(2)
    assert dialog.danmaku_page is page and page.size_spin.value() == 22
    dialog.close()
    if '--snapshot' in sys.argv:
        output = Path(__file__).resolve().parents[1] / 'work' / 'match-sync-ui-light.png'
        output.parent.mkdir(exist_ok=True)
        app.processEvents()
        assert plugin.viewer.settings_panel.grab().save(str(output))
        print(output)
    plugin.on_unload()
window.close()
print('PASS: bounded UI response, stable styles, lazy settings pages retain edits')
