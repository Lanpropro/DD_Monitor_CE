"""隔离压力测试：模拟登录、3000关注分页、750主播列表及真实宿主导入。"""
import json
import os
from pathlib import Path
import sys
import time
import faulthandler
from contextlib import ExitStack
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication
from ddm import bili, theme
from ddm.app import MainWindow
from ddm.account_dialog import AccountPlatformDialog
from ddm.dialogs import FollowImportDialog
from ddm.widgets import RoomStrip


def check_edge_cases():
    entries = [{'mid': i, 'uname': str(i)} for i in range(50)]
    replies = [Mock(json=lambda: {'code': 0, 'data': {'list': entries}}),
               Mock(json=lambda: {'code': 0, 'data': {'list': [dict(mid=99, uname='99')]}})]
    with patch.object(bili.requests, 'get', side_effect=replies):
        assert len(bili.following(123)) == 51, 'Missing totals must use the short final page'
    with patch.object(bili.requests, 'get', return_value=replies[0]) as get:
        assert len(bili.following(123, max_pages=1)) == 50 and get.call_count == 1
    for responses in ([replies[0], replies[0]],
                      [Mock(json=lambda: {'code': 0, 'data': {'list': [], 'total': 3000}})]):
        with patch.object(bili.requests, 'get', side_effect=responses):
            try:
                bili.following(123)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Repeated or prematurely empty pages must not silently truncate')
    with patch.object(bili.requests, 'get', side_effect=[replies[0],
            Mock(json=lambda: {'code': -101, 'message': 'Fixture session expired'})]):
        try:
            bili.following(123)
        except RuntimeError as error:
            assert 'Fixture session expired' in str(error)
        else:
            raise AssertionError('API failure must not return a successful partial import')
    strip = RoomStrip()
    rooms = [dict(room_id=str(i), uname=str(i), live=False) for i in range(3)]
    strip.set_rooms(rooms[:2])
    first = strip._avatars['0']
    strip.set_rooms(rooms)
    assert strip._avatars['0'] is first, 'Appending must retain existing avatar widgets'
    strip.set_rooms(list(reversed(rooms)))
    assert strip._avatars['0'] is first, 'Reordering must retain unchanged avatars'
    strip.set_rooms([dict(rooms[0], live=True)])
    assert strip._avatars['0'] is not first and set(strip._avatars) == {'0'}
    strip.close()


