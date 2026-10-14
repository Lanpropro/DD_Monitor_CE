"""Theme preparation work with a large window and 67 followed rooms."""
import json
import os
from pathlib import Path
import platform
import sys
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
platform._wmi_query = lambda *a: (_ for _ in ()).throw(OSError('Isolated latency test'))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import app as module, motion, theme, theme_transition, widgets
from dev.selfcheck_tile_fullscreen import SilentPoller


def main():
    app = QApplication([])
    module.StatusPoller = module.StatsPoller = SilentPoller
    rooms = [dict(room_id=str(1000+i), uname='Fixture '+str(i), live=False,
                  title='Offline fixture') for i in range(67)]
    with patch('PySide6.QtCore.QTimer.singleShot'):
        window = module.MainWindow(rooms, [], layout_id='corner', state={
            'plugins_enabled': [], 'settings': {'auto_update': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    window.resize(2560, 1440)
    window.show()
    QTest.qWait(50)
    records = []
    original_style = QWidget.setStyleSheet
    original_snapshot = theme_transition.ui_snapshot
    original_apply = theme.apply
    for mode in ('light', 'dark', 'light'):
        record = {'mode': mode, 'stylesheet_resets': 0}
        geometry = [tile.video.geometry() for tile in window.wall.tiles]
        def styled(widget, source):
            record['stylesheet_resets'] += 1
            original_style(widget, source)
        def snapshot(widget):
            started = time.perf_counter()
            result = original_snapshot(widget)
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
                patch.object(widgets, 'folder_icon', side_effect=AssertionError('Default folder icon must be reused')):
            started = time.perf_counter()
            window.set_appearance(mode)
            record['prepare_ms'] = round((time.perf_counter()-started)*1000, 2)
        assert window._theme_transition.overlays
        assert record['stylesheet_resets'] < 20, record
        assert [tile.video.geometry() for tile in window.wall.tiles] == geometry, 'Theme switching must not resize native video windows'
        window._theme_transition.finish()
        QTest.qWait(20)
        records.append(record)
    output = ROOT/'work/theme-latency.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2), encoding='utf-8')
    window.close()
    print('PASS: <20 stylesheet resets, cached folder icons, stable video geometry; measured stages: ' + json.dumps(records))


if __name__ == '__main__':
    main()
