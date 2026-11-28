"""Offline checks for planned recording triggers, migration and ownership."""
from datetime import date, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ddm.app_notices import AppNotices
from ddm.auto_recording import AutoRecording
from ddm.recording_calendar import extract_calendar
from ddm.recording_schedule import normalize_schedule, window_at_or_after
from ddm.streamer_defaults import migrate_folder_recording_plans


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute)


def scan(*lines):
    return dict(lines=[dict(words=[dict(text=text, x=x, y=y, width=20, height=12)
                                   for x, y, text in words]) for words in lines])


class Recorder:
    def __init__(self):
        self.sessions = {}
        self.started = []
        self.stopped = []

    def background_directory(self, _mode):
        return ''

    def start_background(self, tile):
        self.started.append(tile)
        self.sessions[tile] = SimpleNamespace(tile=tile, room_id=tile.room['room_id'],
                                              recording=True, stopping=False, recording_started_at=1)
        return True

    def stop(self, tile, **kwargs):
        self.sessions.pop(tile)
        self.stopped.append((tile, kwargs))


class RecordingScheduleTests(unittest.TestCase):
    def setUp(self):
        self.recorder = Recorder()
        self.refreshes = []
        self.host = SimpleNamespace(
            settings={'streamer_defaults': {
                '1001': {'recording_policy': 'schedule',
                         'recording_schedule': [[4, 1380, 60], [5, 60, 75], [5, 120, 150]]},
                '1002': {'recording_policy': 'off'},
            }},
            recorder=self.recorder, _closing=False, _pending_capture={},
            refresh_status=lambda **options: self.refreshes.append(options))
        self.auto = AutoRecording(self.host)

    def test_cross_midnight_merges_adjoining_windows_and_finds_next_week(self):
        schedule = normalize_schedule([[5, 60, 75], [4, 1380, 60], [4, 1380, 60], [5, 500, 500]])
        self.assertEqual(len(schedule), 2)
        self.assertEqual(window_at_or_after(schedule, at(28, 0, 40)), (at(27, 23), at(28, 1, 15)))
        self.assertEqual(window_at_or_after(schedule, at(28, 1, 15))[0], datetime(2026, 12, 4, 23))
        all_days = normalize_schedule([(day, start, end) for day in range(7)
                                       for start, end in ((0, 720), (720, 0))])
        self.assertEqual(window_at_or_after(all_days, at(28, 3)), (datetime.min, datetime.max))

    def test_ocr_uses_positions_for_multiple_rows_and_ignores_program_version(self):
        reference = date(2026, 11, 30)
        entries = extract_calendar([scan(
            [(20, 70, '11.9')],
            [(20, 120, '11.10')],
            [(20, 170, '11.11')],
            [(20, 220, '11.12')],
            [(120, 123, '15'), (140, 123, '：'), (152, 123, '00')],
            [(245, 125, '21:00')],
            [(120, 165, '版本 3.8')],
            [(120, 175, '18:00')],
            [(120, 223, '20:00')],
        ), scan([(125, 124, '15:00')])], reference)
        self.assertEqual([(item.day.isoformat(), item.start, item.end) for item in entries], [
            ('2026-11-10', 900, None), ('2026-11-10', 1260, None),
            ('2026-11-11', 1080, None), ('2026-11-12', 1200, None)])

    def test_ocr_handles_separate_columns_tentative_slots_and_extended_hours(self):
        entries = extract_calendar([scan(
            [(25, 70, 'Mon')], [(25, 120, 'Tue')], [(25, 170, 'Wed')],
            [(290, 120, 'Sat')], [(290, 170, 'Sun')],
            [(95, 81, '24:00–26:00')], [(96, 133, '待定 22：00 一 00：00')],
            [(355, 134, '22:00–00:00')], [(355, 184, '20:00')],
        )], date(2026, 11, 30))
        self.assertEqual([(item.day, item.start, item.end, item.review) for item in entries], [
            (1, 0, 120, False), (1, 1320, 0, True), (5, 1320, 0, False), (6, 1200, None, False)])

    def test_weekday_labels_use_explicit_date_range_when_recognized(self):
        entries = extract_calendar([scan(
            [(98, 30, '11月23日–11月29日')], [(25, 70, 'MON:')], [(25, 120, 'TUE:')],
            [(100, 76, '20:00')], [(100, 126, '21:00')],
        )], date(2026, 11, 30))
        self.assertEqual([(item.day, item.start) for item in entries], [
            (date(2026, 11, 23), 1200), (date(2026, 11, 24), 1260)])

    def test_single_date_start_only_records_until_confirmed_offline_across_midnight(self):
        self.host.settings['streamer_defaults']['1001']['recording_schedule'] = [['2026-11-27', 1200, None]]
        live = {'1001': {'live': True, 'live_start_ts': 10}}
        self.auto.apply_status(live, now=at(27, 19, 59))
        self.assertFalse(self.recorder.started)
        self.auto.apply_status(live, now=at(27, 20, 12))
        first, = self.recorder.started
        self.assertEqual(first.scheduled_start, at(27, 20))
        self.auto.apply_status({'1001': {'live': False, 'live_known': False}}, now=at(28, 0, 2))
        self.assertIn(first, self.recorder.sessions)
        self.auto.apply_status({'1001': {'live': False}}, now=at(28, 1, 20))
        self.assertEqual(self.recorder.stopped, [(first, {'confirmed_offline': True})])
        self.auto.apply_status(live, now=datetime(2026, 12, 4, 21))
        self.assertEqual(self.recorder.started, [first])

    def test_repeating_start_only_waits_for_next_occurrence_after_offline(self):
        self.host.settings['streamer_defaults']['1001']['recording_schedule'] = [[4, 1200, None]]
        self.auto.apply_status({'1001': {'live': True, 'live_start_ts': 10}}, now=at(27, 20))
        self.auto.apply_status({'1001': {'live': False}}, now=at(27, 20, 30))
        next_live = {'1001': {'live': True, 'live_start_ts': 20}}
        self.auto.apply_status(next_live, now=at(27, 21))
        self.assertEqual(len(self.recorder.started), 1)
        self.auto.apply_status(next_live, now=datetime(2026, 12, 4, 20))
        self.assertEqual(len(self.recorder.started), 2)

    def test_open_start_extends_current_plan_and_does_not_mask_a_later_timed_slot(self):
        self.host.settings['streamer_defaults']['1001']['recording_schedule'] = [
            ['2026-11-27', 1140, 1230], ['2026-11-27', 1200, None], ['2026-11-27', 1320, 1380]]
        self.auto.apply_status({'1001': {'live': True, 'live_start_ts': 10}}, now=at(27, 19))
        first, = self.recorder.started
        self.auto.apply_status({'1001': {'live': True, 'live_start_ts': 10}}, now=at(27, 20))
        self.assertEqual(first.scheduled_start, at(27, 20))
        self.auto.apply_status({'1001': {'live': False}}, now=at(27, 21))
        self.auto.apply_status({'1001': {'live': True, 'live_start_ts': 20}}, now=at(27, 22))
        self.assertEqual(len(self.recorder.started), 2)
        self.assertEqual(self.recorder.started[-1].scheduled_end, at(27, 23))

    def test_time_only_plan_startup_cross_midnight_and_second_window_without_rebroadcast(self):
        live = {room_id: {'live': True, 'live_start_ts': 10} for room_id in ('1001', '1002')}
        self.auto.apply_status(live, now=at(27, 22))
        self.assertFalse(self.recorder.started)
        self.auto.tick(now=at(27, 23))
        self.assertEqual(self.refreshes, [{'force': True}])
        self.auto.apply_status(live, now=at(28, 0))
        first, = self.recorder.started
        self.assertEqual(first.room['room_id'], '1001')
        self.assertEqual(first.scheduled_end, at(28, 1, 15))
        self.auto.apply_status({'1001': {'live_known': False, 'live': False}}, now=at(28, 1))
        self.assertIn(first, self.recorder.sessions)
        self.auto.tick(now=at(28, 1, 15))
        self.assertTrue(first.schedule_completed)
        self.assertEqual(self.recorder.stopped, [(first, {})])
        self.auto.apply_status(live, now=at(28, 2))
        self.assertEqual(len(self.recorder.started), 2)

    def test_manual_recording_is_preserved_and_confirmed_rebroadcast_can_restart(self):
        manual = object()
        self.recorder.sessions[manual] = SimpleNamespace(tile=manual, room_id='1001', recording=True, stopping=False)
        live = {'1001': {'live': True, 'live_start_ts': 10}}
        self.auto.apply_status(live, now=at(27, 23))
        self.auto.tick(now=at(28, 1, 15))
        self.assertIn(manual, self.recorder.sessions)
        self.assertFalse(self.recorder.started)
        self.recorder.sessions.pop(manual)
        self.auto.apply_status({'1001': {'live': False}}, now=at(28, 2))
        self.assertFalse(self.recorder.started)
        self.auto.apply_status(live, now=at(28, 2, 4))
        first, = self.recorder.started
        self.auto.apply_status({'1001': {'live': False}}, now=at(28, 2, 5))
        self.assertEqual(self.recorder.stopped, [(first, {'confirmed_offline': True})])
        self.auto.apply_status(live, now=at(28, 2, 6))
        self.assertEqual(len(self.recorder.started), 2)
        self.host.settings['streamer_defaults']['1001'] = {'monitor_live': False}
        self.auto.tick(now=at(28, 2, 7), config_changed=True)
        self.assertIn(self.recorder.started[-1], self.recorder.sessions)
        self.auto.tick(now=at(28, 2, 30))
        self.assertFalse(self.recorder.sessions)

    def test_folder_plan_migrates_to_room_cards_without_replacing_overrides(self):
        plan = ((4, 1380, 60),)
        folders = [{'id': 'event', 'name': '赛事', 'rooms': ['1', '2', '3', '4', 'fixture:6'],
                    'recording_schedule': plan},
                   {'id': 'smart', 'name': '直播中', 'type': 'smart',
                    'rule': {'sources': ['event'], 'status': 'live'}, 'recording_schedule': plan}]
        rooms = [{'room_id': room_id, 'uname': room_id} for room_id in ('1', '2', '3', '4', '5')]
        settings = {'streamer_defaults': {'2': {'recording_policy': 'off'},
                                          '3': {'auto_record': True},
                                          '4': {'monitor_live': False, 'volume': 40}}}
        suspended = [{'rooms': [{'room_id': 'fixture:6'}],
                      'platform_rooms': {'fixture:6': {'uname': '暂存主播'}}}]
        migrated = migrate_folder_recording_plans(settings, rooms, folders, suspended=suspended)
        profiles = settings['streamer_defaults']
        self.assertEqual(profiles['1']['recording_schedule'], plan)
        self.assertEqual(profiles['1']['recording_policy'], 'schedule')
        self.assertEqual(profiles['2'], {'recording_policy': 'off'})
        self.assertEqual(profiles['3'], {'auto_record': True})
        self.assertEqual(profiles['4']['recording_schedule'], plan)
        self.assertFalse(profiles['4']['monitor_live'])
        self.assertEqual(profiles['4']['volume'], 40)
        self.assertNotIn('5', profiles)
        self.assertEqual(profiles['fixture:6']['recording_schedule'], plan)
        self.assertEqual(profiles['fixture:6']['name'], '暂存主播')
        self.assertTrue(all('recording_schedule' not in folder for folder in migrated))
        self.assertIs(migrate_folder_recording_plans(settings, rooms, migrated), migrated)

    def test_title_only_matches_words_in_full_title_and_starts_after_title_changes(self):
        self.host.settings['streamer_defaults']['1001'] = {
            'recording_policy': 'schedule', 'recording_title_keywords': ['赛事复盘', 'BO3']}
        live = {'live': True, 'live_start_ts': 17}
        self.auto.apply_status({'1001': live}, now=at(27, 15))
        self.auto.apply_status({'1001': dict(live, title='日常聊天')}, now=at(27, 16))
        self.assertFalse(self.recorder.started)
        self.assertNotIn('1001', self.auto.attempted)
        self.auto.apply_status({'1001': dict(live, title='赛后赛事复盘 · 第二局')}, now=at(27, 17))
        first, = self.recorder.started
        self.assertEqual(first.scheduled_end, datetime.max)
        self.auto.apply_status({'1001': dict(live, title='赛后闲聊')}, now=at(27, 18))
        self.assertIn(first, self.recorder.sessions)
        self.auto.apply_status({'1001': {'live': False}}, now=at(27, 19))
        self.assertEqual(self.recorder.stopped, [(first, {'confirmed_offline': True})])
        self.auto.apply_status({'1001': dict(live, title='晚间 bO3 决赛')}, now=at(27, 20))
        self.assertEqual(len(self.recorder.started), 2)

    def test_time_and_title_together_require_both_conditions(self):
        self.host.settings['streamer_defaults']['1001']['recording_title_keywords'] = ['决赛']
        live = {'live': True, 'live_start_ts': 17}
        match = {'1001': dict(live, title='今晚决赛')}
        self.auto.apply_status(match, now=at(27, 22))
        self.auto.apply_status({'1001': dict(live, title='赛前闲聊')}, now=at(27, 23))
        self.assertFalse(self.recorder.started)
        self.auto.apply_status(match, now=at(28, 0))
        first, = self.recorder.started
        self.auto.apply_status(match, now=at(28, 1, 15))
        self.assertEqual(self.recorder.stopped, [(first, {})])
        self.assertEqual(len(self.recorder.started), 1)

    def test_switching_live_recording_to_title_plan_can_start_in_same_broadcast(self):
        profile = self.host.settings['streamer_defaults']['1001']
        profile['recording_policy'] = 'live'
        live = {'1001': {'live': True, 'live_start_ts': 17, 'title': '今晚决赛'}}
        self.auto.apply_status(live, now=at(27, 20))
        first, = self.recorder.started
        profile['recording_policy'] = 'schedule'
        profile.pop('recording_schedule')
        profile['recording_title_keywords'] = ['决赛']
        with patch('ddm.auto_recording.datetime', wraps=datetime) as clock:
            clock.now.return_value = at(27, 20, 2)
            self.auto.settings_changed()
        self.assertEqual(self.recorder.stopped, [(first, {})])
        self.auto.apply_status(live, now=at(27, 20, 3))
        self.assertEqual(len(self.recorder.started), 2)

    def test_scheduled_windows_notification_has_its_own_tag(self):
        notices = AppNotices(self.host)
        self.host.settings.update(notice_windows_recording=True,
                                  streamer_defaults={'1001': {'windows_recording_notice': True}})
        notices._windows_live['1001'] = True, 'old-live-reminder'
        room = {'room_id': '1001', 'scheduled_recording': True}
        with patch('ddm.windows_recording_notifications.send_recording_notification') as send:
            notices.background_recording_transition('started', room)
            self.assertIsNone(send.call_args.kwargs['tag'])
            self.assertFalse(send.call_args.kwargs['suppress_popup'])
            notices.background_recording_transition('stopped_schedule', room)
            self.assertIn('时段已结束', send.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
