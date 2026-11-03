"""Notice close lifecycle regression; synthetic data, not a real-load reproduction."""
import ctypes
from contextlib import ExitStack
from ctypes import wintypes
import os
from pathlib import Path
import sys
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from ddm import motion, theme
from ddm.notification_center import NotificationButton
from ddm.online_ui import UpdateNotice, show_result


class NoticeCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.qss())

    def setUp(self):
        self.animation_setting = patch.object(motion, 'enabled', return_value=True)
        self.animation_setting.start()
        self.addCleanup(self.animation_setting.stop)
        self.owner = QWidget()
        self.owner.setAttribute(Qt.WA_ShowWithoutActivating)
        self.owner.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        self.owner.setGeometry(-13000, -13000, 1000, 800)
        self.button = NotificationButton(self.owner)
        self.owner.sidebar = SimpleNamespace(notification_button=self.button)
        self.owner.show()
        self.addCleanup(self.owner.close)

    def assert_hidden(self, notice):
        self.assertFalse(notice.isVisible())
        self.assertFalse(notice.timer.isActive())
        if self.app.platformName() == 'windows':
            native_visible = ctypes.windll.user32.IsWindowVisible
            native_visible.argtypes = (wintypes.HWND,)
            self.assertFalse(native_visible(int(notice.internalWinId())), 'Native window must hide in the click handler')

    def test_manual_close_does_not_wait_for_exit_animation_or_other_notices(self):
        notices = []
        for index in range(4):
            show_result(self.owner, f'Fixture {index}', persistent=True)
            notice = self.owner._result_notice
            notice._motion.setCurrentTime(notice._motion.duration())
            notices.append(notice)
        self.assertEqual(len(self.button.center.entries), 4)
        for index, notice in enumerate(notices):
            with patch.object(notice, '_animate_to', wraps=notice._animate_to) as animate:
                QTest.mouseClick(notice.findChild(QPushButton, 'NoticeClose'), Qt.LeftButton)
                self.assert_hidden(notice)
                animate.assert_not_called()
            self.assertEqual(len(self.button.center.entries), 3 - index)
            self.assertEqual(len(self.owner._notices), 3 - index)
            for remaining in notices[index + 1:]:
                self.assertTrue(remaining.isVisible())

    def test_close_during_entrance_and_reopen_update_notice(self):
        notice = UpdateNotice(self.owner)
        notice.show_offer({'version': 'fixture'}, persistent=True)
        notice._motion.pause()
        notice._motion.setCurrentTime(40)
        QTest.mouseClick(notice.findChild(QPushButton, 'NoticeClose'), Qt.LeftButton)
        self.assert_hidden(notice)
        notice.show_offer({'version': 'next'}, persistent=True)
        notice._motion.setCurrentTime(notice._motion.duration())
        self.assertTrue(notice.isVisible())
        self.assertEqual(notice.windowOpacity(), 1.0)
        self.assertFalse(notice._leaving)
        self.assertEqual(self.owner._notices, [notice])
        notice.dismiss(animate=False)

    def test_automatic_timeout_keeps_the_existing_exit_animation(self):
        notice = UpdateNotice(self.owner)
        notice.show_offer({'version': 'fixture'})
        notice._motion.setCurrentTime(notice._motion.duration())
        notice.timer.timeout.emit()
        self.assertTrue(notice._leaving)
        self.assertTrue(notice.isVisible())
        notice._motion.setCurrentTime(notice._motion.duration())
        self.assert_hidden(notice)

    def test_capture_is_read_only_bounded_and_does_not_record_notice_text(self):
        from dev.diagnose_notice_close import NoticeCloseTrace
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            trace = NoticeCloseTrace(Path(directory) / 'close.jsonl')
            stack.callback(trace.timer.stop)
            trace.LIMIT = 12
            for name in ('dismiss', '_motion_frame', '_motion_finished', 'showEvent', 'hideEvent'):
                stack.enter_context(patch.object(UpdateNotice, name, getattr(UpdateNotice, name)))
            trace.install()
            notice = UpdateNotice(self.owner)
            secret_text = 'private-notice-do-not-log'
            notice.show_offer({'version': secret_text}, persistent=True)
            notice._motion.setCurrentTime(notice._motion.duration())
            self.assertFalse(trace.path.exists(), 'Idle notices must not consume the capture budget')
            before = (notice.geometry(), notice.internalWinId(), notice.mask(), notice.windowOpacity())
            trace.watch(notice)
            trace.record('read-only', notice)
            self.assertEqual(before, (notice.geometry(), notice.internalWinId(), notice.mask(), notice.windowOpacity()))
            QTest.mouseClick(notice.findChild(QPushButton, 'NoticeClose'), Qt.LeftButton)
            self.assert_hidden(notice)
            for _ in range(30):
                trace.sample()
            rows = [json.loads(line) for line in trace.path.read_text().splitlines()]
            self.assertLessEqual(len(rows), trace.LIMIT)
            self.assertFalse(trace.timer.isActive())
            self.assertNotIn(secret_text, trace.path.read_text())
            hidden = [row for row in rows if row['stage'] == 'dismiss:after']
            self.assertTrue(hidden)
            self.assertFalse(hidden[-1]['visible'])
            if self.app.platformName() == 'windows':
                self.assertFalse(hidden[-1]['native_visible'])


if __name__ == '__main__':
    unittest.main()
