"""Chat widget boundaries, rendering, signals and Qt ownership; synthetic data only."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPointF, QThread, Qt, Signal
from PySide6.QtGui import QDropEvent, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from ddm import danmaku_panel, super_chat_widgets, wall_constants


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.panel = danmaku_panel.DanmakuPanel(self.owner)
        self.panel.resize(420, 340)
        self.owner.show()
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.app.processEvents()
        self.owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_fresh_import_does_not_load_aggregate_player_or_window(self):
        code = '''
import sys
from ddm.danmaku_panel import DanmakuPanel
from ddm.super_chat_widgets import SuperChatCard
assert not any(name in sys.modules for name in (
    'ddm.widgets', 'ddm.app', 'ddm.player', 'ddm.video_surface', 'mpv',
    'PySide6.QtWebEngineWidgets'))
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_exports_retain_identity_and_drag_contract(self):
        from ddm import widgets
        for module, names in (
                (danmaku_panel, ('DanmakuPanel', 'DanmakuTextBrowser',
                                 'DanmakuBottomButton', 'DanmakuConnectionIcon')),
                (super_chat_widgets, ('SuperChatCard', 'SuperChatStack',
                                      'SuperChatAvatarView', 'SuperChatMessage')),
                (wall_constants, ('TILE_MIME', 'DANMAKU_MIME', 'TILE_BAR_HEIGHT'))):
            for name in names:
                self.assertIs(getattr(widgets, name), getattr(module, name))

    def test_message_rendering_font_signal_and_placeholder(self):
        changes = []
        self.panel.fontSizeChanged.connect(changes.append)
        self.panel.add_message('<测试用户>', '<b>不是标签</b> & 文本')
        text = self.panel.body.toPlainText()
        self.assertIn('<测试用户>', text)
        self.assertIn('<b>不是标签</b> & 文本', text)
        self.panel.font_slider.setValue(19)
        self.assertEqual(changes, [19])
        self.assertIn('<b>不是标签</b>', self.panel.body.toPlainText())
        self.panel.set_placeholder('等待新房间')
        self.assertFalse(self.panel._blocks)
        self.assertIn('等待新房间', self.panel.body.toPlainText())

    def test_room_drop_uses_signal_without_starting_a_drag(self):
        rooms = []
        self.panel.roomDropped.connect(rooms.append)
        mime = QMimeData()
        mime.setData(danmaku_panel.ROOM_MIME, b'12345')
        event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime,
                           Qt.LeftButton, Qt.NoModifier)
        self.panel.dropEvent(event)
        self.assertEqual(rooms, ['12345'])
        self.assertTrue(event.isAccepted())

    def test_emoticon_completion_rerenders_and_worker_keeps_panel_parent(self):
        pending = []
        class Loader(QThread):
            loaded = Signal(str, object)
            def __init__(self, items, parent, subdir):
                super().__init__(parent)
                self.items, self.subdir = items, subdir
                pending.append(self)
            def start(self):
                pass

        url = 'https://example.invalid/local-emoticon.png'
        with patch.object(danmaku_panel, 'AvatarLoader', Loader):
            self.panel.add_event({'uname': '测试', 'text': '表情', 'emoticon': url})
        self.assertEqual(len(pending), 1)
        worker = pending[0]
        self.assertIs(worker.parent(), self.panel)
        self.assertEqual(worker.subdir, 'emoticons')
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.red)
        worker.loaded.emit(url, pixmap)
        self.assertIn(url, self.panel._images)
        self.assertIn('<img ', self.panel.body.toHtml())
        worker.finished.emit()
        self.assertNotIn(url, self.panel._loading_emoticons)

    def test_children_and_sc_presentation_die_with_panel(self):
        panel = self.panel
        body, stack = panel.body, panel.super_chats
        presentation = stack.presentation
        self.assertIs(body.parentWidget(), panel)
        self.assertIs(stack.parentWidget(), panel)
        dismissed = []
        panel.superChatDismissed.connect(dismissed.append)
        stack.dismissed.emit('synthetic-sc')
        self.assertEqual(dismissed, ['synthetic-sc'])
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        for child in (panel, body, stack, presentation):
            self.assertFalse(isValid(child))


if __name__ == '__main__':
    unittest.main()
