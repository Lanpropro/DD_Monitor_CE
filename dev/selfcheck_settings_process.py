"""独立设置进程回归；合成配置、离屏窗口，不启动用户客户端。"""
import os
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QProcess, QTimer, qVersion
from PySide6.QtWidgets import QApplication, QMessageBox
from ddm import config, settings_process


def child(action):
    expected_qt = os.environ.get('DDM_SETTINGS_TEST_QT')
    assert expected_qt is None or qVersion() == expected_qt, 'Worker must use the host Qt runtime'
    from ddm import dialogs
    original = dialogs.SettingsDialog

    class AutomatedDialog(original):
        def showEvent(self, event):
            super().showEvent(event)
            QTimer.singleShot(40, self.exercise)

        def exercise(self):
            if action == 'focus':
                self.general_page.volume_slider.setValue(17)
                return
            if action == 'busy':
                print(settings_process.PREFIX + '{"kind":"busy"}', flush=True)
                until = time.perf_counter() + 0.6
                while time.perf_counter() < until:
                    pass  # Deliberately hold this process's GUI thread and GIL.
            self.general_page.volume_slider.setValue(17)
            self.general_page._checks['preview_on_hover'].setChecked(False)
            if 'sidebar_platform_logos' in self.general_page._checks:
                self.general_page._checks['sidebar_platform_logos'].setChecked(False)
            if action.startswith('page'):
                choice = action.split('-')[1]
                with patch.object(QMessageBox, 'question', return_value=getattr(QMessageBox, choice)):
                    self.nav.setCurrentRow(1)
                if choice == 'Cancel':
                    assert self.isVisible() and self.nav.currentRow() == 0
                    self.reject()
            elif action == 'cancel':
                self.reject()
            else:
                # Exercise every supported lazy page without creating host pages.
                for index in (2, 3, 4, 5, 0):
                    self.nav.setCurrentRow(index)
                self.confirm_button.click()

    dialogs.SettingsDialog = AutomatedDialog
    if action == 'focus':
        activate = settings_process._activate_dialog

        def observed_activate(dialog):
            activate(dialog)
            import ctypes
            ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
            QTimer.singleShot(30, lambda: print(settings_process.PREFIX + json.dumps({
                'kind': 'activated', 'hwnd': int(dialog.winId()),
                'foreground': ctypes.windll.user32.GetForegroundWindow(),
                'volume': dialog.general_page.volume_slider.value()}), flush=True))
        settings_process._activate_dialog = observed_activate
    return settings_process.run_worker()


def wait(app, predicate, timeout=12):
    until = time.perf_counter() + timeout
    while not predicate():
        assert time.perf_counter() < until, 'Worker operation timed out'
        app.processEvents()
        time.sleep(0.001)


def check_worker(app, action):
    messages, saves, pages, failures, ticks = [], [], [], [], []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start()
    client = settings_process.SettingsProcess()
    client.received.connect(messages.append)
    client.saved.connect(saves.append)
    client.hostPage.connect(pages.append)
    client.failed.connect(failures.append)
    command = (sys.executable, [str(Path(__file__).resolve()), '--worker-check', action])
    with patch.object(settings_process, 'worker_command', return_value=command), \
            patch.object(settings_process, '_allow_foreground') as grant:
        try:
            client.warm()
            wait(app, lambda: client.ready)
            pid = messages[0]['pid']
            assert client.worker_pid == pid and not grant.called, 'Prewarming must not take focus'
            process_pid = client.process.processId()
            assert pid != os.getpid()
            initial = dict(config.DEFAULT_SETTINGS, default_volume=42)
            client.open(initial, {})
            client.open(initial, {})  # Pending/visible clicks must not recreate the window.
            assert grant.call_count == 2 and all(call.args == (pid,) for call in grant.call_args_list)
            wait(app, lambda: any(m['kind'] == 'result' for m in messages))
            assert not failures and not client.visible
            assert sum(m['kind'] == 'painted' for m in messages) == 1
            assert bool(saves) == (action not in ('cancel', 'page-Discard', 'page-Cancel'))
            if saves:
                assert saves[0]['settings']['default_volume'] == 17
                assert 'appearance_mode' not in saves[0]['settings']
            assert pages == (['appearance'] if action in ('page-Save', 'page-Discard') else [])
            if action == 'busy':
                maximum = max(b - a for a, b in zip(ticks, ticks[1:]))
                assert maximum < 0.15, maximum
                assert len(ticks) > 60, len(ticks)
                print(f'Worker busy 600ms: host maximum heartbeat gap {maximum * 1000:.1f}ms')
            # Closing and reopening uses the same prewarmed process.
            messages.clear()
            client.open(initial, {})
            wait(app, lambda: any(m['kind'] == 'result' for m in messages))
            assert client.process.processId() == process_pid
            assert next(m['pid'] for m in messages if m['kind'] == 'painted') == pid
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)
            timer.stop()
    assert not failures


