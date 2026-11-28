"""Real picker interactions against synthetic catalogs, sends and profile settings."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ddm.bili_interaction import bili_api as bili
from ddm.bili_interaction.session import BiliSession
from ddm import config
from ddm.plugins import PluginContext, PluginManager
from ddm.bili_interaction.composer import DanmakuComposer
from ddm.bili_interaction.recent_emoticons import RecentEmoticons
from ddm.bili_interaction.workers import _active_requests
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])
SMALL = {"pkg_type": 3, "pkg_name": "小表情", "emoticons": [
    {"emoji": "[甲]", "perm": 1}, {"emoji": "[乙]", "perm": 1}]}
LARGE = {"pkg_type": 2, "pkg_name": "主播", "emoticons": [
    {"emoji": "举手", "emoticon_unique": "room_101_hand", "perm": 1}]}


def settle(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    raise AssertionError("picker did not reach the expected state")


class RecentTests(unittest.TestCase):
    def setUp(self):
        self.manager = PluginManager()
        self.context = PluginContext(self.manager, "bili_live")
        self.recent = RecentEmoticons(self.context)
        self.manager._credentials.register("bilibili", lambda: {
            "SESSDATA": "offline-session", "bili_jct": "offline-csrf", "buvid3": "offline-device"})
        self.session = BiliSession(self.context)
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.shutdown()
            widget.deleteLater()
        settle(lambda: not _active_requests)
        APP.sendPostedEvents(None, QEvent.DeferredDelete)

    def composer(self, room):
        widget = DanmakuComposer(self.session, recent=self.recent)
        self.widgets.append(widget)
        widget.set_room(room)
        widget.setGeometry(10, 350, 270, widget.HEIGHT)
        widget.show()
        return widget

    def open(self, widget, packages):
        with patch.object(bili, "get_emoticons", return_value=packages):
            QTest.mouseClick(widget.emote_button, Qt.LeftButton)
            settle(lambda: widget._catalog_pending is None and widget.popup.isVisible())
        self.assertEqual(widget.popup.tabs.currentIndex(), 0)
        return widget.popup

    def test_selection_send_and_outside_click(self):
        widget = self.composer("101")
        popup = self.open(widget, [SMALL, LARGE])
        self.assertIn("暂无", popup.status.text())
        popup.tabs.setCurrentIndex(1)
        settle(lambda: len(popup._buttons) == 2)
        for index in (0, 1, 0):
            QTest.mouseClick(popup._buttons[index], Qt.LeftButton)
            self.assertTrue(popup.isVisible())
        self.assertEqual(widget.edit.text(), "[甲][乙][甲]")
        self.assertEqual(self.manager.plugin_settings, {})

        with patch.object(bili, "send_danmaku", return_value={}) as send:
            settle(widget.edit.hasFocus)
            QTest.keyClick(APP.focusWidget(), Qt.Key_Return)
            settle(lambda: not widget.busy)
            self.assertFalse(popup.isVisible())
            self.assertEqual(send.call_args.args[1], "[甲][乙][甲]")
        self.assertEqual(self.recent.keys, ["text:[甲]", "text:[乙]"])
        self.open(widget, [SMALL, LARGE])
        popup.tabs.setCurrentIndex(2)
        settle(lambda: len(popup._buttons) == 1)
        with patch.object(bili, "send_danmaku", return_value={}) as send:
            QTest.mouseClick(popup._buttons[0], Qt.LeftButton)
            settle(lambda: not widget.busy)
            self.assertEqual(send.call_args.kwargs["dm_type"], 1)
            self.assertTrue(popup.isVisible())
            self.assertEqual(popup.tabs.currentIndex(), 2)
        QTest.mouseClick(widget.edit, Qt.LeftButton)
        self.assertFalse(popup.isVisible())
        self.open(widget, [SMALL, LARGE])
        settle(lambda: [b.text() for b in popup._buttons] == ["举手", "[甲]", "[乙]"])
        QTest.mouseClick(widget.emote_button, Qt.LeftButton)
        self.assertFalse(popup.isVisible())

    def test_restore_history_from_host_config_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "utils" / "config.json"
            with patch.object(config, "CONFIG_PATH", str(path)), patch.dict(os.environ, DDM_NO_SAVE=""):
                self.manager._save_settings = lambda: config.save(
                    {"version": 1, "plugins": self.manager.plugin_settings})
                self.recent.record(("text:[甲]", "id:room_101_hand"))
                restarted = PluginManager()
                restarted.plugin_settings = config.load()["plugins"]
            self.assertEqual(RecentEmoticons(PluginContext(restarted, "bili_live")).keys,
                             ["id:room_101_hand", "text:[甲]"])

    def test_recent_tab_stays_first_when_dragging_across_it(self):
        popup = self.open(self.composer("101"), [SMALL, LARGE])
        popup.tabs.setCurrentIndex(2)
        for source, target in ((2, 0), (0, 1)):
            popup.tabs.moveTab(source, target)
            self.assertEqual(popup.tabs.tabData(0), popup.RECENT)
            self.assertEqual(popup.tabs.currentIndex(), 2)
            self.assertEqual(popup._category, popup.tabs.tabData(2))
            self.assertEqual(popup._packages, [SMALL, LARGE])

    def test_other_room_uses_its_own_catalog_and_permissions(self):
        widget = self.composer("202")
        locked = dict(SMALL, emoticons=[{"emoji": "[甲]", "perm": 0}])
        popup = self.open(widget, [locked])
        self.recent.record(("text:[甲]", "id:room_101_hand"))
        settle(lambda: len(popup._buttons) == 1)
        self.assertEqual(popup._buttons[0].text(), "[甲]")
        self.assertFalse(popup._buttons[0].isEnabled())
        self.assertEqual(self.recent.keys[0], "id:room_101_hand")

    def test_edited_failed_and_stale_sends_do_not_add_history(self):
        widget = self.composer("101")
        popup = self.open(widget, [SMALL])
        popup.tabs.setCurrentIndex(1)
        settle(lambda: len(popup._buttons) == 2)
        QTest.mouseClick(popup._buttons[0], Qt.LeftButton)
        widget.edit.setText("保留文字")
        with patch.object(bili, "send_danmaku", return_value={}):
            widget.send_button.click()
            settle(lambda: not widget.busy)
        self.assertFalse(popup.isVisible())
        self.assertEqual(self.recent.keys, [])
        widget.edit.setText("[乙]")
        with patch.object(bili, "send_danmaku", side_effect=ValueError("failed")):
            widget.send_text()
            settle(lambda: not widget.busy)
        self.assertEqual(self.recent.keys, [])
        release = threading.Event()
        entered = threading.Event()
        def late(*args, **kwargs):
            entered.set()
            release.wait(3)
            return {}
        with patch.object(bili, "send_danmaku", side_effect=late):
            widget.send_text()
            try:
                settle(entered.is_set)
                widget.set_room("202")
            finally:
                release.set()
            settle(lambda: not _active_requests)
        self.assertEqual(self.recent.keys, [])

    def test_bounded_and_deduplicated_across_repeated_sends(self):
        self.recent.record([f"id:{n}" for n in range(50)])
        self.recent.record(["id:20", "id:49", "id:20"])
        self.assertEqual(len(self.recent.keys), self.recent.LIMIT)
        self.assertEqual(self.recent.keys[:3], ["id:20", "id:49", "id:48"])


if __name__ == "__main__":
    unittest.main()
