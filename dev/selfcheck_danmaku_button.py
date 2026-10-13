"""Real button events, visible state and playback-before-status subscription."""
import os
from pathlib import Path
import platform
import sys
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
platform._wmi_query = lambda *a: (_ for _ in ()).throw(OSError('Isolated test'))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import app as module, motion
from dev.selfcheck_tile_fullscreen import SilentPoller
from dev.selfcheck_video_danmaku import Client


def main():
    app = QApplication([])
    module.StatusPoller = module.StatsPoller = SilentPoller
    room = dict(room_id='1001', uname='Offline status, active playback', live=False)
    with patch('PySide6.QtCore.QTimer.singleShot'), patch.object(module, 'DanmakuClient', Client):
        window = module.MainWindow([room], [dict(room)], layout_id='1x1',
            state={'plugins_enabled': [], 'settings': {'auto_update': False}})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.move(-10000, -10000)
        window.show()
        QTest.qWait(20)
        tile = window.wall.tiles[0]
        tile.set_video_active(True)
        with patch.object(motion, 'enabled', return_value=False):
            for mode in ('light', 'dark', 'light'):
                window.set_appearance(mode)
                before = tile.danmaku_button.grab().toImage()
                QTest.mouseClick(tile.danmaku_button, Qt.LeftButton)
                assert tile.danmaku_button.isChecked() and tile.video_danmaku.isVisible()
                assert tile.danmaku_button.grab().toImage() != before, 'Checked state must visibly differ'
                client = window._danmaku_clients['1001']
                client.message.emit({'text': 'Button works before live status arrives'})
                assert tile.video_danmaku.comments
                QTest.mouseClick(tile.danmaku_button, Qt.LeftButton)
                assert not tile.video_danmaku.enabled and not tile.video_danmaku.isVisible()
                assert '1001' not in window._danmaku_clients and client.stopped
        tile.set_video_active(False)
        QTest.mouseClick(tile.danmaku_button, Qt.LeftButton)
        assert '1001' not in window._danmaku_clients, 'A genuinely offline room must not open a connection'
        window.close()
    print('PASS: native button events, checked appearance, active playback with stale offline metadata, received comments, disable and offline gating')


if __name__ == '__main__':
    main()
