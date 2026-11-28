"""Built-in Bilibili interaction with offline account and request fixtures."""
from contextlib import ExitStack
import os
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QTextCharFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import bili, config, plugins
from ddm.app import MainWindow
from ddm.bili_interaction.composer import DanmakuComposer
from ddm.bili_interaction.emoticon_order import EmoticonOrder
from ddm.bili_interaction.emoticons import EmoticonPopup
from ddm.bili_interaction.gift_api import GiftItem
from ddm.bili_interaction.gift_controller import GiftController
from ddm.danmaku_widgets import DanmakuPanel

APP = QApplication.instance() or QApplication([])


class BiliPluginBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.saved = bili._cookies()
        self.addCleanup(lambda: bili.set_login_cookies(
            self.saved.get('SESSDATA', ''), self.saved.get('bili_jct', ''),
            self.saved.get('buvid3', '')))
        for method in ('refresh_status', 'refresh_stats', 'refresh_account', 'load_room_avatars'):
            self.stack.enter_context(patch.object(MainWindow, method))
        self.stack.enter_context(patch('ddm.app.QTimer.singleShot'))
        folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-bili-builtin-')))
        self.legacy = folder / 'bili_live' / 'plugin.py'
        self.legacy.parent.mkdir()
        self.legacy.write_text('raise RuntimeError("obsolete plugin was loaded")\n', encoding='utf-8')
        self.legacy.with_name('plugin.json').write_text(json.dumps({
            'id': 'bili_live', 'name': 'B 站直播互动', 'description': '旧版插件', 'version': '1.1',
        }), encoding='utf-8')
        self.stack.enter_context(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(folder)))
        self.window = MainWindow([], [{'room_id': '101', 'live': False}], layout_id='1x1', state={
            'plugins_enabled': [], 'sessdata': 'fake-session', 'bili_jct': 'fake-csrf',
            'buvid3': 'fake-device', 'settings': {'auto_update': False}})
        self.addCleanup(self.window.close)

    def test_legacy_emoticon_order_is_preserved_for_rollback(self):
        orders = {'_tabs': ['standard'], 'room': ['emote-1']}
        self.window.state['emoticon_order'] = orders
        saved = self.window.current_state()['emoticon_order']
        self.assertEqual(saved, orders)
        self.assertIsNot(saved, orders)

    def test_emoticon_order_reads_the_legacy_file_and_saves_in_user_data(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Path(folder) / 'program'
            data = Path(folder) / 'userdata'
            relative = Path('utils/bili_live/emoticon_order.json')
            legacy = program / relative
            legacy.parent.mkdir(parents=True)
            original = {'version': 1, 'orders': {'standard': ['old']}}
            legacy.write_text(json.dumps(original), encoding='utf-8')
            with patch.object(config, 'REPO', str(program)), patch.object(config, 'DATA_ROOT', str(data)), \
                    patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
                order = EmoticonOrder()
                self.assertEqual(order.orders, original['orders'])
                order.save('standard', [{'emoji': 'new'}])
                self.assertEqual(EmoticonOrder().orders['standard'], ['old', 'new'])
            self.assertEqual(json.loads(legacy.read_text(encoding='utf-8')), original)

    def test_acceptance_preserves_original_titlebar_theme_hook(self):
        with patch('ddm.window_fullscreen.sync_titlebar') as sync:
            self.window.refresh_theme()
        sync.assert_called_once_with(self.window)

    def test_builtin_composer_loads_once_and_preserves_the_old_install(self):
        manager = self.window.plugins
        tile = self.window.wall.tiles[0]
        composer, = tile.bottom.findChildren(DanmakuComposer)
        self.assertTrue(composer.supported)
        self.assertTrue(composer.edit.isEnabled())
        self.assertFalse(manager.plugins)
        self.assertFalse(manager.catalog())
        self.assertTrue(self.legacy.is_file())
        manager.enabled.add('bili_live')
        with patch.object(manager, '_load_module') as load:
            manager.load_bili_interaction()
            manager.load()
            load.assert_not_called()
        self.assertEqual(tile.bottom.findChildren(DanmakuComposer), [composer])
        tile.set_room({'room_id': 'huya:101', 'platform': 'huya', 'live': False})
        self.assertFalse(composer.supported)

    def test_builtin_pickers_share_glass_and_use_the_existing_account(self):
        window = self.window
        window.resize(1020, 700)
        tile = window.wall.tiles[0]
        composer, = tile.bottom.findChildren(DanmakuComposer)
        self.assertEqual(composer.session.snapshot().values['SESSDATA'], 'fake-session')
        window.show()
        APP.processEvents()
        with patch.object(composer, '_start_request') as start, \
                patch.object(composer.catalog_cache, 'load', return_value=None), \
                patch.object(GiftController, 'load') as gifts:
            composer.emote_button.click()
            self.assertTrue(composer.popup.isVisible())
            start.assert_called_once()
            composer.gift_button.click()
            self.assertTrue(composer.gift_popup.isVisible())
            gifts.assert_called_once()
            quantity = composer.gift_popup.quantity_popup
            quantity.set_item(GiftItem('main:1', 'main', 1, '测试礼物', 100, '', '', (1,), 1, False, ''), 100)
            quantity.show()
            for popup in (composer.popup, composer.gift_popup, quantity):
                self.assertTrue(popup.property('playbackGlassPopup'))
                for enabled, opacity, expected in ((True, 0, 214), (True, 100, 255), (False, 0, 255)):
                    window.settings.update(settings_glass_enabled=enabled, settings_glass_opacity=opacity)
                    image = popup.grab().toImage()
                    self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                    self.assertEqual(image.pixelColor(image.width() // 2, 4).alpha(), expected)

    def test_emoticon_picker_keeps_larger_cells_clickable_and_scrollable(self):
        tile = self.window.wall.tiles[0]
        composer, = tile.bottom.findChildren(DanmakuComposer)
        popup = EmoticonPopup(composer, order=EmoticonOrder())
        self.addCleanup(popup.shutdown)
        image = QImage(160, 80, QImage.Format_ARGB32)
        image.fill(Qt.magenta)
        url = 'https://example.invalid/sticker.png'
        emotes = [{'emoji': f'[表情{i}]', 'perm': int(i != 1), 'url': url} for i in range(17)]
        selected = []
        popup.selected.connect(lambda kind, emote: selected.append((kind, emote)))
        with patch('ddm.bili_interaction.emoticons._load_image', return_value=image):
            self.window.show()
            APP.processEvents()
            popup.open_at(composer.emote_button)
            popup.set_packages([{'pkg_type': 3, 'pkg_id': 1, 'emoticons': emotes}])
            popup.tabs.setCurrentIndex(1)
            for _ in range(100):
                if len(popup._buttons) == len(emotes) and not popup._buttons[-1].icon().isNull():
                    break
                QTest.qWait(10)
        buttons = popup._buttons
        self.assertEqual(len(buttons), len(emotes))
        first = buttons[0]
        self.assertEqual(first.size().toTuple(), (84, 84))
        self.assertEqual(first.iconSize().toTuple(), (64, 64))
        self.assertEqual(first.icon().actualSize(first.iconSize()).toTuple(), (64, 32))
        self.assertEqual(popup.grid.getItemPosition(popup.grid.indexOf(buttons[4]))[:2], (1, 0))
        self.assertEqual(popup.scroll.horizontalScrollBar().maximum(), 0)
        self.assertFalse(buttons[1].isEnabled())
        self.assertGreater(popup.scroll.verticalScrollBar().maximum(), 0)

        target = buttons[4].mapToGlobal(buttons[4].rect().center())
        QTest.mousePress(first, Qt.LeftButton, pos=first.rect().center())
        APP.sendEvent(first, QMouseEvent(QEvent.MouseMove, QPointF(first.mapFromGlobal(target)), QPointF(target),
                                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        QTest.mouseRelease(first, Qt.LeftButton, pos=first.mapFromGlobal(target))
        self.assertIs(popup._buttons[4], first)
        self.assertEqual(selected, [])

        popup.hide()
        popup._holder_size = QSize(310, popup._holder_size.height())
        popup.open_at(composer.emote_button)
        popup.tabs.setCurrentIndex(1)
        for _ in range(100):
            if len(popup._buttons) == len(emotes):
                break
            QTest.qWait(10)
        buttons = popup._buttons
        self.assertEqual(popup.grid.getItemPosition(popup.grid.indexOf(buttons[4]))[:2], (1, 1))
        self.assertEqual(popup.scroll.horizontalScrollBar().maximum(), 0)
        popup.scroll.ensureWidgetVisible(buttons[-1])
        self.assertTrue(popup.scroll.viewport().rect().contains(
            buttons[-1].mapTo(popup.scroll.viewport(), buttons[-1].rect().center())))
        QTest.mouseClick(buttons[-1], Qt.LeftButton, pos=buttons[-1].rect().center() + QPoint(36, 0))
        self.assertEqual(selected, [(3, emotes[-1])])

    def test_danmaku_panel_enlarges_inline_and_standalone_emoticons(self):
        panel = DanmakuPanel()
        self.addCleanup(panel.close)
        panel.resize(240, 380)
        panel.show()
        url = 'https://example.invalid/sticker.png'
        pixmap = QPixmap(80, 40)
        pixmap.fill(Qt.magenta)
        with patch.object(panel, '_ensure_emoticon'):
            panel.add_event({'uname': '测试', 'text': '前缀[表情]后缀', 'emoticons': {'[表情]': url}})
            panel.add_event({'uname': '测试', 'text': '[表情]', 'emoticon': url})
            panel.add_event({'uname': '测试', 'text': '普通弹幕'})
            self.assertIn('[表情]', panel.body.toPlainText())
            panel._on_emoticon_loaded(url, pixmap)
        for font_size, height in ((13, 48), (8, 38), (20, 62)):
            panel.apply_style('', font_size)
            rendered = panel.body.toHtml()
            self.assertEqual(rendered.count(f'width="{2 * height}"'), 2)
            self.assertIn('前缀', panel.body.toPlainText())
            self.assertIn('后缀', panel.body.toPlainText())
            self.assertEqual(panel.body.horizontalScrollBar().maximum(), 0)
        block = panel.body.document().begin()
        self.assertEqual(block.blockFormat().lineHeight(), 120)
        self.assertEqual(panel.body.document().lastBlock().blockFormat().lineHeight(), 150)
        fragment = block.begin()
        while not fragment.atEnd() and not fragment.fragment().charFormat().isImageFormat():
            fragment += 1
        self.assertFalse(fragment.atEnd())
        image_format = fragment.fragment().charFormat().toImageFormat()
        self.assertEqual(image_format.verticalAlignment(), QTextCharFormat.AlignMiddle)
        self.assertEqual(image_format.maximumWidth().rawValue(), 100)
        panel.resize(160, 380)
        panel.apply_style('', 32)
        APP.processEvents()
        self.assertLess(panel.body.viewport().width(), 172)
        self.assertEqual(panel.body.horizontalScrollBar().maximum(), 0)

    def test_cookie_restoration_room_and_fullscreen_without_plugin(self):
        self.assertEqual(bili._cookies(), {'SESSDATA': 'fake-session',
            'bili_jct': 'fake-csrf', 'buvid3': 'fake-device'})
        tile = self.window.wall.tiles[0]
        for room in ({'room_id': '202', 'live': False}, {}, {'room_id': '303', 'live': False}):
            tile.set_room(room)
            self.assertEqual(tile.room.get('room_id'), room.get('room_id'))
            self.assertTrue(tile.danmaku_settings_button.isEnabled())
        self.window._on_fullscreen(tile)
        self.window._exit_fullscreen()
        self.assertIsNone(self.window._fullscreen_tile)
        saved = self.window.current_state()
        self.assertEqual((saved['sessdata'], saved['bili_jct'], saved['buvid3']),
                         ('fake-session', 'fake-csrf', 'fake-device'))

    def test_current_platform_codec_and_legacy_sender_apis_survive(self):
        class Legacy(plugins.Platform):
            def play_url(self, room_id, quality=250):
                return ('https://example.invalid/live', quality, 'fixture')
        platform = Legacy()
        self.assertEqual(platform.play_url_for_codec('1'),
                         ('https://example.invalid/live', 250, 'fixture', {}, ''))
        with self.assertRaises(plugins.StreamCodecUnavailable):
            platform.play_url_for_codec('1', codec='hevc')
        self.assertTrue(callable(plugins.PluginContext.register_danmaku_sender))


if __name__ == '__main__':
    unittest.main()
