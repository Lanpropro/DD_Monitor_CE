"""Wall replay acceptance with isolated settings, FFmpeg and libmpv local media."""
from pathlib import Path
import math
import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import selfcheck_main_notices as fixtures
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QLineEdit
from PySide6.QtTest import QTest

from ddm import theme
from ddm.player import EMBEDDED_OPTIONS, TilePlayer, mpv
from ddm.plugin_controls import TileControl
from ddm.recording import ffmpeg_path
from ddm.wall_replay import _ReplayRecorder
from ddm.wall_replay_timeline import ReplayClip, ReplayTimeline, format_time


class WallReplayTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MainNoticesTests.setUpClass.__func__)
    setUp = fixtures.MainNoticesTests.setUp
    window = fixtures.MainNoticesTests.window
    close_window = fixtures.MainNoticesTests.close_window

    def wait_for(self, predicate, timeout=8, detail=lambda: None):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(25)
        self.assertTrue(predicate(), detail())

    def window_with_live_rooms(self):
        window = self.window([dict(room_id='1', uname='测试主播一', live=True),
                              dict(room_id='2', uname='测试主播二', live=True)], offscreen=True)
        window._record_notice = Mock()
        self.assertFalse(window.settings.get('recording_dir'))
        return window

    def test_confirmed_selection_owns_cache_by_room_instead_of_slot(self):
        window = self.window_with_live_rooms()
        replay = window.wall_replay
        first, second = window.wall.tiles[:2]
        first.stream_url = 'fixture-one.mkv'
        second.stream_url = 'fixture-two.mkv'
        with patch.object(_ReplayRecorder, '_launch', autospec=True) as launch:
            def select():
                window.sidebar.replay_button.click()
                dialog = replay.dialog
                self.assertIsNotNone(dialog)
                card = dialog.checks['1']
                self.assertIs(card.parentWidget(), dialog.preview)
                self.assertTrue(card.badge.isHidden())
                QTest.mouseClick(card, Qt.LeftButton)
                self.assertEqual(dialog.selected_rooms(), ('1',))
                self.assertTrue(card.badge.isVisible())
                dialog.shared_minutes.setValue(5)
                self.assertIsNone(replay.recorder)
                launch.assert_not_called()
                return dialog

            QTest.mouseClick(select().titlebar.close_button, Qt.LeftButton)
            self.assertIsNone(replay.dialog)
            launch.assert_not_called()
            self.assertFalse(replay.sources)
            QTest.mouseClick(select().confirm, Qt.LeftButton)
            self.assertIsNone(replay.dialog)

            launch.assert_called_once()
            self.assertTrue(replay.is_selected(first))
            self.assertFalse(replay.is_selected(second))
            self.assertTrue(first.replay_button.isVisible())
            self.assertFalse(second.replay_button.isVisible())
            self.assertEqual(set(replay.chat_rooms()), {'1'})
            source = replay.sources['1']
            session = replay.recorder.sessions[source]
            self.assertEqual(session.settings['recording_replay_minutes'], 5)
            self.assertFalse(window.recorder.sessions)
            folder = session.parts_directory()
            folder.mkdir()
            part = folder / '缓存.mkv'
            part.write_bytes(b'fixture')
            session.parts.append(part)

            # No running live players forces the wall's cold move instead of the hot swap.
            window.room_placement.swap_tile_widgets(first, second)
            self.assertTrue(replay.is_selected(second))
            self.assertFalse(replay.is_selected(first))
            self.assertIs(replay.recorder.sessions[source], session)
            self.assertTrue(part.is_file())
            launch.assert_called_once()

            with patch.dict(window.players, {first: Mock(), second: Mock()}):
                self.assertTrue(window._hot_swap(second, first))
                self.assertIs(window.wall.tiles[0], second)
                self.assertIs(replay.recorder.sessions[source], session)
                self.assertTrue(part.is_file())
                launch.assert_called_once()
            window._fill_plugin_menu(second)
            self.assertIn('回看这路直播…', [label for label, _ in second.plugin_actions])

            replay.configure({'1': 2})
            self.assertEqual(session.settings['recording_replay_minutes'], 2)
            window._clear_tile_room(second)
            window._refresh_meta()
            self.assertFalse(replay.sources)
            self.assertFalse(part.exists())
            self.assertFalse(folder.exists())

    def test_durations_are_saved_by_room_and_applied_to_each_session(self):
        window = self.window_with_live_rooms()
        replay = window.wall_replay
        first, second = window.wall.tiles[:2]
        first.stream_url, second.stream_url = 'first.mkv', 'second.mkv'
        window.sidebar.replay_button.click()
        dialog = replay.dialog
        dialog.individual.setChecked(True)
        for room_id, minutes in (('1', 5), ('2', 30)):
            QTest.mouseClick(dialog.checks[room_id], Qt.LeftButton)
            self.assertTrue(dialog.minutes[room_id].isVisible())
            self.assertEqual(dialog.minutes[room_id].maximum(), 60)
            dialog.minutes[room_id].setValue(minutes)
        with patch.object(_ReplayRecorder, '_launch', autospec=True):
            QTest.mouseClick(dialog.confirm, Qt.LeftButton)
        for room_id, minutes in (('1', 5), ('2', 30)):
            source = replay.sources[room_id]
            self.assertEqual(replay.recorder.sessions[source].settings['recording_replay_minutes'], minutes)
            source.comments.append((0, 'same timestamp'))
            replay._trim_comments(source, 7 * 60)
        self.assertFalse(replay.sources['1'].comments)
        self.assertTrue(replay.sources['2'].comments)
        replay.configure({'2': 30})
        saved_ui = window.current_state()['ui']
        saved = saved_ui['wall_replay_minutes']
        self.assertEqual(saved, {'1': 5, '2': 30})

        rooms = [dict(room_id=key, uname=key, live=True) for key in saved]
        reopened = fixtures.MainWindow(rooms, rooms, layout_id='2x2',
            state={'plugins_enabled': [], 'ui': {'wall_replay_minutes': saved,
                                                 'wall_replay_options': saved_ui['wall_replay_options']},
                   'settings': {'close_behavior': 'exit'}})
        self.addCleanup(self.close_window, reopened)
        reopened.move(-10000, -10000)
        reopened.show()
        self.app.processEvents()
        reopened.sidebar.replay_button.click()
        dialog = reopened.wall_replay.dialog
        self.assertEqual(dialog.selected_rooms(), ())
        self.assertTrue(dialog.individual.isChecked())
        self.assertEqual({key: spin.value() for key, spin in dialog.minutes.items()}, saved)

    def test_picker_estimates_disk_use_from_bitrate_duration_and_selection(self):
        window = self.window_with_live_rooms()
        player = Mock()
        player.stream_info.return_value = {'video_bitrate': 4_800_000, 'audio_bitrate': 200_000}
        with patch.dict(window.players, {window.wall.tiles[0]: player}):
            window.sidebar.replay_button.click()
            dialog = window.wall_replay.dialog
            dialog.individual.setChecked(True)
            self.assertEqual(dialog.total_estimate.text(), '缓存存满预计占用 0 MB')
            QTest.mouseClick(dialog.checks['1'], Qt.LeftButton)
            dialog.minutes['1'].setValue(5)
            self.assertEqual(dialog.estimates['1'].text(), '约 187.5 MB')
            self.assertEqual(dialog.total_estimate.text(), '缓存存满预计占用 187.5 MB')
            QTest.mouseClick(dialog.checks['2'], Qt.LeftButton)
            dialog.minutes['2'].setValue(20)
            self.assertEqual(dialog.estimates['2'].text(), '约 900 MB')
            self.assertEqual(dialog.total_estimate.text(), '缓存存满预计占用 1.09 GB · 部分直播按 6 Mbps 估算')
            QTest.mouseClick(dialog.checks['1'], Qt.LeftButton)
            self.assertEqual(dialog.total_estimate.text(), '缓存存满预计占用 900 MB · 每路按 6 Mbps 估算')
            player.stream_info.assert_called_once()
            dialog.reject()

    def test_shared_duration_preserves_individual_values_and_preview_geometry(self):
        window = self.window_with_live_rooms()
        replay = window.wall_replay
        replay.durations.update({'1': 5, '2': 20})
        window.sidebar.replay_button.click()
        dialog = replay.dialog
        preview_geometry = dialog.preview.geometry()
        cell_sizes = [cell.size() for cell, _rect in dialog.preview.cells]
        self.assertFalse(dialog.individual.isChecked())
        self.assertTrue(dialog.shared_minutes.isVisible())
        for button in dialog.checks.values():
            QTest.mouseClick(button, Qt.LeftButton)
        dialog.shared_minutes.setValue(8)
        self.app.processEvents()
        self.assertEqual(dialog.selected_durations(), {'1': 8, '2': 8})
        self.assertFalse(any(spin.isVisible() for spin in dialog.minutes.values()))
        self.assertEqual(dialog.estimates['2'].text(), '约 360 MB')
        self.assertEqual(dialog.preview.geometry(), preview_geometry)
        self.assertEqual([cell.size() for cell, _rect in dialog.preview.cells], cell_sizes)
        QTest.mouseClick(dialog.confirm, Qt.LeftButton)
        self.assertEqual({key: source.minutes for key, source in replay.sources.items()}, {'1': 8, '2': 8})
        self.assertEqual(replay.durations, {'1': 5, '2': 20})
        self.assertEqual(window.current_state()['ui']['wall_replay_options']['shared_minutes'], 8)

        window.sidebar.replay_button.click()
        dialog = replay.dialog
        self.assertEqual(dialog.shared_minutes.value(), 8)
        dialog.individual.setChecked(True)
        self.app.processEvents()
        self.assertFalse(dialog.shared_minutes.isVisible())
        self.assertTrue(all(spin.isVisible() for spin in dialog.minutes.values()))
        self.assertEqual(dialog.selected_durations(), {'1': 5, '2': 20})
        self.assertEqual(dialog.preview.geometry(), preview_geometry)
        dialog.reject()
        self.assertFalse(replay.individual)

    def test_picker_remembers_dragged_dimensions(self):
        from PySide6.QtCore import QEvent
        from selfcheck_picture_in_picture import pointer

        window = self.window_with_live_rooms()
        anchor = window.sidebar.replay_button
        anchor.click()
        dialog = window.wall_replay.dialog
        original = dialog.size()
        local = QPoint(original.width() - 7, original.height() - 7)
        pressed = dialog.mapToGlobal(local)
        target = pressed + QPoint(45, -39)
        pointer(dialog, QEvent.MouseButtonPress, local, pressed, Qt.LeftButton, Qt.LeftButton)
        pointer(dialog, QEvent.MouseMove, dialog.mapFromGlobal(target), target, Qt.NoButton, Qt.LeftButton)
        pointer(dialog, QEvent.MouseButtonRelease, dialog.mapFromGlobal(target), target, Qt.LeftButton, Qt.NoButton)
        remembered = dialog.size()
        self.assertGreater(remembered.width(), original.width())
        self.assertEqual(remembered.height(), original.height() - 39)
        self.assertEqual(window.current_state()['ui']['wall_replay_options']['picker_size'], remembered.toTuple())
        dialog.reject()
        anchor.click()
        self.assertEqual(window.wall_replay.dialog.size(), remembered)

    def test_picker_anchors_and_uses_the_shape_of_the_current_wall(self):
        window = self.window_with_live_rooms()
        sidebar = window.sidebar
        replay = window.wall_replay
        available = window.screen().availableGeometry()
        window.move(available.topLeft() + QPoint(12, 12))
        window.resize(min(1000, available.width() - 24), min(650, available.height() - 24))
        window.wall.set_layout('corner')
        face = QPixmap(32, 32)
        face.fill(QColor('#b54777'))
        window.sidebar.items()[0].set_room_avatar(face)
        self.app.processEvents()
        anchor = sidebar.replay_button
        QTest.mouseClick(anchor, Qt.LeftButton)
        dialog = replay.dialog
        self.assertIsNotNone(dialog)
        self.assertFalse(dialog.isModal())
        self.assertEqual(dialog.x(), anchor.mapToGlobal(QPoint(anchor.width(), 0)).x() + 8)
        bounds = QRect(window.mapToGlobal(QPoint()), window.size()).intersected(available).adjusted(8, 8, -8, -8)
        self.assertTrue(bounds.contains(dialog.geometry()))
        first, second = dialog.checks['1'], dialog.checks['2']
        self.assertTrue(first.avatar.isVisible())
        self.assertFalse(first.avatar.pixmap().isNull())
        self.assertFalse(first.label.text())
        self.assertGreater(first.width(), second.width())
        self.assertGreater(first.height(), second.height())
        self.assertLess(first.x(), second.x())
        self.assertEqual(len(dialog.preview.cells), 6)
        self.assertEqual(sum(cell.isEnabled() for cell, _rect in dialog.preview.cells), 2)
        QTest.mouseClick(first, Qt.LeftButton)
        QTest.mouseClick(second, Qt.LeftButton)
        self.assertEqual(dialog.selected_rooms(), ('1', '2'))
        QTest.mouseClick(first, Qt.LeftButton)
        self.assertEqual(dialog.selected_rooms(), ('2',))
        QTest.mouseClick(window.windowHandle(), Qt.LeftButton, pos=QPoint(window.width() - 30, 40))
        self.assertIsNone(replay.dialog)
        self.assertFalse(replay.sources)

        window.window_layout.reshape_window(True)
        self.wait_for(lambda: window.orientation == 'portrait')
        self.app.processEvents()
        anchor.click()
        dialog = replay.dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.y(), anchor.mapToGlobal(QPoint(0, anchor.height())).y() + 8)
        QTest.mouseClick(anchor, Qt.LeftButton)
        self.assertIsNone(replay.dialog)

    def test_replay_hover_keeps_icon(self):
        window = self.window_with_live_rooms()
        tile = window.wall.tiles[0]
        theme.apply('dark')
        button = tile.replay_button
        button.show()
        self.app.processEvents()
        self.assertEqual(button.property('tileButton'), tile.danmaku_settings_button.property('tileButton'))
        for checked in (False, True):
            button.setChecked(checked)
            button.setProperty('hovered', True)
            button.style().unpolish(button)
            button.style().polish(button)
            image = button.grab().toImage()
            bright = sum(image.pixelColor(x, y).red() > 170
                         for x in range(image.width()) for y in range(image.height()))
            self.assertGreater(bright, 10)
            self.assertNotEqual(image.pixelColor(image.width() // 2, 3), QColor(theme.ACCENT))

    def test_expiring_segments_preserve_positions_of_remaining_segments(self):
        first, second, third = [ReplayClip(Path(f'{index}.mkv'), 4, 100 + 4 * index)
                                for index in range(3)]
        before = ReplayTimeline((first, second))
        current = ReplayTimeline((second, third), before)
        self.assertEqual((current.start, current.end), (4, 12))
        self.assertEqual(before.frame_source(5), current.frame_source(5))
        self.assertEqual(current.comments([(106, 'new')]), [(10, 'new')])

    def test_local_segments_keep_a_seekable_timeline_and_clear_after_downwall(self):
        window = self.window_with_live_rooms()
        replay = window.wall_replay
        tile = window.wall.tiles[0]
        executable = ffmpeg_path()
        self.assertTrue(executable)
        with tempfile.TemporaryDirectory(prefix='ddm-replay-check-') as folder:
            media = Path(folder) / '输入含标点,;.mkv'
            subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                            '-i', 'testsrc2=s=96x54:r=8', '-t', '76', '-c:v', 'libx264',
                            '-threads', '1', '-preset', 'ultrafast', '-g', '8', str(media)],
                           check=True, timeout=20)
            tile.stream_url = str(media)
            tile.room['uname'] = '测试,主播;一'
            replay.configure({'1': 1})
            cache = replay.recorder
            source = replay.sources['1']
            session = cache.sessions[source]
            process = session.process
            self.wait_for(lambda: process.poll() is not None)
            tile.room['live'] = False
            replay.sync()
            cache._poll()
            process.stdin.close()
            self.assertIs(cache.sessions[source], session)
            parts = session.finished_parts()
            self.assertLessEqual(len(parts), 17)
            self.assertGreater(len(parts), 12)
            self.assertTrue(all(part.is_file() for part in parts))
            session.retry_at = 1
            with patch.object(cache, '_launch', wraps=cache._launch) as launch:
                cache._poll()
            launch.assert_not_called()
            self.assertIs(cache.sessions[source], session)

            anchor = time.time() - len(parts) * 4
            for index, part in enumerate(parts, 1):
                ended = anchor + 4 * index
                os.utime(part, (ended, ended))
            client = Mock()
            with patch.dict(window._danmaku_clients, {'1': client}), \
                    patch('ddm.wall_replay.time.time', return_value=anchor + 21):
                window._on_danmaku_message(client, {'kind': 'danmaku', 'text': '时间轴历史弹幕'})
            self.assertEqual(source.comments[-1][1]['text'], '时间轴历史弹幕')

            window.resize(1480, 780)
            self.app.processEvents()
            tile.danmaku_button.setChecked(True)
            controls = tile._plugin_controls
            def composer(context):
                return TileControl(QLineEdit(context.parent), minimum_width=40)

            controls.add('fixture', 'composer', composer, 0, 0)
            next(entry.control.widget for entry in controls.entries if entry.owner == 'fixture').show()
            controls.invalidate()
            self.app.processEvents()
            self.assertTrue(controls.widget.isVisible(),
                            (tile.size(), tile.bottom.isVisible(), controls._panel, controls.widget.size(),
                             len(controls.applicable()), tile._plugin_controls is controls))

            def headless_bind(player):
                if player.player is None:
                    player.player = mpv.MPV(vo='null', ao='null', idle=True, keep_open=True, **EMBEDDED_OPTIONS)

            live = Mock()
            window.players[tile] = live
            native = self.app.platformName() == 'windows'
            session.parts[:] = parts[:-3]
            tile.room['live'] = True
            tile.stream_url = ''
            tile.replay_button.click()
            view = replay._reviews['1']
            if not native:
                self.enterContext(patch.object(view.player, 'bind', lambda: headless_bind(view.player)))
            self.wait_for(view.slider.isEnabled)
            self.assertTrue(view.widget.isVisible())
            self.assertTrue(view.surface.isHidden())
            self.assertTrue(controls.widget.isHidden())
            self.assertLessEqual(view.slider.maximum() - view.slider.minimum(), 60)
            self.assertEqual(view.slider.value(), view.slider.maximum())
            initial_time = format_time(view.snapshot.end - view.snapshot.start)
            self.assertTrue(view.status.text().endswith(initial_time))
            initial_status = view.status.text()
            self.assertGreater(view.scale.duration, 0)
            self.assertTrue(view.latest.isVisible())
            self.assertEqual(view.latest.text(), '')
            self.assertEqual(view.latest.toolTip(), '回到最新时间')
            self.assertFalse(view.latest.isEnabled())
            live.set_replay_muted.assert_not_called()
            with patch.object(tile.video_danmaku, 'add_event', return_value=True) as emit, \
                    patch.dict(window._danmaku_clients, {'1': client}):
                window._on_danmaku_message(client, {'kind': 'danmaku', 'text': '直播弹幕'})
                self.assertEqual(emit.call_args.args[0]['text'], '直播弹幕')

            target = 20
            self.assertEqual([event['text'] for _, event in view.comments], ['时间轴历史弹幕'])
            with patch.object(tile.video_danmaku, 'add_event', return_value=True) as emit:
                view.slider.setValue(target)
                self.assertTrue(view.surface.isVisible())
                live.set_replay_muted.assert_called_once_with(True)
                with patch.dict(window._danmaku_clients, {'1': client}):
                    window._on_danmaku_message(client, {'kind': 'danmaku', 'text': '此刻的直播弹幕'})
                emit.assert_not_called()
                self.wait_for(lambda: emit.called, timeout=4)
                self.assertEqual([call.args[0]['text'] for call in emit.call_args_list], ['时间轴历史弹幕'])

            tile.pause_button.click()
            self.assertTrue(view.player.paused)
            before = view.player.playback_timing()[0]
            end = view.slider.maximum()
            loaded = view._media
            session.parts[:] = parts
            source.comments.append((anchor + len(parts) * 4 - 2, {'kind': 'danmaku', 'text': '后来缓存的弹幕'}))
            replay.sync()
            self.wait_for(lambda: view.slider.maximum() > end)
            self.assertNotEqual(view.status.text(), initial_status)
            retained = min(60, view.snapshot.end - view.snapshot.start)
            self.assertTrue(view.status.text().endswith(format_time(retained)))
            self.assertIs(view._media, loaded)
            self.assertAlmostEqual(view.player.playback_timing()[0], before, delta=.3)
            self.assertTrue(view.player.paused)
            view.slider.setValue(math.floor(loaded.end) - 1)
            self.wait_for(lambda: view._pending_seek is None)
            tile.pause_button.click()
            self.wait_for(lambda: view._media is view.snapshot and view._pending_seek is None,
                          detail=lambda: (view.player.playback_timing(), view.player.paused,
                                          view.player._prop('eof-reached'), view._pending_seek,
                                          view._seek_started, view._media is view.snapshot,
                                          loaded.end, view.snapshot.end))
            self.assertFalse(view.player.paused)
            tile.pause_button.click()
            self.app.processEvents()
            target = math.ceil(loaded.end) + 2
            self.assertGreater(view.slider.width(), 48)
            x = min(range(view.slider.width()), key=lambda pixel: abs(view.slider.value_at(pixel) - target))
            target = view.slider.value_at(x)
            self.assertGreater(target, loaded.end,
                               (view.widget.width(), view.slider.width(), view.slider.minimum(), view.slider.maximum()))
            self.assertLess(target, view.slider.maximum())
            point = QPoint(x, view.slider.height() // 2)
            QTest.mouseMove(view.slider, point)
            self.assertFalse(view.preview.card.isVisible())
            before_scrub = view.player.playback_timing()[0]
            QTest.mousePress(view.slider, Qt.LeftButton, pos=point - QPoint(12, 0))
            self.assertTrue(view.preview.card.isVisible())
            QTest.mouseMove(view.slider, point)
            self.wait_for(lambda: view.preview.label.isVisible() and
                          view.preview.caption.text() == format_time(target - view.slider.minimum()))
            self.assertGreater(view.preview.label.pixmap().width(), 0)
            self.assertAlmostEqual(view.player.playback_timing()[0], before_scrub, delta=.3)
            preview_top = tile.video.mapFromGlobal(view.preview.card.mapToGlobal(QPoint()))
            self.assertEqual(preview_top.x(), 8)
            self.assertLessEqual(preview_top.y() + view.preview.card.height(), tile.video.height())
            self.assertIn('后来缓存的弹幕', [event['text'] for _, event in view.comments])
            QTest.mouseRelease(view.slider, Qt.LeftButton, pos=point)
            self.assertFalse(view.preview.card.isVisible())
            self.assertEqual(view.slider.value(), target)
            self.wait_for(lambda: view._pending_seek is None)
            self.assertIs(view._media, view.snapshot)
            self.assertTrue(view.player.paused)
            self.assertAlmostEqual(view._media.start + view.player.playback_timing()[0], target, delta=.3)
            self.assertTrue(cache._part_leases)
            self.assertTrue(view.latest.isEnabled())
            QTest.mouseClick(view.latest, Qt.LeftButton)
            self.assertFalse(view.in_history)
            self.assertTrue(view.surface.isHidden())
            self.assertFalse(cache._part_leases)
            live.set_replay_muted.assert_called_with(False)
            tile.replay_button.click()
            self.assertFalse(view.preview.label.isVisible())
            self.assertTrue(controls.widget.isVisible())
            self.assertIsNone(tile._replay_view)
            self.assertTrue(all(part.exists() for part in parts))
            tile.replay_button.click()
            reopened = replay._reviews['1']
            if not native:
                self.enterContext(patch.object(reopened.player, 'bind', lambda: headless_bind(reopened.player)))
            reopened.slider.setValue(reopened.slider.minimum())
            self.assertTrue(cache._part_leases)
            window.players.pop(tile)
            window._clear_tile_room(tile)
            window._refresh_meta()
            self.assertFalse(replay._reviews)
            self.assertFalse(cache._part_leases)
            self.assertTrue(all(not part.exists() for part in parts))
            live.set_replay_muted.assert_called_with(False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
