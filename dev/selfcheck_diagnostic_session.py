"""Isolated capture integration checks; synthetic data, not an issue reproduction."""
import json
import os
from pathlib import Path
import runpy
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.diagnostic_session import MODES
from ddm.diagnostic_startup_request import (
    MATCH_MODES, REQUEST_NAME, SOURCE_MODES, available_modes, consume, prepare,
)


def child(mode, directory):
    from PySide6.QtCore import QEvent, Qt
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
        elif mode == 'drag':
            assert capture.recorder.profile_first_drag
        elif mode == 'dock-hover':
            from PySide6.QtWidgets import QApplication
            button = window.sidebar.workspace_controls.launcher
            button.setAccessibleName('PRIVATE_DOCK_LABEL_MUST_NOT_BE_CAPTURED')
            trace = window._dock_hover_trace
            trace.timer.stop()
            position = button.mapToGlobal(button.rect().center())
            with patch('ddm.dock_hover_diagnostics.QCursor.pos', return_value=position), \
                    patch.object(QApplication, 'widgetAt', return_value=button) as hit:
                button.setAttribute(Qt.WA_UnderMouse, False)
                for _ in range(3):
                    trace.sample_pointer()
                event = QEvent(QEvent.Enter)
                event.ignore()
                assert trace.eventFilter(button, event) is False and not event.isAccepted()
                button.setAttribute(Qt.WA_UnderMouse, True)
                trace.sample_pointer()
                trace.eventFilter(button, QEvent(QEvent.ActionChanged))
                trace.eventFilter(button, QEvent(QEvent.Leave))
                button.setAttribute(Qt.WA_UnderMouse, False)
                for _ in range(3):
                    trace.sample_pointer()
                with patch('ddm.sidebar_navigation.QCursor.pos', return_value=position):
                    window.sidebar.navigation.sync_pointer_hover()
                for _ in range(3):
                    trace.sample_pointer()
                hit.return_value = None
                window.sidebar.navigation.sync_pointer_hover()
                for _ in range(3):
                    trace.sample_pointer()
        elif mode == 'tiles':
            first, second = window.wall.visible_tiles()[:2]
            trace = window._tile_trace
            with patch('ddm.tile_diagnostics.QCursor') as cursor:
                for tile in (first, second):
                    cursor.pos.return_value = tile.mapToGlobal(tile.rect().center())
                    trace.sample_pointer()
                    tile.set_controls_visible(True)
                    trace.sample_pointer()
                    event = QEvent(QEvent.Leave)
                    event.ignore()
                    assert trace.eventFilter(tile, event) is False
                    assert not event.isAccepted()
                    tile.set_controls_visible(False)
        if mode == 'responsiveness':
            assert window._startup_scroll_capture.probe is capture.probe
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
        if mode == 'dock-hover':
            assert trace.closed
        if mode in ('notices', 'danmaku'):
            # Wait for the same bounded asynchronous writer used by the frozen app.
            import atexit
            atexit._run_exitfuncs()
        files = list(Path(directory).glob('*.jsonl'))
        content = '\n'.join(path.read_text(encoding='utf-8') for path in files)
        assert 'PRIVATE_NAME_MUST_NOT_BE_CAPTURED' not in content
        assert 'PRIVATE_NOTICE_MUST_NOT_BE_CAPTURED' not in content
        assert 'PRIVATE_DOCK_LABEL_MUST_NOT_BE_CAPTURED' not in content
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
        if mode == 'fullscreen':
            assert not (Path(directory) / 'fullscreen.jsonl').exists()
            trace = Path(directory) / f"fullscreen-session-{ready['run']}.jsonl"
            records = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
            assert any(row['phase'] == 'start' and row['session'] == ready['linked_sessions'][mode]
                       for row in records)
        if mode == 'dock-hover':
            misses = [row for row in metadata if row['stage'] == 'dock-hover-mismatch']
            assert [row['reason'] for row in misses] == ['missing-on-entry', 'lost-while-inside']
            assert all(row['qtHit'] == 'button' and not row['underMouse'] for row in misses)
            events = [row for row in metadata if row['stage'] == 'dock-hover-event']
            assert {'Enter', 'Leave', 'ActionChanged'} <= {row['event'] for row in events}
            assert any(row['stage'] == 'dock-hover-pointer' and row.get('qtHit') == 'none'
                       for row in metadata)
            assert any(row['stage'] == 'dock-hover-pointer' and row.get('effectiveHover')
                       and not row.get('underMouse') for row in metadata)
            assert ready['linked_sessions']['dock-hover'] == ready['run']
        if mode == 'tiles':
            startup = [row for row in metadata if row['stage'] == 'tile-startup']
            assert any(row['event'] == 'ready' and not row['visible'] for row in startup)
            assert any(row['event'] == 'Paint' and row['tileGeometry'] for row in startup)
            pointer = [row for row in metadata if row['stage'] == 'tile-pointer' and row['tile'] is not None]
            assert len({row['tile'] for row in pointer}) == 2
            assert any(row['controlsVisible'] for row in pointer)
            assert all(isinstance(row['barExposed'], bool) and isinstance(row['titleVisible'], bool)
                       for row in pointer)
            events = [row for row in metadata if row['stage'] == 'tile-event']
            assert {'Show', 'Hide', 'Leave'} <= {row['event'] for row in events}
            assert ready['linked_sessions']['tiles'] == ready['run']
        print('capture mode passed:', mode)
    finally:
        capture.close()
        fixture.doCleanups()


