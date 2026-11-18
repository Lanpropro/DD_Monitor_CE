"""Theme preparation work with a large window and 67 followed rooms."""
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
platform._wmi_query = lambda *a: (_ for _ in ()).throw(OSError('Isolated latency test'))
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QScrollArea, QSlider, QWidget
from ddm import app as module, config, continuous_corners, motion, sidebar_folders, theme, theme_transition
from ddm.skins import import_asset
from dev.selfcheck_tile_fullscreen import SilentPoller


def main():
    app = QApplication([])
    module.StatusPoller = module.StatsPoller = SilentPoller
    rooms = [dict(room_id=str(1000+i), uname='Fixture '+str(i), live=False,
                  title='Offline fixture') for i in range(67)]
    with patch('PySide6.QtCore.QTimer.singleShot'):
        window = module.MainWindow(rooms, [], layout_id='corner', state={
            'plugins_enabled': [], 'settings': {'auto_update': False}})
    window._startup_update_timer.stop()  # Installed plugin catalogs must not start network checks.
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    window.resize(2560, 1440)
    window.show()
    QTest.qWait(50)
    check_shared_local_styles(window)
    check_palette_polish(window)
    records = []
    original_style = QWidget.setStyleSheet
    original_snapshot = theme_transition.ui_snapshot
    original_apply = theme.apply
    with tempfile.TemporaryDirectory() as directory, patch.object(config, 'REPO', directory):
        image = QImage(160, 90, QImage.Format_RGB32)
        image.fill(QColor('#426CDB'))
        path = Path(directory)/'background.png'
        assert image.save(str(path))
        asset = import_asset(path)
        for background in ('default', 'skin', 'skin-sidebar'):
            with patch.object(motion, 'enabled', return_value=False):
                window.set_appearance('dark')
            window.set_skin({'skin_background': '' if background == 'default' else asset,
                             'skin_sidebar': background == 'skin-sidebar'})
            QTest.qWait(20)
            for mode in ('light', 'dark', 'light'):
                record = {'background': background, 'mode': mode, 'stylesheet_resets': 0}
                geometry = [tile.video.geometry() for tile in window.wall.tiles]
                skin_styles = {widget: widget.styleSheet() for widget in window.findChildren(QWidget)
                              if widget.objectName() in ('Sidebar', 'WallGrid', 'Tile', 'TileVideo', 'TileBottom', 'DanmakuPanel')}
                def styled(widget, source):
                    record['stylesheet_resets'] += 1
                    original_style(widget, source)
                def snapshot(widget, *args):
                    started = time.perf_counter()
                    result = original_snapshot(widget, *args)
                    record['snapshot_ms'] = round((time.perf_counter()-started)*1000, 2)
                    return result
                def applied(value):
                    started = time.perf_counter()
                    original_apply(value)
                    record['apply_ms'] = round((time.perf_counter()-started)*1000, 2)
                with patch.object(motion, 'enabled', return_value=True), \
                        patch.object(QWidget, 'setStyleSheet', styled), \
                        patch.object(theme_transition, 'ui_snapshot', snapshot), \
                        patch.object(theme, 'apply', applied), \
                        patch.object(sidebar_folders, 'folder_icon', side_effect=AssertionError('Default folder icon must be reused')):
                    started = time.perf_counter()
                    window.set_appearance(mode)
                    record['prepare_ms'] = round((time.perf_counter()-started)*1000, 2)
                assert window._theme_transition.overlays
                assert record['stylesheet_resets'] < 20, record
                assert all(widget.styleSheet() == source for widget, source in skin_styles.items()), 'Skin styles must remain installed across theme switches'
                assert [tile.video.geometry() for tile in window.wall.tiles] == geometry, 'Theme switching must not resize native video windows'
                window._theme_transition.finish()
                QTest.qWait(20)
                records.append(record)
    output = ROOT/'work/theme-latency.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2), encoding='utf-8')
    window.close()
    print('PASS: <20 stylesheet resets, cached folder icons, stable video geometry; measured stages: ' + json.dumps(records))


def check_shared_local_styles(window):
    theme.apply('dark')
    source = f'QLabel {{ color: {theme.TEXT1}; margin: 1px; }}'
    widgets = [QWidget(window) for _ in range(3)]
    try:
        for widget in widgets:
            widget.setStyleSheet(source)
        with patch.object(continuous_corners, 'stylesheet', wraps=continuous_corners.stylesheet) as compile_style:
            theme.apply('light')
        target = f'QLabel {{ color: {theme.TEXT1}; margin: 1px; }}'
        assert [widget.styleSheet() for widget in widgets] == [target] * 3
        assert sum(call.args[0] == target for call in compile_style.call_args_list) == 1
        theme.apply('dark')
        assert [widget.styleSheet() for widget in widgets] == [source] * 3
    finally:
        for widget in widgets:
            widget.deleteLater()


def check_palette_polish(window):
    theme.apply('dark')
    hint = QLabel('Fixture', window)
    hint.setObjectName('NavThumbHint')
    local = QLabel('Local', window)
    local.setObjectName('NavThumbHint')
    local.setStyleSheet(f'#NavThumbHint {{ color: {theme.TEXT1}; }}')
    editor = QLineEdit(window)
    slider = QSlider(window)
    placeholder = QColor('#8a8f98')
    scroll = QScrollArea(window)
    scroll.setGeometry(0, 200, 200, 120)
    content = QWidget()
    content.setFixedSize(160, 600)
    scroll.setWidget(content)
    clipped = QLabel('Clipped', content)
    clipped.setObjectName('NavThumbHint')
    clipped.setGeometry(0, 420, 120, 30)
    controls = (hint, local, editor, slider)
    for row, widget in enumerate(controls):
        widget.setGeometry(8, 8 + row*36, 140, 30)
    widgets = (*controls, scroll)
    try:
        for widget in widgets:
            widget.show()
        QTest.qWait(20)
        palette = slider.palette()
        palette.setColor(QPalette.PlaceholderText, placeholder)
        slider.setPalette(palette)
        dark_placeholder = editor.palette().color(QPalette.PlaceholderText)
        for mode in ('light', 'dark', 'light'):
            with patch.object(theme, '_refresh_widget_palette', wraps=theme._refresh_widget_palette) as polish:
                theme.apply(mode)
            for widget in (hint, editor):
                calls = [call for call in polish.call_args_list if call.args[0] is widget]
                assert len(calls) == 1 and calls[0].kwargs.get('invalidate', False) == (widget is editor)
            assert not any(call.args[0] is local for call in polish.call_args_list)
            assert hint.property('appearanceLight') == (mode == 'light')
            if mode == 'light':
                assert hint.palette().color(QPalette.WindowText) == QColor('#F1F2F5')
            assert local.palette().color(QPalette.WindowText) == QColor(theme.TEXT1)
            assert (editor.palette().color(QPalette.PlaceholderText) == dark_placeholder) == (mode == 'dark')
            assert slider.palette().color(QPalette.PlaceholderText) == placeholder
            assert clipped in theme._pending_palette
        scroll.verticalScrollBar().setValue(400)
        QTest.qWait(20)
        assert clipped not in theme._pending_palette
        assert clipped.palette().color(QPalette.WindowText) == QColor('#F1F2F5')
    finally:
        for widget in widgets:
            widget.deleteLater()
        QTest.qWait(20)
        theme.apply('dark')


if __name__ == '__main__':
    main()
