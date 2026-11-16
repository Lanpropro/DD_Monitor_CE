"""Mobile share parsing, bounded redirects and background room lookup; offline fixtures."""
from contextlib import nullcontext
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from ddm.app import MainWindow
from ddm.bili import InfoResolver
from ddm.dialogs import AddRoomDialog
from ddm.room_input import bili_room_id, extract_room_input, resolve_bili_share
from ddm.room_input import bili_profile_uid
from ddm.bili_profile import room_for_uid

SHARE = '【直播就是生活就是直播-哔哩哔哩直播】 https://b23.tv/DDsx7iz'
SHORT = 'https://b23.tv/DDsx7iz'
LIVE = 'https://live.bilibili.com/47867?broadcast_type=0&share_medium=iphone'
PROFILE = 'https://space.bilibili.com/2094031249'


def profile_response(payload):
    return nullcontext(SimpleNamespace(raise_for_status=Mock(), json=lambda: payload))


def redirect(target, status=302):
    return nullcontext(SimpleNamespace(status_code=status, headers={'Location': target},
                                       raise_for_status=Mock()))


class MobileShareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_profile_uid_is_distinct_from_room_number_and_host_is_exact(self):
        for url in (PROFILE, PROFILE + '/?spm_id_from=333.1387', PROFILE + '/video',
                    'space.bilibili.com/2094031249', 'HTTP://SPACE.BILIBILI.COM/2094031249'):
            self.assertEqual(bili_profile_uid(url), '2094031249')
            self.assertEqual(bili_room_id(url), '')
        for url in ('2094031249', 'https://example.invalid/2094031249',
                    'https://space.bilibili.com.example.invalid/2094031249',
                    'https://space.bilibili.com/not2094031249',
                    'file://space.bilibili.com/2094031249', 'https://space.bilibili.com/0'):
            self.assertEqual(bili_profile_uid(url), '')
        self.assertEqual(bili_room_id('2094031249'), '2094031249')

    def test_profile_dialog_accepts_links_without_network_or_uid_fallback(self):
        owner = SimpleNamespace(plugins=SimpleNamespace(platform_for=lambda _: None))
        from ddm.room_placement import RoomPlacement
        owner.room_placement = RoomPlacement(owner)
        normalize = lambda text: MainWindow._normalize_room_input(owner, text)
        with patch('ddm.bili_profile.requests.get') as get:
            for resolver in (None, normalize):
                for value in (PROFILE, 'UP主页：' + PROFILE + '。', PROFILE.removeprefix('https://')):
                    dialog = AddRoomDialog(room_id_resolver=resolver)
                    dialog.edit.setText(value)
                    dialog.accept()
                    self.assertEqual(dialog.result(), QDialog.Accepted)
                    self.assertNotEqual(dialog.room_id, '2094031249')
                    self.assertEqual(bili_profile_uid(dialog.room_id), '2094031249')
                    self.assertIn('个人主页', dialog.hint.text())
                    dialog.close()
                dialog = AddRoomDialog(room_id_resolver=resolver)
                dialog.edit.setText('space.bilibili.com/not2094031249')
                dialog.accept()
                self.assertEqual(dialog.result(), QDialog.Rejected)
                self.assertEqual(dialog.room_id, '')
                dialog.close()
            get.assert_not_called()

    def test_public_profile_lookup_returns_offline_room_without_cookies(self):
        for live_status in (0, 1):
            with patch('ddm.bili_profile.requests.get', return_value=profile_response(
                    {'code': 0, 'data': {'roomStatus': 1, 'liveStatus': live_status, 'roomid': 22748536}})) as get, \
                    patch('ddm.bili._cookies') as cookies:
                self.assertEqual(room_for_uid('2094031249'), '22748536')
                self.assertEqual(get.call_args.args[0], 'https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld')
                self.assertEqual(get.call_args.kwargs['params'], {'mid': '2094031249'})
                self.assertEqual(get.call_args.kwargs['timeout'], (3, 8))
                self.assertNotIn('cookies', get.call_args.kwargs)
                cookies.assert_not_called()

    def test_profile_failures_are_explicit_and_do_not_query_uid_as_room(self):
        cases = [({'code': 0, 'data': {'roomStatus': 0, 'roomid': 0}}, '尚未开通'),
                 ({'code': -400, 'message': 'private raw response'}, '查询失败'),
                 ({'code': 0, 'data': None}, '有效的直播间资料'),
                 ({'code': 0, 'data': {'roomStatus': 1, 'roomid': 'not22748536'}}, '有效的直播间号')]
        for payload, expected in cases:
            worker = InfoResolver(PROFILE)
            failed = []
            worker.failed.connect(failed.append)
            with patch('ddm.bili_profile.requests.get', return_value=profile_response(payload)), \
                    patch('ddm.bili.room_info') as info:
                worker.run()
                info.assert_not_called()
            self.assertEqual(failed, [PROFILE])
            self.assertIn(expected, worker.error_message)
            self.assertNotIn('private', worker.error_message)
        with patch('ddm.bili_profile.requests.get', side_effect=requests.Timeout('private URL')), \
                patch('ddm.bili.room_info') as info:
            worker = InfoResolver(PROFILE)
            worker.run()
            self.assertIn('超时', worker.error_message)
            info.assert_not_called()

    def test_short_share_can_redirect_to_profile_and_fetch_canonical_room(self):
        with patch('ddm.room_input.requests.get', side_effect=[redirect(PROFILE), profile_response(
                {'code': 0, 'data': {'roomStatus': 1, 'roomid': 22748536}})]) as get:
            self.assertEqual(resolve_bili_share(SHORT), '22748536')
        self.assertEqual(get.call_count, 2)

    def test_profile_lookup_runs_in_worker_and_keeps_gui_responsive(self):
        entered, release = threading.Event(), threading.Event()
        worker = InfoResolver(PROFILE)
        answers, timers = [], []
        worker.resolved.connect(answers.append)
        def get(*args, **kwargs):
            self.assertNotEqual(QThread.currentThread(), self.app.thread())
            entered.set()
            if not release.wait(3):
                raise requests.Timeout()
            return profile_response({'code': 0, 'data': {'roomStatus': 1, 'roomid': 22748536}})
        with patch('ddm.bili_profile.requests.get', side_effect=get), \
                patch('ddm.bili.room_info', return_value={'room_id': '22748536', 'live': False}) as info:
            try:
                worker.start()
                self.assertTrue(entered.wait(2))
                QTimer.singleShot(0, lambda: timers.append(True))
                QTest.qWait(30)
                self.assertEqual(timers, [True])
                info.assert_not_called()
                release.set()
                self.assertTrue(worker.wait(2000))
                QTest.qWait(10)
                self.assertEqual(answers, [{'room_id': '22748536', 'live': False}])
                info.assert_called_once_with('22748536')
            finally:
                release.set()
                worker.wait(5000)

    def test_profile_add_uses_core_worker_and_keeps_per_request_error_and_folder(self):
        class Pending(QObject):
            resolved = Signal(dict)
            failed = Signal(str)
            finished = Signal()
            def __init__(self, room_id, parent):
                super().__init__()
                self.room_id, self.error_message = room_id, ''
            def start(self):
                pass
        owner = SimpleNamespace(sidebar=SimpleNamespace(rooms=lambda: []),
            plugins=SimpleNamespace(platform_for=lambda _: None), _closing=False,
            _platform_info_running=set(), _on_room_added=Mock())
        from ddm.room_placement import RoomPlacement
        owner.room_placement = RoomPlacement(owner)
        with patch('ddm.app.InfoResolver', Pending):
            MainWindow._add_room_id(owner, PROFILE, folder_id='my-folder')
            first = next(iter(owner._platform_info_running))
            MainWindow._add_room_id(owner, 'https://space.bilibili.com/193559518')
            second = next(worker for worker in owner._platform_info_running if worker is not first)
        first.error_message = '该 B 站账号尚未开通直播间'
        second.error_message = '房间资料请求超时，请稍后重试'
        with patch('PySide6.QtWidgets.QMessageBox.warning') as warning:
            second.failed.emit(second.room_id)
            first.failed.emit(first.room_id)
            self.assertIn('超时', warning.call_args_list[0].args[2])
            self.assertIn('尚未开通', warning.call_args_list[1].args[2])
            owner._closing = True
            first.failed.emit(first.room_id)
            self.assertEqual(warning.call_count, 2)
        owner._closing = False
        first.resolved.emit({'room_id': '22748536'})
        owner._on_room_added.assert_called_once_with({'room_id': '22748536'}, folder_id='my-folder')
        first.finished.emit()
        second.finished.emit()
        self.assertFalse(owner._platform_info_running)

    def test_exact_idea_example_and_chinese_punctuation(self):
        for value in (SHARE, '今天2026第23场：' + SHORT + '。',
                      '【直播标题】\n' + SHORT + '）', '“' + SHORT + '”'):
            self.assertEqual(extract_room_input(value), SHORT)

    def test_direct_urls_ignore_title_and_tracking_digits(self):
        for text in ('直播2026：' + LIVE, 'https://live.bilibili.com/blanc/47867?share=123',
                     'live.bilibili.com/47867', '47867'):
            self.assertEqual(bili_room_id(extract_room_input(text)), '47867')
        self.assertFalse(bili_room_id('https://example.invalid/live.bilibili.com/47867'))
        self.assertFalse(bili_room_id('https://live.bilibili.com/47867extra'))

    def test_multiple_links_are_not_silently_assigned(self):
        with self.assertRaisesRegex(ValueError, '多个链接'):
            extract_room_input(SHORT + ' ' + LIVE)

    def test_short_link_resolves_without_fetching_room_page_or_using_cookies(self):
        with patch('ddm.room_input.requests.get', return_value=redirect(LIVE)) as get:
            self.assertEqual(resolve_bili_share(SHORT), '47867')
        get.assert_called_once_with(SHORT, headers={'User-Agent': 'Mozilla/5.0'},
                                    timeout=(3, 5), allow_redirects=False, stream=True)

    def test_relative_redirects_and_redirect_limit(self):
        with patch('ddm.room_input.requests.get', side_effect=[redirect('/another'), redirect(LIVE)]) as get:
            self.assertEqual(resolve_bili_share(SHORT), '47867')
            self.assertEqual(get.call_args_list[1].args[0], 'https://b23.tv/another')
        with patch('ddm.room_input.requests.get', side_effect=lambda *a, **kw: redirect(SHORT)) as get:
            with self.assertRaises(ValueError):
                resolve_bili_share(SHORT)
            self.assertEqual(get.call_count, 3)

    def test_non_live_and_external_redirects_do_not_become_room_numbers(self):
        for target in ('https://www.bilibili.com/video/BV123',
                       'https://example.invalid/47867', 'file:///47867'):
            with patch('ddm.room_input.requests.get', return_value=redirect(target)) as get:
                with self.assertRaisesRegex(ValueError, '直播间'):
                    resolve_bili_share(SHORT)
                self.assertEqual(get.call_count, 1)

    def test_missing_redirect_is_reported(self):
        with patch('ddm.room_input.requests.get', return_value=redirect('', 200)):
            with self.assertRaisesRegex(ValueError, '未能跳转'):
                resolve_bili_share(SHORT)

    def test_dialog_validation_does_not_make_network_requests(self):
        owner = SimpleNamespace(plugins=SimpleNamespace(platform_for=lambda _: None))
        from ddm.room_placement import RoomPlacement
        owner.room_placement = RoomPlacement(owner)
        resolver = lambda text: MainWindow._normalize_room_input(owner, text)
        with patch('ddm.room_input.requests.get') as get:
            for normalize in (None, resolver):
                dialog = AddRoomDialog(room_id_resolver=normalize)
                dialog.edit.setText(SHARE)
                dialog.accept()
                self.assertEqual(dialog.result(), QDialog.Accepted)
                self.assertEqual(dialog.room_id, SHORT)
                dialog.close()
            self.assertEqual(resolver('直播2026：' + LIVE), '47867')
            get.assert_not_called()

    def test_plugin_receives_extracted_url_and_unknown_platform_is_rejected(self):
        plugin = SimpleNamespace(normalize=Mock(return_value='huya:room'))
        lookup = Mock(return_value=plugin)
        owner = SimpleNamespace(plugins=SimpleNamespace(platform_for=lookup))
        from ddm.room_placement import RoomPlacement
        owner.room_placement = RoomPlacement(owner)
        self.assertEqual(MainWindow._normalize_room_input(owner, '【中文标题】 https://www.huya.com/room'), 'huya:room')
        lookup.assert_called_once_with('https://www.huya.com/room')
        plugin.normalize.assert_called_once_with('https://www.huya.com/room')
        lookup.return_value = None
        with self.assertRaisesRegex(ValueError, '未识别平台'):
            MainWindow._normalize_room_input(owner, '【标题123】 https://example.invalid/456')

    def test_resolver_failure_never_queries_a_mistaken_numeric_room(self):
        worker = InfoResolver(SHORT)
        failed = []
        worker.failed.connect(failed.append)
        with patch('ddm.room_input.requests.get', side_effect=requests.Timeout), \
                patch('ddm.bili.room_info') as room_info:
            worker.run()
            room_info.assert_not_called()
        self.assertEqual(failed, [SHORT])

    def test_lookup_runs_in_background_while_gui_timer_remains_responsive(self):
        entered, release = threading.Event(), threading.Event()
        worker = InfoResolver(SHORT)
        answers, timers, background = [], [], []
        worker.resolved.connect(answers.append)
        def get(*args, **kwargs):
            background.append(QThread.currentThread() != self.app.thread())
            entered.set()
            if not release.wait(3):
                raise requests.Timeout()
            return redirect(LIVE)
        with patch('ddm.room_input.requests.get', side_effect=get), \
                patch('ddm.bili.room_info', return_value={'room_id': '47867'}) as info:
            try:
                worker.start()
                self.assertTrue(entered.wait(2))
                QTimer.singleShot(0, lambda: timers.append(True))
                QTest.qWait(30)
                self.assertEqual(timers, [True])
                info.assert_not_called()
                release.set()
                self.assertTrue(worker.wait(2000))
                QTest.qWait(10)
                self.assertEqual(answers, [{'room_id': '47867'}])
                self.assertEqual(background, [True])
                info.assert_called_once_with('47867')
            finally:
                release.set()
                worker.wait(5000)

    def test_main_window_routes_short_link_to_core_and_tracks_thread(self):
        class Pending(QObject):
            resolved = Signal(dict)
            failed = Signal(str)
            finished = Signal()
            def __init__(self, room_id, parent):
                super().__init__()
                self.room_id = room_id
                self.started = False
            def start(self):
                self.started = True
        owner = SimpleNamespace(sidebar=SimpleNamespace(rooms=lambda: []),
            plugins=SimpleNamespace(platform_for=lambda _: None), _closing=False,
            _platform_info_running=set(), _on_room_added=Mock())
        from ddm.room_placement import RoomPlacement
        owner.room_placement = RoomPlacement(owner)
        with patch('ddm.app.InfoResolver', Pending):
            MainWindow._add_room_id(owner, SHORT, folder_id='my-folder')
        self.assertEqual(len(owner._platform_info_running), 1)
        worker = next(iter(owner._platform_info_running))
        self.assertTrue(worker.started)
        worker.resolved.emit({'room_id': '47867'})
        owner._on_room_added.assert_called_once_with({'room_id': '47867'}, folder_id='my-folder')
        worker.finished.emit()
        self.assertFalse(owner._platform_info_running)


if __name__ == '__main__':
    unittest.main()