class SessionTests(unittest.TestCase):
    def test_startup_request_is_checkout_scoped_single_use_and_expires(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as other:
            root, other = Path(directory), Path(other)
            self.assertIsNone(consume(root))
            self.assertFalse((root / 'work').exists())
            for mode in ('all', '../drag', *MATCH_MODES):
                with self.assertRaises(ValueError):
                    prepare(root, mode)
            for mode in available_modes(root):
                request = prepare(root, mode)
                self.assertIsNone(consume(other))
                self.assertEqual(consume(root), request)
                self.assertIsNone(consume(root))
            prepare(root, 'drag')
            request = prepare(root, 'fullscreen-input')
            with ThreadPoolExecutor(4) as readers:
                results = list(readers.map(consume, [root] * 4))
            self.assertEqual([item for item in results if item], [request])
            path = root / 'work' / REQUEST_NAME
            prepare(root, 'drag')
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE pending SET expires_at = ?', (int(time.time()) - 1,))
            self.assertIsNone(consume(root))
            self.assertIsNone(consume(root))

    def test_source_modes_install_in_the_main_process(self):
        for mode in (*SOURCE_MODES, *(mode for mode in MATCH_MODES if mode in available_modes(ROOT))):
            if mode == 'live-elapsed' and sys.platform != 'win32':
                continue
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if mode in MATCH_MODES:
                    for name in ('dev/match_gui_dispatch.py', 'work/match-d3d11-prototype/presenter.exe',
                                 'work/match-d3d11-prototype/mailbox.dll'):
                        path = root / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.touch()
                request = prepare(root, mode)
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'dev/checks/bootstrap.py'), __file__, '--source-child', directory],
                    env=dict(os.environ, DDM_NO_SAVE='1', QT_QPA_PLATFORM='offscreen', DDM_CHECK_MODE='offline'),
                    capture_output=True, timeout=45,
                )
                output = result.stdout.decode('utf-8', 'replace') + result.stderr.decode('utf-8', 'replace')
                self.assertEqual(result.returncode, 0, output)
                self.assertIn(request['request_id'], output)
                self.assertIsNone(consume(root))

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


def source_child(root):
    from ddm import app, diagnostics
    from ddm.app import MainWindow
    from ddm.room_placement import RoomPlacement
    from ddm.wall_replacement import WallReplacement
    from ddm.video_danmaku import SuperChatOverlay
    from ddm.danmaku_diagnostics import MotionTrace
    from dev.startup_diagnostics import ENVIRONMENT, install

    hooks = {
        'window-resize': (MainWindow, 'nativeEvent'),
        'window-dpi-profile': (MainWindow, 'nativeEvent'),
        'control-swap': (RoomPlacement, 'hot_swap'),
        'wall-replacement': (WallReplacement, 'place'),
        'sc': (SuperChatOverlay, '_render_layered'),
        'danmaku-motion': (MotionTrace, 'install'),
        'live-elapsed': (MainWindow, '_on_status_updated'),
        'responsiveness-profile': (MainWindow, '__init__'),
    }
    with closing(sqlite3.connect(root / 'work' / REQUEST_NAME)) as db:
        mode, request_id = db.execute('SELECT mode, request_id FROM pending').fetchone()
    if mode == 'settings-scroll':
        launcher = root / 'main.py'
        shutil.copyfile(ROOT / 'main.py', launcher)
        with patch.object(app, 'main', return_value=0) as launch, \
                patch.object(diagnostics, 'start'), patch.object(sys, 'argv', [str(launcher)]):
            for expected in (dict(mode=mode, request_id=request_id), None):
                try:
                    runpy.run_path(str(launcher), run_name='__main__')
                except SystemExit as exit_result:
                    assert exit_result.code == 0
                launch.assert_called_once_with(startup_diagnostics=expected)
                launch.reset_mock()
        assert os.environ['DDM_SETTINGS_SCROLL_CAPTURE'] == '1'
        print(request_id)
        return
    request = consume(root)
    mode = request['mode']
    hook = hooks.get(mode)
    if mode == 'danmaku-motion' or mode in MATCH_MODES:
        # Observe the real MotionTrace installation without leaving fixture hooks behind.
        with patch.object(MotionTrace, 'install', autospec=True, side_effect=MotionTrace.install) as called:
            state = install(ROOT, root / 'logs', request)
            called.assert_called_once()
    else:
        original = getattr(*hook) if hook else None
        state = install(ROOT, root / 'logs', request)
        if hook:
            assert getattr(*hook) is not original, mode
    assert state == dict(mode=mode, request_id=request['request_id'])
    for name, value in ENVIRONMENT.get(mode, {}).items():
        assert os.environ[name] == value
    print(state['request_id'])


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(sys.argv[2], sys.argv[3])
    elif len(sys.argv) > 1 and sys.argv[1] == '--source-child':
        source_child(Path(sys.argv[2]))
    else:
        unittest.main()