def check_native_focus(app):
    """Use real Windows foreground handles, not Qt's requested active state."""
    import ctypes
    from ctypes import wintypes
    from PySide6.QtWidgets import QWidget
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.IsIconic.argtypes = (wintypes.HWND,)
    user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.WindowFromPoint.argtypes = (wintypes.POINT,)
    user32.WindowFromPoint.restype = wintypes.HWND
    window = QWidget()
    window.setWindowTitle('Settings foreground regression (synthetic)')
    window.resize(760, 520)
    client = settings_process.SettingsProcess(window)
    messages = []
    client.received.connect(messages.append)
    command = (sys.executable, [str(Path(__file__).resolve()), '--worker-check', 'focus'])

    def foreground_host():
        window.show()
        window.raise_()
        window.activateWindow()
        user32.SetForegroundWindow(int(window.winId()))
        # Give the synthetic host an actual click/last-input event. A Qt-only
        # synthetic click does not acquire Windows foreground permission.
        hwnd = int(window.winId())
        cursor, rect = wintypes.POINT(), wintypes.RECT()
        user32.GetCursorPos(ctypes.byref(cursor))
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        point = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x13)  # Test fixture only: TOPMOST, no activate/move/resize.
        try:
            assert user32.WindowFromPoint(point) == hwnd, 'Only click the empty test fixture'
            user32.SetCursorPos(point.x, point.y)
            user32.mouse_event(0x2, 0, 0, 0, 0)
            user32.mouse_event(0x4, 0, 0, 0, 0)
            wait(app, lambda: user32.GetForegroundWindow() == hwnd, timeout=3)
        finally:
            user32.SetCursorPos(cursor.x, cursor.y)
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x13)  # NOTOPMOST

    def click():
        messages.clear()
        client.open(config.DEFAULT_SETTINGS, {})
        wait(app, lambda: any(m['kind'] == 'activated' for m in messages))
        message = next(m for m in messages if m['kind'] == 'activated')
        hwnd = message['hwnd']
        print('Native focus observation:', message, 'current:', user32.GetForegroundWindow(), flush=True)
        wait(app, lambda: user32.GetForegroundWindow() == hwnd, timeout=3)
        assert not user32.IsIconic(hwnd)
        return hwnd, message['volume']

    with patch.object(settings_process, 'worker_command', return_value=command):
        try:
            foreground_host()
            hwnd, _ = click()  # Cold start: PID is only known after the handshake.
            wait(app, lambda: user32.GetForegroundWindow() == hwnd)
            foreground_host()  # Cover the already open settings window.
            assert click() == (hwnd, 17), 'Refocusing must preserve unsaved edits'
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            wait(app, lambda: bool(user32.IsIconic(hwnd)))
            foreground_host()
            assert click() == (hwnd, 17), 'A minimized editor must restore, not be recreated'
            user32.PostMessageW(hwnd, 0x10, 0, 0)  # WM_CLOSE -> cancel
            wait(app, lambda: not client.visible)
            foreground_host()
            click()  # Reopen in the already warm worker.
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)
            window.close()
    print('PASS: Windows foreground HWND on cold open, covered refocus, minimized restore and warm reopen')


def check_failure(app):
    client = settings_process.SettingsProcess()
    failures = []
    client.failed.connect(failures.append)
    with patch.object(settings_process, 'worker_command', return_value=(str(ROOT / 'missing-worker.exe'), [])):
        client.open({}, {})
        wait(app, lambda: bool(failures))
    assert client.pending is None and not client.ready
    # A subsequent attempt can launch normally.
    client.warm()
    wait(app, lambda: client.ready)
    client.process.kill()
    wait(app, lambda: client.process.state() == QProcess.NotRunning)
    assert len(failures) == 1, 'An idle worker crash should not interrupt the host'
    client.warm()
    wait(app, lambda: client.ready)
    client.stop()
    wait(app, lambda: client.process.state() == QProcess.NotRunning)
    # No synchronous waits even when a worker never completes its handshake.
    client = settings_process.SettingsProcess()
    failures = []
    client.failed.connect(failures.append)
    command = (getattr(sys, '_base_executable', sys.executable), ['-c', 'import time; time.sleep(5)'])
    with patch.object(settings_process, 'worker_command', return_value=command):
        started = time.perf_counter()
        client.open({}, {})
        assert time.perf_counter() - started < .1
        client.start_timer.start(100)
        wait(app, lambda: bool(failures))
    client.stop()


