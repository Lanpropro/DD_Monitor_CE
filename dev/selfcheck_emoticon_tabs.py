"""离屏回归：表情包 Tab、按需加载、限流及过期图片隔离。"""
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch, Mock
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QBuffer, QIODevice, QEvent, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabBar, QToolButton, QWidget
from ddm import images
from ddm.danmaku_send import EmoticonPopup, EmoticonOrder, emoticon_order, _active_requests

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


class EmoticonCacheTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        for name, value in (("REPO", self.directory), ("_EMOTICON_IMAGES", OrderedDict()),
                            ("_EMOTICON_PENDING", {}), ("_EMOTICON_BYTES", 0)):
            self.stack.enter_context(patch.object(images, name, value))
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor("#00a1d6"))
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        pixmap.save(buffer, "PNG")
        self.response = Mock(status_code=200, content=bytes(buffer.data()))

    def test_shared_memory_and_disk_cache_avoid_repeated_requests_and_decode(self):
        url = "https://example.invalid/shared.png"
        with patch.object(images.requests, "get", return_value=self.response) as fetch, \
                patch.object(images, "_load_one", wraps=images._load_one) as load:
            self.assertIsNotNone(images.load_pixmap(url, "emoticons"))
            self.assertIsNotNone(images.load_pixmap(url, "emoticons"))
            self.assertEqual(load.call_count, 1)
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(Path(images._cache_path(url, "emoticons")).is_file())
            images._EMOTICON_IMAGES.clear()
            images._EMOTICON_BYTES = 0
            self.assertIsNotNone(images.load_pixmap(url, "emoticons"))
            self.assertEqual(load.call_count, 2)
            self.assertEqual(fetch.call_count, 1, "重启后仍应从磁盘读取")

    def test_concurrent_same_image_requests_are_coalesced(self):
        def fetch(*args, **kwargs):
            time.sleep(.05)
            return self.response
        with patch.object(images.requests, "get", side_effect=fetch) as get:
            with ThreadPoolExecutor(max_workers=6) as pool:
                loaded = list(pool.map(lambda _: images.load_pixmap(
                    "https://example.invalid/concurrent.png", "emoticons"), range(6)))
        self.assertTrue(all(pixmap is not None for pixmap in loaded))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(images._EMOTICON_PENDING, {})

    def test_failure_is_not_cached_and_lru_has_a_memory_limit(self):
        url = "https://example.invalid/retry.png"
        with patch.object(images.requests, "get", side_effect=[Mock(status_code=503), self.response]) as fetch:
            self.assertIsNone(images.load_pixmap(url, "emoticons"))
            self.assertIsNotNone(images.load_pixmap(url, "emoticons"))
            self.assertEqual(fetch.call_count, 2)
        images._EMOTICON_IMAGES.clear()
        images._EMOTICON_BYTES = 0
        with patch.object(images, "_EMOTICON_CACHE_LIMIT", 1024), \
                patch.object(images.requests, "get", return_value=self.response) as fetch:
            for name in ("first", "second", "first"):
                self.assertIsNotNone(images.load_pixmap(f"https://example.invalid/{name}.png", "emoticons"))
            self.assertLessEqual(images._EMOTICON_BYTES, 1024)
            self.assertEqual(len(images._EMOTICON_IMAGES), 1)
            self.assertEqual(fetch.call_count, 2)


