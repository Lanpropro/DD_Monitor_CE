"""Temporary menus and background theme subscriptions must release Qt/Python objects."""
import gc
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref

os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QTimer
from PySide6.QtWidgets import QApplication, QMenu, QSlider, QWidget
from ddm import theme
from ddm.skins import BackgroundLayer
from ddm.widgets import DanmakuPanel, Tile


def drain():
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
    gc.collect()


class WidgetLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_queued_scroll_restore_ignores_deleted_panel(self):
        panel = DanmakuPanel()
        panel.add_message('测试用户', '排队重排后立即关闭')
        errors = []
        with patch.object(sys, 'excepthook', side_effect=lambda *args: errors.append(args[1])):
            panel.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
        self.assertEqual(errors, [])

    def test_repeated_context_and_quality_menus_release_children(self):
        tile = Tile(dict(room_id='1', uname='Menu fixture', live=False))
        event = SimpleNamespace(globalPos=lambda: QPoint(-10000, -10000))
        before = (len(tile.findChildren(QMenu)), len(tile.findChildren(QSlider)))
        qualities, volumes, callbacks = [], [], []
        tile.qualityChanged.connect(lambda room, quality: qualities.append(quality))
        tile.volumeChanged.connect(lambda room, volume: volumes.append(volume))
        tile.plugin_actions = [('Fixture action', lambda: callbacks.append(True))]
        observed = []
        references = []
        timer = QTimer()

        def operate():
            menu = self.app.activePopupWidget()
            if not isinstance(menu, QMenu):
                return
            timer.stop()
            observed.append(True)
            references.append(weakref.ref(menu))
            if len(observed) == 1:
                slider = menu.findChild(QSlider)
                slider.setValue(37)
                next(action for action in menu.actions() if action.text() == 'Fixture action').trigger()
            elif len(observed) == 31:
                menu.actions()[-1].trigger()
            menu.close()

        timer.timeout.connect(operate)
        try:
            for operation in (lambda: tile.contextMenuEvent(event), tile._open_quality_menu):
                for _ in range(30):
                    timer.start(0)
                    operation()
                    timer.stop()
                    drain()
                    self.assertEqual((len(tile.findChildren(QMenu)), len(tile.findChildren(QSlider))), before)
            self.assertEqual(len(observed), 60)
            self.assertEqual(volumes, [37])
            self.assertEqual(callbacks, [True])
            self.assertEqual(len(qualities), 1)
            self.assertEqual(tile.quality, 80)
            self.assertTrue(all(reference() is None for reference in references))
        finally:
            timer.stop()
            tile.deleteLater()
            drain()

    def test_menus_release_children_even_if_execution_raises(self):
        class FailedMenu(QMenu):
            def exec(self, *args):
                raise RuntimeError('Fixture menu failure')

        tile = Tile(dict(room_id='1', uname='Menu fixture', live=False))
        event = SimpleNamespace(globalPos=lambda: QPoint())
        before = (len(tile.findChildren(QMenu)), len(tile.findChildren(QSlider)))
        try:
            with patch('ddm.tile_widgets.QMenu', FailedMenu):
                for operation in (lambda: tile.contextMenuEvent(event), tile._open_quality_menu):
                    with self.assertRaisesRegex(RuntimeError, 'Fixture menu failure'):
                        operation()
                    drain()
                    self.assertEqual((len(tile.findChildren(QMenu)), len(tile.findChildren(QSlider))), before)
        finally:
            tile.deleteLater()
            drain()

    def test_background_theme_receiver_is_live_then_released(self):
        references = []
        errors = []
        hook = patch.object(sys, 'excepthook', lambda kind, value, traceback: errors.append(value))
        hook.start()
        self.addCleanup(hook.stop)
        for _ in range(20):
            root = QWidget()
            layer = BackgroundLayer(root, root)
            with patch.object(layer, 'update') as update:
                theme.signals().changed.emit('dark')
                update.assert_called_once_with()
            references.append(weakref.ref(layer))
            root.deleteLater()
            drain()
            del layer, root
        drain()
        theme.signals().changed.emit('light')
        self.assertEqual(len(errors), 0, 'Destroyed backgrounds must not receive theme callbacks')
        self.assertTrue(all(reference() is None for reference in references),
                        'Global theme subscriptions must not retain deleted backgrounds')


if __name__ == '__main__':
    unittest.main()
