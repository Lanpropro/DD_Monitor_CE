"""Hidden sidebar layout/account contracts; fake identities, no browser, network or media."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import QApplication, QBoxLayout, QLayout, QPushButton, QWidgetAction
from shiboken6 import isValid
from ddm import config, images, motion, theme
from ddm import sidebar_widgets as module
from ddm.account_widgets import AccountRow
from ddm.avatar_widgets import RoomStrip
from ddm.capture_control import CaptureControl
from ddm.sidebar_account_control import SidebarAccountControl
from ddm.sidebar_presentation import SidebarPresentation
from ddm.sidebar_navigation import RAIL_WIDTH
from ddm.widget_support import NAV_COMPACT_ITEM_HEIGHT, NAV_ITEM_GAP, NAV_ITEM_HEIGHT


class SidebarPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-sidebar-presentation-'))
        self.stack.enter_context(patch.object(config, 'DATA_ROOT', directory))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')))
        self.stack.enter_context(patch.object(images, 'REPO', directory))
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.sidebar = module.Sidebar([{'room_id': 'fixture:1', 'uname': 'Fixture', 'live': False}],
            auto_compact=False)

    def tearDown(self):
        if isValid(self.sidebar):
            self.sidebar.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def test_tool_reordering_invalidates_removed_layout_items(self):
        navigation = self.sidebar.navigation
        items = [navigation.bottom.itemAt(index) for index in range(navigation.bottom.count())]
        navigation.restore_order(['pip', 'clear', 'layout'])
        current = [navigation.bottom.itemAt(index) for index in range(navigation.bottom.count())]
        self.assertEqual([widget.kind for widget in navigation.movable_tools()], ['pip', 'clear', 'layout'])
        for item in items:
            self.assertTrue(not isValid(item) or item in current,
                            'Removed C++ layout items must not keep valid Python wrappers')
        retained = list(current)
        navigation.restore_order(['pip', 'clear', 'layout'])
        self.assertEqual(retained, [navigation.bottom.itemAt(index) for index in range(navigation.bottom.count())])

    def test_follow_avatar_ring_tracks_recording_off_wall_in_cards_and_strip(self):
        sidebar = self.sidebar
        room, = sidebar._items
        control = sidebar.items_control
        sidebar.resize(sidebar.width(), 720)
        sidebar.setStyleSheet(theme.qss())
        sidebar.show()
        self.app.processEvents()
        avatar = room.thumb.face
        self.assertEqual(avatar.recording_state, '')
        control.set_monitored_rooms({'fixture:1', 'fixture:2'})
        self.assertEqual(avatar.recording_state, 'monitoring')
        self.assertTrue(avatar.isVisible())
        self.assertFalse(room.property('onWall'))
        self.assertFalse(room.room['live'])
        self.assertIsNone(avatar._ripple_timer)
        self.assertIsNone(room.thumb.findChild(module.QLabel, 'BadgeAutoRecord'))

        def avatar_pixel(dx):
            image = avatar.grab().toImage()
            scale = image.devicePixelRatio()
            return image.pixelColor(round((avatar.width() - avatar.ring_margin + dx) * scale),
                                    round(avatar.height() / 2 * scale))

        ready = avatar_pixel(avatar.RING_GAP)
        self.assertLess(ready.red(), ready.blue())
        self.assertEqual(avatar_pixel(1).alpha(), 0, '头像和圆环之间有独立的透明间隙')
        room.set_live(True)
        session = SimpleNamespace(room_id='fixture:1', recording=True, stopping=False, started_at=0)
        capture = CaptureControl(SimpleNamespace(sidebar=sidebar, recorder=SimpleNamespace(sessions={room: session})))
        capture.sync_follow_recording_states()
        self.assertEqual(avatar.recording_state, 'monitoring')
        session.started_at = 1
        with patch.object(motion, 'enabled', return_value=True):
            capture.sync_follow_recording_states()
            self.assertEqual(avatar.recording_state, 'recording')
            self.assertTrue(avatar._ripple_timer.isActive())
            red = avatar_pixel(avatar.RING_GAP)
            self.assertGreater(red.red(), red.blue())
            with patch.object(avatar, '_ripple_clock', SimpleNamespace(elapsed=lambda: 100)):
                early = avatar.grab().toImage()
            with patch.object(avatar, '_ripple_clock', SimpleNamespace(elapsed=lambda: 800)):
                self.assertNotEqual(early, avatar.grab().toImage())
        avatar.hide()
        self.assertFalse(avatar._ripple_timer.isActive())
        avatar.show()
        self.assertFalse(avatar._ripple_timer.isActive())
        self.assertEqual(avatar.recording_state, 'recording')
        static_red = avatar_pixel(avatar.RING_GAP)
        self.assertGreater(static_red.red(), static_red.blue())
        sidebar.set_compact_policy(False, False, 18)
        self.app.processEvents()
        self.assertTrue(avatar.isVisible())
        room.set_compact(True)
        self.assertTrue(avatar.isVisible())
        self.app.processEvents()
        self.assertTrue(room.rect().contains(avatar.geometry()))
        room.set_compact(False)
        sidebar.set_side('top')
        self.app.processEvents()
        self.assertTrue(avatar.isVisible())
        sidebar.set_collapsed(True, animate=False)
        self.app.processEvents()
        strip_avatar = sidebar._head_strip._avatars['fixture:1']
        self.assertEqual(strip_avatar.recording_state, 'recording')
        session.stopping = True
        capture.sync_follow_recording_states()
        self.assertEqual(strip_avatar.recording_state, 'monitoring')
        self.assertEqual(avatar.recording_state, 'monitoring')
        new = sidebar._append_item({'room_id': 'fixture:2', 'uname': 'Second', 'live': False})
        self.assertEqual(new.thumb.face.recording_state, 'monitoring')
        control.set_monitored_rooms(set())
        self.assertEqual(avatar.recording_state, '')
        self.assertEqual(new.thumb.face.recording_state, '')

    def test_monitor_only_avatar_animates_in_both_collapsed_follow_views(self):
        sidebar = self.sidebar
        settings = {'streamer_defaults': {'fixture:1': {'monitor_live': True}}}
        capture = CaptureControl(SimpleNamespace(sidebar=sidebar, settings=settings))
        sidebar.resize(sidebar.width(), 720)
        sidebar.setStyleSheet(theme.qss())
        sidebar.show()
        sidebar.set_collapsed(True, animate=False)
        self.app.processEvents()
        avatar = sidebar._items[0].thumb.face
        with patch.object(motion, 'enabled', return_value=True):
            capture.sync_follow_monitored_rooms()
            self.assertEqual(avatar.accessibleDescription(), '监控中')
            self.assertTrue(avatar._ripple_timer.isActive())
            self.assertTrue(sidebar._items[0].rect().contains(avatar.geometry()),
                            (sidebar._items[0].rect(), avatar.geometry(), avatar.visibleRegion().boundingRect()))
            sidebar.set_side('top')
            self.app.processEvents()
            strip_avatar = sidebar._head_strip._avatars['fixture:1']
            self.assertEqual(strip_avatar.recording_state, 'monitoring')
            self.assertTrue(strip_avatar._ripple_timer.isActive())
            self.assertTrue(sidebar._head_strip.rect().contains(strip_avatar.geometry()))
            with patch.object(strip_avatar, '_ripple_clock', SimpleNamespace(elapsed=lambda: 100)):
                early = strip_avatar.grab().toImage()
                scale = early.devicePixelRatio()
                ring = early.pixelColor(round((strip_avatar.width() - strip_avatar.ring_margin
                                               + strip_avatar.RING_GAP) * scale),
                                        round(strip_avatar.height() / 2 * scale))
            self.assertGreater(ring.blue(), ring.red())
            with patch.object(strip_avatar, '_ripple_clock', SimpleNamespace(elapsed=lambda: 800)):
                self.assertNotEqual(early, strip_avatar.grab().toImage())
            settings['streamer_defaults']['fixture:1']['monitor_live'] = False
            capture.sync_follow_monitored_rooms()
            self.assertEqual(strip_avatar.recording_state, '')
            self.assertFalse(strip_avatar._ripple_timer.isActive())
            self.assertEqual(avatar.recording_state, '')

    def test_replay_stays_between_wall_settings_and_picture_in_picture(self):
        sidebar, nav = self.sidebar, self.sidebar.navigation
        settings, pip, replay = (sidebar.wall_settings_button, sidebar.picture_in_picture_button,
                                 sidebar.replay_button)
        for order in (['layout', 'clear', 'pip'], ['pip', 'layout', 'clear']):
            nav.restore_order(order)
            self.assertEqual(nav.bottom.indexOf(settings) + 1, nav.bottom.indexOf(replay))
            self.assertEqual(nav.bottom.indexOf(replay) + 1, nav.bottom.indexOf(pip))
            self.assertEqual(nav.order_state(), order)
        sidebar.set_side('top')
        sidebar.resize(650, sidebar.height())
        sidebar._sync_bar_density()
        self.assertEqual(sidebar._bar_row_box.indexOf(settings) + 1, sidebar._bar_row_box.indexOf(replay))
        self.assertEqual(sidebar._bar_row_box.indexOf(replay) + 1, sidebar._bar_row_box.indexOf(pip))
        sidebar.set_side('left')
        self.assertEqual(nav.bottom.indexOf(settings) + 1, nav.bottom.indexOf(replay))
        self.assertEqual(nav.bottom.indexOf(replay) + 1, nav.bottom.indexOf(pip))

    def test_plugin_content_stays_below_host_search_and_filters_after_orientation_switch(self):
        from PySide6.QtGui import QIcon
        content=QPushButton('视频内容')
        pages=self.sidebar.plugin_pages
        pages.add('fixture','order',content,'观看顺序',QIcon())
        for turn in range(3):
            if turn:
                self.sidebar.set_side('top')
                self.sidebar.set_side('left')
            pages.select(('fixture','order'))
            layout=self.sidebar._layout
            self.assertLess(layout.indexOf(self.sidebar.search),layout.indexOf(self.sidebar.navigation.filters))
            self.assertLess(layout.indexOf(self.sidebar.navigation.filters),layout.indexOf(content))
            self.assertLess(layout.indexOf(content),layout.indexOf(self.sidebar.scroll))
            self.assertLess(layout.indexOf(content),layout.indexOf(self.sidebar.account_row))
            self.assertFalse(content.isHidden())
            self.assertFalse(self.sidebar.navigation.filters.isHidden())
            self.assertTrue(self.sidebar.scroll.isHidden())
            pages.select()
            self.assertTrue(content.isHidden())
            self.assertFalse(self.sidebar.scroll.isHidden())

    def test_plugin_sync_repairs_displaced_content_once_without_replacing_host_controls(self):
        from PySide6.QtGui import QIcon
        content=QPushButton('视频内容')
        pages=self.sidebar.plugin_pages
        pages.add('fixture','order',content,'观看顺序',QIcon())
        pages.select(('fixture','order'))
        layout=self.sidebar._layout
        host_controls=(self.sidebar.navigation.header,self.sidebar.search,self.sidebar.navigation.filters)
        layout.removeWidget(content)
        layout.insertWidget(0,content)
        pages.sync()
        self.assertLess(layout.indexOf(self.sidebar.navigation.filters),layout.indexOf(content))
        self.assertLess(layout.indexOf(content),layout.indexOf(self.sidebar.scroll))
        before=[layout.itemAt(i) for i in range(layout.count())]
        pages.sync()
        self.assertEqual(before,[layout.itemAt(i) for i in range(layout.count())])
        self.assertEqual(host_controls,(self.sidebar.navigation.header,self.sidebar.search,self.sidebar.navigation.filters))

    def test_navigation_mode_skips_matching_style_and_refreshes_changed_dock_or_size(self):
        button = self.sidebar.layout_button
        button.set_navigation_mode(True)
        style = button.style()
        with patch.object(style, 'unpolish', wraps=style.unpolish) as unpolish:
            for _ in range(4):
                button.set_navigation_mode(True)
            unpolish.assert_not_called()
            button.setProperty('dockRail', False)
            button.set_navigation_mode(True)
            self.assertEqual(unpolish.call_count, 1)
            button.setFixedSize(22, 22)
            button.set_navigation_mode(True)
            self.assertEqual(button.size(), QSize(34, 34))
            self.assertEqual(unpolish.call_count, 2)
            button.set_navigation_mode(False)
            self.assertEqual(button.text(), button._label)

    def test_navigation_sync_keeps_matching_fixed_tool_styles(self):
        navigation = self.sidebar.navigation
        navigation.sync()
        button = self.sidebar.notification_button
        style = button.style()
        with patch.object(style, 'unpolish', wraps=style.unpolish) as unpolish:
            navigation.sync()
            navigation.sync()
            unpolish.assert_not_called()
            button.setObjectName('BarIcon')
            button.setProperty('sidebarCompact', True)
            navigation.sync()
            self.assertEqual(button.objectName(), 'NavigationButton')
            self.assertIs(button.property('sidebarCompact'), False)
            self.assertGreaterEqual(unpolish.call_count, 1)

    def test_sidebar_creation_and_local_server_leave_no_stale_item_bindings(self):
        source = '''
import tempfile
from unittest.mock import patch
import shiboken6 as s
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication, QLayout, QLayoutItem, QWidget
from ddm import config, images
from ddm.sidebar_widgets import Sidebar
app = QApplication([])
with tempfile.TemporaryDirectory() as directory, patch.object(config, 'DATA_ROOT', directory), \\
        patch.object(config, 'CONFIG_PATH', directory + '/config.json'), patch.object(images, 'REPO', directory):
    for attempt in range(60):
        root = QWidget()
        sidebar = Sidebar([dict(room_id=str(i), uname='Fixture') for i in range(5)], root, auto_compact=False)
        registered = {s.getCppPointer(obj)[0] for obj in s.getAllValidWrappers()
                      if isinstance(obj, QLayoutItem) and not isinstance(obj, QLayout)}
        actual = {s.getCppPointer(layout.itemAt(index))[0] for layout in root.findChildren(QLayout)
                  for index in range(layout.count())}
        assert not registered - actual, ('stale layout item bindings', attempt, len(registered - actual))
        server = QLocalServer(root)
        server.newConnection.connect(lambda: None)
        root.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not any(isinstance(obj, QLayoutItem) and not isinstance(obj, QLayout)
                       for obj in s.getAllValidWrappers()), attempt
app.shutdown()
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'sidebar_lifetime.py'
            script.write_text(source, encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'dev/checks/bootstrap.py'), str(script)],
                                    cwd=ROOT, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_orientation_changes_invalidate_removed_layout_items(self):
        from shiboken6 import getCppPointer, ownedByPython
        for side in ('top', 'left', 'top', 'left'):
            items = [layout.itemAt(index) for layout in self.sidebar.findChildren(QLayout)
                     for index in range(layout.count())]
            self.sidebar.set_side(side)
            actual = {getCppPointer(layout.itemAt(index))[0] for layout in self.sidebar.findChildren(QLayout)
                      for index in range(layout.count())}
            stale = [item for item in items if isValid(item) and not ownedByPython(item)
                     and getCppPointer(item)[0] not in actual]
            self.assertFalse(stale, f'{side}: removed layout items retain valid wrappers')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows platform window lifecycle')
    def test_native_reparented_windows_release_backing_stores(self):
        # The same Qt-only sequence crashes qoffscreen 6.11.2 at +0x32ad.
        # Validate the production Windows backend without touching desktop input.
        source = '''
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtCore import Qt, QCoreApplication, QEvent
app = QApplication([])
assert app.platformName() == 'windows'
for attempt in range(30):
    first, second = QWidget(), QWidget()
    first.setGeometry(-12000, -12000, 400, 300)
    second.setGeometry(-12000, -12000, 400, 300)
    left, right = QVBoxLayout(first), QVBoxLayout(second)
    child = QWidget()
    child.setAttribute(Qt.WA_NativeWindow)
    left.addWidget(child)
    first.show(); second.show(); app.processEvents()
    left.removeWidget(child); right.addWidget(child); app.processEvents()
    right.removeWidget(child); left.addWidget(child); app.processEvents()
    first.deleteLater(); second.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
app.shutdown()
print('30 native reparent cycles completed', flush=True)
'''
        import os
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'native_reparent.py'
            script.write_text(source, encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'dev/checks/bootstrap.py'), str(script)],
                                    cwd=ROOT, env=dict(os.environ, QT_QPA_PLATFORM='windows'),
                                    capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertIn(b'30 native reparent cycles completed', result.stdout)

    def logged_menu(self):
        self.sidebar.set_account('Current', platform='bilibili', uid='100')
        self.sidebar.logged_accounts = [('bilibili', {'uname': 'Current', 'uid': '100'}),
            ('douyu', {'uname': 'Other', 'uid': '200', '_login_expired': True}),
            ('huya', {'uname': 'Third', 'uid': '300'})]
        return self.sidebar.account_menu()

    def test_independent_imports_legacy_identity_and_single_state_owner(self):
        for name in ('sidebar_account_control', 'sidebar_presentation', 'sidebar_portrait'):
            code = 'import sys; import ddm.' + name + '; ' + \
                "assert not {'ddm.app','ddm.widgets','ddm.sidebar_widgets','ddm.player','mpv'}.intersection(sys.modules)"
            result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        from ddm.widgets import Sidebar
        self.assertIs(Sidebar, module.Sidebar)
        self.assertIsInstance(self.sidebar.account_control, SidebarAccountControl)
        self.assertIsInstance(self.sidebar.presentation_control, SidebarPresentation)
        self.assertEqual(vars(self.sidebar.account_control), {'host': self.sidebar})
        presenter = self.sidebar.presentation_control
        self.assertEqual(set(vars(presenter)), {'host', 'orientation', 'collapse', 'layout_picker'})
        self.assertIs(presenter.host, self.sidebar)
        self.assertEqual(vars(presenter.collapse), {'host': self.sidebar})
        self.assertIs(presenter.layout_picker.host, self.sidebar)
        self.assertIs(presenter.layout_picker.parent(), self.sidebar)
        portrait = presenter.orientation.portrait
        self.assertEqual(vars(presenter.orientation), {'host': self.sidebar, 'portrait': portrait})
        self.assertEqual(vars(portrait), {'host': self.sidebar})

    def test_account_values_selection_visibility_and_clear_keep_same_row(self):
        row = self.sidebar.account_row
        self.sidebar.set_side('top')
        self.sidebar.set_select_mode(True)
        self.sidebar.set_account('Current', platform='douyu', uid='200')
        self.assertEqual((row.uname, row.platform), ('Current', 'douyu'))
        self.assertTrue(row.isHidden())
        self.sidebar.set_select_mode(False)
        self.sidebar.clear_account()
        self.assertIs(self.sidebar.account_row, row)
        self.assertEqual(row.uname, '')
        self.assertFalse(row.isHidden())

    def test_old_popup_row_factories_parentage_and_platform_logout_binding(self):
        self.sidebar.set_account('Current', platform='bilibili', uid='100')
        self.sidebar.logged_accounts = [('douyu', {'uname': 'Other', 'uid': '200', '_login_expired': True}),
            ('huya', {'uname': 'Third', 'uid': '300'})]
        with patch.object(module, 'AccountPopupMenu', wraps=module.AccountPopupMenu) as popup, \
                patch.object(module, 'AccountRow', wraps=module.AccountRow) as row_factory:
            menu = self.sidebar.account_menu()
        popup.assert_called_once_with(self.sidebar)
        self.assertEqual(row_factory.call_count, 2)
        self.assertIs(menu.parent(), self.sidebar)
        self.assertEqual(menu.width(), self.sidebar.account_row.width())
        rows = menu.findChildren(AccountRow)
        self.assertEqual([row.platform for row in rows], ['huya', 'douyu'])
        self.assertIn('已失效', rows[1].account_id.text())
        self.assertTrue(all(row.parentWidget().parentWidget() is menu for row in rows))
        logged_out = []
        self.sidebar.platformLogoutRequested.connect(logged_out.append)
        for row in rows:
            row.logoutClicked.emit()
        self.assertEqual(logged_out, ['huya', 'douyu'])

    def test_login_button_is_deferred_and_uses_sidebar_qt_context(self):
        menu = self.logged_menu()
        action = next(a for a in menu.actions() if isinstance(a, QWidgetAction)
                      and isinstance(a.defaultWidget(), QPushButton))
        requests = []
        self.sidebar.loginRequested.connect(lambda: requests.append('login'))
        action.defaultWidget().click()
        self.assertEqual(requests, [])
        self.app.processEvents()
        self.assertEqual(requests, ['login'])

    def test_destroying_sidebar_cancels_queued_login_and_releases_popup_rows(self):
        menu = self.logged_menu()
        button = next(a.defaultWidget() for a in menu.actions() if isinstance(a, QWidgetAction)
                      and isinstance(a.defaultWidget(), QPushButton))
        rows = menu.findChildren(AccountRow)
        requests = []
        self.sidebar.loginRequested.connect(lambda: requests.append('login'))
        button.click()
        self.sidebar.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(requests, [])
        self.assertFalse(isValid(menu))
        self.assertTrue(all(not isValid(row) for row in rows))

    def test_logged_out_expanded_click_emits_login_without_opening_popup(self):
        requests = []
        self.sidebar.loginRequested.connect(lambda: requests.append(True))
        with patch.object(self.sidebar, 'account_menu') as factory:
            self.sidebar._open_account_menu()
        factory.assert_not_called()
        self.assertEqual(requests, [True])

    def test_popup_result_routes_all_existing_actions_without_exec_or_browser(self):
        self.sidebar.set_account('Current')
        received = []
        for signal, name in ((self.sidebar.loginRequested, 'login'), (self.sidebar.logoutRequested, 'logout'),
                (self.sidebar.pictureInPictureRequested, 'pip'), (self.sidebar.settingsRequested, 'settings'),
                (self.sidebar.importFollowsClicked, 'import'), (self.sidebar.addRoomClicked, 'add')):
            signal.connect(lambda n=name: received.append(n))
        choices = [('登录', 'login'), ('退出登录', 'logout'), ('登录其他平台', 'login'),
            ('所有平台均已登录', 'login'), ('画中画', 'pip'), ('设置', 'settings'), ('导入关注', 'import'),
            ('+ 添加直播间', 'add')]
        for label, expected in choices:
            action = QAction(label, self.sidebar)
            menu = SimpleNamespace(actions=lambda: [action], sizeHint=lambda: QSize(240, 100),
                exec=Mock(return_value=action))
            with patch.object(self.sidebar, 'account_menu', return_value=menu):
                self.sidebar._open_account_menu()
            menu.exec.assert_called_once()
            self.assertEqual(received[-1], expected)
        action = QAction('布局预设', self.sidebar)
        menu = SimpleNamespace(actions=lambda: [action], sizeHint=lambda: QSize(240, 100),
            exec=Mock(return_value=action))
        with patch.object(self.sidebar, 'account_menu', return_value=menu), \
                patch.object(self.sidebar, 'open_layout_picker') as picker:
            self.sidebar._open_account_menu()
        picker.assert_called_once_with()

    def test_menu_entries_follow_side_and_collapse_without_duplicate_tools(self):
        self.sidebar.set_account('Current')
        for side, collapsed in (('left', False), ('left', True), ('top', False), ('top', True)):
            with self.subTest(side=side, collapsed=collapsed):
                self.sidebar.set_side(side)
                self.sidebar.set_collapsed(collapsed, animate=False)
                menu = self.sidebar.account_menu()
                labels = [a.text() for a in menu.actions() if a.text()]
                self.assertEqual('导入关注' in labels, side == 'top' and collapsed)
                self.assertEqual('+ 添加直播间' in labels, side == 'top' and collapsed)
                self.assertNotIn('画中画', labels)
                self.assertNotIn('设置', labels)
                self.assertNotIn('布局预设', labels)
                if side == 'top':
                    self.assertEqual(menu.width(), 240)

    def test_orientation_roundtrip_keeps_widgets_and_restores_original_parents(self):
        widgets = [self.sidebar.search, self.sidebar.scroll, self.sidebar.tool_row, self.sidebar.account_row,
            self.sidebar.batch_button, self.sidebar.appearance_button, self.sidebar.refresh_button,
            self.sidebar.toggle_button, self.sidebar._header_row]
        parents = {widget: widget.parentWidget() for widget in widgets}
        hwnd = int(self.sidebar.winId()) if QApplication.platformName() == 'windows' else None
        self.sidebar.set_side('top')
        rows = (self.sidebar._bar_row, self.sidebar._bar_row2, self.sidebar._bar_right,
                self.sidebar.presentation_control.orientation.portrait.controls)
        self.assertIs(self.sidebar.search.parentWidget(), rows[3])
        self.assertIs(self.sidebar.scroll.parentWidget(), parents[self.sidebar.scroll])
        self.assertIs(self.sidebar.account_row.parentWidget(), rows[0])
        for _ in range(2):
            self.sidebar.set_side('left')
            self.assertEqual({widget: widget.parentWidget() for widget in widgets}, parents)
            self.sidebar.set_side('top')
            self.assertEqual((self.sidebar._bar_row, self.sidebar._bar_row2, self.sidebar._bar_right,
                              self.sidebar.presentation_control.orientation.portrait.controls), rows)
        if hwnd is not None:
            self.assertEqual(int(self.sidebar.winId()), hwnd)

    def test_same_side_resets_scroll_constraints_without_borrowing_controls(self):
        self.sidebar.scroll.setMaximumHeight(42)
        self.sidebar.scroll.horizontal_only = True
        self.sidebar.set_side('left')
        self.assertEqual(self.sidebar.scroll.maximumHeight(), 16_777_215)
        self.assertFalse(self.sidebar.scroll.horizontal_only)
        self.assertEqual(self.sidebar.scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertEqual(self.sidebar.scroll.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOn)
        self.assertFalse(self.sidebar._bar_in_use)

    def test_top_density_scroll_axis_and_left_tool_direction_restore(self):
        self.sidebar.set_side('top')
        for card_mode in (False, True):
            self.sidebar.set_card_mode(card_mode)
            self.sidebar._apply_scroll_axis()
            rows = self.sidebar.list_box.item_size()[1] + NAV_ITEM_GAP + theme.SCROLLBAR_SIZE
            self.assertEqual((self.sidebar.scroll.minimumHeight(), self.sidebar.scroll.maximumHeight()), (rows, rows))
            self.assertTrue(self.sidebar.tool_row.isHidden())
            self.assertEqual(self.sidebar._bar_row_box.direction(), QBoxLayout.LeftToRight)
            self.assertEqual(self.sidebar.presentation_control.orientation.portrait.controls_box.direction(), QBoxLayout.LeftToRight)
            self.assertTrue(self.sidebar.scroll.horizontal_only)
        self.sidebar.set_side('left')
        self.assertEqual(self.sidebar.tool_row.layout().direction(), QBoxLayout.LeftToRight)
        self.assertFalse(self.sidebar.scroll.horizontal_only)

    def test_top_collapse_keeps_account_in_toolbar_and_compact_size(self):
        self.sidebar.set_side('top')
        self.sidebar.set_collapsed(True, animate=False)
        self.assertIs(self.sidebar.account_row.parentWidget(), self.sidebar._bar_row)
        self.assertEqual(self.sidebar.account_row.avatar.width(), RoomStrip.AVATAR)
        self.assertTrue(self.sidebar.scroll.isHidden())
        self.assertFalse(self.sidebar._head_scroll.isHidden())
        self.sidebar.set_collapsed(False, animate=False)
        self.assertIs(self.sidebar.account_row.parentWidget(), self.sidebar._bar_row)
        self.assertFalse(self.sidebar.scroll.isHidden())
        self.assertTrue(self.sidebar._head_scroll.isHidden())

    def test_left_collapse_restores_updates_cover_holds_and_emits_once(self):
        transitions, collapsed = [], []
        self.sidebar.collapseAnimationChanged.connect(transitions.append)
        self.sidebar.collapsedChanged.connect(collapsed.append)
        self.sidebar.setUpdatesEnabled(False)
        self.sidebar.set_collapsed(True)
        self.assertEqual(transitions, [True, False])
        self.assertEqual(collapsed, [True])
        self.assertFalse(self.sidebar.updatesEnabled())
        self.assertFalse(self.sidebar._collapse_animating)
        self.assertTrue(all(not item.thumb._cover_hold for item in self.sidebar.items()))
        self.assertEqual(self.sidebar.width(), theme.SIDEBAR_RAIL_WIDTH + RAIL_WIDTH)
        self.sidebar.set_collapsed(True)
        self.assertEqual(collapsed, [True])
        self.sidebar.setUpdatesEnabled(True)
        self.sidebar.set_collapsed(False, animate=False)
        self.assertEqual(self.sidebar.width(), theme.SIDEBAR_WIDTH + RAIL_WIDTH)
        self.assertEqual(collapsed, [True, False])

    def test_adding_follows_while_collapsed_keeps_avatars_in_their_rows(self):
        sidebar = self.sidebar
        sidebar.resize(sidebar.width(), 720)
        sidebar.setStyleSheet(theme.qss())
        sidebar.show()
        sidebar.set_collapsed(True, animate=False)
        sidebar.default_folder()['sort'] = 'name'
        self.app.processEvents()

        new_rooms = [
            {'room_id': 'fixture:2', 'uname': 'AAA', 'live': True},
            {'room_id': 'fixture:3', 'uname': 'ZZZ', 'live': False},
        ]
        with patch.object(motion, 'enabled', return_value=True):
            self.assertEqual(sidebar.add_rooms(new_rooms), new_rooms)
            cards = sidebar.visible_items()
            self.assertEqual([card.room['uname'] for card in cards], ['AAA', 'Fixture', 'ZZZ'])
            cover = QPixmap(96, 54)
            cover.fill(Qt.darkBlue)
            for card in cards:
                card.thumb.set_cover(cover)
            self.assertTrue(all(card._compact and card.thumb.cover.isHidden() for card in cards))
            self.app.processEvents()
            for card in cards:
                self.assertEqual(card.height(), NAV_COMPACT_ITEM_HEIGHT)
                face = card.thumb.face
                avatar = QRect(face.mapTo(card, QPoint()), face.size())
                self.assertTrue(card.rect().contains(avatar))
                self.assertAlmostEqual(avatar.center().x(), card.rect().center().x(), delta=1)
            for before, after in zip(cards, cards[1:]):
                self.assertEqual(after.y() - before.y(), NAV_COMPACT_ITEM_HEIGHT + NAV_ITEM_GAP)

        sidebar.set_collapsed(False, animate=False)
        self.app.processEvents()
        for card in cards:
            self.assertFalse(card._compact)
            self.assertEqual(card.height(), NAV_ITEM_HEIGHT)
            self.assertTrue(card.thumb.cover.isVisible())

    def test_collapse_error_keeps_original_finally_cleanup_and_emits_no_commit(self):
        transitions, committed = [], []
        self.sidebar.collapseAnimationChanged.connect(transitions.append)
        self.sidebar.collapsedChanged.connect(committed.append)
        with patch.object(self.sidebar, '_apply_collapsed_controls', side_effect=RuntimeError('fixture')):
            with self.assertRaisesRegex(RuntimeError, 'fixture'):
                self.sidebar.set_collapsed(True)
        self.assertTrue(self.sidebar.updatesEnabled())
        self.assertFalse(self.sidebar._collapse_animating)
        self.assertTrue(all(not item.thumb._cover_hold for item in self.sidebar.items()))
        self.assertEqual(transitions, [True, False])
        self.assertEqual(committed, [])

    def test_parent_deletion_releases_borrowed_rows_controls_and_existing_timers(self):
        self.sidebar.set_side('top')
        portrait = self.sidebar.presentation_control.orientation.portrait
        children = [self.sidebar._bar_row, self.sidebar._bar_row2, self.sidebar._bar_right,
            portrait.controls, portrait.follow_group, self.sidebar.navigation.follow_button,
            self.sidebar.search, self.sidebar.scroll, self.sidebar.account_row, self.sidebar._card_entry_timer]
        self.sidebar.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertTrue(all(not isValid(child) for child in children))


if __name__ == '__main__':
    native = '--native' in sys.argv
    if native:
        sys.argv.remove('--native')
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(SidebarPresentationTests, __file__,
            ('--native',) if native else ()))
    else:
        unittest.main(verbosity=2)