class EmoticonTabTests(unittest.TestCase):
    def setUp(self):
        emoticon_order.load({})
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

    def test_drag_reorders_without_sending_and_shares_persistent_category_order(self):
        packs = [package('drag', 8), package('other', 2, 2)]
        for pack in packs:
            for emote in pack['emoticons']:
                emote.pop('url')
        self.popup.set_packages(packs)
        settle(lambda: len(self.popup._buttons) == 8)
        APP.processEvents()
        selected = []
        self.popup.selected.connect(lambda *args: selected.append(args))
        source = self.popup._buttons[0]
        target = self.popup._buttons[3]
        destination = target.mapToGlobal(target.rect().center())
        QTest.mousePress(source, Qt.LeftButton, pos=source.rect().center())
        event = QMouseEvent(QEvent.MouseMove, QPointF(source.mapFromGlobal(destination)),
                            QPointF(destination), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        APP.sendEvent(source, event)
        self.assertIs(self.popup._drag_button, source)
        self.assertEqual(self.popup._buttons.index(source), 3)
        self.assertTrue(self.popup._animations, '让位应沿用关注栏的位置动效')
        QTest.mouseRelease(source, Qt.LeftButton, pos=source.rect().center())
        self.assertEqual(selected, [], '拖动释放不能发送表情')
        self.assertTrue(self.popup.isVisible())
        QTest.qWait(180)
        for index, button in enumerate(self.popup._buttons):
            self.assertEqual(button.geometry().center(), self.popup.grid.cellRect(index // 5, index % 5).center())
        expected = ['drag_1', 'drag_2', 'drag_3', 'drag_0', 'drag_4', 'drag_5', 'drag_6', 'drag_7']
        self.assertEqual(emoticon_order.orders['3:drag'], expected)
        # The API objects must retain their original order/permission metadata.
        self.assertEqual(packs[0]['emoticons'][0]['emoticon_unique'], 'drag_0')
        import json
        restored = EmoticonOrder()
        restored.load(json.loads(json.dumps(emoticon_order.orders)))
        self.assertEqual([restored.key(e) for e in restored.arrange('3:drag', packs[0]['emoticons'])], expected)
        self.assertEqual([restored.key(e) for e in restored.arrange('2:other', packs[1]['emoticons'])], ['other_0', 'other_1'])
        self.popup.tabs.setCurrentIndex(1)
        self.popup.tabs.setCurrentIndex(0)
        settle(lambda: len(self.popup._buttons) == 8)
        self.assertEqual([e['emoticon_unique'] for e in self.popup._emotes], expected)
        second = EmoticonPopup()
        try:
            second.set_packages(packs)
            self.assertEqual([e['emoticon_unique'] for e in second._emotes], expected)
        finally:
            second.deleteLater()

    def test_order_handles_new_missing_and_invalid_saved_entries(self):
        order = EmoticonOrder()
        order.load({'pack': ['b', 'missing', 'b', 'a'], 'bad': [1]})
        emotes = [{'emoji': name, 'perm': 0} for name in ('a', 'new', 'b')]
        self.assertEqual([e['emoji'] for e in order.arrange('pack', emotes)], ['b', 'a', 'new'])
        self.assertNotIn('bad', order.orders)
        self.assertEqual(emotes[0]['perm'], 0)

    def test_drag_through_popup_window_routes_pointer_to_original_button(self):
        pack = package('window-drag', 12)
        for emote in pack['emoticons']:
            emote.pop('url')
        self.popup.set_packages([pack])
        settle(lambda: len(self.popup._buttons) == 12)
        APP.processEvents()
        source, target = self.popup._buttons[0], self.popup._buttons[4]
        origin = source.mapTo(self.popup, source.rect().center())
        destination = target.mapTo(self.popup, target.rect().center())
        selected = []
        self.popup.selected.connect(lambda *args: selected.append(args))
        handle = self.popup.windowHandle()
        QTest.mousePress(handle, Qt.LeftButton, pos=origin)
        for step in range(1, 11):
            QTest.mouseMove(handle, origin + (destination - origin) * step / 10, delay=10)
        QTest.mouseRelease(handle, Qt.LeftButton, pos=destination)
        APP.processEvents()
        self.assertEqual(self.popup._buttons.index(source), 4)
        self.assertEqual(selected, [])
        self.assertTrue(self.popup.isVisible())

    def test_reopening_cached_menu_preserves_widgets_positions_and_scroll(self):
        anchor = QToolButton()
        anchor.move(500, 500)
        anchor.show()
        self.addCleanup(anchor.close)
        self.popup.open_at(anchor)
        pack = package('reopen', 40)
        for emote in pack['emoticons']:
            emote.pop('url')
        self.popup.set_packages([pack])
        settle(lambda: len(self.popup._buttons) == 40)
        APP.processEvents()
        original_body = self.popup.scroll.widget()
        original_buttons = list(self.popup._buttons)
        original_positions = [button.pos() for button in original_buttons]
        self.popup.scroll.verticalScrollBar().setValue(80)
        for _ in range(5):
            self.popup.hide()
            self.popup.open_at(anchor)
            APP.processEvents()
            self.assertIs(self.popup.scroll.widget(), original_body)
            self.assertEqual(self.popup._buttons, original_buttons)
            self.assertEqual([button.pos() for button in self.popup._buttons], original_positions)
            self.assertEqual(self.popup.scroll.verticalScrollBar().value(), 80)

    def test_native_category_drag_preserves_current_cells_and_global_order(self):
        packs = [package('first', 4), package('second', 4, 2), package('third', 4, 5)]
        for pack in packs:
            for emote in pack['emoticons']:
                emote.pop('url')
        self.popup.set_packages(packs)
        settle(lambda: len(self.popup._buttons) == 4)
        APP.processEvents()
        body, cells = self.popup.scroll.widget(), list(self.popup._buttons)
        tabs = self.popup.tabs
        self.assertTrue(tabs.isMovable())
        origin = tabs.mapTo(self.popup, tabs.tabRect(0).center())
        destination = tabs.mapTo(self.popup, tabs.tabRect(2).center())
        handle = self.popup.windowHandle()
        QTest.mousePress(handle, Qt.LeftButton, pos=origin)
        for step in range(1, 16):
            QTest.mouseMove(handle, origin + (destination - origin) * step / 15, delay=10)
        QTest.mouseRelease(handle, Qt.LeftButton, pos=destination)
        APP.processEvents()
        expected = ['3:first', '2:second', '5:third']
        self.assertNotEqual([tabs.tabData(i) for i in range(tabs.count())], expected)
        current = [tabs.tabData(i) for i in range(tabs.count())]
        self.assertEqual(emoticon_order.orders['_tabs'], current)
        self.assertEqual([emoticon_order.package_key(p) for p in self.popup._packages], current)
        self.assertIs(self.popup.scroll.widget(), body)
        self.assertEqual(self.popup._buttons, cells)
        self.assertEqual(self.popup._category, '3:first')
        other = EmoticonPopup()
        try:
            other.set_packages(packs)
            self.assertEqual([other.tabs.tabData(i) for i in range(other.tabs.count())], current)
        finally:
            other.deleteLater()

    def test_category_order_keeps_absent_room_categories_and_cover_targets(self):
        emoticon_order.load({'_tabs': ['3:first', '2:absent', '2:second']})
        packs = [package('first', 0), package('second', 0, 2)]
        packs[1]['current_cover'] = 'https://example.invalid/second-cover.png'
        self.popup.set_packages(packs)
        self.popup.tabs.moveTab(1, 0)
        self.assertEqual(emoticon_order.orders['_tabs'], ['2:second', '2:absent', '3:first'])
        self.assertEqual(self.popup._covers['https://example.invalid/second-cover.png'], [0])

    def test_dragged_category_cover_is_painted_once_without_original_slot_copy(self):
        self.popup.set_packages([package('red', 0), package('green', 0), package('blue', 0)])
        tabs = self.popup.tabs
        for index, color in enumerate(('#ff0000', '#00ff00', '#0000ff')):
            image = QPixmap(32, 32)
            image.fill(QColor(color))
            tabs.setTabText(index, '')
            tabs.setTabIcon(index, QIcon(image))
        APP.processEvents()

        def red_pixels():
            image = tabs.grab().toImage()
            return sum(image.pixelColor(x, y).red() > 220
                       and image.pixelColor(x, y).green() < 40
                       and image.pixelColor(x, y).blue() < 40
                       for y in range(image.height()) for x in range(image.width()))

        baseline = red_pixels()
        self.assertGreater(baseline, 400)
        origin = tabs.mapTo(self.popup, tabs.tabRect(0).center())
        handle = self.popup.windowHandle()
        QTest.mousePress(handle, Qt.LeftButton, pos=origin)
        try:
            QTest.mouseMove(handle, origin + QPoint(18, 0), delay=30)
            APP.processEvents()
            self.assertTrue(any(isinstance(child, QWidget) and not isinstance(child, QToolButton)
                                and child.isVisible() for child in tabs.children()),
                            '必须检查 Qt 实际创建的拖动图像')
            during = red_pixels()
            self.assertGreaterEqual(during, baseline * .95, '拖动图案不能消失')
            self.assertLessEqual(during, baseline * 1.05, '原位不能残留第二份封面图案')
        finally:
            QTest.mouseRelease(handle, Qt.LeftButton, pos=origin + QPoint(18, 0))
        QTest.qWait(250)
        self.assertEqual(red_pixels(), baseline)

    def test_drag_keeps_lazy_building_and_respects_system_motion_setting(self):
        pack = package('lazy-drag', 600)
        for emote in pack['emoticons']:
            emote.pop('url')
        self.popup.set_packages([pack])
        self.popup._build_timer.stop()
        self.popup._build_batch()
        APP.processEvents()
        source, target = self.popup._buttons[0], self.popup._buttons[4]
        point = target.mapToGlobal(target.rect().center())
        QTest.mousePress(source, Qt.LeftButton, pos=source.rect().center())
        with patch('ddm.danmaku_send.motion.enabled', return_value=False):
            APP.sendEvent(source, QMouseEvent(QEvent.MouseMove, QPointF(source.mapFromGlobal(point)),
                          QPointF(point), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
            self.assertEqual(len(self.popup._buttons), 10)
            self.assertFalse(self.popup._animations)
            QTest.mouseRelease(source, Qt.LeftButton, pos=source.rect().center())
        self.popup._build_batch()
        self.assertEqual(len({e['emoticon_unique'] for e in self.popup._emotes}), 600)
        self.assertEqual(self.popup._buttons[10].text(), '[lazy-drag-10]')

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

    def test_package_tabs_are_equal_squares_before_and_after_cover_load(self):
        packs = [package("emoji", 0), package("主播表情", 0, 2),
                 package("一个名字很长的装扮表情包", 0, 5)]
        for pack in packs[1:]:
            pack["current_cover"] = f"https://example.invalid/{pack['pkg_name']}.png"

        def load(url, subdir):
            self.release.wait(2)
            return self.pixmap

        def sizes():
            APP.processEvents()
            return [(self.popup.tabs.tabRect(i).width(), self.popup.tabs.tabRect(i).height())
                    for i in range(self.popup.tabs.count())]

        with patch.object(images, "load_pixmap", side_effect=load):
            self.popup.set_packages(packs)
            before = sizes()
            self.assertEqual(len(set(before)), 1, "包名长度不应改变分类按钮的尺寸")
            self.assertTrue(all(width == height for width, height in before), "分类入口应是方形")
            self.assertEqual(self.popup.tabs.tabText(0), "表情")
            self.release.set()
            settle(lambda: not _active_requests)
            self.assertFalse(self.popup.tabs.tabIcon(1).isNull())
            self.assertEqual(sizes(), before, "封面逐张加载时不能改变按钮尺寸")

    def test_emoticon_grid_is_centered_as_a_block(self):
        pack = package("emoji", 12)
        for emote in pack["emoticons"]:
            emote.pop("url")
        self.popup.set_packages([pack])
        settle(lambda: len(buttons(self.popup)) == 12)
        for width in (340, 380):
            self.popup._holder.setFixedWidth(width)
            APP.processEvents()
            body = self.popup.scroll.widget()
            first = self.popup.grid.itemAtPosition(0, 0).widget().geometry()
            last = self.popup.grid.itemAtPosition(0, 4).widget().geometry()
            left_gap = first.left()
            right_gap = body.width() - last.right() - 1
            self.assertLessEqual(abs(left_gap - right_gap), 1, "整个五列网格应水平居中")
            self.assertGreater(left_gap, 0)
            self.assertEqual(self.popup.grid.itemAtPosition(2, 0).widget().x(), first.x(),
                             "不足一行时仍与上方网格列对齐")

    def test_cover_pixels_are_centered_in_square_tabs(self):
        marker = QColor("#fe007f")
        packs, covers = [], {}
        for index, (width, height) in enumerate(((48, 48), (64, 32), (32, 64))):
            pack = package(f"封面{index}", 0, 2)
            pack["current_cover"] = f"https://example.invalid/centered-{index}.png"
            pixmap = QPixmap(width, height)
            pixmap.fill(marker)
            covers[pack["current_cover"]] = pixmap
            packs.append(pack)
        with patch.object(images, "load_pixmap", side_effect=lambda url, subdir: covers[url]):
            self.popup.set_packages(packs)
            settle(lambda: all(not self.popup.tabs.tabIcon(i).isNull() for i in range(3)))
            for selected in (0, 2):
                self.popup.tabs.setCurrentIndex(selected)
                APP.processEvents()
                for index in range(3):
                    rendered = self.popup.tabs.grab(self.popup.tabs.tabRect(index)).toImage()
                    points = [(x, y) for x in range(rendered.width()) for y in range(rendered.height())
                              if rendered.pixelColor(x, y) == marker]
                    self.assertTrue(points, "封面必须实际绘制在按钮内")
                    xs, ys = zip(*points)
                    with self.subTest(selected=selected, cover=index):
                        self.assertLessEqual(abs(min(xs) + max(xs) - (rendered.width() - 1)), 2,
                                             "封面可见像素应水平居中")
                        self.assertLessEqual(abs(min(ys) + max(ys) - (rendered.height() - 1)), 2,
                                             "封面可见像素应垂直居中")

    def test_covers_cannot_paint_over_navigation_arrows(self):
        marker = QColor("#fe007f")
        self.pixmap.fill(marker)
        packs = [package(f"分类{index}", 0, 2) for index in range(20)]
        for pack in packs:
            pack["current_cover"] = "https://example.invalid/overflow-cover.png"
        with patch.object(images, "load_pixmap", return_value=self.pixmap):
            self.popup.set_packages(packs)
            settle(lambda: all(not self.popup.tabs.tabIcon(i).isNull() for i in range(20)))
            for selected in (0, 19):
                self.popup.tabs.setCurrentIndex(selected)
                APP.processEvents()
                rendered = self.popup.tabs.grab().toImage()
                ratio = rendered.devicePixelRatio()
                for name in ("ScrollLeftButton", "ScrollRightButton"):
                    arrow = self.popup.tabs.findChild(QToolButton, name)
                    self.assertTrue(arrow.isVisible())
                    rect = arrow.geometry()
                    points = [rendered.pixelColor(x, y)
                              for x in range(round(rect.left() * ratio), round((rect.right() + 1) * ratio))
                              for y in range(round(rect.top() * ratio), round((rect.bottom() + 1) * ratio))]
                    with self.subTest(selected=selected, arrow=name):
                        self.assertFalse(any(pixel == marker for pixel in points), "封面不能覆盖左右滚动箭头")

    def test_package_covers_replace_names_except_emoji_and_reuse_cache(self):
        packs = [package("emoji", 0), package("通用表情", 0, 1),
                 package("主播表情", 0, 2), package("装扮表情", 0, 5)]
        for index, pack in enumerate(packs):
            pack["current_cover"] = f"https://example.invalid/cover-{index}.png"

        def load(url, subdir):
            self.release.wait(2)
            return self.load(url, subdir)

        with patch.object(images, "load_pixmap", side_effect=load):
            self.popup.set_packages(packs)
            self.assertEqual([self.popup.tabs.tabText(i) for i in range(4)],
                             ["表情", "通用表情", "主播表情", "装扮表情"], "先显示包名，再逐张替换封面")
            self.assertTrue(all(self.popup.tabs.tabIcon(i).isNull() for i in range(4)))
            self.release.set()
            settle(lambda: not _active_requests)
            self.assertEqual(self.popup.tabs.tabText(0), "表情")
            self.assertTrue(self.popup.tabs.tabIcon(0).isNull())
            for index, name in ((1, "通用表情"), (2, "主播表情"), (3, "装扮表情")):
                self.assertFalse(self.popup.tabs.tabIcon(index).isNull(), "未选中的表情包也需要封面导航")
                self.assertEqual(self.popup.tabs.tabText(index), "")
                self.assertEqual(self.popup.tabs.tabToolTip(index), name)
                self.assertEqual(self.popup.tabs.accessibleTabName(index), name)
            self.assertEqual({url for url, _ in self.calls}, {
                "https://example.invalid/cover-1.png", "https://example.invalid/cover-2.png",
                "https://example.invalid/cover-3.png"})
            self.popup.tabs.setCurrentIndex(3)
            self.popup.tabs.setCurrentIndex(0)
            self.popup.hide()
            self.popup.show()
            APP.processEvents()
            self.assertEqual(len(self.calls), 3, "切包和重开菜单应复用封面")

    def test_missing_invalid_and_failed_cover_keep_readable_names(self):
        packs = [package(name, 0, 2) for name in ("缺失", "非法", "失败")]
        packs[1]["current_cover"] = {"url": "https://example.invalid/not-a-string.png"}
        packs[2]["current_cover"] = "https://example.invalid/failed-cover.png"
        with patch.object(images, "load_pixmap", return_value=None):
            self.popup.set_packages(packs)
            settle(lambda: not _active_requests)
            self.assertEqual([self.popup.tabs.tabText(i) for i in range(3)], ["缺失", "非法", "失败"])
            self.assertTrue(all(self.popup.tabs.tabIcon(i).isNull() for i in range(3)))

    def test_shared_cover_is_downloaded_once_and_does_not_load_package_contents(self):
        first, second = package("第一包", 2, 2), package("第二包", 2, 5)
        for pack in (first, second):
            pack["current_cover"] = "https://example.invalid/shared-cover.png"
        with patch.object(images, "load_pixmap", side_effect=self.load):
            self.popup.set_packages([package("emoji", 0), first, second])
            settle(lambda: not _active_requests)
            self.assertTrue(all(not self.popup.tabs.tabIcon(i).isNull() for i in (1, 2)))
            self.assertEqual(buttons(self.popup), [])
            self.assertEqual(self.calls, [("https://example.invalid/shared-cover.png", "emoticons")])

    def test_hidden_catalog_defers_cover_download_until_reopen(self):
        pack = package("后台目录", 0, 2)
        pack["current_cover"] = "https://example.invalid/hidden-cover.png"
        with patch.object(images, "load_pixmap", side_effect=self.load):
            self.popup.hide()
            self.popup.set_packages([pack])
            QTest.qWait(30)
            self.assertEqual(self.calls, [])
            self.popup.show()
            settle(lambda: not self.popup.tabs.tabIcon(0).isNull())
            self.assertEqual(self.popup.tabs.tabText(0), "")

    def test_refresh_cannot_apply_old_cover_to_a_new_catalog(self):
        first = package("旧目录", 0, 2)
        second = package("新目录", 0, 2)
        for pack in (first, second):
            pack["current_cover"] = "https://example.invalid/reused-cover.png"

        def load(url, subdir):
            self.calls.append((url, subdir))
            if len(self.calls) == 1:
                self.release.wait(2)
                return self.pixmap
            return None

        with patch.object(images, "load_pixmap", side_effect=load):
            self.popup.set_packages([first])
            settle(lambda: bool(self.calls))
            self.popup.set_loading()
            self.popup.set_packages([second])
            self.release.set()
            settle(lambda: not _active_requests)
            self.assertEqual(len(self.calls), 2)
            self.assertTrue(self.popup.tabs.tabIcon(0).isNull())
            self.assertEqual(self.popup.tabs.tabText(0), "新目录")
            self.assertEqual(self.popup.tabs.tabToolTip(0), "新目录")

    def test_current_icons_load_before_slow_unselected_package_covers(self):
        first = package("emoji", 1)
        second, third = package("第二包", 0, 2), package("第三包", 0, 5)
        for index, pack in enumerate((second, third)):
            pack["current_cover"] = f"https://example.invalid/slow-cover-{index}.png"

        def load(url, subdir):
            self.calls.append((url, subdir))
            if "slow-cover" in url:
                self.release.wait(2)
            return self.pixmap

        with patch.object(images, "load_pixmap", side_effect=load):
            self.popup.set_packages([first, second, third])
            settle(lambda: bool(self.calls))
            self.assertEqual(self.calls[0][0], "https://example.invalid/emoji-0.png",
                             "未选中包的封面不能挡住当前包的图片")
            settle(lambda: len(buttons(self.popup)) == 1 and not buttons(self.popup)[0].icon().isNull())
            self.release.set()
            settle(lambda: not _active_requests)

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
