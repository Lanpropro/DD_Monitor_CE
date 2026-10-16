"""One empty-state prompt across transparent skins, themes and playback lifecycle."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('DDM_NO_SAVE', '1')
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
from ddm import plugins, theme
from dev.selfcheck_match_sync import FakeDecoder, FakeChat
from dev.selfcheck_match_sync_appearance import Controller
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None):
        host = QMainWindow()
        root = QWidget()
        host.setCentralWidget(root)
        host.settings = {}
        host.skin_controller = Controller(host, root)
        context = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'empty_check')
        viewer = module.Viewer(context, {})
        viewer.embed(root)
        host.resize(1000, 700)
        host.show()
        viewer.show()
        try:
            for mode in ('light', 'dark'):
                theme.apply(mode)
                for skin in (False, True):
                    host.skin_controller.layer.path = 'fixture.png' if skin else ''
                    viewer.refresh_appearance()
                    viewer.sync_picture()
                    for size in ((1000, 700), (780, 900)):
                        host.resize(*size)
                        app.processEvents()
                        assert viewer.canvas.isVisible() and viewer.canvas.image.isNull()
                        assert viewer.picture.cover.isHidden(), 'The native tile prompt overlaps the transparent canvas prompt'
                        viewer.picture.set_video_active(False)
                        viewer.picture.cover.show()
                        assert viewer.picture.cover.isHidden(), 'Later host state changes must not restore the second prompt'
                    viewer.add_room('1', {'alias': 'Fixture'})
                    viewer.toggle_running()
                    viewer.render_timer.stop()
                    viewer.match_timer.stop()
                    viewer.stop()
                    assert viewer.picture.cover.isHidden()
                    viewer.remove_room('1')
                    app.processEvents()
                    assert not viewer.rows and viewer.canvas.image.isNull()
                    assert viewer.picture.cover.isHidden()
            native = module.Tile({})
            native.set_room(None)
            assert not native.cover.isHidden(), 'Ordinary tiles retain their original prompt'
            native.close()
        finally:
            viewer.close()
            host.close()
    print('PASS: one prompt with/without skins, light/dark, resize, stop/remove; ordinary tile prompts retained')


if __name__ == '__main__':
    main()
