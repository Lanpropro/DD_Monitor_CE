"""Exercise the installed development plugin without opening media or user settings."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from ddm import config, plugins


def main():
    assert os.environ['DDM_NO_SAVE'] == '1'
    assert os.environ['DDM_MATCH_QUICK_DANMAKU'] == '1'
    assert os.environ['DDM_MATCH_MONITOR'] == '0'
    app = QApplication([])
    host = QWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen)
    host.settings, host.rooms = {}, []
    with tempfile.TemporaryDirectory() as temporary:
        manager = plugins.PluginManager(window=host, plugins_dir=temporary)
        folder = Path(config.REPO) / 'plugins_user' / 'match_sync'
        manifest = plugins.read_manifest(str(folder), 'match_sync')
        assert manifest['version'] == '2.0'
        installed = manager._load_module('match_sync', str(folder / 'plugin.py'))
        assert installed is not None
        module = sys.modules[type(installed).__module__]
        viewer_module = sys.modules[module.Viewer.__module__]
        with patch.object(viewer_module.Decoder, 'start', side_effect=AssertionError('Unexpected live media')), \
                patch.object(viewer_module.Chat, 'start', side_effect=AssertionError('Unexpected network')):
            viewer = module.Viewer(plugins.PluginContext(manager, 'match_sync'), {})
            try:
                gpu = viewer.d3d11_picture
                assert viewer.quick_danmaku is not None
                assert not hasattr(viewer, 'monitor_bridge')
                assert gpu is not None and not gpu.requested
                assert (gpu.directory / 'presenter.exe').is_file()
                assert (gpu.directory / 'mailbox.dll').is_file()
                gpu.toggle()
                assert gpu.requested
                gpu.toggle()
                assert not gpu.requested
            finally:
                viewer.close()
                viewer.deleteLater()
                app.processEvents()
        manager.unload()
    host.close()
    print('PASS: installed Match Sync 2.0, Qt Quick, default raster and optional D3D11 via run.cmd')


if __name__ == '__main__':
    main()
