"""Appearance persistence, live settings, sidebar placement and native alpha badges."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import platform
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
platform._wmi_query = lambda *args: (_ for _ in ()).throw(OSError('Isolated test'))
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest
from ddm import theme, config, app as app_module
from ddm.dialogs import SettingsDialog
from dev.selfcheck_tile_fullscreen import SilentPoller


def main():
    errors = []
    original_hook = sys.excepthook
    def capture(kind, value, traceback):
        errors.append(value)
        original_hook(kind, value, traceback)
    sys.excepthook = capture
    app = QApplication([])
    theme.apply('dark')
    original_style = theme.qss()
    app_module.StatusPoller = app_module.StatsPoller = SilentPoller
    room = dict(room_id='990000', uname='Appearance test', title='Offline test', live=False)
    with patch('PySide6.QtCore.QTimer.singleShot'):
        window = app_module.MainWindow([room], [dict(room)], layout_id='corner',
            state={'plugins_enabled': [], 'settings': {'appearance_mode': 'invalid', 'auto_update': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    window.resize(1440, 900)
    window.show()
    QTest.qWait(60)
    tile = window.wall.tiles[0]
    tile.set_controls_visible(True)
    handles = [int(t.video.winId()) for t in window.wall.tiles]
    objects = (window.wall, window.recorder, tile.video_danmaku)
    local = QLabel(window)
    local.setStyleSheet(f'background: {theme.CONTENT}; color: {theme.TEXT2};')
    original_local = local.styleSheet()
    panel = window.wall.danmaku
    panel.add_message('Test user', 'History must survive theme changes', '#00a1d6')
    messages = list(panel._blocks)
    assert theme.mode() == window.settings['appearance_mode'] == 'dark'
    with patch.object(config, 'save') as save:
        window.sidebar.appearanceChanged.emit('light')
        QTest.qWait(120)
        assert theme.is_light() and save.call_args.args[0]['settings']['appearance_mode'] == 'light'
        saved_light = save.call_args.args[0]
        assert objects == (window.wall, window.recorder, tile.video_danmaku)
        assert handles == [int(t.video.winId()) for t in window.wall.tiles]
        assert theme.TEXT1 == '#202630' and theme.TILE_BG == '#101114'
        assert '浅色' in window.sidebar.appearance_button.toolTip()
        assert '切换为深色' in window.sidebar.appearance_button.toolTip()
        with patch('ddm.widgets.QMenu', side_effect=AssertionError('Toggle must not open a menu')), \
                patch.object(window, 'open_settings', return_value=False) as open_settings:
            window.sidebar.appearance_button.click()
            assert theme.mode() == window.settings['appearance_mode'] == 'dark'
            assert '切换为浅色' in window.sidebar.appearance_button.toolTip()
            window.sidebar.appearance_button.click()
            assert theme.mode() == window.settings['appearance_mode'] == 'light'
            assert save.call_args.args[0]['settings']['appearance_mode'] == 'light'
            open_settings.assert_not_called()
        assert handles == [int(t.video.winId()) for t in window.wall.tiles]
        assert '#FFFFFF' in local.styleSheet()
        assert panel._blocks == messages and '#202630' in panel.body.toHtml()
        if app.platformName() == 'windows':
            for badge in (tile.stream_badge, tile.title_badge):
                image = badge.grab().toImage()
                assert getattr(badge, '_alpha_uploaded', False), type(badge).__name__
                alphas = [image.pixelColor(x, y).alpha()
                    for y in range(image.height()) for x in range(image.width())]
                assert 0 in alphas and any(0 < a < 255 for a in alphas), 'Rounded alpha fringe lost'
        with patch('PySide6.QtCore.QTimer.singleShot'):
            dialog = SettingsDialog(window.settings, window.shortcuts, window)
        dialog.appearanceChanged.connect(window.set_appearance)
        index = next(i for i, item in enumerate(dialog.PAGES) if item[0] == 'appearance')
        dialog.nav.setCurrentRow(index)
        assert dialog.stack.currentWidget() is dialog.appearance_page
        dialog.appearance_page.buttons['dark'].click()
        assert theme.mode() == window.settings['appearance_mode'] == 'dark'
        assert dialog.settings()['appearance_mode'] == 'dark'
        assert theme.qss() == original_style, 'Original dark QSS changed after round trip'
        assert local.styleSheet() == original_local
        assert panel._blocks == messages and '#e6e9ee' in panel.body.toHtml()
        dialog.appearance_page.buttons['light'].click()
        dialog.reject()  # Appearance is explicitly immediate, independent of other settings.
        assert window.settings['appearance_mode'] == 'light'
        with patch.object(app.styleHints(), 'colorScheme', return_value=Qt.ColorScheme.Light) as scheme:
            window.set_appearance('system')
            assert theme.is_light() and window.settings['appearance_mode'] == 'system'
            window.sidebar.appearance_button.click()
            assert not theme.is_light() and window.settings['appearance_mode'] == 'dark'
            app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
            assert not theme.is_light(), 'Manual toggle must stop following the system'
            window.set_appearance('system')
            scheme.return_value = Qt.ColorScheme.Dark
            app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
            assert not theme.is_light() and theme.mode() == 'system'
            window.sidebar.appearance_button.click()
            assert theme.is_light() and window.settings['appearance_mode'] == 'light'
        for side in ('left', 'top', 'left'):
            window.sidebar.set_side(side)
            for collapsed in (True, False):
                window.sidebar.set_collapsed(collapsed, animate=False)
                QTest.qWait(40)
                button = window.sidebar.appearance_button
                assert button.isVisible() == (not collapsed) and not button.text()
                assert button.size() == QSize(22, 22), (side, collapsed, button.size(), button.minimumSize(), button.maximumSize())
                if side == 'left' and not collapsed:
                    row = window.sidebar.status_row.layout()
                    assert row.indexOf(window.sidebar.sort_button) < row.indexOf(button) < row.indexOf(window.sidebar.refresh_button)
                    assert not button.geometry().intersects(window.sidebar.refresh_button.geometry())
        window.set_appearance('dark')
    window.close()
    app.processEvents()
    with tempfile.TemporaryDirectory() as directory, \
            patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')), \
            patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
        config.save(saved_light)
        loaded = config.load()
        assert loaded['settings']['appearance_mode'] == 'light'
    with patch('PySide6.QtCore.QTimer.singleShot'):
        restored = app_module.MainWindow([], [], state=loaded)
    assert restored.settings['appearance_mode'] == 'light' and theme.is_light()
    restored.close()
    theme.apply('dark')
    assert not errors, errors
    print('PASS: appearance persistence; immediate settings; original dark QSS; local QSS round trip; system changes; native alpha; horizontal/portrait/collapsed entry; stable video HWNDs')


if __name__ == '__main__':
    main()
