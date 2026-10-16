"""New match rooms use the host volume setting; saved room gains take priority."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import config, plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None):
        host = QWidget()
        host.settings = {'default_volume': 23}
        viewer = module.Viewer(plugins.PluginContext(
            plugins.PluginManager(window=host, plugins_dir=directory), 'volume'), {})
        try:
            viewer.add_room('1')
            assert viewer.rows['1'].volume.value() == 23
            host.settings['default_volume'] = 67
            viewer.add_room('2')
            assert viewer.rows['2'].volume.value() == 67
            assert viewer.rows['1'].volume.value() == 23
            viewer.saved_rooms['3'] = {'volume': 15}
            viewer.add_room('3')
            assert viewer.rows['3'].volume.value() == 15
            viewer.saved_rooms['4'] = {'volume': 15}
            viewer.add_room('4', {'volume': 0})
            assert viewer.rows['4'].volume.value() == 0
            assert viewer.rows['4'].preferences()['volume'] == 0
            host.settings['default_volume'] = 0
            viewer.add_room('5')
            assert viewer.rows['5'].volume.value() == 0
            host.settings.clear()
            viewer.add_room('6')
            assert viewer.rows['6'].volume.value() == config.DEFAULT_VOLUME
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: host default volume, live setting changes, saved gain priority and zero volume')


if __name__ == '__main__':
    main()
