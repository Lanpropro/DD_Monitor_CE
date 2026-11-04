"""Offline recording service ownership, tail safety and segment lease regression."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.recording import RecordingManager, _Session
from ddm.recording_service import RecordingService
from ddm.plugins import PluginContext, PluginManager

APP = QApplication.instance() or QApplication([])


class RecordingServiceTests(unittest.TestCase):
    def test_snapshot_excludes_writing_tail_and_lease_protects_pruning(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            tile = Mock(room={'room_id': 'test', 'uname': '测试'})
            recorder = RecordingManager({'recording_replay_minutes': 1})
            recorder.timer.stop()
            session = _Session(tile, {'recording_replay_minutes': 1}, False, folder)
            session.process = Mock()
            session.process.poll.return_value = None
            session.active_pattern = folder / 'part-%05d.ts'
            parts = []
            for index in range(12):
                path = folder / f'part-{index:05d}.ts'
                path.write_bytes(b'completed-test-segment')
                parts.append(path)
            recorder.sessions[tile] = session
            host = SimpleNamespace(recorder=recorder, capture_control=Mock(),
                                   wall=SimpleNamespace(tiles=[tile]), settings={})
            context = SimpleNamespace(window=host, _active=True)
            service = RecordingService(context)
            source = service.sources()[0]
            snapshot = service.snapshot(source['source_id'], source['session_id'])
            self.assertEqual(snapshot['parts'], list(map(str, parts[:-1])))
            recorder._prune_cache(session)
            self.assertTrue(all(path.exists() for path in parts))
            recorder._delete_after_exports.update(parts[:-1])
            recorder._cleanup_parts()
            self.assertTrue(parts[0].exists())
            context._active = False
            with self.assertRaises(RuntimeError):
                service.snapshot(source['source_id'], source['session_id'])
            service.release(snapshot['lease'])
            self.assertFalse(any(path.exists() for path in parts[:-1]))
            self.assertTrue(parts[-1].exists())
            self.assertFalse(recorder._part_leases)

    def test_stale_session_and_unknown_action_are_rejected(self):
        tile = Mock(room={'room_id': 'test'})
        session = SimpleNamespace(session_id='new', stopping=False, retry_at=0,
                                  recording=True, created_at=1)
        host = SimpleNamespace(recorder=SimpleNamespace(sessions={tile: session}),
                               capture_control=Mock(), wall=SimpleNamespace(tiles=[tile]))
        service = RecordingService(SimpleNamespace(window=host, _active=True))
        with self.assertRaises(RuntimeError):
            service.control(str(id(tile)), 'stop', session_id='old')
        with self.assertRaises(ValueError):
            service.control(str(id(tile)), 'unknown', session_id='new')
        service.control(str(id(tile)), 'record', session_id='new')
        host.capture_control.start_capture.assert_called_once_with(tile, recording=True)

    def test_manager_unload_releases_owned_service_even_without_plugin_cleanup(self):
        recorder = Mock()
        manager = PluginManager(plugins_dir='unused', enabled=[])
        manager.window = SimpleNamespace(recorder=recorder)
        context = PluginContext(manager, 'test')
        context.recording._leases.add('lease')
        manager.unload()
        recorder.release_parts.assert_called_once_with('lease')
        self.assertFalse(context._active)


if __name__ == '__main__':
    unittest.main()
