"""The match player's advanced danmaku action opens the host page and applies edits."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.object(module.AudioPump, 'start', lambda _: None):
        host = QWidget()
        host.settings = {'video_danmaku_size': 20, 'danmaku_font_size': 13}
        host.open_settings = Mock(side_effect=lambda page: host.settings.update(
            video_danmaku_size=28, danmaku_font_size=18, danmaku_max_blocks=1500))
        viewer = module.Viewer(plugins.PluginContext(
            plugins.PluginManager(window=host, plugins_dir=directory), 'danmaku_settings'), {})
        try:
            action = next(action for action in viewer.picture.danmaku_settings_menu.actions()
                          if action.text() == '更多弹幕设置')
            with patch.object(viewer.panel, 'apply_style', wraps=viewer.panel.apply_style) as style, \
                    patch.object(viewer.panel, 'set_max_blocks', wraps=viewer.panel.set_max_blocks) as blocks:
                action.trigger()
                host.open_settings.assert_called_once_with('danmaku')
                assert viewer.video_danmaku.settings['video_danmaku_size'] == 28
                assert viewer.picture.danmaku_settings_menu.controls['video_danmaku_size'].value() == 28
                style.assert_called_once_with('', 18)
                blocks.assert_called_once_with(1500)
            before = dict(host.settings)
            host.open_settings = Mock(return_value=False)
            action.trigger()
            host.open_settings.assert_called_once_with('danmaku')
            assert host.settings == before
            assert viewer.video_danmaku.settings['video_danmaku_size'] == 28
            assert not viewer.running and not viewer.rows
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: real advanced menu action opens host danmaku page, applies saved overlay/panel settings and respects cancellation')


if __name__ == '__main__':
    main()
