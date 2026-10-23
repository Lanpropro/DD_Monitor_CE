"""Offline drag cleanup and callback ownership checks; no native hooks or drags."""
import ctypes
import gc
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import weakref

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication
from ddm import mouse_hook, motion
from ddm.widgets import Sidebar


PROC = ctypes.CFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)


class HookAPI:
    def __init__(self):
        self.outcome = True
        self.alive_at_unhook = []
        self.installs = 0
        self.forwarded = 0

    def SetWindowsHookExW(self, kind, callback, module, thread):
        self.callback = weakref.ref(callback)
        self.installs += 1
        return 123

    def UnhookWindowsHookEx(self, handle):
        self.alive_at_unhook.append(self.callback() is not None)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def CallNextHookEx(self, *args):
        self.forwarded += 1
        return 987


class DragLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.api = HookAPI()
        self.loader = patch.object(mouse_hook, '_load', return_value=(self.api, object, PROC))
        self.loader.start()
        self.retained = patch.object(mouse_hook, '_pending_hooks', set(), create=True)
        self.retained.start()
        self.hooks = []

    def tearDown(self):
        self.api.outcome = True
        for hook in self.hooks:
            hook.stop()
        self.app.processEvents()
        self.retained.stop()
        self.loader.stop()

    def hook(self):
        hook = mouse_hook.WheelHook(lambda delta: None)
        self.hooks.append(hook)
        self.assertTrue(hook.start())
        return hook

    def test_callback_survives_until_successful_unhook_and_can_restart(self):
        hook = self.hook()
        for _ in range(10):
            hook.stop()
            self.assertTrue(self.api.alive_at_unhook[-1])
            self.assertFalse(hook.active)
            self.assertIsNone(hook._callback)
            hook.start()
        self.assertEqual(self.api.installs, 11)

    def test_failed_unhook_retains_callback_and_suppresses_ui_dispatch(self):
        for outcome in (False, OSError('synthetic unhook failure')):
            with self.subTest(outcome=outcome):
                hook = self.hook()
                self.api.outcome = outcome
                hook.stop()
                self.assertTrue(hook.active)
                self.assertIn(hook, mouse_hook._pending_hooks)
                with patch.object(hook, '_dispatch') as dispatch:
                    self.assertEqual(hook._callback(0, 0, 0), 987)
                    dispatch.assert_not_called()
                self.assertFalse(hook.start(), '不能叠加或重新启用卸载失败的旧钩子')
                self.api.outcome = True
                hook.stop()
                self.assertNotIn(hook, mouse_hook._pending_hooks)
                self.assertFalse(hook.active)

    def test_failed_unhook_has_an_owner_even_if_sidebar_releases_it(self):
        hook = self.hook()
        self.api.outcome = False
        hook.stop()
        self.hooks.remove(hook)
        reference = weakref.ref(hook)
        del hook
        gc.collect()
        self.assertIsNotNone(reference())
        self.assertIsNotNone(self.api.callback())
        self.api.outcome = True
        reference().stop()

    def test_unavailable_api_keeps_the_hook_until_retry(self):
        hook = self.hook()
        with patch.object(mouse_hook, '_load', return_value=None):
            hook.stop()
        self.assertTrue(hook.active)
        self.assertIn(hook, mouse_hook._pending_hooks)
        hook.stop()
        self.assertFalse(hook.active)

    def test_callback_always_forwards_and_self_stop_defers_release(self):
        hook = self.hook()
        with patch.object(hook, '_dispatch', side_effect=RuntimeError('synthetic UI failure')):
            self.assertEqual(hook._callback(0, 0, 0), 987)
        with patch.object(hook, '_dispatch', side_effect=lambda *args: hook.stop()):
            self.assertEqual(hook._callback(0, 0, 0), 987)
        self.assertTrue(self.api.alive_at_unhook[-1])
        self.assertIsNotNone(hook._callback, '回调返回原生调用方前必须保持存活')
        self.app.processEvents()
        self.assertIsNone(hook._callback)
        self.assertEqual(self.api.forwarded, 2)

    def test_deferred_release_does_not_clear_a_restarted_hook(self):
        hook = self.hook()
        with patch.object(hook, '_dispatch', side_effect=lambda *args: hook.stop()):
            hook._callback(0, 0, 0)
        self.assertTrue(hook.start())
        callback = hook._callback
        self.app.processEvents()
        self.assertIs(hook._callback, callback)
        self.assertTrue(hook.active)

    def test_sidebar_retries_failed_unhook_without_stacking_hooks(self):
        sidebar = Sidebar([])
        try:
            sidebar.begin_drag_scroll()
            hook = sidebar._wheel_hook
            self.hooks.append(hook)
            self.api.outcome = False
            sidebar.end_drag_scroll()
            self.assertIs(sidebar._wheel_hook, hook)
            sidebar.begin_drag_scroll()
            self.assertEqual(self.api.installs, 1)
            self.api.outcome = True
            sidebar.begin_drag_scroll()
            self.assertEqual(self.api.installs, 2)
            sidebar.end_drag_scroll()
            self.assertIsNone(sidebar._wheel_hook)
        finally:
            self.api.outcome = True
            sidebar.end_drag_scroll()
            sidebar.close()

    def test_card_drag_cancel_exception_and_reentry_restore_placeholder(self):
        with patch.object(motion, 'enabled', return_value=False):
            for mode in ('drop', 'cancel', 'error', 'start_error', 'reentry'):
                with self.subTest(mode=mode):
                    sidebar = Sidebar([{'room_id': '1', 'uname': 'Test', 'live': False}])
                    sidebar.resize(250, 500)
                    sidebar.show()
                    self.app.processEvents()
                    item = sidebar.items()[0]
                    item._press_pos = QPoint(1, 1)
                    event = SimpleNamespace(buttons=lambda: Qt.LeftButton, pos=lambda: QPoint(40, 40))
                    drag = Mock()
                    def execute(*args):
                        self.assertTrue(item.isHidden())
                        if mode == 'error':
                            raise RuntimeError('synthetic drag failure')
                        if mode == 'reentry' and drag.exec.call_count == 1:
                            item.mouseMoveEvent(event)
                        return Qt.IgnoreAction if mode == 'cancel' else Qt.CopyAction
                    drag.exec.side_effect = execute
                    try:
                        with patch('ddm.widgets.QDrag', return_value=drag), \
                                patch.object(sidebar, 'begin_drag_scroll') as begin, \
                                patch.object(sidebar, 'end_drag_scroll') as end, \
                                patch.object(QApplication, 'mouseButtons', return_value=(
                                    Qt.LeftButton if mode == 'cancel' else Qt.NoButton)):
                            if mode == 'start_error':
                                begin.side_effect = RuntimeError('synthetic hook setup failure')
                            if mode in ('error', 'start_error'):
                                with self.assertRaises(RuntimeError):
                                    item.mouseMoveEvent(event)
                            else:
                                item.mouseMoveEvent(event)
                            end.assert_called_once()
                        self.assertFalse(item.isHidden(), '取消或异常后原卡片必须归位')
                        self.assertFalse(sidebar.list_box._scroll_timer.isActive())
                        self.assertIsNone(item._press_pos)
                        self.assertEqual(drag.exec.call_count, int(mode != 'start_error'))
                        drag.deleteLater.assert_called_once()
                    finally:
                        sidebar.close()


if __name__ == '__main__':
    unittest.main()
