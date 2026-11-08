"""Functional ownership boundaries; isolated Qt processes and temporary data only."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


class FunctionalModulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ddm import config, images, motion
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-functional-'))
        self.stack.enter_context(patch.object(config, 'DATA_ROOT', directory))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')))
        self.stack.enter_context(patch.object(images, 'REPO', directory))
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            if isValid(widget):
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def child(self, code):
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sidebar_domains_import_without_aggregate_or_main_window(self):
        for name in ('sidebar_items', 'sidebar_interaction'):
            self.child('import sys; import ddm.'+name+'; '
                "assert not {'ddm.app','ddm.widgets','ddm.sidebar_widgets'}.intersection(sys.modules)")

    def test_sidebar_collection_and_interaction_use_the_sidebar_as_only_owner(self):
        from ddm.sidebar_widgets import AppearanceButton, Sidebar
        sidebar, appearance = Sidebar([], auto_compact=False), AppearanceButton()
        self.widgets += [sidebar, appearance]
        for name in ('items_control', 'interaction_control'):
            self.assertEqual(vars(getattr(sidebar, name)), {'host': sidebar})
            self.assertFalse(hasattr(appearance, name))

    def test_sidebar_card_factory_add_remove_and_shared_room_data(self):
        from ddm import sidebar_widgets as module
        sidebar = module.Sidebar([], auto_compact=False)
        self.widgets.append(sidebar)
        room = {'room_id': 'fixture:1', 'uname': 'Fixture', 'live': False}
        with patch.object(module, 'NavItem', wraps=module.NavItem) as factory:
            self.assertEqual(sidebar.add_rooms([room, room]), [room])
        factory.assert_called_once()
        item = sidebar.items()[0]
        self.assertIs(item.room, room)
        self.assertIs(item.drop_host, sidebar)
        self.assertIs(item.parentWidget(), sidebar.list_box)
        self.assertEqual(sidebar.rooms(), [room])
        sidebar.remove_room(room)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(sidebar.items(), [])
        self.assertEqual(sidebar.rooms(), [])
        self.assertFalse(isValid(item))

    def test_tile_domains_keep_shared_state_signals_and_widget_ownership(self):
        from ddm.tile_widgets import Tile
        tile = Tile({'room_id': 'fixture:1', 'uname': 'Fixture'})
        self.widgets.append(tile)
        for name in ('state_control', 'controls_control', 'presentation_control', 'menu_control'):
            self.assertEqual(vars(getattr(tile, name)), {'host': tile})
        changes = []
        tile.volumeChanged.connect(lambda room, value: changes.append(value))
        tile.set_volume(27)
        self.assertEqual((tile.volume, tile.room['volume'], tile.volume_slider.value()), (27, 27, 27))
        self.assertEqual(changes, [27])
        self.assertIs(tile.video.parentWidget(), tile)
        self.assertIs(tile._control_hover_timer.parent(), tile)
        tile.set_room({'room_id': 'fixture:2', 'uname': 'Other'})
        self.assertEqual(tile.volume, 27)
        menu = tile.build_menu()
        self.assertIs(menu.parentWidget(), tile)
        menu.deleteLater()

    def test_tile_domains_import_without_widget_aggregate(self):
        for name in ('tile_state', 'tile_controls', 'tile_presentation', 'tile_context_menu'):
            self.child('import sys; import ddm.'+name+'; '
                "assert not {'ddm.app','ddm.widgets','ddm.tile_widgets'}.intersection(sys.modules)")

    def test_window_domains_import_independently_and_keep_one_host(self):
        from types import SimpleNamespace
        import importlib
        host = SimpleNamespace()
        for module, name in (('app_accounts', 'AppAccounts'), ('app_shortcuts', 'AppShortcuts'),
                ('fullscreen_control', 'FullscreenControl'), ('app_notices', 'AppNotices')):
            self.child('import sys; import ddm.'+module+'; '
                "assert not {'ddm.app','ddm.widgets'}.intersection(sys.modules)")
            controller = getattr(importlib.import_module('ddm.'+module), name)(host)
            self.assertEqual(vars(controller), {'host': host})

    def test_super_chat_model_is_independent_and_legacy_exports_keep_identity(self):
        self.child("import sys; import ddm.super_chat_model; "
            "assert not {'PySide6','requests','ddm.app','ddm.widgets'}.intersection(sys.modules)")
        from ddm import super_chat, super_chat_model, super_chat_presentation, super_chat_api
        from ddm import danmaku_widgets, super_chat_widgets, video_danmaku, video_super_chat
        for module, names in ((super_chat_model, ('SuperChatStore', 'normalize')),
                (super_chat_presentation, ('SuperChatPresentation', 'SuperChatAvatar')),
                (super_chat_api, ('SuperChatSnapshot', 'snapshot_events'))):
            for name in names:
                self.assertIs(getattr(super_chat, name), getattr(module, name))
        self.assertIs(danmaku_widgets.SuperChatCard, super_chat_widgets.SuperChatCard)
        self.assertIs(video_danmaku.SuperChatOverlay, video_super_chat.SuperChatOverlay)

    def test_pip_geometry_and_views_import_without_playback_controller(self):
        for name in ('pip_geometry', 'pip_preview', 'pip_picker', 'pip_window'):
            self.child('import sys; import ddm.'+name+'; '
                "assert not {'ddm.app','ddm.widgets','ddm.picture_in_picture','ddm.player'}.intersection(sys.modules)")
        from ddm import picture_in_picture as legacy, pip_preview, pip_picker, pip_window
        for module, name in ((pip_preview, 'CompositionPreview'),
                (pip_picker, 'PictureInPictureDialog'), (pip_window, 'PictureInPictureWindow')):
            self.assertIs(getattr(legacy, name), getattr(module, name))

    def test_online_pages_and_notifications_keep_legacy_class_identity(self):
        from ddm import online_ui, online_tasks, update_notice, result_notice, plugin_store_ui, app_update_ui
        for module, names in ((online_tasks, ('OnlineTask', 'OnlinePage', '_retired_online_tasks')),
                (update_notice, ('UpdateNotice', 'UpdateDot')),
                (result_notice, ('ResultNotice', 'show_result')),
                (plugin_store_ui, ('PluginStorePage',)), (app_update_ui, ('AppUpdatePage',))):
            for name in names:
                self.assertIs(getattr(online_ui, name), getattr(module, name))
        self.assertIs(result_notice.ResultNotice.__bases__[0], update_notice.UpdateNotice)

    def test_bili_workers_import_without_api_and_read_current_api_functions(self):
        self.child("import sys; import ddm.bili_workers; assert 'ddm.bili' not in sys.modules")
        from ddm import bili, bili_workers
        for name in ('StreamResolver', 'InfoResolver', 'FollowLoader', 'StatusPoller', 'AccountLoader', 'StatsPoller'):
            self.assertIs(getattr(bili, name), getattr(bili_workers, name))
        worker = bili_workers.AccountLoader()
        seen = []
        worker.loaded.connect(seen.append)
        with patch.object(bili, 'my_account', return_value={'uname': 'current-api'}):
            worker.run()
        self.assertEqual(seen, [{'uname': 'current-api'}])
        worker.deleteLater()

    def test_wall_controllers_keep_original_timer_and_session_owners(self):
        from ddm.wall_widgets import WallGrid
        wall = WallGrid([])
        self.widgets.append(wall)
        for name in ('layout_control', 'presentation_control'):
            self.assertEqual(vars(getattr(wall, name)), {'host': wall})
        self.assertIs(wall._resize_timer.parent(), wall)
        self.assertIs(wall._border_drag_timer.parent(), wall._border_interaction)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(FunctionalModulesTests, __file__))
    else:
        unittest.main(verbosity=2)