def main():
    faulthandler.dump_traceback_later(30)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    check_edge_cases()
    report = {'fixture_follows': 3000, 'fixture_rooms': 750, 'stages': {}}
    calls = []
    # Spread broadcasters over ALL pages, including the final page.
    def get(url, **kwargs):
        assert url.endswith('/x/relation/followings'), url
        page, size = kwargs['params']['pn'], kwargs['params']['ps']
        calls.append(page)
        time.sleep(.002)  # Simulated I/O, not a real Bilibili latency claim.
        items = [{'mid': i, 'uname': f'Anchor {i:04d}'}
                 for i in range((page - 1) * size + 1, min(page * size, 3000) + 1)]
        return Mock(json=lambda: {'code': 0, 'data': {'list': items, 'total': 3000}})

    def post(url, **kwargs):
        assert url.endswith('/get_status_info_by_uids'), url
        ids = json.loads(kwargs['data'])['uids']
        assert len(ids) <= 100
        time.sleep(.002)
        return Mock(json=lambda: {'code': 0, 'data': {
            str(i): dict(room_id=10000+i, uname=f'Anchor {i:04d}',
                         live_status=1 if i % 8 == 0 else 0, title='Fixture')
            for i in ids if i % 4 == 0}})

    timer = QTimer()
    timer.setInterval(5)
    gaps, previous = [], [time.perf_counter()]
    def beat():
        now = time.perf_counter()
        gaps.append((now - previous[0]) * 1000)
        previous[0] = now
    timer.timeout.connect(beat)
    def measure(name, action):
        print('START', name, flush=True)
        app.processEvents()
        gaps.clear()
        previous[0] = time.perf_counter()
        start = previous[0]
        result = action()
        app.processEvents()
        elapsed = (time.perf_counter() - start) * 1000
        report['stages'][name] = {'elapsed_ms': round(elapsed, 2),
                                 'max_event_gap_ms': round(max(gaps, default=elapsed), 2)}
        print(name, report['stages'][name], flush=True)
        return result
    def wait_until(done):
        deadline = time.monotonic() + 90
        while not done():
            assert time.monotonic() < deadline, 'Stress stage timed out'
            app.processEvents()
            time.sleep(.001)

    with ExitStack() as stack:
        stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network')))
        stack.enter_context(patch.object(bili.requests, 'get', side_effect=get))
        stack.enter_context(patch.object(bili.requests, 'post', side_effect=post))
        stack.enter_context(patch.object(bili, 'my_uid', return_value=123))
        with patch('ddm.app.QTimer.singleShot'):
            owner = MainWindow([], [], state={'plugins_enabled': []})
        owner.resize(1200, 800)
        owner.show()
        stack.enter_context(patch.object(bili, 'SESSION_DATA', 'synthetic-login'))
        for name in ('_start_avatar_loader', 'load_avatars_for', '_refresh_meta'):
            stack.enter_context(patch.object(owner, name))
        stack.enter_context(patch('ddm.online_ui.show_result'))
        dialog = None
        timer.start()
        try:
            def load():
                nonlocal dialog
                dialog = AccountPlatformDialog(owner, {}, import_follows=True)
                dialog.show()
                wait_until(lambda: isinstance(dialog.page, FollowImportDialog)
                           and not dialog.page.property('loading'))
            measure('load_and_present', load)
            page = dialog.page
            report['pages_read'] = len(calls)
            report['rooms_loaded'] = page.list.count()
            # Independently exercise the requested 750-row UI even on truncated baselines.
            rooms = [dict(room_id=str(10000+i), uname=f'Anchor {i:04d}', live=i % 8 == 0)
                     for i in range(4, 3001, 4)]
            measure('present_750', lambda: dialog._show_rooms(rooms))
            page = dialog.page
            measure('select_live', page._check_live)
            assert len(page.selected()) == 375
            measure('select_all', lambda: page._check_all(True))
            measure('search', lambda: page.search_edit.setText('Anchor 29'))
            page.search_edit.clear()
            pixmap = QPixmap(32, 32)
            pixmap.fill(QColor('red'))
            measure('avatar_750', lambda: [page.set_avatar(r['room_id'], pixmap) for r in rooms])
            def imports():
                owner._import_selected_follows(page.selected())
                wait_until(lambda: owner._follow_import_timer is None)
            if os.environ.get('DDM_STRESS_PROFILE'):
                import cProfile
                import pstats
                with cProfile.Profile() as profile:
                    measure('import_750', imports)
                pstats.Stats(profile).sort_stats('cumtime').print_stats(24)
            else:
                measure('import_750', imports)
            assert {r['room_id'] for r in owner.sidebar.rooms()} == {r['room_id'] for r in rooms}
            avatars = dict(owner.sidebar._head_strip._avatars)
            measure('reimport_750', imports)
            assert len(owner.sidebar.rooms()) == 750
            assert avatars == owner.sidebar._head_strip._avatars
        finally:
            timer.stop()
            if dialog:
                dialog.close()
            owner.close()
    output = Path(os.environ.get('DDM_STRESS_REPORT', 'results/follow-stress.json'))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    assert report['rooms_loaded'] == 750, '3000 follows must not truncate to the first 1000'
    assert report['pages_read'] == 60
    assert report['stages']['avatar_750']['elapsed_ms'] < 250
    assert report['stages']['import_750']['max_event_gap_ms'] < 250
    faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    main()
