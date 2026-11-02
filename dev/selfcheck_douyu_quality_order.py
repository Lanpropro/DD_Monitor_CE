"""斗鱼 2K 菜单顺序和取流档位映射；仅使用离线替身。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from ddm import plugins
from ddm.app import MainWindow


def check_menu(window):
    platform = window.plugins.platforms['douyu']
    module = sys.modules[type(platform).__module__]
    source = {'rtmp_url': 'https://cdn.test', 'rtmp_live': 'source.flv', 'rate': 0,
              'multirates': [{'rate': 0, 'bit': 16000, 'name': '原画1080P60'},
                            {'rate': 15, 'bit': 15000, 'name': '2K超高清'},
                            {'rate': 4, 'bit': 4000, 'name': '蓝光4M'}]}
    session = module.Streamlink()
    tile = window.wall.tiles[0]
    try:
        with patch.object(platform, 'room_info', return_value=plugins.RoomInfo('douyu:123', live=True)), \
                patch.object(platform, '_request_source',
                             side_effect=lambda parser, raw, cdn='', rate=0: dict(source, rate=rate)):
            for qn in (10000, 2000015):
                stream = platform._streams(session, 'douyu:123', qn)['source']
                assert stream.ddm_quality == qn
            tile.set_room({'room_id': 'douyu:123', 'quality': 10000, 'live': True})
            tile.set_quality_options(platform.room_quality_options('douyu:123'))
            assert tile._quality_choices() == [('2K超高清', 2000015),
                                               ('原画1080P60', 10000), ('蓝光4M', 2000004)]
            assert tile.quality_button.text() == '原画1080P60'
            tile.set_actual_quality(2000015)
            assert tile.quality_button.text() == '2K超高清'
    finally:
        session.http.close()


def main():
    app = QApplication.instance() or QApplication([])
    state = {'plugins_enabled': ['domestic_live'], 'settings': {'auto_quality': False,
             'recording_enabled': False, 'recording_replay_enabled': False,
             'danmaku_enabled': False, 'preview_on_hover': False}}
    with patch('ddm.app.QTimer.singleShot'), patch.object(MainWindow, 'sync_danmaku'), \
            patch.object(MainWindow, 'refresh_status'), patch.object(MainWindow, 'refresh_stats'), \
            patch.object(MainWindow, 'start_tile'):
        window = MainWindow([], [], layout_id='1x1', state=state)
        try:
            check_menu(window)
        finally:
            window.close()
            app.processEvents()
    print('PASS: Douyu 2K before original 1080P60, native stream IDs and displayed labels preserved')


if __name__ == '__main__':
    main()
