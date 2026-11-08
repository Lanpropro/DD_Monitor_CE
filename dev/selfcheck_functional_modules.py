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

    def test_recording_session_and_replay_share_original_manager_state(self):
        from ddm.recording import RecordingManager, RecordingSession
        from ddm.recording_session import _Session
        self.assertIs(RecordingSession, _Session)
        manager = RecordingManager({})
        self.assertEqual(vars(manager.replay_control), {'host': manager})
        self.assertIs(manager.timer.parent(), manager)
        token = manager.pin_parts([Path('fixture-segment')])
        self.assertIn(Path('fixture-segment'), manager._protected_parts())
        manager.release_parts(token)
        self.assertFalse(manager._protected_parts())
        manager.shutdown()
        manager.deleteLater()

    def test_plugin_contract_and_package_boundaries_keep_one_runtime_owner(self):
        from ddm import plugins, plugin_types, plugin_manifest
        for name in ('Plugin', 'PluginContext', 'RoomInfo', 'StreamSource', 'Platform'):
            self.assertIs(getattr(plugins, name), getattr(plugin_types, name))
        self.assertIs(plugins.RENAMED_PLUGINS, plugin_manifest.RENAMED_PLUGINS)
        with tempfile.TemporaryDirectory(prefix='ddm-functional-plugins-') as directory:
            manager = plugins.PluginManager(plugins_dir=directory)
            self.assertEqual(vars(manager.package_control), {'host': manager})
            self.assertEqual(manager.catalog(), [])
            import json
            import zipfile
            archive = Path(directory).parent / (Path(directory).name + '.zip')
            try:
                with zipfile.ZipFile(archive, 'w') as package:
                    package.writestr('fixture_plugin/plugin.py', 'raise AssertionError("Install must not execute code")')
                    package.writestr('fixture_plugin/plugin.json', json.dumps({'id': 'fixture_plugin',
                        'name': 'Fixture', 'version': '1.0', 'description': 'Fixture package'}))
                self.assertEqual(manager.install_zip(str(archive)), 'fixture_plugin')
                self.assertEqual([item['id'] for item in manager.catalog()], ['fixture_plugin'])
                manager.remove_plugin('fixture_plugin')
                self.assertEqual(manager.catalog(), [])
            finally:
                archive.unlink(missing_ok=True)

    def test_skin_shared_controls_and_part_dialog_keep_legacy_identity(self):
        from ddm import skin_settings, skin_controls, skin_part_settings
        self.assertIs(skin_settings.SkinAssetDropArea, skin_controls.SkinAssetDropArea)
        self.assertIs(skin_settings.PartSettings, skin_part_settings.PartSettings)
        self.child("import sys; import ddm.skin_part_settings; "
            "assert not {'ddm.skin_settings','ddm.app','ddm.widgets'}.intersection(sys.modules)")

    def test_chat_document_and_surface_helpers_keep_single_widget_state(self):
        from ddm.danmaku_widgets import DanmakuPanel
        from ddm.video_danmaku import VideoDanmaku
        from ddm.video_super_chat import _paint_super_chat
        panel, video = DanmakuPanel(), VideoDanmaku()
        self.widgets += [panel, video]
        for owner, fields in ((panel, ('document_control', 'scroll_control')),
                (video, ('raster_control', 'surface_control'))):
            for name in fields:
                self.assertEqual(vars(getattr(owner, name)), {'host': owner})
        self.assertIs(VideoDanmaku._paint_super_chat, _paint_super_chat)
        self.assertIs(video.timer.parent(), video)

    def test_skin_part_editor_builds_with_the_original_global_background_controls(self):
        from PySide6.QtCore import QTimer
        from ddm.app import MainWindow
        from ddm.plugins import PluginManager
        from ddm.skin_part_settings import PartSettings
        from ddm.skin_settings import SkinSettings
        with patch.object(QTimer, 'singleShot', lambda *args: None), patch.object(PluginManager, 'load'):
            window = MainWindow([], [], state={'plugins_enabled': []})
            self.widgets.append(window)
            editor = PartSettings(window, window, embedded=True)
            self.widgets.append(editor)
            self.assertIsInstance(editor.background_controls, SkinSettings)
            self.assertIs(editor.parentWidget(), window)

    def test_chat_document_uses_original_emoticon_loader_and_queued_result(self):
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtGui import QPixmap
        from ddm import danmaku_widgets
        class Loader(QObject):
            loaded = Signal(str, QPixmap)
            finished = Signal()
            def __init__(self, items, parent, **kwargs):
                super().__init__(parent)
            def start(self):
                pass
            def isRunning(self):
                return True
        panel = danmaku_widgets.DanmakuPanel()
        self.widgets.append(panel)
        with patch.object(danmaku_widgets, 'AvatarLoader', Loader):
            panel._ensure_emoticon('fixture:first')
            panel._ensure_emoticon('fixture:second')
        self.assertEqual(len(panel._emoticon_loaders), 2)
        loader = panel._emoticon_loaders[-1]
        self.assertIs(loader.parent(), panel)
        pixmap = QPixmap(8, 8)
        pixmap.fill()
        loader.loaded.emit('fixture:second', pixmap)
        self.assertIn('fixture:second', panel._images)

    def test_worker_and_protocol_imports_are_independent_and_keep_legacy_aliases(self):
        self.child("import sys; import ddm.live_danmaku_protocol; "
            "assert not {'aiohttp','PySide6','ddm.live_danmaku'}.intersection(sys.modules)")
        self.child("import sys; import ddm.image_workers; assert 'ddm.images' not in sys.modules")
        self.child("import sys; import ddm.settings_worker; "
            "assert not {'ddm.settings_process','ddm.dialogs','ddm.app'}.intersection(sys.modules)")
        from ddm import images, image_workers, account_dialog, account_workers
        from ddm import live_danmaku, live_danmaku_protocol, settings_process, settings_worker
        for name in ('CachedCoverLoader', 'CachedAvatarLoader', 'AvatarLoader'):
            self.assertIs(getattr(images, name), getattr(image_workers, name))
        self.assertIs(account_dialog.FollowAccountResolver, account_workers.FollowAccountResolver)
        self.assertIs(settings_process.run_worker, settings_worker.run_worker)
        self.assertIs(live_danmaku.douyu_packet, live_danmaku_protocol.douyu_packet)
        self.assertEqual(live_danmaku.douyu_messages(bytearray(live_danmaku.douyu_packet('type@=chatmsg/txt@=fixture/'))),
            [{'type': 'chatmsg', 'txt': 'fixture'}])

    def test_login_workers_import_without_dialogs_and_profiles_share_one_registry(self):
        for worker, view in (('bili_login_worker', 'login'), ('oauth_worker', 'oauth_login'),
                ('platform_follow_worker', 'platform_login')):
            self.child('import sys; import ddm.'+worker+'; assert "ddm.'+view+'" not in sys.modules')
        from ddm import login, bili_login_worker, oauth_login, oauth_worker
        from ddm import platform_login, platform_follow_worker, platform_profiles
        self.assertIs(login.QRLogin, bili_login_worker.QRLogin)
        self.assertIs(oauth_login.OAuthLoader, oauth_worker.OAuthLoader)
        self.assertIs(platform_login.PlatformFollowLoader, platform_follow_worker.PlatformFollowLoader)
        self.assertIs(platform_login._profiles, platform_profiles._profiles)

    def test_login_workers_publish_fixture_identity_and_obey_cancellation(self):
        from types import SimpleNamespace
        from ddm import oauth_login
        from ddm.oauth_worker import OAuthLoader
        from ddm.platform_follow_worker import PlatformFollowLoader
        room = {'room_id': 'fixture:room'}
        platform = SimpleNamespace(kind='fixture', account_info=lambda *_: {'uid': 'fixture'},
            follow_rooms=lambda *_: [room])
        oauth = OAuthLoader(platform, {}, {})
        follows = PlatformFollowLoader(platform, {})
        for worker in (oauth, follows):
            seen = []
            worker.loaded.connect(seen.append)
            with patch.object(oauth_login, 'authorize', return_value={'access_token': 'fixture-token'}):
                worker.run()
                self.assertEqual(seen, [[room]])
                worker.cancel()
                worker.run()
                self.assertEqual(seen, [[room]])
            worker.deleteLater()

    def test_room_collection_navigation_and_sampling_have_independent_boundaries(self):
        from types import SimpleNamespace
        from ddm.room_placement import RoomPlacement
        from ddm.room_catalog import RoomCatalog
        from ddm.room_navigation import RoomNavigation
        host = SimpleNamespace(plugins=SimpleNamespace(platforms={}))
        placement = RoomPlacement(host)
        self.assertIsInstance(placement.catalog, RoomCatalog)
        self.assertIsInstance(placement.navigation, RoomNavigation)
        self.assertEqual(vars(placement.catalog), {'host': host})
        self.assertEqual(vars(placement.navigation), {'host': host})
        self.assertEqual(placement.room_browser_url({'room_id': '123'}), 'https://live.bilibili.com/123')
        for module in ('room_catalog', 'room_navigation', 'watch_history_sampling'):
            self.child('import sys; import ddm.'+module+'; '
                "assert not {'PySide6','ddm.app','ddm.widgets'}.intersection(sys.modules)")

    def test_room_configuration_roundtrip_is_pure_and_uses_current_defaults(self):
        from copy import deepcopy
        from ddm import config, room_configuration
        self.child("import sys; import ddm.room_configuration; "
            "assert not {'PySide6','ddm.config'}.intersection(sys.modules)")
        self.assertIs(config.build_rooms, room_configuration.build_rooms)
        state = {'rooms': ['douyin:fixture', '123'], 'pinned': ['douyin:fixture'],
            'wall': [{'room_id': 'douyin:fixture', 'volume': 17}],
            'platform_rooms': {'douyin:fixture': {'uname': 'Fixture', 'playback_mode': 'stream'}}}
        original = deepcopy(state)
        hidden = config.sync_platform_rooms(state, set())
        self.assertEqual(state, original)
        self.assertEqual(hidden['rooms'], ['123'])
        restored = config.sync_platform_rooms(hidden, {'douyin'})
        self.assertEqual(restored['rooms'], state['rooms'])
        sidebar, wall = config.build_rooms(restored)
        self.assertEqual(sidebar[0]['uname'], 'Fixture')
        self.assertEqual(wall[0]['volume'], 17)
        with patch.object(config, 'DEFAULT_VOLUME', 29):
            self.assertEqual(config.build_rooms({'wall': [{}]})[1][0]['volume'], 29)

    def test_super_chat_preview_resources_and_deadlines_have_separate_owners(self):
        from ddm import super_chat_presentation as legacy, super_chat_layout as layout
        from ddm.super_chat_animation import SuperChatPresentation
        from ddm.super_chat_avatar import SuperChatAvatar
        from ddm.super_chat_preview import SuperChatPlacementPreview
        from PySide6.QtWidgets import QWidget
        owner = QWidget()
        self.widgets.append(owner)
        presentation = SuperChatPresentation(owner)
        avatar = SuperChatAvatar(owner)
        self.assertIs(presentation.parent(), owner)
        self.assertIs(presentation.timer.parent(), presentation)
        self.assertIs(presentation.entrance.parent(), presentation)
        self.assertIs(avatar.parent(), owner)
        self.assertIs(legacy.SuperChatPresentation, SuperChatPresentation)
        self.assertIs(legacy.SuperChatAvatar, SuperChatAvatar)
        self.assertIs(legacy.SuperChatPlacementPreview, SuperChatPlacementPreview)
        self.assertIs(legacy.sc_placement_rects, layout.sc_placement_rects)
        self.child("import sys; import ddm.super_chat_preview; "
            "assert not {'ddm.super_chat_presentation','ddm.super_chat_avatar','ddm.super_chat_animation'}.intersection(sys.modules)")

    def test_sidebar_orientation_collapse_and_picker_share_original_controls(self):
        from ddm.sidebar_widgets import Sidebar
        sidebar = Sidebar([], auto_compact=False)
        self.widgets.append(sidebar)
        presenter = sidebar.presentation_control
        for name in ('orientation', 'collapse', 'layout_picker'):
            self.assertEqual(vars(getattr(presenter, name)), {'host': sidebar})
        original = sidebar.account_row
        sidebar.set_side('top')
        self.assertIs(sidebar.account_row, original)
        sidebar.set_side('left')
        self.assertIs(sidebar.account_row, original)
        sidebar.set_collapsed(True, animate=False)
        self.assertTrue(sidebar.collapsed)
        sidebar.set_collapsed(False, animate=False)
        self.assertFalse(sidebar.collapsed)

    def test_responsiveness_probe_folder_and_theme_captures_keep_public_hooks(self):
        from ddm import responsiveness, responsiveness_probe, folder_motion_capture, theme_capture
        self.assertIs(responsiveness.Probe, responsiveness_probe.Probe)
        self.assertIs(responsiveness.FolderMotionCapture, folder_motion_capture.FolderMotionCapture)
        self.assertIs(responsiveness.install_theme_capture, theme_capture.install_theme_capture)
        for module in ('responsiveness_probe', 'folder_motion_capture', 'theme_capture'):
            self.child('import sys; import ddm.'+module+'; '
                "assert not {'PySide6','ddm.app','ddm.responsiveness'}.intersection(sys.modules)")


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(FunctionalModulesTests, __file__))
    else:
        unittest.main(verbosity=2)
