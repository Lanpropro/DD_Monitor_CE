"""One wall's border session, cancellation and Qt ownership; synthetic panes, no media."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from ddm.wall_border import WallBorderInteraction, WallPaneBorder, WallResizePreview
from ddm.wall_widgets import WallGrid


class WallBorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.wall = WallGrid([], layout_id='corner')
        self.wall.setAttribute(Qt.WA_ShowWithoutActivating)
        self.wall.setGeometry(-20000, -20000, 1200, 800)
        self.wall.show()
        self.app.processEvents()

    def tearDown(self):
        if isValid(self.wall):
            self.wall.close()
            self.wall.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def begin(self):
        border = self.wall._pane_borders[self.wall.tiles[0]]
        edges = {'right': border.targets['right']}
        origin = QPoint(100, 100)
        self.wall._begin_border_drag(border, edges, origin)
        self.assertIs(self.wall._border_drag['border'], border)
        return border, origin

    def test_ownership_and_legacy_aliases_have_one_session(self):
        from ddm import wall_widgets, widgets
        owner = self.wall._border_interaction
        self.assertIsInstance(owner, WallBorderInteraction)
        self.assertIs(owner.parent(), self.wall)
        self.assertIs(owner.timer.parent(), owner)
        self.assertIs(owner.preview.parentWidget(), self.wall)
        self.assertIs(owner.preview, self.wall._border_preview)
        self.assertIs(owner.timer, self.wall._border_drag_timer)
        for name, value in (('WallPaneBorder', WallPaneBorder), ('WallResizePreview', WallResizePreview)):
            self.assertIs(getattr(wall_widgets, name), value)
            self.assertIs(getattr(widgets, name), value)
        self.begin()
        self.assertIs(self.wall._border_drag, owner.drag)
        self.wall._cancel_border_drag()
        self.assertIsNone(owner.drag)
        self.assertIsNone(self.wall._border_drag)

    def test_preview_defers_geometry_and_release_commits_once(self):
        wall = self.wall
        tiles = list(wall.tiles)
        before = [tile.geometry() for tile in tiles]
        changed = []
        wall.cornerRatiosChanged.connect(lambda: changed.append(True))
        border, origin = self.begin()
        wall._move_border_drag(origin + QPoint(80, 0))
        self.assertTrue(wall._border_drag_timer.isActive())
        wall._flush_border_drag()
        self.assertTrue(wall._border_preview.isVisible())
        self.assertEqual([tile.geometry() for tile in tiles], before)
        wall._finish_border_drag(border, origin + QPoint(80, 0))
        self.assertEqual(changed, [True])
        self.assertEqual(wall.tiles, tiles)
        self.assertNotEqual(wall.tiles[0].geometry(), before[0])
        self.assertIsNone(wall._border_drag)
        self.assertFalse(wall._border_drag_timer.isActive())
        self.assertFalse(wall._border_preview.isVisible())
        QTest.qWait(50)
        self.assertEqual(changed, [True])

    def test_cancel_discards_pending_preview_and_leaves_ratios(self):
        wall = self.wall
        before = wall.corner_ratios()
        border, origin = self.begin()
        wall._move_border_drag(origin + QPoint(60, 0))
        wall._flush_border_drag()
        wall._cancel_border_drag()
        QTest.qWait(50)
        self.assertEqual(wall.corner_ratios(), before)
        self.assertIsNone(wall._border_pending)
        self.assertIsNone(wall._border_drag)
        self.assertFalse(wall._border_drag_timer.isActive())
        self.assertFalse(wall._border_preview.isVisible())
        self.assertTrue(all(not item.highlights for item in wall._pane_borders.values()))

    def test_layout_change_and_hide_cancel_the_session(self):
        wall = self.wall
        _, origin = self.begin()
        wall._move_border_drag(origin + QPoint(80, 0))
        wall.set_layout('2x2')
        QTest.qWait(50)
        self.assertIsNone(wall._border_drag)
        self.assertFalse(wall._border_drag_timer.isActive())
        wall.set_layout('corner')
        _, origin = self.begin()
        wall._move_border_drag(origin + QPoint(80, 0))
        wall.hide()
        QTest.qWait(50)
        self.assertIsNone(wall._border_drag)
        self.assertFalse(wall._border_preview.isVisible())
        self.assertFalse(wall._border_drag_timer.isActive())

    def test_deleting_wall_releases_session_timer_and_preview(self):
        wall = self.wall
        owner = wall._border_interaction
        timer, preview = owner.timer, owner.preview
        _, origin = self.begin()
        wall._move_border_drag(origin + QPoint(80, 0))
        wall.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        for child in (wall, owner, timer, preview):
            self.assertFalse(isValid(child))


if __name__ == '__main__':
    unittest.main()
