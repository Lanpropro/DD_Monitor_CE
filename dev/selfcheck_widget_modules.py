"""Widget module boundaries and legacy identities; imports only, no user data or media."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class WidgetModulesTests(unittest.TestCase):
    def child(self, code):
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_presentation_imports_do_not_load_player_aggregate_or_window(self):
        for module in ('account_widgets', 'danmaku_widgets', 'layout_picker', 'wall_border'):
            with self.subTest(module=module):
                self.child(f'''
import importlib, sys
importlib.import_module('ddm.{module}')
assert not any(name in sys.modules for name in (
    'ddm.widgets', 'ddm.app', 'ddm.player', 'ddm.video_surface',
    'PySide6.QtWebEngineWidgets', 'mpv'))
''')

    def test_legacy_classes_and_shared_values_keep_identity(self):
        from ddm import (account_widgets, danmaku_widgets, layout_picker,
                         sidebar_cards, sidebar_widgets, tile_widgets, wall_widgets,
                         widget_support, widgets)
        modules = (
            (account_widgets, ('AccountPopupMenu', 'AccountRow')),
            (danmaku_widgets, ('DanmakuTextBrowser', 'DanmakuBottomButton',
                               'SuperChatAvatarView', 'SuperChatMessage',
                               'SuperChatCard', 'SuperChatStack',
                               'DanmakuConnectionIcon', 'DanmakuPanel')),
            (sidebar_cards, ('LiveAlert', 'NavThumb', 'NavSelectionCheck', 'NavItem',
                             'SmartFolderDialog', 'SmartFolderCard', 'FollowFolderButton',
                             'RoomListBox', 'CarouselScroll')),
            (layout_picker, ('LayoutPicker',)),
            (sidebar_widgets, ('AppearanceButton', 'Sidebar')),
            (tile_widgets, ('Tile',)),
            (wall_widgets, ('best_columns', 'WallPaneBorder', 'WallResizePreview', 'WallGrid')),
            (widget_support, ('QUALITY_CHOICES', 'QUALITY_NAMES', 'TILE_BAR_HEIGHT',
                               'TILE_MIME', 'DANMAKU_MIME', 'BRAND_ASSETS_DIR',
                               '_repolish', 'rounded_pixmap', '_ignore_mouse', '_allow_shrink')),
        )
        for module, names in modules:
            for name in names:
                with self.subTest(module=module.__name__, name=name):
                    self.assertIs(getattr(widgets, name), getattr(module, name))

    def test_owned_domains_do_not_import_the_compatibility_entry_or_window(self):
        for module, forbidden in (
                ('sidebar_cards', ('ddm.widgets', 'ddm.app', 'ddm.wall_widgets')),
                ('sidebar_widgets', ('ddm.widgets', 'ddm.app', 'ddm.wall_widgets')),
                ('tile_widgets', ('ddm.widgets', 'ddm.app', 'ddm.wall_widgets')),
                ('wall_widgets', ('ddm.widgets', 'ddm.app', 'ddm.sidebar_widgets'))):
            with self.subTest(module=module):
                self.child(f'''
import importlib, sys
importlib.import_module('ddm.{module}')
assert not any(name in sys.modules for name in {forbidden!r})
''')

    def test_main_window_uses_owned_domains_without_the_compatibility_entry(self):
        self.child('''
import sys
import ddm.app
assert 'ddm.widgets' not in sys.modules
''')

    def test_compatibility_entry_keeps_original_qt_subclass_order(self):
        self.child('''
import builtins
expected = ['DanmakuTextBrowser', 'DanmakuBottomButton', 'SuperChatAvatarView',
    'SuperChatMessage', 'SuperChatCard', 'SuperChatStack', 'DanmakuConnectionIcon',
    'DanmakuPanel', 'ElidedLabel', 'AccountPopupMenu', 'AccountRow', 'LiveAlert',
    'NavThumb', 'NavSelectionCheck', 'NavItem', 'SmartFolderDialog', 'SmartFolderCard',
    'FollowFolderButton', 'RoomListBox', 'CarouselScroll', 'BarIconButton',
    'AppearanceButton', 'Sidebar', 'Tile', 'WallPaneBorder', 'WallResizePreview',
    'WallGrid', 'LayoutPicker']
original, seen = builtins.__build_class__, []
def record(function, name, *bases, **keywords):
    if name in expected:
        seen.append(name)
    return original(function, name, *bases, **keywords)
builtins.__build_class__ = record
try:
    import ddm.widgets
finally:
    builtins.__build_class__ = original
assert seen == expected, seen
''')


if __name__ == '__main__':
    unittest.main()
