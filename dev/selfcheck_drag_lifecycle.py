"""关注栏应用内拖拽：落点、鼠标捕获、取消、滚轮与移动合并；无账号或网络。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QWidget
from ddm import motion
from ddm.sidebar_drag import ROOM_MIME
from ddm.widgets import Sidebar


class DropTarget(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.received = []
        self.left = 0
        self.moves = 0

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(ROOM_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.moves += 1
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.left += 1

    def dropEvent(self, event):
        assert QWidget.mouseGrabber() is None, 'Drop callbacks must run after releasing mouse capture'
        self.received.append(bytes(event.mimeData().data(ROOM_MIME)).decode())
        event.acceptProposedAction()


class DragLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.animation = patch.object(motion, 'enabled', return_value=False)
        self.animation.start()
        self.native_drag = patch('ddm.widgets.QDrag', side_effect=AssertionError('Sidebar must not enter native drag'))
        self.native_drag.start()
        self.window = QWidget()
        self.window.setGeometry(-10000, -10000, 900, 750)
        self.sidebar = Sidebar([dict(room_id=str(i), uname=f'Fixture {i}', live=False)
                                for i in range(30)], self.window, auto_compact=False)
        self.sidebar.setGeometry(0, 0, 248, 700)
        self.target = DropTarget(self.window)
        self.target.setGeometry(300, 10, 500, 500)
        self.window.show()
        self.app.processEvents()
        self.session = self.sidebar.drag_session
        self.hit = None
        self.hit_test = patch.object(QApplication, 'widgetAt', side_effect=lambda _p: self.hit)
        self.hit_test.start()

    def tearDown(self):
        self.session.cancel()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.hit_test.stop()
        self.native_drag.stop()
        self.animation.stop()

    def start(self, item=None):
        item = item or self.sidebar.items()[0]
        QTest.mousePress(item, Qt.LeftButton, pos=QPoint(5, 5))
        self.move(item.mapToGlobal(QPoint(40, 40)), item)
        self.assertTrue(self.session.active)
        return item

    def move(self, global_pos, receiver=None, buttons=Qt.LeftButton):
        receiver = receiver or self.window
        event = QMouseEvent(QEvent.MouseMove, QPointF(receiver.mapFromGlobal(global_pos)),
                            QPointF(global_pos), Qt.NoButton, buttons, Qt.NoModifier)
        QApplication.sendEvent(receiver, event)

    def release(self, global_pos):
        event = QMouseEvent(QEvent.MouseButtonRelease, QPointF(self.window.mapFromGlobal(global_pos)),
                            QPointF(global_pos), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
        QApplication.sendEvent(self.window, event)
        self.assertFalse(self.session.active)
        self.assertFalse(self.session.timer.isActive())
        self.assertIsNone(self.session.ghost)
        self.assertIsNone(QWidget.mouseGrabber())
        self.assertTrue(all(not i.isHidden() for i in self.sidebar.visible_items()))

    def test_release_uses_latest_position_and_restores_card_without_click(self):
        clicked = Mock()
        self.sidebar.roomSelected.connect(clicked)
        item = self.start()
        self.hit = self.target
        self.release(self.target.mapToGlobal(QPoint(10, 10)))
        self.assertEqual(self.target.received, ['0'])
        clicked.assert_not_called()
        QTest.mouseClick(item, Qt.LeftButton)
        self.assertEqual(clicked.call_count, 1)

    def test_reorder_uses_existing_drop_logic(self):
        self.start()
        self.hit = self.sidebar.list_box
        other = self.sidebar.items()[2]
        self.release(other.mapToGlobal(QPoint(20, other.height()-1)))
        self.assertEqual([i.room['room_id'] for i in self.sidebar.items()][:3], ['1','2','0'])

    def test_smart_copy_and_collapsed_avatar_share_the_controller(self):
        folder = self.sidebar.create_folder('Smart', rule={'status':'any','platforms':['bilibili'],'display':'copy'})
        self.app.processEvents()
        copy = self.sidebar._smart_cards[(folder, '0')]
        self.start(copy)
        self.hit = self.target
        self.release(self.target.mapToGlobal(QPoint(20,20)))
        self.assertEqual(self.target.received, ['0'])
        self.sidebar.set_side('top')
        self.sidebar.resize(850, self.sidebar.height())
        self.sidebar.set_collapsed(True, animate=False)
        self.app.processEvents()
        strip = self.sidebar._head_strip
        avatar = strip._avatars['0']
        point = avatar.mapTo(strip, avatar.rect().center())
        self.hit = None
        QTest.mousePress(strip, Qt.LeftButton, pos=point)
        self.assertEqual(strip._press_room, '0')
        self.move(strip.mapToGlobal(point+QPoint(25,0)), strip)
        self.assertTrue(self.session.active)
        self.hit = self.target
        self.release(self.target.mapToGlobal(QPoint(20,20)))
        self.assertEqual(self.target.received, ['0','0'])

    def test_multiselect_folder_drop_and_smart_folder_rejection(self):
        folder = self.sidebar.create_folder('Normal')
        smart = self.sidebar.create_folder('Smart', rule={'status':'any','platforms':['bilibili'],'display':'copy'})
        self.sidebar.select_sort_item('0', Qt.ControlModifier)
        self.sidebar.select_sort_item('1', Qt.ControlModifier)
        self.start()
        self.hit = self.sidebar._folder_buttons[smart]
        self.release(self.hit.mapToGlobal(QPoint(10,10)))
        self.assertNotEqual(self.sidebar.folder_for('0'), smart)
        self.start()
        self.hit = self.sidebar._folder_buttons[folder]
        self.release(self.hit.mapToGlobal(QPoint(10,10)))
        self.assertEqual(self.sidebar.folder_for('0'), folder)
        self.assertEqual(self.sidebar.folder_for('1'), folder)

    def test_move_events_are_coalesced_and_pixmap_is_not_recaptured(self):
        item = self.start()
        self.hit = self.target
        with patch.object(item, '_drag_pixmap', side_effect=AssertionError('No repeated capture')):
            for x in range(100):
                self.move(self.target.mapToGlobal(QPoint(x, 10)))
            self.assertEqual(self.target.moves, 0)
            self.session._tick()
            self.assertEqual(self.target.moves, 1)
            self.assertEqual(self.session.ghost.pos(), self.session.position-self.session.hotspot)
        self.release(self.target.mapToGlobal(QPoint(120, 10)))
        self.assertEqual(self.target.received, ['0'])

    def test_cancel_escape_deactivate_close_and_lost_capture(self):
        for kind in ('escape', 'deactivate', 'hide', 'close', 'ungrab', 'missing-button'):
            with self.subTest(kind=kind):
                self.start()
                self.hit = self.target
                self.session.position = self.target.mapToGlobal(QPoint(20,20))
                self.session._tick()
                if kind == 'escape':
                    QTest.keyClick(self.window, Qt.Key_Escape)
                elif kind == 'missing-button':
                    self.move(self.session.position, buttons=Qt.NoButton)
                else:
                    event = {'deactivate':QEvent.ApplicationDeactivate,'hide':QEvent.Hide,
                             'close':QEvent.Close,'ungrab':QEvent.UngrabMouse}[kind]
                    QApplication.sendEvent(self.window, QEvent(event))
                self.assertFalse(self.session.active)
                self.assertFalse(self.session.timer.isActive())
                self.assertEqual(self.target.received, [])
                self.assertIsNone(QWidget.mouseGrabber())
                self.assertFalse(self.sidebar.items()[0].isHidden())
                self.hit = None

    def test_destroyed_source_cancels_session(self):
        item = self.start()
        self.sidebar.remove_room(item.room)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(self.session.active)
        self.assertIsNone(QWidget.mouseGrabber())

    def test_exception_in_target_restores_capture_and_placeholder(self):
        self.start()
        with patch.object(self.session, '_update_target', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.session.finish()
        self.assertFalse(self.session.active)
        self.assertIsNone(QWidget.mouseGrabber())
        self.assertFalse(self.session.timer.isActive())
        self.assertFalse(self.sidebar.items()[0].isHidden())

    def test_outside_drop_cancels_without_changing_order(self):
        before = self.sidebar.rooms()
        self.start()
        self.release(self.window.mapToGlobal(QPoint(-50,-50)))
        self.assertEqual(self.sidebar.rooms(), before)

    def test_target_transition_leaves_old_highlight_and_drops_only_once(self):
        self.start()
        self.hit = self.target
        self.session.position = self.target.mapToGlobal(QPoint(20,20))
        self.session._tick()
        self.assertIs(self.session.target, self.target)
        self.hit = self.sidebar.list_box
        self.session.position = self.sidebar.list_box.mapToGlobal(QPoint(20,20))
        self.session._tick()
        self.assertEqual(self.target.left, 1)
        self.hit = self.target
        self.release(self.target.mapToGlobal(QPoint(20,20)))
        self.assertEqual(self.target.received, ['0'])

    def test_another_application_window_can_receive_the_room(self):
        other = QWidget()
        other.setAttribute(Qt.WA_ShowWithoutActivating)
        receiver = DropTarget(other)
        receiver.resize(200,200)
        other.show()
        self.app.processEvents()
        try:
            self.start()
            self.hit = receiver
            self.release(receiver.mapToGlobal(QPoint(10,10)))
            self.assertEqual(receiver.received, ['0'])
        finally:
            other.close()
            other.deleteLater()

    def test_wheel_and_edge_scroll_stop_on_cancel(self):
        self.start()
        viewport = self.sidebar.scroll.viewport()
        position = viewport.mapToGlobal(viewport.rect().center())
        bar = self.sidebar.scroll.verticalScrollBar()
        before = bar.value()
        event = QWheelEvent(QPointF(self.window.mapFromGlobal(position)), QPointF(position),
                            QPoint(), QPoint(0,-120), Qt.LeftButton, Qt.NoModifier,
                            Qt.NoScrollPhase, False)
        QApplication.sendEvent(self.window, event)
        self.assertGreater(bar.value(), before)
        self.hit = self.sidebar.list_box
        self.session.position = viewport.mapToGlobal(QPoint(10,viewport.height()-2))
        self.session._tick()
        self.assertTrue(self.sidebar.list_box._scroll_timer.isActive())
        self.session.cancel()
        self.assertFalse(self.sidebar.list_box._scroll_timer.isActive())

    def test_hotspot_stays_inside_card_and_start_cannot_reenter(self):
        for point in (QPoint(-40,-40), QPoint(800,800)):
            item = self.sidebar.items()[0]
            QTest.mousePress(item, Qt.LeftButton, pos=QPoint(1,1))
            self.move(item.mapToGlobal(point), item)
            self.assertTrue(item.rect().contains(self.session.hotspot))
            ghost = self.session.ghost
            item.mouseMoveEvent(QMouseEvent(QEvent.MouseMove,QPointF(40,40),QPointF(),
                                Qt.NoButton,Qt.LeftButton,Qt.NoModifier))
            self.assertIs(self.session.ghost, ghost)
            self.session.cancel()

    def test_repeated_drag_layout_preserves_animation_progress(self):
        sidebar = Sidebar([{'room_id': '1', 'uname': 'Test'}])
        try:
            item = sidebar.items()[0]
            box = sidebar.list_box
            item.move(0, 0)
            box._glide_to(item, 0, 100, True)
            animation = box._animations[item]
            animation.setCurrentTime(75)
            position = item.pos()
            for _ in range(20):
                box._glide_to(item, 0, 100, True)
                self.assertIs(box._animations[item], animation)
                self.assertEqual(animation.currentTime(), 75)
                self.assertEqual(item.pos(), position)
            box._glide_to(item, 0, 20, True)
            self.assertEqual(box._animations[item].endValue(), QPoint(0, 20))
            box._glide_to(item, 0, 10, False)
            self.assertEqual(item.pos(), QPoint(0, 10))
        finally:
            sidebar.close()


if __name__ == '__main__':
    unittest.main()
