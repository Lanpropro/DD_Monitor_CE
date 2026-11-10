"""Isolated response, editor and playback-lifecycle regression; no account or network."""
import json
import gc
import math
import os
from pathlib import Path
import sys
import unittest
import weakref
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from ddm.audio_normalization import GainResponse, PRESETS, normalize_curve, preset_curve, response_preview
from ddm.audio_normalization_ui import AudioNormalizationEditor
from ddm.dialogs import GeneralSettingsPage, SettingsDialog
from ddm.player import TilePlayer


class ResponseTests(unittest.TestCase):
    def test_attack_hold_and_release_have_distinct_timing(self):
        curve = dict(preset_curve(), attack=1., hold=2., release=4.)
        response = GainResponse(curve)
        for _ in range(10):
            response.step(-6., .1)
        self.assertAlmostEqual(response.gain, -6 * (1 - math.exp(-3)), places=6)
        held = response.gain
        for _ in range(20):
            response.step(0., .1)
            self.assertAlmostEqual(response.gain, held, places=6)
        for _ in range(40):
            response.step(0., .1)
        self.assertAlmostEqual(response.gain, held * math.exp(-3), places=6)

    def test_silence_does_not_raise_background_and_limits_apply(self):
        response = GainResponse(dict(preset_curve(), hold=0., max_boost_db=2., max_cut_db=8.))
        response.measure(-40., 60.)
        self.assertAlmostEqual(response.gain, 2., places=5)
        for loudness in (-120., -60., float('nan'), float('inf')):
            held = response.gain
            self.assertEqual(response.measure(loudness, 20.), held)
        response.measure(0., 60.)
        self.assertAlmostEqual(response.gain, -8., places=5)
        held = response.gain
        response.measure(-120., 30.)
        self.assertEqual(response.gain, held)

    def test_settings_are_finite_independent_and_json_round_trip(self):
        first = preset_curve('spotify')
        first['attack'] = 9.
        self.assertEqual(preset_curve('spotify')['attack'], 3.)
        curve = normalize_curve(dict(preset='unknown', attack=-5., release=float('nan'),
                                    max_boost_db=True, target_lufs=1e20))
        self.assertEqual(curve['preset'], 'custom')
        self.assertEqual(curve['attack'], .1)
        self.assertEqual(curve['max_boost_db'], 3.)
        self.assertEqual(curve['target_lufs'], -10.)
        self.assertEqual(normalize_curve(json.loads(json.dumps(curve))), curve)

    def test_preview_uses_the_playback_response(self):
        curve = preset_curve('netflix')
        points = response_preview(curve)
        self.assertAlmostEqual(points[-1][0], curve['attack'] + curve['hold'] + curve['release'])
        self.assertTrue(all(-6. <= gain <= 0. for _, gain in points))
        response = GainResponse(curve)
        dt = points[1][0]
        for instant, gain in points[1:]:
            self.assertEqual(response.step(-6. if instant <= curve['attack'] else 0., dt), gain)


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_presets_manual_edits_drag_and_reset(self):
        dialog = AudioNormalizationEditor()
        dialog.resize(850, 540)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()
        for index, name in enumerate(PRESETS):
            dialog.presets.setCurrentIndex(index)
            self.assertEqual(dialog.values(), preset_curve(name))
        self.assertIn('非 Apple', dialog.description.text())
        dialog.controls['hold'].setValue(4.5)
        self.assertEqual(dialog.values()['preset'], 'custom')
        self.assertEqual(dialog.values()['hold'], 4.5)
        graph = dialog.graph
        start = graph.handles()[0].toPoint()
        QTest.mousePress(graph, Qt.LeftButton, pos=start)
        QTest.mouseMove(graph, start + QPoint(30, 0))
        QTest.mouseRelease(graph, Qt.LeftButton, pos=start + QPoint(30, 0))
        self.assertGreater(dialog.values()['attack'], 3.)
        self.assertAlmostEqual(graph.settings['attack'], dialog.controls['attack'].value(), places=1)
        dialog._reset()
        self.assertEqual(dialog.values(), preset_curve())
        dialog.close()

    def test_inline_page_edits_persistence_playback_toggle_and_reset(self):
        settings = {'volume_normalization': True, 'volume_normalization_curve': preset_curve()}
        page = GeneralSettingsPage(settings)
        self.addCleanup(page.deleteLater)
        editor = page.normalization_editor
        self.assertFalse(editor.isWindow())
        self.assertIs(editor.parentWidget(), page.sections.section('normalization'))
        self.assertFalse(any('响应曲线' in button.text() for button in page.findChildren(QPushButton)))
        editor.presets.setCurrentIndex(list(PRESETS).index('spotify'))
        self.assertEqual(page.values()['volume_normalization_curve'], preset_curve('spotify'))
        self.assertEqual(settings['volume_normalization_curve'], preset_curve())
        saved = json.loads(json.dumps(page.values()))
        restored = GeneralSettingsPage(saved)
        self.addCleanup(restored.deleteLater)
        self.assertEqual(restored.values()['volume_normalization_curve'], preset_curve('spotify'))
        page._checks['volume_normalization'].setChecked(False)
        self.assertTrue(editor.isEnabled())
        self.assertEqual(page.values()['volume_normalization_curve'], preset_curve('spotify'))
        page.reset()
        self.assertEqual(page.values()['volume_normalization_curve'], preset_curve())

    def test_disabled_playback_still_allows_preset_selection_and_autosave(self):
        from ddm.ui import SelectControl
        dialog = SettingsDialog({'volume_normalization': False}, {}, preview=True)
        self.addCleanup(dialog.deleteLater)
        editor = dialog.general_page.normalization_editor
        self.assertIsInstance(editor.presets, SelectControl)
        dialog.auto_save.start()
        requests = []
        def save(changes):
            requests.append(changes)
            dialog.auto_save.acknowledge()
        dialog.auto_save.requested.connect(save)
        dialog.resize(1200, 900)
        dialog.show()
        self.app.processEvents()
        self.assertTrue(editor.presets.isEnabled())
        editor.presets.setFocus()
        # Exercise the enabled combobox's keyboard path, not just its setter.
        QTest.keyClick(editor.presets, Qt.Key_Down)
        self.assertEqual(editor.values(), preset_curve('spotify'))
        self.assertEqual(editor.graph.settings, preset_curve('spotify'))
        self.assertEqual(editor.controls['target_lufs'].value(), -14.)
        self.assertTrue(editor.steppers['target_lufs'].minus.isEnabled())
        dialog.auto_save.flush()
        self.assertFalse(dialog.settings()['volume_normalization'])
        self.assertEqual(requests[-1]['settings']['volume_normalization_curve'], preset_curve('spotify'))
        editor._reset()
        dialog.auto_save.flush()
        self.assertEqual(requests[-1]['settings']['volume_normalization_curve'], preset_curve())
        self.assertFalse(dialog.settings()['volume_normalization'])
        restored = GeneralSettingsPage(json.loads(json.dumps(dialog.settings())))
        self.addCleanup(restored.deleteLater)
        self.assertEqual(restored.normalization_editor.values(), preset_curve())
        self.assertFalse(restored.values()['volume_normalization'])
        dialog.close()

    def test_parent_settings_cancel_keeps_original_curve_and_save_includes_inline_edits(self):
        settings = {'volume_normalization': True, 'volume_normalization_curve': preset_curve()}
        original = json.loads(json.dumps(settings))
        dialog = SettingsDialog(settings, {}, preview=True)
        self.addCleanup(dialog.deleteLater)
        editor = dialog.general_page.normalization_editor
        editor.controls['hold'].setValue(4.5)
        self.assertEqual(dialog.settings()['volume_normalization_curve']['hold'], 4.5)
        dialog.reject()
        self.assertEqual(settings, original)
        restored = SettingsDialog(settings, {}, preview=True)
        self.addCleanup(restored.deleteLater)
        self.assertEqual(restored.general_page.normalization_editor.values(), preset_curve())
        restored.general_page.normalization_editor.presets.setCurrentIndex(list(PRESETS).index('netflix'))
        self.assertEqual(restored.settings()['volume_normalization_curve'], preset_curve('netflix'))

    def test_player_commands_pause_channel_changes_and_release(self):
        widget = QWidget()
        self.addCleanup(widget.deleteLater)
        player = TilePlayer(widget)
        core = Mock(core_idle=False)
        core._get_property.return_value = {'lavfi.r128.M': '-10.0'}
        player.player = core
        curve = dict(preset_curve('netflix'), hold=.5)
        player.set_volume_normalization(True, curve)
        self.assertTrue(player._normalizer.timer.isActive())
        with patch('ddm.audio_normalization.time.monotonic', return_value=player._normalizer.last_time + .1):
            player._normalizer.tick()
        command = core.command.call_args.args
        self.assertEqual(command[:3], ('af-command', 'ddm_gain', 'volume'))
        self.assertEqual(command[-1], 'volume')
        self.assertLess(float(command[-2][:-2]), 0.)
        core.command.reset_mock()
        player.paused = True
        player._normalizer.tick()
        core.command.assert_not_called()
        player.set_audio_channel(3)
        self.assertIn('ddm_meter', core.af)
        self.assertIn('pan=', core.af)
        self.assertEqual(player.normalization_curve, normalize_curve(curve))
        player.set_volume_normalization(False, curve)
        self.assertNotIn('ddm_meter', core.af)
        self.assertFalse(player._normalizer.timer.isActive())
        player.release()
        core.command.reset_mock()
        player._normalizer.tick()
        core.command.assert_not_called()

    def test_player_release_does_not_need_cyclic_garbage_collection(self):
        widget = QWidget()
        self.addCleanup(widget.deleteLater)
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            player = TilePlayer(widget)
            reference = weakref.ref(player)
            player.release()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            del player
            self.assertIsNone(reference())
        finally:
            if was_enabled:
                gc.enable()


if __name__ == '__main__':
    unittest.main(verbosity=2)