def check_windowed_worker(app):
    executable = Path(sys.executable).with_name('pythonw.exe')
    if sys.platform != 'win32' or not executable.exists():
        return
    client = settings_process.SettingsProcess()
    command = (str(executable), [str(ROOT / 'main.py'), '--settings-worker'])
    with patch.object(settings_process, 'worker_command', return_value=command):
        try:
            client.warm()
            wait(app, lambda: client.ready)
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)


def check_close_during_edit(app):
    client = settings_process.SettingsProcess()
    messages, saves = [], []
    client.received.connect(messages.append)
    client.saved.connect(saves.append)
    command = (sys.executable, [str(Path(__file__).resolve()), '--worker-check', 'busy'])
    with patch.object(settings_process, 'worker_command', return_value=command):
        try:
            client.open(config.DEFAULT_SETTINGS, {})
            wait(app, lambda: any(m['kind'] == 'busy' for m in messages))
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)
            assert not saves, 'Closing host must ignore late saves'
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)


def check_host_adapter():
    from ddm.app import MainWindow
    applied = []
    host = SimpleNamespace(shortcuts={'keep': 'K'}, plugins=SimpleNamespace(
        enabled={'fixture'}, _platform_owner={}, _removed=set()),
        _apply_settings_dialog=lambda dialog, before: applied.append(
            (dialog.settings(), dialog.shortcuts(), dialog.enabled_plugins())))
    MainWindow._remote_settings_saved(host, {'settings': {'default_volume': 17}, 'shortcuts': {'edit': 'E'}})
    assert applied == [({'default_volume': 17}, {'keep': 'K', 'edit': 'E'}, {'fixture'})]
    MainWindow._remote_settings_saved(host, {'settings': {}, 'shortcuts': {}})
    host._closing = True
    MainWindow._remote_settings_saved(host, {'settings': {'default_volume': 33}})
    assert len(applied) == 1
    host.open_settings = lambda: applied.append('original')
    with patch.dict(os.environ, {'DDM_SETTINGS_PROCESS': '0'}):
        MainWindow._open_sidebar_settings(host)
    assert applied[-1] == 'original'


def check_host_application(app):
    from ddm import app as host, plugins
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'REPO', temporary))
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')))
        stack.enter_context(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(Path(temporary) / 'plugins')))
        for name in ('start_all', 'refresh_account', 'refresh_status', 'refresh_stats',
                     'load_cached_covers', 'load_cached_avatars', 'load_room_avatars'):
            stack.enter_context(patch.object(host.MainWindow, name))
        with patch.object(host.QTimer, 'singleShot'):
            window = host.MainWindow([], [], layout_id='1x1', state={'plugins_enabled': []})
        client = window._get_settings_process()
        command = (sys.executable, [str(Path(__file__).resolve()), '--worker-check', 'save'])
        stack.enter_context(patch.object(settings_process, 'worker_command', return_value=command))
        try:
            client.open(window.settings, window.shortcuts)
            # Host changes made while the editor is open must survive its save.
            window.settings['skin_mask'] = 29
            window.shortcuts['fullscreen'] = 'Ctrl+F10'
            wait(app, lambda: window.settings['default_volume'] == 17)
            assert window.settings['skin_mask'] == 29
            assert window.shortcuts['fullscreen'] == 'Ctrl+F10'
            assert window.current_state()['settings']['default_volume'] == 17
            assert window.settings['preview_on_hover'] is False and not window.hover_preview.enabled
            if 'sidebar_platform_logos' in window.settings:
                assert window.settings['sidebar_platform_logos'] is False
                assert window.sidebar.show_platform_logos is False
            assert not Path(config.CONFIG_PATH).exists(), 'NO_SAVE must protect test state'
        finally:
            window.close()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)


def main():
    if sys.argv[1:2] == ['--worker-check']:
        return child(sys.argv[2])
    app = QApplication.instance() or QApplication([])
    os.environ['DDM_SETTINGS_TEST_QT'] = qVersion()
    app.setQuitOnLastWindowClosed(False)
    if sys.argv[1:] == ['--native-focus']:
        check_native_focus(app)
        return 0
    for action in ('save', 'cancel', 'page-Save', 'page-Discard', 'page-Cancel', 'busy'):
        check_worker(app, action)
    check_failure(app)
    check_windowed_worker(app)
    check_close_during_edit(app)
    check_host_adapter()
    check_host_application(app)
    print('PASS: isolated settings save/cancel, host page handoff, reuse, failure/retry, shutdown and GUI isolation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
