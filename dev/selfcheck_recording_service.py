"""Offline recording service ownership, tail safety and segment lease regression."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from xml.etree.ElementTree import fromstring

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.recording import RecordingManager, RecordingSession, _Session
from ddm.recording_service import RecordingService
from ddm.auto_recording import AutoRecording
from ddm.app_notices import AppNotices
from ddm.windows_recording_notifications import toast_xml
from ddm.plugins import PluginContext, PluginManager

APP = QApplication.instance() or QApplication([])


class RecordingServiceTests(unittest.TestCase):
    def test_background_recording_uses_the_recording_center_and_waits_for_next_live(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = {'recording_dir': '', 'streamer_defaults': {
                '1001': {'name': '示例主播', 'recording': 720, 'auto_record': True},
                '1002': {'name': '旧配置'},
            }}
            resolve = Mock()
            recorder = RecordingManager(settings, source_resolver=resolve)
            recorder.timer.stop()
            host = SimpleNamespace(settings=settings, recorder=recorder, _closing=False,
                                   wall=SimpleNamespace(tiles=[]), _pending_capture={},
                                   refresh_status=Mock(), capture_control=Mock())
            auto = AutoRecording(host)
            service = RecordingService(SimpleNamespace(window=host, _active=True))
            transitions = []
            recorder.backgroundTransition.connect(lambda event, _room: transitions.append(event))
            live = {'1001': {'live': True, 'live_start_ts': 100}, '1002': {'live': True}}
            with patch('ddm.recording.ffmpeg_path', return_value='fixture-ffmpeg'), \
                    patch.object(recorder, '_free_enough', return_value=True):
                auto.apply_status(live)
                resolve.assert_not_called()
                settings['recording_dir'] = directory
                auto.settings_changed()
                host.refresh_status.assert_called_once_with(force=True)
                auto.apply_status(live)
                auto.apply_status(live)
                resolve.assert_called_once()
                source = auto.source_for('1001')
                self.assertEqual(source.quality, 720)
                self.assertEqual(source.room['uname'], '示例主播')
                self.assertIsNone(auto.source_for('1002'))
                row, = service.sources()
                self.assertEqual(row['state'], 'reconnecting')
                self.assertEqual(row['room']['room_id'], '1001')
                auto.apply_status({'1001': {'live': False, 'live_known': False}})
                self.assertIs(auto.source_for('1001'), source)
                recorder.sessions[source].started_at = 1
                service.control(row['source_id'], 'stop', session_id=row['session_id'])
                self.assertFalse(service.sources())
                self.assertFalse(transitions, '手动停止不会被当作下播')
                auto.apply_status(live)
                self.assertFalse(service.sources())
                auto.apply_status({'1001': {'live': True, 'live_start_ts': 200}})
                self.assertEqual(resolve.call_count, 2)
                self.assertIsNot(auto.source_for('1001'), source)
                auto.apply_status({'1001': {'live': False}})
                self.assertFalse(service.sources())
                self.assertFalse(transitions, '尚未开录的任务下播时也不发送停止通知')
                auto.apply_status({'1001': {'live': True, 'live_start_ts': 300}})
                self.assertEqual(resolve.call_count, 3)
                session = recorder.sessions[auto.source_for('1001')]
                session.started_at = 1
                process = session.process = Mock(returncode=0)
                process.poll.return_value = None
                auto.apply_status({'1001': {'live': False}})
                self.assertFalse(transitions, '录制进程仍在收尾时不会提前通知')
                process.stdin.write.assert_called_once_with(b'q\n')
                process.poll.return_value = 0
                recorder._poll()
                auto.apply_status({'1001': {'live': False}})
                self.assertEqual(transitions, ['stopped_offline'])
                auto.apply_status({'1001': {'live': True, 'live_start_ts': 400}})
                settings['recording_enabled'] = False
                auto.settings_changed()
                self.assertFalse(service.sources())
                self.assertFalse(auto.monitored_rooms())

    def test_only_opted_in_recording_transitions_use_windows(self):
        host = SimpleNamespace(settings={}, _closing=False, _show_notice=Mock())
        notices = AppNotices(host)
        room = {'room_id': '1001', 'uname': '示例主播'}
        with patch('ddm.windows_recording_notifications.send_recording_notification') as send:
            notices.record_notice('示例主播 开始自动录制', room)
            send.assert_not_called()
            notices.background_recording_transition('started', room)
            send.assert_not_called()
            host.settings.update(notice_windows_recording=True, notifications_enabled=False)
            notices.background_recording_transition('started', room)
            notices.record_notice('示例主播 重新获取录制地址失败：网络断开；稍后重试', room)
            notices.record_notice('已保存录制：C:/fixture/示例.mp4', room)
            notices.background_recording_transition('stopped_offline', room)
            notices.record_notice('导出录制失败（原始分段保留）：C:/fixture/示例.mp4', room)
            self.assertEqual([call.args for call in send.call_args_list], [
                ('开播 · 已开启自动录制', '示例主播'),
                ('下播 · 已停止自动录制', '示例主播'),
            ])
            self.assertEqual(host._show_notice.call_count, 4)
            host.settings['notice_windows_recording'] = False
            notices.background_recording_transition('started', room)
            self.assertEqual(send.call_count, 2)
        xml = fromstring(toast_xml('测试 <A>', '文件 & 目录'))
        self.assertEqual(xml.get('activationType'), 'protocol')
        self.assertEqual([node.text for node in xml.iter('text')], ['测试 <A>', '文件 & 目录'])

    def test_public_backend_selection_and_chat_delivery(self):
        class DualSession(RecordingSession):
            pass
        recorder = RecordingManager({})
        recorder.timer.stop()
        service = RecordingService(SimpleNamespace(window=SimpleNamespace(recorder=recorder, capture_control=Mock()), _active=True))
        service.register_backend(DualSession, enabled=False)
        service.select_backend(DualSession)
        self.assertTrue(recorder.supports_replay)
        tile = Mock(room={'room_id': 'offline'})
        session = DualSession(tile, {}, True, Path('unused'))
        session.record_danmaku = Mock()
        recorder.sessions[tile] = session
        service.record_danmaku('offline', {'text': 'test'})
        session.record_danmaku.assert_called_once_with({'text': 'test'})
        service.record_danmaku('other', {'text': 'ignored'})
        with self.assertRaisesRegex(RuntimeError, '请先停止'):
            service.select_backend()
        recorder.sessions.clear()
        service.select_backend()
        self.assertIs(recorder.session_factory, RecordingSession)
        service.close()

    def test_capture_modes_are_exclusive_and_running_captures_block_switch(self):
        class ClipSession(RecordingSession):
            supports_replay = False
        recorder = RecordingManager({})
        recorder.timer.stop()
        host = SimpleNamespace(recorder=recorder, capture_control=Mock())
        service = RecordingService(SimpleNamespace(window=host, _active=True))
        service.register_backend(ClipSession)
        self.assertFalse(recorder.supports_replay)
        self.assertFalse(recorder.start(Mock(), recording=False))
        self.assertFalse(recorder.save_replay(Mock()))
        service.set_backend_enabled(False)
        self.assertIs(recorder.session_factory, RecordingSession)
        self.assertTrue(recorder.supports_replay)
        recorder.sessions['running'] = object()
        with self.assertRaisesRegex(RuntimeError, '请先停止'):
            service.set_backend_enabled(True)
        self.assertIs(recorder.session_factory, RecordingSession)
        recorder.sessions.clear()
        service.set_backend_enabled(True)
        self.assertIs(recorder.session_factory, ClipSession)
        service.close()
        self.assertIs(recorder.session_factory, RecordingSession)

    def test_backend_snapshot_preserves_init_map_and_pins_both_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            media, init = folder / 'part.mp4', folder / 'init.mp4'
            media.write_bytes(b'closed fragment')
            init.write_bytes(b'fragment initialization')

            class HlsSession(RecordingSession):
                def snapshot_info(self, parts):
                    return {'index_format': 'hls', 'segments': [
                        {'path': str(parts[0]), 'duration': 2, 'init': str(init)}]}

            tile = Mock(room={'room_id': 'test'})
            recorder = RecordingManager({})
            recorder.timer.stop()
            session = HlsSession(tile, {}, True, folder)
            session.parts = [media]
            recorder.sessions[tile] = session
            host = SimpleNamespace(recorder=recorder, capture_control=Mock(), wall=SimpleNamespace(tiles=[tile]))
            service = RecordingService(SimpleNamespace(window=host, _active=True))
            snapshot = service.snapshot(str(id(tile)), session.session_id)
            self.assertEqual(snapshot['index_format'], 'hls')
            self.assertEqual(snapshot['segments'][0]['init'], str(init))
            recorder._delete_after_exports.update((media, init))
            recorder._cleanup_parts()
            self.assertTrue(media.exists() and init.exists())
            service.release(snapshot['lease'])
            self.assertFalse(media.exists() or init.exists())

    def test_backend_ownership_unload_and_running_session_are_independent(self):
        class PluginSession(RecordingSession):
            pass

        recorder = RecordingManager({})
        recorder.timer.stop()
        tile = Mock(room={'room_id': 'test'})
        session = PluginSession(tile, {}, True, Path('unused'))
        recorder.sessions[tile] = session
        host = SimpleNamespace(recorder=recorder, capture_control=Mock())
        first = RecordingService(SimpleNamespace(window=host, _active=True))
        second = RecordingService(SimpleNamespace(window=host, _active=True))
        first.register_backend(PluginSession)
        self.assertIs(recorder.session_factory, PluginSession)
        with self.assertRaises(RuntimeError):
            second.register_backend(PluginSession)
        with self.assertRaises(TypeError):
            first.register_backend(object)
        second.close()
        self.assertIs(recorder.session_factory, PluginSession)
        first.close()
        self.assertIs(recorder.session_factory, RecordingSession)
        self.assertIs(recorder.sessions[tile], session)
        self.assertFalse(session.stopping)

    def test_live_recording_rejects_old_sessions_and_unavailable_indexes(self):
        tile = Mock(room={'room_id': 'test'})
        session = RecordingSession(tile, {}, True, Path('unused'))
        recorder = SimpleNamespace(sessions={tile: session})
        host = SimpleNamespace(recorder=recorder, capture_control=Mock(), wall=SimpleNamespace(tiles=[tile]))
        service = RecordingService(SimpleNamespace(window=host, _active=True))
        with self.assertRaisesRegex(RuntimeError, '会话已变化'):
            service.live_recording(str(id(tile)), 'old')
        with self.assertRaisesRegex(RuntimeError, '尚无可回看'):
            service.live_recording(str(id(tile)), session.session_id)

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
