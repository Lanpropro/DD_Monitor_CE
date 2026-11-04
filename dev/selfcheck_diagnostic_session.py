"""Isolated capture integration checks; synthetic data, not an issue reproduction."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.diagnostic_session import MODES, requested_mode


def child(mode, directory):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from ddm.diagnostic_session import install
    from ddm.online_ui import show_result
    from dev.selfcheck_main_notices import MainNoticesTests
    MainNoticesTests.setUpClass()
    fixture = MainNoticesTests()
    fixture.setUp()
    capture = install(mode, directory)
    try:
        rooms = [{'room_id': 'fixture-1', 'uname': 'PRIVATE_NAME_MUST_NOT_BE_CAPTURED'}]
        window = fixture.window(rooms, offscreen=True)
        window.settings['close_behavior'] = 'exit'
        before_rooms = [dict(room) for room in window.sidebar.rooms()]
        before_wall = [dict(tile.room) for tile in window.wall.tiles]
        if mode in ('folders', 'responsiveness'):
            folder = window.sidebar.folders[0]
            window.sidebar.toggle_folder(folder['id'])
            QTest.qWait(650)
            window.hover_preview._room = {}
            window.hover_preview._delay.timeout.emit()
            window.hover_preview._grace.timeout.emit()
        elif mode == 'notices':
            show_result(window, 'PRIVATE_NOTICE_MUST_NOT_BE_CAPTURED', persistent=True, kind='live')
        entries = window.sidebar._items + list(window.sidebar._folder_buttons.values())
        before_geometry = [entry.geometry() for entry in entries]
        before_scroll = window.sidebar.scroll.verticalScrollBar().value()
        window._diagnostic_shortcut.activated.emit()
        assert [entry.geometry() for entry in entries] == before_geometry
        assert window.sidebar.scroll.verticalScrollBar().value() == before_scroll
        QTest.qWait(650)
        assert window.sidebar.rooms() == before_rooms
        assert [dict(tile.room) for tile in window.wall.tiles] == before_wall
        fixture.app.aboutToQuit.emit()
        capture.close()
        if mode in ('notices', 'danmaku'):
            # Wait for the same bounded asynchronous writer used by the frozen app.
            import atexit
            atexit._run_exitfuncs()
        files = list(Path(directory).glob('*.jsonl'))
        content = '\n'.join(path.read_text(encoding='utf-8') for path in files)
        assert 'PRIVATE_NAME_MUST_NOT_BE_CAPTURED' not in content
        assert 'PRIVATE_NOTICE_MUST_NOT_BE_CAPTURED' not in content
        metadata = [json.loads(line) for line in (Path(directory) / 'diagnostic-session.jsonl').read_text().splitlines()]
        assert {'session-start', 'window-ready', 'user-marker'} <= {row['stage'] for row in metadata}
        ready = next(row for row in metadata if row['stage'] == 'window-ready')
        assert ready['linked_sessions']
        if mode in ('folders', 'responsiveness'):
            path = Path(directory) / ('folder-motion.jsonl' if mode == 'folders' else 'responsiveness.jsonl')
            records = [json.loads(line) for line in path.read_text().splitlines()]
            manual = next(row for row in records if row.get('action') == 'manual-snapshot')
            assert manual['frames'] and manual['folders']
            assert manual['schema'] == 2 and manual['evidence_after']['widgets']
            assert manual['post_window_ms'] == 2000 and manual['evidence_before']['model']
            assert {'preview:delay-fired', 'preview:grace-fired'} <= {row['stage'] for row in manual['events']}
        if mode == 'notices':
            records = [json.loads(line) for line in (Path(directory) / 'notice-close.jsonl').read_text().splitlines()]
            assert any(row['stage'] == 'manual-snapshot' for row in records)
        print('capture mode passed:', mode)
    finally:
        capture.close()
        fixture.doCleanups()


class SessionTests(unittest.TestCase):
    def test_mode_selection_is_explicit_and_rejects_unknown_or_repeated_modes(self):
        self.assertIsNone(requested_mode([]))
        self.assertIsNone(requested_mode(['--unrelated']))
        for mode in MODES:
            self.assertEqual(requested_mode(['--diagnose-session=' + mode]), mode)
        for arguments in (['--diagnose-session=all'], ['--diagnose-session='],
                          ['--diagnose-session=folders', '--diagnose-session=notices']):
            with self.assertRaises(ValueError):
                requested_mode(arguments)

    def test_modes_collect_without_changing_rooms_or_capturing_text(self):
        for mode in MODES:
            if mode == 'drag' and sys.platform != 'win32':
                continue
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                env = dict(os.environ, DDM_NO_SAVE='1', QT_QPA_PLATFORM='offscreen', DDM_CHECK_MODE='offline')
                result = subprocess.run([sys.executable, str(ROOT / 'dev/checks/bootstrap.py'),
                                         __file__, '--child', mode, directory],
                                        env=env, capture_output=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout.decode('utf-8', errors='replace')
                                 + result.stderr.decode('utf-8', errors='replace'))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(sys.argv[2], sys.argv[3])
    else:
        unittest.main()
