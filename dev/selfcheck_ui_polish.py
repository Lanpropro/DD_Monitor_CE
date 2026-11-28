"""Offline regressions for badge edges, history navigation, scaling and tile menus."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QStyle, QStyleOptionButton, QStyleOptionSlider, QWidget
from ddm import config, theme
from ddm.dialogs import DanmakuSettingsPage, TraySettingsPage
from ddm.playback_badges import StreamBadge, TitleBadge
from ddm.playback_controls import TileButton
from ddm.super_chat import sc_placement_rects
from ddm.tile_menu import MENU_ITEMS, menu_choices
from ddm.video_danmaku import VideoDanmaku
from ddm.viewport_scale import scale_curve_points, viewport_scale
from ddm.ui import ScaleCurveControl
from ddm.widgets import DanmakuPanel, Tile

APP = QApplication.instance() or QApplication([])


class UiPolishTests(unittest.TestCase):
    def test_modal_chrome_and_file_chooser(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox
        from ddm.window_chrome import WindowTitleBar

        theme.apply(theme.mode())
        observations = []

        def cancel():
            dialog = APP.activeModalWidget()
            bar = dialog.findChild(WindowTitleBar, 'WindowTitleBar', Qt.FindDirectChildrenOnly)
            observations.append((bool(dialog.windowFlags() & Qt.FramelessWindowHint),
                                 bar.breadcrumb.text() if bar and bar.isVisible() else '',
                                 dialog.contentsRect().top() >= bar.height() if bar else False))
            if bar:
                QTest.mouseClick(bar.close_button, Qt.LeftButton)
            else:
                dialog.reject()

        QTimer.singleShot(0, cancel)
        _, accepted = QInputDialog.getText(None, '重命名文件夹', '文件夹名称')
        self.assertFalse(accepted)
        QTimer.singleShot(0, cancel)
        result = QMessageBox.question(None, '删除布局', '删除示例？', QMessageBox.Yes | QMessageBox.No)
        self.assertEqual(result, QMessageBox.No)
        self.assertEqual(observations, [(True, '重命名文件夹', True), (True, '删除布局', True)])
        for dialog in (QFileDialog(), QDialog(None, Qt.Dialog | Qt.FramelessWindowHint)):
            self.addCleanup(dialog.deleteLater)
            flags = dialog.windowFlags()
            dialog.ensurePolished()
            self.assertEqual(dialog.windowFlags(), flags)
            self.assertIsNone(dialog.findChild(WindowTitleBar))
            if isinstance(dialog, QFileDialog):
                self.assertFalse(dialog.testOption(QFileDialog.DontUseNativeDialog))

    def test_workspace_detach_embed_and_reopen_title_bar(self):
        from ddm.window_chrome import WindowTitleBar
        theme.apply(theme.mode())
        host = QWidget()
        page = QWidget(host)
        page.setWindowTitle('独立工作区')
        host.show()
        self.addCleanup(host.close)
        self.addCleanup(page.close)
        page.show()
        for _ in range(2):
            page.setParent(None, Qt.Window)
            page.show()
            APP.processEvents()
            bars = page.findChildren(WindowTitleBar, options=Qt.FindDirectChildrenOnly)
            self.assertEqual(len(bars), 1)
            bar = bars[0]
            self.assertTrue(page.windowFlags() & Qt.FramelessWindowHint)
            self.assertTrue(bar.isVisible())
            self.assertEqual(bar.width(), page.width())
            self.assertEqual(page.contentsMargins().top(), bar.height())
            handle = page.windowHandle()
            with patch.object(handle, 'startSystemMove', return_value=True) as move:
                QTest.mouseClick(bar, Qt.LeftButton, pos=QPoint(24, bar.height() // 2))
                move.assert_called_once_with()
            with patch.object(handle, 'startSystemResize', return_value=True) as resize:
                QTest.mouseClick(page, Qt.LeftButton, pos=page.rect().bottomRight())
                resize.assert_called_once_with(Qt.BottomEdge | Qt.RightEdge)
            page.setWindowTitle('工作区')
            self.assertEqual(bar.breadcrumb.text(), page.windowTitle())
            page.setParent(host, Qt.Widget)
            page.show()
            APP.processEvents()
            self.assertFalse(bar.isVisible())
            self.assertEqual(page.contentsMargins().top(), 0)

    def assert_pointer_feedback(self, button):
        window = button.window()
        window.show()
        window.raise_()
        APP.processEvents()
        parent = button.parentWidget()
        while parent:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(button)
            parent = parent.parentWidget()
        APP.processEvents()
        area = QRect(button.mapTo(window, QPoint()), button.size())
        handle = window.windowHandle()
        away = QPoint(10, 10) if not area.contains(QPoint(10, 10)) else window.rect().bottomRight()

        def pixels():
            APP.processEvents()
            return window.grab(area).toImage().convertToFormat(QImage.Format_RGBA8888)

        QTest.mouseMove(handle, area.center())
        QTest.mouseMove(handle, away)
        normal = pixels()
        self.assertFalse(button.underMouse())
        QTest.mouseMove(handle, area.center())
        hover = pixels()
        self.assertTrue(button.underMouse(), (button, area, window.childAt(area.center()), button.visibleRegion()))
        QTest.mousePress(handle, Qt.LeftButton, pos=area.center())
        pressed = pixels()
        cancel = QPoint(area.center().x(), area.top() - 2)
        QTest.mouseMove(handle, cancel)
        QTest.mouseRelease(handle, Qt.LeftButton, pos=cancel)
        for phase, before, after in (('hover', normal, hover), ('press', hover, pressed)):
            self.assertEqual(before.size(), after.size())
            changed = sum(abs(a - b) >= 8 for a, b in zip(before.constBits(), after.constBits()))
            self.assertGreater(changed, 40, (phase, button.accessibleName() or button.text()))
            if button.objectName() in ('IconReset', 'IconClose', 'IconDropArea'):
                for x in (0, after.width() - 1):
                    for y in (0, after.height() - 1):
                        self.assertEqual(before.pixel(x, y), after.pixel(x, y),
                                         (button.objectName(), phase, x, y))

    def test_reported_controls_show_hover_and_press_in_both_selection_states(self):
        from ddm.folder_icons import FolderIconDialog
        from ddm.layout_picker import LayoutPicker
        from ddm.room_choice import RoomChoice
        from ddm.settings_streamer_defaults import StreamerDefaultsPage
        from ddm.settings_window import SettingsWindow
        from ddm.super_chat_model import normalize as normalize_sc
        from ddm.super_chat_widgets import SuperChatCard
        from ddm.ui.color_dialog import ColorDialog
        from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout

        self.addCleanup(theme.apply, theme.mode())
        for mode in ('dark', 'light'):
            theme.apply(mode)
            settings = SettingsWindow()
            search = QLineEdit(objectName='Search')
            settings.window_header.set_search(search)
            settings.window_header.close_button.setFocus()
            self.assert_pointer_feedback(search)
            self.assertTrue(search.hasFocus())
            settings.hide()
            folder = FolderIconDialog(dict(name='示例', type='normal'))
            colors = ColorDialog(QColor('#ffd16a'))
            picker = LayoutPicker('2x2')
            page = StreamerDefaultsPage(dict(streamer_defaults={'100': {}}), {'100': '示例'})
            page.resize(760, 600)
            avatar = next(iter(page.cards.values())).avatars['100']
            card = SuperChatCard()
            card.resize(250, 118)
            event = normalize_sc(dict(id='1', uname='示例', price=1000, message='示例留言'))
            card.set_event(event)
            video = VideoDanmaku()
            video.resize(800, 450)
            video.set_enabled(True)
            video.set_active(True)
            video.show()
            video.set_super_chats([event])
            self.assert_pointer_feedback(video.super_chat_overlay.close_button)
            video.close()
            owner = QWidget()
            room = RoomChoice(dict(room_id='100'), '示例', 0, None, owner, compact=True)
            QVBoxLayout(owner).addWidget(room)
            layout_card = next(b for buttons in picker._cards.values() for b in buttons if b.isChecked())

            for button in (*folder.choices, folder.drop_area, folder.findChild(QPushButton, 'IconReset'),
                           folder.findChild(QPushButton, 'IconClose'), card.close_button, room, avatar,
                           colors.swatch_palette.buttons['#ffffff'], colors.swatch_palette.buttons['custom'], layout_card):
                for selected in ((False, True) if button.isCheckable() else (False,)):
                    with self.subTest(mode=mode, button=button.accessibleName() or button.text(), selected=selected):
                        button.setChecked(selected)
                        self.assert_pointer_feedback(button)
                button.window().hide()
            for window in (settings, folder, colors, picker, page, card, owner, video):
                window.deleteLater()
            APP.processEvents()

    def test_selected_and_unselected_press_feedback_on_segments_and_follow_markers(self):
        from ddm.sidebar_item import NavItem
        from ddm.ui import SegmentedControl

        group = SegmentedControl((('dark', '深色'), ('light', '浅色')))
        item = NavItem(dict(room_id='100', uname='示例'), 0)
        item.set_select_mode(True)
        for window in (group, item):
            self.addCleanup(window.deleteLater)
            self.addCleanup(window.close)
        for selected in (False, True):
            item.check.setChecked(selected)
            self.assert_pointer_feedback(item.check)
            group.setValue('light' if selected else 'dark')
            for sliding in (False, True):
                with self.subTest(selected=selected, sliding=sliding), \
                        patch('ddm.settings_material.segment_motion_enabled', return_value=sliding), \
                        patch('ddm.motion.enabled', return_value=True):
                    self.assert_pointer_feedback(group.buttons['light'])
                    self.assertEqual(group.buttons['light'].isChecked(), selected)

    def test_badges_keep_alpha_edges_without_integer_masks(self):
        owner = QWidget()
        self.addCleanup(owner.deleteLater)
        for mode in ('dark', 'light'):
            theme.apply(mode)
            for badge in (StreamBadge(owner), TitleBadge(owner)):
                if isinstance(badge, TitleBadge):
                    badge.set_text('Fixture', 'Title')
                badge.refresh_theme()
                self.assertTrue(badge.mask().isEmpty())
                for dpr in (1, 1.25, 1.5, 2):
                    image = QImage(round(badge.width()*dpr), round(badge.height()*dpr), QImage.Format_ARGB32_Premultiplied)
                    image.setDevicePixelRatio(dpr)
                    image.fill(Qt.transparent)
                    painter = QPainter(image)
                    badge._render_badge(painter)
                    painter.end()
                    self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                    self.assertTrue(any(0 < image.pixelColor(x, y).alpha() < 255
                                        for x in range(round(8*dpr)) for y in range(round(8*dpr))))

    def test_bottom_button_hover_is_one_symmetric_surface(self):
        button = TileButton('')
        self.addCleanup(button.deleteLater)
        button.setObjectName('TileCtrl')
        button.setProperty('tileButton', True)
        button.setProperty('hovered', True)
        button.setFixedSize(26, 26)
        button.ensurePolished()
        option = QStyleOptionButton()
        button.initStyleOption(option)
        for mode in ('dark', 'light'):
            theme.apply(mode)
            for dpr in (1, 1.5, 2):
                image = QImage(round(26*dpr), round(26*dpr), QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(dpr)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                button._paint_button(painter, option)
                painter.end()
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                center = image.pixelColor(image.width()//2, image.height()//2)
                self.assertAlmostEqual(center.alphaF(), .15, delta=.01)
                for x in range(image.width()//2):
                    for y in range(image.height()):
                        self.assertLessEqual(abs(image.pixelColor(x, y).alpha() -
                                                 image.pixelColor(image.width()-x-1, y).alpha()), 6)

    @unittest.skipUnless(sys.platform == 'win32' and APP.platformName() == 'windows',
                         'Windows child-window alpha uploads required')
    def test_native_badge_alpha_in_both_themes(self):
        owner = QWidget()
        owner.setAttribute(Qt.WA_ShowWithoutActivating)
        owner.setGeometry(-10000, -10000, 600, 100)
        self.addCleanup(owner.deleteLater)
        self.addCleanup(owner.close)
        badges = [StreamBadge(owner), TitleBadge(owner)]
        badges[1].set_text('Fixture', 'Antialiased title')
        for index, badge in enumerate(badges):
            badge.move(index * 200, 20)
            badge.setAttribute(Qt.WA_NativeWindow)
        owner.show()
        for mode in ('dark', 'light', 'dark'):
            theme.apply(mode)
            APP.processEvents()
            for badge in badges:
                badge.refresh_theme()
                badge._paint_layered()
                self.assertTrue(badge._alpha_uploaded)
                self.assertTrue(badge.mask().isEmpty())

    def test_history_button_stays_in_view_after_refresh_and_scroll(self):
        panel = DanmakuPanel()
        self.addCleanup(panel.deleteLater)
        panel.resize(360, 280)
        panel.show()
        APP.processEvents()
        for i in range(70):
            panel.add_message('reader', f'{i} reading history ' * 3)
        APP.processEvents()
        bar = panel.body.verticalScrollBar()
        panel._on_scroll_pressed()
        bar.setValue(bar.maximum() // 2)
        panel._on_scroll_released()
        for i in range(12):
            panel.add_message('new', str(i))
            if i % 3 == 0:
                panel._render_all()  # The same document replacement as an emote arriving.
            APP.processEvents()
            self.assertFalse(panel._follow_tail)
            self.assertTrue(panel.bottom_button.isVisible())
            viewport = panel.body.viewport()
            self.assertTrue(viewport.rect().contains(panel.bottom_button.geometry()))
            self.assertEqual(viewport.height() - panel.bottom_button.geometry().bottom(), 11)
        panel.jump_to_bottom()
        APP.processEvents()
        self.assertTrue(panel.bottom_button.isHidden())

    def test_curve_endpoints_and_live_redraw(self):
        for strength in (0, 35, 50, 100):
            self.assertEqual(viewport_scale(720, strength), 1)
            self.assertLessEqual(viewport_scale(180, strength), viewport_scale(360, strength))
        self.assertEqual(viewport_scale(180, 0), 1)
        self.assertEqual(viewport_scale(180, 100), .25)
        self.assertGreater(viewport_scale(180, 35), .6)
        overlay = VideoDanmaku()
        self.addCleanup(overlay.deleteLater)
        overlay.resize(1280, 180)
        settings = {**config.DEFAULT_SETTINGS, 'video_danmaku_size': 40}
        overlay.apply_settings({**settings, 'video_danmaku_scale_strength': 0})
        self.assertEqual(overlay.font_pixels(), 40)
        overlay.apply_settings({**settings, 'video_danmaku_scale_strength': 100})
        self.assertEqual(overlay.font_pixels(), 10)
        overlay.apply_settings({**settings, 'video_danmaku_scale': False})
        self.assertEqual(overlay.font_pixels(), 40)
        event = {'id': 'test', 'message': 'readable', 'price': 30, 'uname': 'fixture'}
        # SC retains the readable 90% minimum even when the viewport curve is smaller.
        sizes = [sc_placement_rects([event], 1280, 360, scale_with_video=True,
                                   scale_strength=value, collapsed=True)[1] for value in (0, 35, 100)]
        self.assertEqual(sizes[0], 1)
        self.assertEqual(sizes[1:], [.9, .9])
        self.assertIn('video_danmaku_scale_strength', config.VIDEO_DANMAKU_SETTING_KEYS)
        page = DanmakuSettingsPage(config.DEFAULT_SETTINGS)
        self.addCleanup(page.deleteLater)
        points = [[0, .5], [.5, .8], [1, 1], [2, 1.4]]
        page.super_chat_scale_curve.set_curve(points)
        page.video_danmaku_scale_curve.set_curve(points)
        self.assertEqual(page.values()['super_chat_scale_curve'], points)
        self.assertEqual(page.values()['video_danmaku_scale_curve'], points)
        page.reset()
        self.assertEqual(page.values()['super_chat_scale_curve'], scale_curve_points())
        self.assertEqual(page.values()['video_danmaku_scale_curve'], scale_curve_points())
        self.assertEqual(page.super_chat_placement.scale_curve, page.super_chat_scale_curve.curve())

    def test_graph_add_drag_delete_anchor_and_runtime_curve(self):
        control = ScaleCurveControl()
        self.addCleanup(control.deleteLater)
        control.resize(380, 290)
        control.show()
        APP.processEvents()
        graph = control.graph
        points = [[0, .5], [.5, .8], [1, 1], [2, 1.4]]
        control.set_curve(points)
        changes = []
        control.curveChanged.connect(changes.append)
        self.assertEqual(viewport_scale(360, points=points), .8)
        self.assertAlmostEqual(viewport_scale(540, points=points), .9)
        self.assertEqual(viewport_scale(2000, points=points), 1.4)
        before_hover = graph.grab().toImage()
        QTest.mouseMove(graph, graph.point_position(points[1]).toPoint())
        self.assertEqual(graph._readout_index(), 1)
        self.assertIsNone(graph.selected)
        self.assertEqual(control.curve(), points)
        self.assertFalse(changes)
        self.assertNotEqual(graph.grab().toImage(), before_hover)
        start = graph.point_position([.75, .9]).toPoint()
        QTest.mousePress(graph, Qt.LeftButton, pos=start)
        QTest.mouseMove(graph, start-QPoint(0, 15))
        self.assertEqual(graph._readout_index(), 2)
        self.assertEqual(viewport_scale(720, points=control.curve()), 1)
        QTest.mouseRelease(graph, Qt.LeftButton, pos=start-QPoint(0, 15))
        self.assertEqual(len(control.curve()), 5)
        added = control.curve()[2]
        self.assertGreater(added[1], .9)
        self.assertTrue(changes)
        # A settings feedback update during dragging must not reset the gesture.
        original = graph.point_position(added).toPoint()
        QTest.mousePress(graph, Qt.LeftButton, pos=original)
        control.set_curve(control.curve())
        QTest.mouseMove(graph, original-QPoint(0, 8))
        QTest.mouseRelease(graph, Qt.LeftButton, pos=original-QPoint(0, 8))
        self.assertGreater(control.curve()[2][1], added[1])
        QTest.mouseClick(graph, Qt.RightButton, pos=graph.point_position(control.curve()[2]).toPoint())
        self.assertEqual(len(control.curve()), 4)
        anchor = graph.point_position([1, 1]).toPoint()
        QTest.mousePress(graph, Qt.LeftButton, pos=anchor)
        QTest.mouseRelease(graph, Qt.LeftButton, pos=anchor+QPoint(10, 15))
        self.assertIn([1, 1], control.curve())
        QTest.mouseClick(graph, Qt.RightButton, pos=anchor)
        self.assertIn([1, 1], control.curve())
        overlay = VideoDanmaku()
        self.addCleanup(overlay.deleteLater)
        overlay.resize(1280, 360)
        overlay.apply_settings({**config.DEFAULT_SETTINGS, 'video_danmaku_size': 40,
                                'video_danmaku_scale_curve': points})
        self.assertEqual(overlay.font_pixels(), 32)
        event = {'id': 'curve', 'message': 'readable', 'price': 30, 'uname': 'fixture'}
        self.assertEqual(sc_placement_rects([event], 1280, 360, scale_with_video=True,
                                          collapsed=True, scale_curve=points)[1], .9)
        self.assertIn('video_danmaku_scale_curve', config.VIDEO_DANMAKU_SETTING_KEYS)
        tile = Tile({'room_id': 'curve-fixture'})
        self.addCleanup(tile.deleteLater)
        tile.apply_video_danmaku_settings(config.DEFAULT_SETTINGS)
        tile._set_video_danmaku_independent(True)
        tile.danmaku_settings_menu.settingsChanged.emit({'video_danmaku_scale_curve': points})
        self.assertEqual(tile.video_danmaku_overrides['video_danmaku_scale_curve'], points)
        self.assertIsNone(tile._video_danmaku_global_settings['video_danmaku_scale_curve'])
        tile._set_video_danmaku_independent(False)
        self.assertIsNone(tile.video_danmaku.settings['video_danmaku_scale_curve'])
        control.reset()
        self.assertEqual(control.curve(), scale_curve_points())
        image = graph.grab().toImage()
        grid_point = graph.point_position([.4, .4]).toPoint()
        self.assertNotEqual(image.pixelColor(grid_point), theme.qcolor(theme.CONTENT),
                            'An open curve must not fill over the grid below it')

    def test_tile_danmaku_menu_keeps_scale_toggle_without_curve_editor(self):
        from ddm.video_danmaku_settings import VideoDanmakuSettings
        menu = VideoDanmakuSettings()
        self.addCleanup(menu.deleteLater)
        received = []
        menu.settingsChanged.connect(received.append)
        menu.apply_settings(config.DEFAULT_SETTINGS)
        self.assertIsNone(menu.findChild(ScaleCurveControl))
        self.assertFalse(received)
        menu.scale.setChecked(False)
        self.assertEqual(received, [{'video_danmaku_scale': False}])

    def test_tile_danmaku_menu_waits_for_use_and_tracks_theme(self):
        from ddm.video_danmaku_settings import VideoDanmakuSettings
        theme.apply('dark')
        self.addCleanup(theme.apply, 'dark')
        tile = Tile({'room_id': '1'})
        self.addCleanup(tile.deleteLater)
        self.assertIsNone(tile.findChild(VideoDanmakuSettings))
        tile.apply_video_danmaku_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_speed=77, video_danmaku_size=36))
        tile._set_video_danmaku_independent(True)
        theme.apply('light')
        self.assertIsNone(tile.findChild(VideoDanmakuSettings))

        tile.danmaku_settings_button.click()
        menu = tile.danmaku_settings_menu
        self.addCleanup(menu.hide)
        self.assertIs(menu.parentWidget(), tile)
        self.assertTrue(menu.independent.isChecked())
        self.assertEqual(menu.controls['video_danmaku_speed'].value(), 77)
        slider = menu.controls['video_danmaku_size']
        self.assertEqual(slider.value(), 36)
        slider.setValue(40)
        self.assertEqual(tile.video_danmaku.settings['video_danmaku_size'], 40)
        stylesheet = menu.styleSheet()
        for mode in ('light', 'dark', 'light'):
            theme.apply(mode)
            self.assertIs(tile.danmaku_settings_menu, menu)
            self.assertEqual(menu.styleSheet(), stylesheet)
            option = QStyleOptionSlider()
            slider.initStyleOption(option)
            handle = slider.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, slider)
            image = slider.grab().toImage()
            ratio = image.devicePixelRatio()
            y = round(handle.center().y() * ratio)
            self.assertEqual(image.pixelColor(round(handle.center().x() * ratio), y), QColor('#ffffff'))
            accent = theme.mix(theme.ACCENT, '#ffffff', .35) if slider.underMouse() else theme.ACCENT
            self.assertEqual(image.pixelColor(round(handle.center().x() * ratio / 2), y), QColor(accent))

    def test_menu_editor_and_runtime_keep_order_callbacks_and_visibility(self):
        page = TraySettingsPage(config.DEFAULT_SETTINGS)
        self.addCleanup(page.deleteLater)
        editor = page.tile_menu
        page.resize(600, 700)
        page.show()
        APP.processEvents()
        self.assertLess(editor.items.x(), editor.checks['volume'].mapTo(editor, QPoint()).x())
        self.assertTrue(editor.preview.isVisible())
        self.assertLessEqual(editor.preview.width(), 300)
        for mode in ('dark', 'light'):
            theme.apply(mode)
            APP.processEvents()
            image = editor.items.grab().toImage()
            self.assertGreater(image.pixelColor(editor.items.width()//2, 5).alpha(), 0)
            preview = editor.preview.grab().toImage()
            self.assertGreater(preview.pixelColor(editor.preview.width()//2, 5).alpha(), 0)
        rows = dict(editor.items.rows())
        start = rows['volume'].center().toPoint()
        end = QPoint(start.x(), int(rows['quality'].bottom()-1))
        QTest.mousePress(editor.items, Qt.LeftButton, pos=start)
        QTest.mouseMove(editor.items, end)
        QTest.mouseRelease(editor.items, Qt.LeftButton, pos=end)
        self.assertEqual(editor.values()[0]['id'], 'quality')
        editor.checks['quality'].setChecked(False)
        self.assertIn('quality', dict(editor.items.rows()))
        self.assertFalse(editor.checks['quality'].isChecked())
        self.assertNotIn('quality', dict(editor.preview.rows()))
        choices = page.values()['tile_context_menu']
        self.assertEqual(choices[0], {'id': 'quality', 'enabled': False})
        tile = Tile({'room_id': '1'})
        self.addCleanup(tile.deleteLater)
        called = []
        tile.plugin_actions = [('Fixture plugin', lambda: called.append('plugin'))]
        tile.apply_video_danmaku_settings({**config.DEFAULT_SETTINGS, 'tile_context_menu': choices})
        menu = tile.build_menu()
        self.addCleanup(menu.deleteLater)
        actions = [a for a in menu.actions() if not a.isSeparator()]
        self.assertEqual(actions[0].data(), 'volume')
        self.assertNotIn('quality', [a.data() for a in actions])
        next(a for a in actions if a.data() == 'plugins').trigger()
        self.assertEqual(called, ['plugin'])
        muted = tile.muted
        next(a for a in actions if a.data() == 'mute').trigger()
        self.assertEqual(tile.muted, not muted)
        page.reset()
        self.assertEqual([x['id'] for x in page.values()['tile_context_menu']], [x[0] for x in MENU_ITEMS])
        self.assertEqual(len(menu_choices([{'id': 'bad'}, {'id': 'close'}, {'id': 'close'}])), len(MENU_ITEMS))
        tile.setProperty('fullscreen', True)
        fullscreen_menu = tile.build_menu()
        self.addCleanup(fullscreen_menu.deleteLater)
        self.assertNotIn('switch_danmaku', [a.data() for a in fullscreen_menu.actions()])
        tile.apply_video_danmaku_settings({'tile_context_menu': [
            {'id': key, 'enabled': False} for key, _label in MENU_ITEMS]})
        empty_menu = tile.build_menu()
        self.addCleanup(empty_menu.deleteLater)
        self.assertTrue(empty_menu.isEmpty())

    def test_narrow_menu_preview_drag_selection_hidden_rows_and_single_owner(self):
        from ddm.tile_menu import MENU_GROUPS, TileMenuEditor
        editor = TileMenuEditor()
        self.addCleanup(editor.deleteLater)
        editor.setStyleSheet(theme.qss())
        editor.resize(800, 650)
        editor.show()
        APP.processEvents()
        changed = []
        editor.changed.connect(lambda: changed.append(editor.values()))
        self.assertIs(editor.preview.choices, editor._choices)
        self.assertIs(editor.items.choices, editor._choices)
        rows = dict(editor.preview.rows())
        self.assertGreater(rows['volume'].height(), rows['quality'].height())
        for (left, before), (right, after) in zip(editor.preview.rows(), editor.preview.rows()[1:]):
            if MENU_GROUPS[left] != MENU_GROUPS[right]:
                self.assertGreater(after.top(), before.bottom())
        start = rows['reload'].center().toPoint()
        end = rows['quality'].topLeft().toPoint() + QPoint(20, 1)
        QTest.mousePress(editor.preview, Qt.LeftButton, pos=start)
        QTest.mouseMove(editor.preview, end)
        QTest.mouseRelease(editor.preview, Qt.LeftButton, pos=end)
        self.assertEqual(len(changed), 1)
        self.assertEqual(editor.items.selected, 'reload')
        self.assertEqual(editor.preview.selected, 'reload')
        ids = [entry['id'] for entry in editor.values()]
        self.assertLess(ids.index('reload'), ids.index('quality'))
        editor.checks['reload'].click()
        self.assertEqual(len(changed), 2)
        self.assertNotIn('reload', dict(editor.preview.rows()))
        self.assertIn('reload', dict(editor.items.rows()))
        editor.move_item(1)
        self.assertEqual(len(changed), 3)
        self.assertFalse(next(entry for entry in editor.values() if entry['id'] == 'reload')['enabled'])
        editor.set_choices(None)
        self.assertEqual(len(changed), 4)
        self.assertEqual(editor.values(), menu_choices(None))
        editor.set_choices([{'id': key, 'enabled': False} for key, _label in MENU_ITEMS])
        self.assertEqual(editor.preview.rows(), [])
        self.assertFalse(editor.preview.grab().isNull())
        self.assertEqual(len(editor.items.rows()), len(MENU_ITEMS))

    def test_menu_and_curves_round_trip_without_touching_real_settings(self):
        settings = {**config.DEFAULT_SETTINGS,
                    'tile_context_menu': list(reversed(menu_choices(None))),
                    'super_chat_scale_strength': 17, 'video_danmaku_scale_strength': 29,
                    'super_chat_scale_curve': [[0, .4], [1, 1], [2, 1.5]],
                    'video_danmaku_scale_curve': [[0, .6], [1, 1], [2, 1.4]]}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(config, 'CONFIG_PATH', str(Path(directory)/'config.json')), patch.dict(os.environ):
                os.environ.pop('DDM_NO_SAVE', None)
                config.save({'version': 1, 'settings': settings})
                loaded = config.load()['settings']
        for key in ('tile_context_menu', 'super_chat_scale_strength', 'video_danmaku_scale_strength',
                    'super_chat_scale_curve', 'video_danmaku_scale_curve'):
            self.assertEqual(loaded[key], settings[key])


if __name__ == '__main__':
    APP.setStyleSheet(theme.qss())
    unittest.main()
