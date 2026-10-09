"""Confirmed offline status clears stream failures across all six platforms."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from ddm import app as module, bili
from ddm.app import MainWindow
from dev.selfcheck_offline_badges import IdlePoller, FakePlayer


def main():
    app = QApplication([])
    with patch.object(module, 'StatusPoller', IdlePoller), patch.object(module, 'StatsPoller', IdlePoller), \
            patch.object(bili, 'play_url', side_effect=RuntimeError('offline fixture')):
        window = MainWindow([], [], layout_id='single')
        window.refresh_status = lambda: None
        tile = window.wall.tiles[0]
        try:
            for kind in ('bilibili', 'huya', 'douyin', 'douyu', 'twitch', 'youtube'):
                rid = '1001' if kind == 'bilibili' else kind + ':1001'
                room = dict(room_id=rid, uname=kind, live=False, live_known=False)
                item = window.sidebar._append_item(dict(room))
                tile.set_room(dict(room))
                tile.set_status('连接失败')
                tile.set_buffering(True)
                player = FakePlayer()
                window.players[tile] = player
                resolver = SimpleNamespace(cancel=lambda: cancelled.append(True))
                cancelled = []
                window._resolvers[tile] = resolver
                # Unknown offline placeholders must not stop an existing request.
                window._on_status_updated({rid: dict(live=False, live_known=False, viewers='', title='')})
                assert not player.released and not cancelled
                window._on_status_updated({rid: dict(live=False, live_known=True, viewers='', title='')})
                assert player.released and cancelled
                assert tile.room['live_known'] and not tile.room['live']
                assert tile._status_text == tile.cover.text() == '未开播'
                assert item.badge.text() == '未开播'
                assert not tile._buffering and not tile._connecting
                assert tile not in window.players and tile not in window._resolvers
                assert tile not in window._retry_timers
                window._on_resolve_failed(tile, 'late failure')
                assert tile._status_text == '未开播'
                with patch.object(window.plugins, 'platform_for', return_value=(
                        None if kind == 'bilibili' else SimpleNamespace(kind=kind))):
                    window.start_tile(tile)
                assert tile._status_text == '未开播' and tile not in window._resolvers
                with patch.object(window, 'start_tile') as start:
                    window._on_status_updated({rid: dict(live=True, viewers='', title='')})
                    start.assert_called_once_with(tile)
                with patch.object(window, '_schedule_retry') as retry:
                    window._on_resolve_failed(tile, 'real network failure')
                    retry.assert_called_once_with(tile)
                    assert tile._status_text == '连接失败' and tile.room['live']
                window._on_status_updated({rid: dict(live=False, viewers='', title='')})
                assert tile._status_text == '已下播'
            print('PASS: all six platforms; confirmed offline clears errors/buffering, cancels playback, ignores late failures, resumes on live; network errors remain failures')
        finally:
            window.close()
            app.processEvents()


if __name__ == '__main__':
    main()
