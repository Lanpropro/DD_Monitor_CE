"""Issue149 evidence mechanics; deliberate bad geometry is not a real reproduction."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPoint, QPropertyAnimation, Qt
from PySide6.QtWidgets import QApplication, QWidget
from ddm.responsiveness import FolderMotionCapture, Probe
from ddm.widgets import Sidebar


class SidebarEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'folder-motion.jsonl'
        self.probe = Probe(self.path)
        self.addCleanup(self.probe.stop)
        self.sidebar = Sidebar([{'room_id': str(i), 'uname': 'PRIVATE_NAME_' + str(i)} for i in range(6)], auto_compact=False)
        self.sidebar.setAttribute(Qt.WA_ShowWithoutActivating)
        self.sidebar.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        self.sidebar.set_folders([
            {'id': 'PRIVATE_FOLDER_A', 'name': 'PRIVATE_TITLE_A', 'type': 'normal',
             'rooms': ['0', '1', '2'], 'collapsed': False},
            {'id': 'PRIVATE_FOLDER_B', 'name': 'PRIVATE_TITLE_B', 'type': 'normal',
             'rooms': ['3', '4', '5'], 'collapsed': True}])
        self.sidebar.setGeometry(-14000, -14000, 248, 750)
        self.sidebar.show()
        self.app.processEvents()
        self.addCleanup(self.sidebar.close)
        self.capture = FolderMotionCapture(self.probe, self.sidebar, extended=True)
        self.addCleanup(self.capture.close)
        self.evidence = self.capture.evidence

    def snapshot(self):
        widgets = [self.sidebar, self.sidebar.list_box, self.sidebar.scroll, self.sidebar.scroll.viewport()]
        widgets += self.sidebar._items + list(self.sidebar._folder_buttons.values())
        widgets += [item.thumb.video for item in self.sidebar._items]
        widgets += [item.thumb for item in self.sidebar._items]
        return (deepcopy(self.sidebar.folders),
                [(widget.geometry(), widget.isHidden(), widget.internalWinId(),
                  widget.testAttribute(Qt.WA_NativeWindow)) for widget in widgets],
                self.sidebar.scroll.verticalScrollBar().value())

    def test_inspection_is_read_only_and_independent_of_layout_and_native_creation(self):
        before = self.snapshot()
        with patch.object(self.sidebar, 'folder_entries', side_effect=AssertionError('No layout mutation')), \
                patch.object(self.sidebar.list_box, 'relayout', side_effect=AssertionError('No relayout')):
            with patch.object(QWidget, 'winId', side_effect=AssertionError('No native window creation')), \
                    patch.object(QWidget, 'grab', side_effect=AssertionError('No screenshots')), \
                    patch.object(QWidget, 'repaint', side_effect=AssertionError('No forced repaint')):
                state = self.evidence.inspect(detail=True)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(state['mismatches'], 0)
        self.assertFalse(state['model']['truncated'])
        self.assertTrue(state['widgets'])
        self.assertNotIn('PRIVATE_', json.dumps(state))

    def test_stale_animation_target_wrong_geometry_and_hidden_occupants_are_visible(self):
        item = self.sidebar._items[0]
        expected, _model = self.evidence.expected_layout()
        correct = expected[item]
        item.move(correct.topLeft() + QPoint(0, 400))
        animation = QPropertyAnimation(item, b'pos', item)
        animation.setEndValue(item.pos())
        self.sidebar.list_box._animations[item] = animation
        state = self.evidence.inspect()
        row = next(row for row in state['rows'] if row['row'] == self.evidence.stats[item]['row'])
        self.assertEqual(row['expected'], list(correct.getRect()))
        self.assertNotEqual(row['expected'][:2], [animation.endValue().x(), animation.endValue().y()])
        self.assertTrue(row['mismatch'])
        self.assertFalse(state['in_transition'])
        hidden_item = self.sidebar._items[1]
        hidden_item.hide()
        state = self.evidence.inspect()
        self.assertGreaterEqual(state['mismatches'], 2)
        self.assertEqual(item.y(), correct.y() + 400, 'Capture must leave bad geometry intact')
        self.assertTrue(hidden_item.isHidden())

    def test_expected_slots_follow_compact_orientation_search_and_smart_copies(self):
        for compact in (True, False):
            self.sidebar.set_card_mode(compact)
            self.sidebar.list_box.relayout(animate=False)
            self.assertEqual(self.evidence.inspect()['mismatches'], 0)
        for collapsed in (True, False):
            self.sidebar.set_collapsed(collapsed, animate=False)
            self.sidebar.list_box.relayout(animate=False)
            self.assertEqual(self.evidence.inspect()['mismatches'], 0)
        self.sidebar.set_side('top')
        self.sidebar.list_box.relayout(animate=False)
        self.assertEqual(self.evidence.inspect()['mismatches'], 0)
        self.sidebar.set_side('left')
        self.sidebar.filter_text = 'PRIVATE_NAME_0'
        self.sidebar.refresh_filter()
        self.assertEqual(self.evidence.inspect()['mismatches'], 0)
        self.sidebar.filter_text = ''
        folders = deepcopy(self.sidebar.folders)
        folders.append({'id': 'PRIVATE_COPY', 'name': 'PRIVATE_COPY_TITLE', 'type': 'smart',
                        'collapsed': False, 'sort': 'name', 'rule': {'display': 'copy', 'sources': [], 'status': 'any'}})
        self.sidebar.set_folders(folders)
        self.sidebar.list_box.relayout(animate=False)
        state = self.evidence.inspect()
        self.assertEqual(state['model']['missing_widgets'], 0)
        self.assertEqual(state['mismatches'], 0)

    def test_drag_restore_generation_and_paint_event_filter_are_recorded(self):
        before = [folder['collapsed'] for folder in self.sidebar.folders]
        generation = self.evidence.generation
        self.sidebar.start_folder_drag()
        self.assertEqual(self.evidence.inspect()['drag']['restore_count'], len(before))
        self.sidebar.end_folder_drag()
        self.assertEqual([folder['collapsed'] for folder in self.sidebar.folders], before)
        self.assertEqual(self.evidence.inspect()['drag']['restore_count'], 0)
        self.assertGreater(self.evidence.generation, generation)
        item = self.sidebar._items[0]
        count = self.evidence.stats[item]['paints']
        from PySide6.QtGui import QPaintEvent
        self.assertFalse(self.evidence.eventFilter(item, QPaintEvent(item.rect())))
        self.assertGreater(self.evidence.stats[item]['paints'], count)
        viewport = self.sidebar.scroll.viewport()
        self.app.sendEvent(viewport, QEvent(QEvent.UpdateRequest))
        self.assertGreater(self.evidence.stats[viewport]['updates'], 0)
        stages = [event['stage'] for event in self.evidence.events]
        self.assertIn('sidebar.start_folder_drag:before', stages)
        self.assertIn('sidebar.end_folder_drag:after', stages)
        self.assertIn('layout:after', stages)

    def test_old_animation_generation_and_stops_remain_distinguishable(self):
        with patch('ddm.motion.enabled', return_value=True):
            self.sidebar.toggle_folder('PRIVATE_FOLDER_B', animate=True)
        animations = list(self.evidence.animations)
        self.assertTrue(animations)
        first_generation = self.evidence.generation
        self.sidebar.list_box.relayout(animate=False)
        self.assertGreater(self.evidence.generation, first_generation)
        self.assertTrue(any(event['stage'] == 'animation:state' and
                            event['born_generation'] < event['generation']
                            for event in self.evidence.motion_events))
        self.assertFalse(self.evidence.inspect()['running'])

    def test_history_payload_limits_privacy_and_stop(self):
        self.sidebar.add_rooms([{'room_id': str(index), 'uname': 'PRIVATE_EXTRA_' + str(index)}
                                for index in range(6, 70)])
        self.sidebar.set_card_mode(False)
        self.sidebar.resize(248, 1200)
        folders = deepcopy(self.sidebar.folders)
        folders += [{'id': 'PRIVATE_LARGE_' + str(index), 'name': 'PRIVATE_HEADER_' + str(index),
                     'type': 'normal', 'rooms': [], 'collapsed': True} for index in range(35)]
        self.sidebar.set_folders(folders)
        self.app.processEvents()
        for _ in range(35):
            self.evidence.poll()
        for _ in range(200):
            self.evidence.mark('bounded-fixture')
        self.assertEqual(len(self.evidence.history), 20)
        self.assertEqual(len(self.evidence.events), 96)
        self.capture.snapshot()
        for _ in range(45):
            self.capture.frame()
        self.capture.finish('fixture')
        record = json.loads(self.path.read_text(encoding='utf-8').splitlines()[-1])
        self.assertEqual(record['schema'], 2)
        self.assertTrue(record['before'] and record['evidence_after']['widgets'])
        self.assertLess(len(json.dumps(record)), 262144)
        self.assertTrue(record['evidence_after']['folders_truncated'])
        self.assertNotIn('PRIVATE_', json.dumps(record))
        self.capture.close()
        count = len(self.evidence.events)
        self.sidebar.list_box.relayout(animate=False)
        self.evidence.poll()
        self.assertFalse(self.evidence.timer.isActive())
        self.assertEqual(len(self.evidence.events), count)

    def test_wrapped_operations_preserve_results_and_exceptions(self):
        target = self.sidebar.drag_session
        self.evidence.stop()
        cancel_slot = target.cancel
        with patch.object(target, 'finish', return_value='original-result'):
            from ddm.sidebar_diagnostics import SidebarEvidence
            evidence = SidebarEvidence(self.sidebar, self.probe)
            try:
                self.assertEqual(target.cancel, cancel_slot, 'Observing cleanup must not replace the Qt cancel slot')
                self.assertEqual(target.finish(), 'original-result')
            finally:
                evidence.stop()
            self.assertEqual(target.cancel, cancel_slot, 'Qt cancellation signal slot identity must stay stable')
        with patch.object(target, 'finish', side_effect=ValueError('PRIVATE_EXCEPTION')):
            evidence = SidebarEvidence(self.sidebar, self.probe)
            try:
                with self.assertRaises(ValueError):
                    target.finish()
                self.assertNotIn('PRIVATE_EXCEPTION', json.dumps(list(evidence.events)))
            finally:
                evidence.stop()

    def test_existing_native_video_handle_is_observed_without_creating_others(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Native Windows window rectangle requires windows backend')
        video = self.sidebar._items[3].thumb.video  # Its folder is collapsed: inspect existing hidden surfaces too.
        video.winId()  # Only the fixture creates its preview surface, before capture.
        before = self.snapshot()
        with patch.object(QWidget, 'winId', side_effect=AssertionError('No native creation')):
            state = self.evidence.inspect(detail=True)
        observed = next(row for row in state['widgets'] if row['hwnd'] == hex(int(video.internalWinId())))
        self.assertIn('native', observed)
        self.assertGreater(state['hidden_native_candidates'], 0)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
