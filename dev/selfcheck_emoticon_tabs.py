"""离屏回归：表情包 Tab、按需加载、限流及过期图片隔离。"""
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabBar, QToolButton
from ddm import images
from ddm.danmaku_send import EmoticonPopup, _active_requests

APP = QApplication.instance() or QApplication([])


def settle(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    raise AssertionError("表情窗口未在限时内完成更新")


def package(name, count=2, kind=3):
    return {"pkg_type": kind, "pkg_name": name, "emoticons": [
        {"emoji": f"[{name}-{i}]", "perm": 1, "emoticon_unique": f"{name}_{i}",
         "url": f"https://example.invalid/{name}-{i}.png"} for i in range(count)]}


def buttons(popup):
    return popup.scroll.findChildren(QToolButton)


class EmoticonTabTests(unittest.TestCase):
    def setUp(self):
        self.popup = EmoticonPopup()
        self.popup.show()
        APP.processEvents()
        self.pixmap = QPixmap(32, 32)
        self.pixmap.fill(QColor("#00a1d6"))
        self.release = threading.Event()
        self.calls = []
        self.lock = threading.Lock()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.popup.hide()
        self.release.set()
        for worker in list(_active_requests):
            worker.wait(3000)
        APP.processEvents()
        self.popup.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)

    def load(self, url, subdir):
        with self.lock:
            self.calls.append((url, subdir))
        return self.pixmap

    def test_only_selected_package_is_built_and_downloaded(self):
        with patch.object(images, "load_pixmap", side_effect=self.load):
            self.popup.set_packages([package("小表情"), package("主播表情", kind=2),
                                     package("未知", kind=8)])
            tabs = self.popup.findChild(QTabBar)
            self.assertIsNotNone(tabs, "每个支持的表情包应有独立 Tab")
            self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ["小表情", "主播表情"])
            settle(lambda: len(buttons(self.popup)) == 2 and all(not b.icon().isNull() for b in buttons(self.popup)))
            self.assertEqual({b.text() for b in buttons(self.popup)}, {"[小表情-0]", "[小表情-1]"})
            self.assertEqual({url for url, _ in self.calls}, {
                "https://example.invalid/小表情-0.png", "https://example.invalid/小表情-1.png"})
            QTest.keyClick(tabs, Qt.Key_Right)
            settle(lambda: {b.text() for b in buttons(self.popup)} == {"[主播表情-0]", "[主播表情-1]"})
            settle(lambda: all(not b.icon().isNull() for b in buttons(self.popup)))
            tabs.setCurrentIndex(0)
            settle(lambda: {b.text() for b in buttons(self.popup)} == {"[小表情-0]", "[小表情-1]"})
            self.assertEqual(len(self.calls), 4, "访问过的 Tab 应复用已加载图标")
            self.assertTrue(all(subdir == "emoticons" for _, subdir in self.calls))

    def test_large_package_yields_between_batches(self):
        pack = package("大表情包", 600)
        for item in pack["emoticons"]:
            item.pop("url")
        self.popup.set_packages([pack, package("未打开", 600)])
        self.assertLess(len(buttons(self.popup)), 600, "不能同步创建整个长表情包")
        observed = []
        timer = QTimer()
        timer.setInterval(1)
        timer.timeout.connect(lambda: observed.append(len(buttons(self.popup))))
        timer.start()
        try:
            settle(lambda: len(buttons(self.popup)) == 600)
        finally:
            timer.stop()
        self.assertTrue(any(0 < count < 600 for count in observed), "构建期间必须让事件循环继续运行")
        self.assertTrue(all("大表情包" in b.text() for b in buttons(self.popup)))

    def test_tab_change_cancels_old_downloads_without_parallel_workers(self):
        active = peak = 0

        def slow_load(url, subdir):
            nonlocal active, peak
            with self.lock:
                self.calls.append((url, subdir))
                active += 1
                peak = max(peak, active)
            self.release.wait(2)
            with self.lock:
                active -= 1
            return self.pixmap

        with patch.object(images, "load_pixmap", side_effect=slow_load):
            self.popup.set_packages([package("旧包", 20), package("新包", 3)])
            settle(lambda: bool(self.calls))
            tabs = self.popup.findChild(QTabBar)
            self.assertIsNotNone(tabs, "切换包需要 Tab")
            tabs.setCurrentIndex(1)
            settle(lambda: len(buttons(self.popup)) == 3)
            self.release.set()
            settle(lambda: all(not b.icon().isNull() for b in buttons(self.popup)))
            settle(lambda: not _active_requests)
            self.assertEqual(peak, 1, "表情下载不能同时争用多个工作线程")
            self.assertEqual(sum("旧包" in url for url, _ in self.calls), 1, "切 Tab 后应取消旧包未开始的图片")

    def test_hiding_pauses_build_and_images_until_reopen(self):
        with patch.object(images, "load_pixmap", side_effect=self.load):
            self.popup.set_packages([package("暂停", 70)])
            self.popup.hide()
            QTest.qWait(80)
            self.assertFalse(self.calls, "已关闭的窗口不能启动图片下载")
            self.assertLess(len(buttons(self.popup)), 70)
            self.popup.show()
            settle(lambda: len(buttons(self.popup)) == 70)
            settle(lambda: all(not b.icon().isNull() for b in buttons(self.popup)))

    def test_permissions_selection_and_empty_package_are_preserved(self):
        small = package("小表情", 1)
        locked = package("主播表情", 1, kind=2)
        locked["emoticons"][0].update(perm=0, unlock_show_text="粉丝团")
        selected = []
        self.popup.selected.connect(lambda kind, emote: selected.append((kind, emote["emoji"])))
        with patch.object(images, "load_pixmap", side_effect=self.load):
            self.popup.set_packages([small, locked, package("空包", 0)])
            tabs = self.popup.findChild(QTabBar)
            self.assertIsNotNone(tabs, "表情包应按 Tab 呈现")
            tabs.setCurrentIndex(1)
            settle(lambda: len(buttons(self.popup)) == 1)
            self.assertFalse(buttons(self.popup)[0].isEnabled())
            self.assertIn("粉丝团", buttons(self.popup)[0].toolTip())
            tabs.setCurrentIndex(2)
            APP.processEvents()
            self.assertEqual(buttons(self.popup), [])
            self.assertIn("暂无", self.popup.status.text())
            tabs.setCurrentIndex(0)
            settle(lambda: len(buttons(self.popup)) == 1)
            buttons(self.popup)[0].click()
            self.assertEqual(selected, [(3, "[小表情-0]")])
            self.assertFalse(self.popup.isVisible())

    def test_active_download_stops_on_hide_and_resumes_after_reopen(self):
        def slow_load(url, subdir):
            with self.lock:
                self.calls.append((url, subdir))
            self.release.wait(2)
            return self.pixmap

        with patch.object(images, "load_pixmap", side_effect=slow_load):
            self.popup.set_packages([package("重开", 3)])
            settle(lambda: bool(self.calls))
            self.popup.hide()
            self.release.set()
            settle(lambda: not _active_requests)
            self.assertEqual(len(self.calls), 1, "关闭菜单后不能继续读取剩余图片")
            self.popup.show()
            settle(lambda: len(buttons(self.popup)) == 3 and all(not b.icon().isNull() for b in buttons(self.popup)))
            settle(lambda: not _active_requests)
            self.assertEqual(len(self.calls), 4, "重开后应重新排队被中断的三张图片")

    def test_refresh_ignores_old_image_result_and_hidden_catalog_stays_idle(self):
        started = threading.Event()

        def slow_load(url, subdir):
            started.set()
            self.release.wait(2)
            return self.pixmap

        with patch.object(images, "load_pixmap", side_effect=slow_load):
            self.popup.set_packages([package("旧目录", 10)])
            settle(started.is_set)
            self.popup.set_loading()
            self.popup.hide()
            self.popup.set_packages([package("新目录", 1)])
            self.release.set()
            settle(lambda: not _active_requests)
            self.assertEqual(buttons(self.popup), [], "窗口隐藏时返回的目录应延迟构建")
        with patch.object(images, "load_pixmap", return_value=None):
            self.popup.show()
            settle(lambda: len(buttons(self.popup)) == 1)
            self.assertEqual(buttons(self.popup)[0].text(), "[新目录-0]")
            self.assertTrue(buttons(self.popup)[0].icon().isNull(), "旧目录的图片不能回填到新目录")
            settle(lambda: not _active_requests)


if __name__ == "__main__":
    unittest.main()
