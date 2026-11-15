"""Offline checks for player teardown and recovery scheduling lifetimes."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid
from ddm.player import TilePlayer
from ddm.playback_recovery import PlaybackRecovery


class PlayerLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_native_sibling_policy_is_restored_when_window_creation_fails(self):
        flag = Qt.AA_DontCreateNativeWidgetSiblings
        previous = QCoreApplication.testAttribute(flag)
        video = QWidget()
        player = TilePlayer(video, silent=True)
        try:
            with patch.object(video, 'winId', side_effect=RuntimeError('fixture')), \
                    patch('ddm.player.mpv.MPV') as core:
                with self.assertRaisesRegex(RuntimeError, 'fixture'):
                    player.bind()
                core.assert_not_called()
            self.assertEqual(QCoreApplication.testAttribute(flag), previous)
        finally:
            player.release()
            video.close()

    def test_audio_output_is_not_retained_until_gui_thread_termination(self):
        for silent in (False, True):
            with self.subTest(silent=silent), patch('ddm.player.mpv.MPV') as create:
                widget = QWidget()
                player = TilePlayer(widget, silent=silent)
                try:
                    player.bind()
                    options = create.call_args.kwargs
                    self.assertIs(options.get('gapless_audio'), False)
                    self.assertEqual(options['ao'], 'null' if silent else 'wasapi')
                    self.assertEqual(options['audio'], 'no' if silent else 'auto')
                    self.assertIs(options['force_window'], False)
                    self.assertTrue(options['idle'])
                    self.assertTrue(options['keep_open'])
                    player.bind()
                    self.assertEqual(create.call_count, 1)
                    player.release()
                    player.release()
                    create.return_value.terminate.assert_called_once_with()
                finally:
                    player.release()
                    widget.close()

    def test_rebound_core_keeps_the_audio_teardown_option(self):
        widget = Mock()
        widget.winId.side_effect = (100, 200)
        with patch('ddm.player.mpv.MPV', side_effect=(Mock(), Mock())) as create:
            player = TilePlayer(widget)
            try:
                player.bind()
                first = player.player
                player.bind()
                first.terminate.assert_called_once_with()
                self.assertEqual(create.call_count, 2)
                for call in create.call_args_list:
                    self.assertIs(call.kwargs.get('gapless_audio'), False)
            finally:
                player.release()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows embedded GPU output')
    def test_normal_player_opens_output_only_when_local_media_is_ready(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Requires native Windows Qt')
        from ddm.video_surface import VideoSurface
        widget = VideoSurface()
        widget.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        widget.setAttribute(Qt.WA_ShowWithoutActivating)
        widget.setGeometry(-15000, -15000, 320, 180)
        widget.show()
        self.app.processEvents()
        player = TilePlayer(widget)
        player.set_muted(True)
        def pump(milliseconds=30):
            loop = QEventLoop()
            QTimer.singleShot(milliseconds, loop.quit)
            loop.exec()
        try:
            with tempfile.TemporaryDirectory() as temp:
                source = str(Path(temp) / 'blue.png')
                image = QImage(160, 90, QImage.Format_RGB32)
                image.fill(Qt.blue)
                self.assertTrue(image.save(source))
                player.bind()
                self.assertFalse(player._prop('current-vo'), 'Idle binding must not initialize GPU output')
                core = player.player
                for index in range(2):
                    player.play(source)
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        pump()
                        if player._prop('vo-configured', False):
                            break
                    self.assertTrue(player._prop('vo-configured', False), 'Local image did not reach video output')
                    self.assertIs(player.player, core)
                    self.assertEqual(player._prop('current-vo'), 'gpu')
                    screenshot = str(Path(temp) / f'frame-{index}.png')
                    core.command('screenshot-to-file', screenshot, 'video')
                    captured = QImage(screenshot)
                    self.assertFalse(captured.isNull())
                    self.assertGreater(captured.pixelColor(captured.width()//2, captured.height()//2).blue(), 200)
                    player.stop(keep_core=True)
                    pump()
                # Cancellation while mpv's native output is opening must release cleanly.
                player.play(source)
                QTimer.singleShot(0, player.release)
                pump(200)
                self.assertIsNone(player.player)
                self.assertEqual(player.state, 'idle')
                self.assertFalse(isValid(player._watch))
                self.assertFalse(isValid(player._picture_watch))
        finally:
            player.release()
            widget.close()

    def test_destroy_does_not_reconfigure_the_native_window(self):
        class Core:
            command = Mock()
            terminate = Mock()

            @property
            def force_window(self):
                return 'immediate'

            @force_window.setter
            def force_window(self, _value):
                raise AssertionError('Teardown must not synchronously reconfigure the native video window')

        widget = QWidget()
        player = TilePlayer(widget)
        core = player.player = Core()
        player._bound, player._bound_hwnd = True, 100
        try:
            player._destroy_core()
            core.command.assert_called_once_with('stop')
            core.terminate.assert_called_once_with()
            self.assertIsNone(player.player)
            self.assertFalse(player._bound)
            self.assertEqual(player._bound_hwnd, 0)
        finally:
            player.player = None
            player.release()
            widget.close()

    def test_audio_refresh_uses_core_thread_and_waits_for_completion(self):
        player = TilePlayer(Mock())
        core = player.player = Mock()
        try:
            player.refresh_audio_device()
            core.command.assert_not_called()
            core.command_async.assert_called_once_with('ao-reload')
            core.command_async.return_value.result.assert_called_once_with()
            core.command_async.return_value.result.side_effect = RuntimeError('reload failed')
            with self.assertRaisesRegex(RuntimeError, 'reload failed'):
                player.refresh_audio_device()
        finally:
            player.release()

    def test_audio_refresh_skips_missing_silent_or_released_core(self):
        for state in ('missing', 'silent', 'released'):
            with self.subTest(state=state):
                player = TilePlayer(Mock(), silent=state == 'silent')
                core = Mock()
                player.player = None if state == 'missing' else core
                player._released = state == 'released'
                try:
                    player.refresh_audio_device()
                    core.command.assert_not_called()
                    core.command_async.assert_not_called()
                finally:
                    player._released = False
                    player.release()

    def test_shared_popup_keeps_one_idle_core_but_releases_media_and_watchers(self):
        widget = QWidget()
        with patch('ddm.player.mpv.MPV') as create:
            player = TilePlayer(widget, silent=True)
            try:
                player.bind()
                core = player.player
                for _ in range(25):
                    player._media = 'local-test.mp4'
                    player._watch.start()
                    player._picture_watch.start()
                    proxy = player._hls_proxy = Mock()
                    player.stop(keep_core=True)
                    self.assertIsNone(player._media)
                    self.assertIsNone(player._hls_proxy)
                    proxy.stop.assert_called_once_with()
                    self.assertFalse(player._watch.isActive())
                    self.assertFalse(player._picture_watch.isActive())
                    core.terminate.assert_not_called()
                    player.bind()
                self.assertEqual(create.call_count, 1, 'Only the shared popup retains a core')
                self.assertEqual(core.command.call_count, 25)
                self.assertTrue(all(call.args == ('stop',) for call in core.command.call_args_list))
                player.release()
                player.release()
                core.terminate.assert_called_once_with()
            finally:
                player.release()
                widget.close()

    def test_normal_thumbnail_stop_still_destroys_its_silent_core(self):
        widget = QWidget()
        with patch('ddm.player.mpv.MPV') as create:
            player = TilePlayer(widget, silent=True)
            try:
                player.bind()
                player.stop()
                create.return_value.terminate.assert_called_once_with()
                self.assertIsNone(player.player)
            finally:
                player.release()
                widget.close()

    def test_huya_uses_same_http_relay_as_probe_and_stops_it(self):
        for profile, relayed in (('huya', True), ('youtube', True), ('twitch', True), ('web', False)):
            with self.subTest(profile=profile):
                widget = QWidget()
                relay = Mock(url='http://127.0.0.1:34567/test.m3u8')
                with patch('ddm.player.mpv.MPV'), patch('ddm.hls_proxy.HlsProxy', return_value=relay) as create, \
                        patch('ddm.global_danmaku.request_proxy', return_value=None):
                    player = TilePlayer(widget)
                    try:
                        headers = {'User-Agent': 'fixture-UA', 'Referer': 'https://www.huya.com/'}
                        player.play('https://cdn.test/live.m3u8', profile, headers)
                        self.assertEqual(create.called, relayed)
                        self.assertEqual(player._media, relay.url if relayed else 'https://cdn.test/live.m3u8')
                        if relayed:
                            self.assertEqual(create.call_args.args[1], headers)
                            self.assertEqual(create.call_args.args[2], None)
                            player.stop()
                            relay.stop.assert_called_once_with()
                    finally:
                        player.release()
                        widget.close()

    def test_error_or_connecting_cannot_trigger_frozen_picture_recovery(self):
        widget = Mock()
        widget.isVisible.return_value = True
        widget.window.return_value.isMinimized.return_value = False
        player = TilePlayer(widget)
        player._media = 'fixture'
        try:
            for state in ('error', 'connecting', 'buffering'):
                player.state = state
                with patch.object(player, '_check_picture', return_value=False) as picture:
                    player._check_picture_tick()
                    picture.assert_called_once_with(False)
            player.play_session = 'new'
            player._transport_diagnostic('old', 'huya:123', host='cdn.test', resource='media',
                status=403, elapsed=1, attempt=1, local=False, error='HTTPError')
            self.assertEqual(player.source_failure, '', 'Old relay must not reject the new source')
        finally:
            player.release()

    def test_huya_recovery_has_one_timer_and_resets_only_after_stable_generation(self):
        tile = Mock(room={'room_id': 'huya:123'}, paused=False)
        host = QObject()
        host._resolvers, host.players = {tile: object()}, {}
        host.start_tile, host.refresh_status, host._closing = Mock(), Mock(), False
        recovery = PlaybackRecovery(host)
        recovery.schedule_retry(tile)
        recovery.picture_frozen(tile)
        self.assertFalse(recovery.retry_timers)
        host._resolvers.clear()
        with patch('ddm.playback_recovery.QTimer') as timer:
            recovery.schedule_retry(tile)
            recovery.schedule_retry(tile)
            recovery.picture_frozen(tile)
            timer.assert_called_once_with(recovery)
            self.assertEqual(recovery.retry_count[tile], 1)
            host.start_tile.assert_not_called()
        player = SimpleNamespace(state='playing', state_generation=4)
        host.players[tile] = player
        recovery.reset_stable_retry(tile, player, 3)
        self.assertIn(tile, recovery.retry_count)
        recovery.reset_stable_retry(tile, player, 4)
        self.assertNotIn(tile, recovery.retry_count)

    def test_all_platforms_keep_pending_recovery_without_restarting_it(self):
        for room_id in ('1001', 'huya:123', 'youtube:fixture', 'douyu:123'):
            with self.subTest(room_id=room_id):
                tile = Mock(room={'room_id': room_id}, paused=False)
                host = QObject()
                host._resolvers, host.players = {tile: object()}, {}
                host.start_tile, host.refresh_status = Mock(), Mock()
                recovery = PlaybackRecovery(host)
                with patch('ddm.playback_recovery.QTimer') as create:
                    recovery.schedule_retry(tile)
                    create.assert_not_called()
                    recovery.picture_frozen(tile)
                    host.start_tile.assert_not_called()
                    host._resolvers.clear()
                    recovery.schedule_retry(tile)
                    recovery.schedule_retry(tile)
                    recovery.picture_frozen(tile)
                    create.assert_called_once_with(recovery)
                    create.return_value.start.assert_called_once_with(5000)
                    self.assertEqual(recovery.retry_count[tile], 1)
                    host.start_tile.assert_not_called()

    def test_completed_recovery_timers_release_qt_children(self):
        tile = Mock(room={'room_id': '1001'}, paused=False)
        host = QObject()
        host._resolvers, host.players = {}, {}
        host.start_tile = Mock()
        recovery = PlaybackRecovery(host)
        recovery.freeze_refreshed.add(tile)
        with patch('builtins.print'):
            for schedule, pending in ((recovery.schedule_retry, recovery.retry_timers),
                                      (recovery.picture_frozen, recovery.freeze_retry_timers)):
                for _ in range(30):
                    before = host.start_tile.call_count
                    schedule(tile)
                    timer = pending[tile]
                    self.assertIs(timer.parent(), recovery)
                    timer.start(0)
                    self.app.processEvents()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    self.assertEqual(host.start_tile.call_count, before + 1)
                    self.assertFalse(pending)
                    self.assertFalse(isValid(timer), 'Completed timer must release its Qt parent reference')
                self.assertEqual(host.findChildren(QTimer), [])


class SourceRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def player(self, profile='douyu'):
        player = TilePlayer(Mock())
        self.addCleanup(player.release)
        player.stream_profile = profile
        player.decode_mode = 'auto'
        player._play_request = ('https://cdn.test/live.flv', profile, {}, ())
        player._media = player._play_request[0]
        return player

    def test_observed_network_then_invalid_nal_does_not_reload_the_same_url_in_cpu_mode(self):
        player = self.player()
        props = {'time-pos':57.743,'eof-reached':True,'vo-configured':True}
        player._log('error', 'curl', 'transfer failed: Failure when receiving data from the peer')
        player._log('error', 'ffmpeg/video', 'h264: Invalid NAL unit size (97832 > 32688).')
        with patch.object(player, '_prop', side_effect=lambda name, default=None: props.get(name, default)), \
                patch.object(player, '_play_media') as reload:
            player._check()
            reload.assert_not_called()
        self.assertEqual(player.decode_mode, 'auto')
        self.assertEqual(player.state, 'error')
        self.assertEqual(player.source_failure, 'LIVE_EOF')

    def test_observed_corrupt_input_at_stream_join_does_not_trigger_cpu_fallback(self):
        for message in ('h264: mmco: unref short failure',
                        'h264: number of reference frames exceeds max (probably corrupt input)',
                        'h264: Invalid NAL unit size (97832 > 32688)',
                        'h264: missing picture in access unit with size 32763',
                        'h264: Error splitting the input into NAL units'):
            with self.subTest(message=message):
                player = self.player()
                player._log('error', 'ffmpeg/video', message)
                with patch.object(player, '_prop', return_value=None), patch.object(player, '_play_media') as reload:
                    self.assertFalse(player._recover_decoder())
                    reload.assert_not_called()
                    # A later, independent hardware failure must still work.
                    player._log('error', 'vd', 'hardware decoder failed')
                    self.assertTrue(player._recover_decoder())

    def test_decoder_failure_without_transport_error_still_falls_back(self):
        player = self.player()
        player._log('error', 'ffmpeg/video', 'hardware decoder failed')
        with patch.object(player, '_prop', return_value=None), patch.object(player, '_play_media') as reload:
            self.assertTrue(player._recover_decoder())
            reload.assert_called_once_with(*player._play_request)
        self.assertEqual(player.decode_mode, 'none')

    def test_warnings_and_unrelated_curl_messages_do_not_suppress_fallback(self):
        for level, prefix, message in (('warn','curl','transfer failed'),
                                       ('error','other','transfer failed'),
                                       ('error','curl','unrelated message')):
            with self.subTest(level=level,prefix=prefix,message=message):
                player = self.player()
                player._log(level,prefix,message)
                player._log('error','ffmpeg/video','decoder failed')
                with patch.object(player,'_prop',return_value=None),patch.object(player,'_play_media'):
                    self.assertTrue(player._recover_decoder())

    def test_other_platforms_keep_their_existing_decoder_recovery(self):
        for profile in ('web','app','douyin','huya'):
            with self.subTest(profile=profile):
                player = self.player(profile)
                player._log('error','curl','transfer failed: Failure when receiving data from the peer')
                player._log('error','ffmpeg/video','decoder failed')
                with patch.object(player,'_prop',return_value=None),patch.object(player,'_play_media'):
                    self.assertTrue(player._recover_decoder())

    def test_new_playback_clears_the_input_error_and_keeps_decoder_fallback_available(self):
        player = self.player()
        player._log('error','curl','transfer failed: Failure when receiving data from the peer')
        with patch.object(player,'bind'),patch.object(player,'_start_pending_media'):
            player._play_media('https://another.test/live.flv','douyu',{},())
        player._log('error','ffmpeg/video','decoder failed on new source')
        with patch.object(player,'_prop',return_value=None),patch.object(player,'_play_media'):
            self.assertTrue(player._recover_decoder())

    def test_transport_failure_does_not_leak_to_another_player(self):
        failed, healthy = self.player(), self.player()
        failed._log('error','curl','transfer failed: Failure when receiving data from the peer')
        healthy._log('error','ffmpeg/video','decoder failed')
        with patch.object(healthy,'_prop',return_value=None),patch.object(healthy,'_play_media'):
            self.assertTrue(healthy._recover_decoder())


class LiveBufferingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def player(self, profile='douyin', *, silent=False):
        player = TilePlayer(Mock(), silent=silent)
        player.stream_profile = profile
        player._media = 'fixture'
        player.decode_mode = 'none'
        player._last_time = 39.316
        player._startup_buffering = False
        player.state = 'playing'
        self.addCleanup(player.release)
        return player

    def check(self, player, props):
        with patch.object(player, '_prop', side_effect=lambda key, default=None: props.get(key, default)):
            player._check()

    def test_live_refill_can_recover_past_nine_seconds_without_an_error(self):
        # Actual 23:00 capture: clock stopped while the minimum A/V cache grew,
        # then resumed on the same stream. Fixture replay checks policy only.
        for profile in ('douyu', 'douyin'):
            with self.subTest(profile=profile):
                player = self.player(profile)
                changes = Mock()
                player.stateChanged.connect(changes)
                props = {'time-pos': 39.316, 'paused-for-cache': True, 'vo-configured': True}
                for end in (39.316, 39.38, 39.444, 39.508, 39.593, 39.636, 39.743, 39.871):
                    props['demuxer-cache-state'] = {'cache-end': end}
                    self.check(player, props)
                self.assertNotIn(unittest.mock.call('error'), changes.call_args_list)
                props.update({'time-pos': 39.699, 'paused-for-cache': False})
                self.check(player, props)
                self.assertEqual(player.state, 'playing')
                self.assertEqual(player._stall_ticks, 0)

    def test_audio_bytes_alone_do_not_extend_a_stalled_video(self):
        player = self.player()
        props = {'time-pos': 39.316, 'paused-for-cache': True, 'vo-configured': True,
                 'demuxer-cache-state': {'cache-end': 39.316, 'fw-bytes': 0}}
        for index in range(7):
            props['demuxer-cache-state']['fw-bytes'] = index * 100000
            self.check(player, props)
        self.assertEqual(player.state, 'error')

    def test_slow_refill_has_a_finite_total_wait(self):
        player = self.player()
        props = {'time-pos': 39.316, 'paused-for-cache': True}
        for index in range(20):
            props['demuxer-cache-state'] = {'cache-end': 39.316 + index / 100}
            self.check(player, props)
        self.assertEqual(player.state, 'error')

    def test_real_eof_and_transfer_error_do_not_wait_for_refill(self):
        for profile in ('douyu', 'douyin'):
            with self.subTest(profile=profile):
                player = self.player(profile)
                player._source_read_error = True
                props = {'time-pos': 39.316, 'paused-for-cache': True}
                for index in range(6):
                    props['demuxer-cache-state'] = {'cache-end': 40 + index}
                    self.check(player, props)
                self.assertEqual(player.state, 'error')
        player = self.player('douyu')
        self.check(player, {'time-pos': 39.316, 'eof-reached': True})
        self.assertEqual(player.state, 'error')
        self.assertEqual(player.source_failure, 'LIVE_EOF')

    def test_bili_and_preview_stall_limits_are_unchanged(self):
        for profile, silent in (('app', False), ('douyu', True), ('douyin', True)):
            with self.subTest(profile=profile, silent=silent):
                player = self.player(profile, silent=silent)
                props = {'time-pos': 39.316, 'paused-for-cache': True}
                for index in range(6):
                    props['demuxer-cache-state'] = {'cache-end': 40 + index}
                    self.check(player, props)
                self.assertEqual(player.state, 'error')

    def test_cache_policy_is_scoped_and_reset_when_the_core_is_reused(self):
        for silent in (False, True):
            with self.subTest(silent=silent):
                player = self.player(silent=silent)
                core = player.player = Mock()
                with patch.object(player, 'bind'), patch.object(player, '_start_pending_media'):
                    for profile in ('douyu', 'douyin', 'app', 'huya', 'youtube'):
                        player._play_media('https://fixture.invalid/live.flv', profile, {}, ())
                        protected = not silent and profile in ('douyu', 'douyin')
                        self.assertEqual(core.demuxer_max_bytes, '64MiB' if protected else '16MiB')
                        self.assertEqual(core.cache_pause_initial, protected)
                        self.assertEqual(core.cache_pause_wait, 3 if protected else 1)

    def test_new_media_discards_previous_refill_progress(self):
        player = self.player()
        props = {'time-pos': 39.316, 'paused-for-cache': True}
        for index in range(5):
            props['demuxer-cache-state'] = {'cache-end': 40 + index}
            self.check(player, props)
        with patch.object(player, 'bind'), patch.object(player, '_start_pending_media'):
            player._play_media('https://fixture.invalid/new.flv', 'douyin', {}, ())
        player._last_time = 39.316
        props.pop('demuxer-cache-state')
        for _ in range(6):
            self.check(player, props)
        self.assertEqual(player.state, 'error')


    def test_refill_progress_is_owned_by_each_player(self):
        filling, stopped = self.player(), self.player()
        props = {'time-pos': 39.316, 'paused-for-cache': True}
        for index in range(8):
            props['demuxer-cache-state'] = {'cache-end': 40 + index}
            self.check(filling, props)
            self.check(stopped, {'time-pos': 39.316, 'paused-for-cache': True})
        self.assertEqual(filling.state, 'buffering')
        self.assertEqual(stopped.state, 'error')

    def test_actual_mpv_accepts_and_resets_the_live_cache_options(self):
        from ddm.player import EMBEDDED_OPTIONS, mpv
        player = self.player()
        player.player = mpv.MPV(vo='null', ao='null', **EMBEDDED_OPTIONS)
        with patch.object(player, 'bind'), patch.object(player, '_start_pending_media'):
            player._play_media('https://fixture.invalid/live.flv', 'douyin', {}, ())
            self.assertEqual(player._prop('demuxer-max-bytes'), 64 * 1024 * 1024)
            self.assertTrue(player._prop('cache-pause-initial'))
            self.assertEqual(player._prop('cache-pause-wait'), 3)
            player._play_media('https://fixture.invalid/bili.flv', 'app', {}, ())
            self.assertEqual(player._prop('demuxer-max-bytes'), 16 * 1024 * 1024)
            self.assertFalse(player._prop('cache-pause-initial'))
            self.assertEqual(player._prop('cache-pause-wait'), 1)


if __name__ == '__main__':
    unittest.main()
