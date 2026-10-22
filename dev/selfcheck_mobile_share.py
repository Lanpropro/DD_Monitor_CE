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

SHARE = '【直播就是生活就是直播-哔哩哔哩直播】 https://b23.tv/DDsx7iz'
SHORT = 'https://b23.tv/DDsx7iz'
LIVE = 'https://live.bilibili.com/47867?broadcast_type=0&share_medium=iphone'


def redirect(target, status=302):
    return nullcontext(SimpleNamespace(status_code=status, headers={'Location': target},
                                       raise_for_status=Mock()))


class MobileShareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
