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
from PySide6.QtWidgets import QApplication
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
            if action.startswith('logos-'):
                if len(self.plugin_checks) != 2:
                    QTimer.singleShot(10, self.exercise)
                    return
                assert {check.text() for check in self.plugin_checks.values()} == {'显示海外平台 Logo', '显示国内平台 Logo'}
                assert not self.general_page._checks['sidebar_platform_logos'].isVisible()
                assert not any(check.isChecked() for check in self.plugin_checks.values())
                self.plugin_checks['global_live_show_platform_logo'].setChecked(True)
                self.general_page.volume_slider.setValue(17)
                if action == 'logos-save':
                    self.confirm_button.click()
                else:
                    self.reject()
                return
            if action.startswith(('clean-', 'revert-')):
                before = int(self.winId())
                if action.startswith('revert-'):
                    initial = self.general_page.volume_slider.value()
                    self.general_page.volume_slider.setValue(17)
                    self.general_page.volume_slider.setValue(initial)
                for index in (2, 3, 4, 5, 0):
                    self.nav.setCurrentRow(index)
                page = action.split('-')[1]
                self.nav.setCurrentRow(self.PAGE_INDEX[page])
                assert self.isVisible() and self.isEnabled()
                assert int(self.winId()) == before and self.nav.currentRow() == self.PAGE_INDEX[page]
                self.nav.setCurrentRow(0)
                self.reject()
                return
            if action.startswith('embed-'):
                self.general_page.volume_slider.setValue(17)
                self.shell_hwnd = int(self.winId())
                self.sequence = iter((6,) if action.startswith('embed-restart-') else (1, 0, 6, 2, 7, 5, 1, 0))
                QTimer.singleShot(10000 if action == 'embed-save' else 40, self.step)
                return
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
            if action == 'cancel':
                self.reject()
            else:
                for index in (2, 3, 4, 5, 0):
                    self.nav.setCurrentRow(index)
                self.confirm_button.click()

        def step(self):
            index = next(self.sequence, None)
            if index is None:
                if action == 'embed-save' or action.startswith('embed-restart-'):
                    self.confirm_button.click()
                else:
                    self.reject()
                return
            self.nav.setCurrentRow(index)
            def observed():
                assert int(self.winId()) == self.shell_hwnd and self.isVisible() and self.isEnabled()
                assert self.nav.currentRow() == index
                assert self.general_page.volume_slider.value() == 17
                print(settings_process.PREFIX + json.dumps({
                    'kind': 'shell', 'index': index, 'hwnd': int(self.winId()),
                    'embedded': self.host_container is not None,
                    'size': [self.width(), self.height()]}), flush=True)
                QTimer.singleShot(50, self.step)
            QTimer.singleShot(200, observed)

    dialogs.SettingsDialog = AutomatedDialog
    if action.startswith('embed-'):
        def background_activate(dialog):
            from PySide6.QtCore import Qt
            dialog.setAttribute(Qt.WA_ShowWithoutActivating)
            dialog.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
            dialog.setGeometry(-10000, -10000, 980, 720)
            dialog.show()
        settings_process._activate_dialog = background_activate
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
    client.hostRequest.connect(lambda message: pages.append(message['index']) if message['kind'] == 'host-page' else None)
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
            initial = dict(config.DEFAULT_SETTINGS, default_volume=42, seen_update_versions={'app': '0.5.1'})
            client.open(initial, {})
            client.open(initial, {})  # Pending/visible clicks must not recreate the window.
            assert grant.call_count == 2 and all(call.args == (pid,) for call in grant.call_args_list)
            wait(app, lambda: any(m['kind'] == 'result' for m in messages))
            assert not failures and not client.visible
            assert sum(m['kind'] == 'painted' for m in messages) == 1
            clean = action.startswith(('clean-', 'revert-'))
            assert bool(saves) == (not clean and action != 'cancel')
            if saves:
                assert saves[0]['settings']['default_volume'] == 17
                assert 'appearance_mode' not in saves[0]['settings']
                assert 'seen_update_versions' not in saves[0]['settings'], 'Worker must not clear host update history'
            assert pages == ([{'appearance': 1, 'plugins': 6, 'updates': 7}[action.split('-')[1]]] if clean else [])
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


def check_host_save_validation():
    from unittest.mock import Mock
    from ddm.dialogs import SettingsDialog
    from ddm.settings_host import SettingsHost
    default_dialog = SettingsDialog(config.DEFAULT_SETTINGS, {}, preview=True)
    assert default_dialog.width() == 720 and default_dialog.height() == 650
    default_dialog.deleteLater()
    dialog = Mock()
    dialog.confirm_button.isEnabled.return_value = True
    dialog.result.return_value = SettingsDialog.Accepted
    dialog.enabled_plugins.return_value = {'fixture'}
    dialog._loaded_pages = {7: SimpleNamespace(install_requested=False)}
    dialog.restart_requested = True
    applied = []
    client = SimpleNamespace(_send=Mock(), closing=False)
    window = SimpleNamespace(shortcuts={'keep': 'K'},
                             _close_settings_host=lambda: order.append('closed'),
                             _apply_settings_dialog=lambda adapter, before: applied.append((adapter, before)))
    order = []
    session = SimpleNamespace(dialog=dialog, client=client, window=window, before='before',
                              values=lambda: {'auto_update': True}, sync=Mock(), pending_apply=None)
    changes = {'settings': {'default_volume': 17}, 'shortcuts': {'edit': 'E'}}
    SettingsHost.save(session, changes)
    assert not applied, 'Must wait for the worker to detach and close'
    assert session.pending_apply is not None
    SettingsHost.save(session, changes)
    client._send.assert_called_once_with({'kind': 'host-saved'})
    SettingsHost.handle(session, {'kind': 'result'})
    assert order == ['closed']
    adapter, before = applied.pop()
    assert adapter.settings() == {'default_volume': 17, 'auto_update': True}
    assert adapter.shortcuts() == {'keep': 'K', 'edit': 'E'}
    assert adapter.enabled_plugins() == {'fixture'} and adapter.restart_requested and before == 'before'
    assert adapter.update_page.install_requested is False and adapter.update_page.plan_path == ''
    client._send.assert_called_once_with({'kind': 'host-saved'})
    client._send.reset_mock()
    dialog.result.return_value = SettingsDialog.Rejected
    SettingsHost.save(session, changes)
    assert not applied
    client._send.assert_called_once_with({'kind': 'host-save-blocked', 'index': 1})
    client._send.reset_mock()
    dialog.confirm_button.isEnabled.return_value = False
    SettingsHost.save(session, changes)
    assert not applied and not client._send.called and session.sync.called


def check_host_application(app, action='save', *, installed_controls=False):
    from ddm import app as host, plugins, online_ui, theme
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'REPO', temporary))
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')))
        stack.enter_context(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(Path(temporary) / 'plugins')))
        stack.enter_context(patch.object(online_ui.OnlinePage, 'start'))
        for name in ('start_all', 'refresh_account', 'refresh_status', 'refresh_stats',
                     'load_cached_covers', 'load_cached_avatars', 'load_room_avatars'):
            stack.enter_context(patch.object(host.MainWindow, name))
        with patch.object(host.QTimer, 'singleShot'):
            window = host.MainWindow([], [], layout_id='1x1', state={
                'plugins_enabled': [], 'settings': {'seen_update_versions': {'app': '0.5.1'},
                                                   'appearance_mode': 'light' if action == 'embed-cancel' else 'dark',
                                                   'sidebar_platform_logos': not action.startswith('logos-')}})
        plugin_saves = {}
        if action.startswith('logos-'):
            from PySide6.QtCore import QEvent, QObject
            from PySide6.QtWidgets import QCheckBox
            from ddm.dialogs import SettingsDialog

            class ContributedChecks(QObject):
                def eventFilter(self, watched, event):
                    if (event.type() == QEvent.Show and isinstance(watched, SettingsDialog)
                            and watched._plugin_manager is window.plugins):
                        page = watched.general_page
                        grid = page.layout().itemAt(1).layout()
                        for name, label in (('domestic_live', '显示国内平台 Logo'), ('global_live', '显示海外平台 Logo')):
                            control_name = name + '_show_platform_logo'
                            if page.findChild(QCheckBox, control_name) is None:
                                check = QCheckBox(label, page)
                                check.setObjectName(control_name)
                                check.setChecked(True)
                                grid.addWidget(check, grid.rowCount(), 0, 1, 2)
                                watched.accepted.connect(lambda key=name, check=check: plugin_saves.update({key: check.isChecked()}))
                    return False
            if installed_controls:
                import ast
                from PySide6.QtWidgets import QLabel
                from PySide6.QtCore import Qt
                for name, label in (('domestic_live', '显示国内平台 Logo'), ('global_live', '显示海外平台 Logo')):
                    source = ROOT / 'plugins_user' / name / 'plugin.py'
                    tree = ast.parse(source.read_text(encoding='utf-8'))
                    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                                      and node.name == 'PlatformLogoControl')
                    namespace = dict(QObject=QObject, QApplication=QApplication, QEvent=QEvent, Qt=Qt,
                                     SettingsDialog=SettingsDialog, QCheckBox=QCheckBox, QLabel=QLabel)
                    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), 'exec'), namespace)
                    context = SimpleNamespace(window=window, manager=window.plugins, name=name,
                        setting=lambda _key, default: default,
                        set_setting=lambda _key, value, name=name: plugin_saves.update({name: value}))
                    extension = namespace['PlatformLogoControl'](context, (), label)
                    stack.callback(extension.detach)
            else:
                extension = ContributedChecks(window)
                app.installEventFilter(extension)
                stack.callback(app.removeEventFilter, extension)
        client = window._get_settings_process()
        initial_volume = window.settings['default_volume']
        messages = []
        client.received.connect(messages.append)
        command = (sys.executable, [str(Path(__file__).resolve()), '--worker-check', action])
        stack.enter_context(patch.object(settings_process, 'worker_command', return_value=command))
        if action.startswith('embed-'):
            errors = []
            stack.enter_context(patch.object(sys, 'excepthook', lambda _kind, error, _tb: errors.append(error)))
            from ddm.dialogs import SettingsDialog
            stack.enter_context(patch.object(SettingsDialog, 'exec', side_effect=AssertionError('Settings reopened')))
            if action == 'embed-install':
                stack.enter_context(patch.object(sys, 'frozen', True, create=True))

            def observed(message):
                if message['kind'] != 'shell':
                    return
                import ctypes
                session = window._settings_host
                assert session is not None and not session.dialog.isVisible()
                user32 = ctypes.windll.user32
                user32.GetAncestor.restype = ctypes.c_void_p
                handle = ctypes.c_void_p(int(session.stack.winId()))
                assert user32.GetAncestor(handle, 2) == message['hwnd'], 'Host page is not inside worker shell'
                assert user32.GetDpiForWindow(handle) == user32.GetDpiForWindow(ctypes.c_void_p(message['hwnd']))
                assert session.stack.isVisible()
                assert session.stack.width() > 400 and session.stack.height() > 300
                assert message['embedded']
                assert session.dialog.nav.currentRow() == (message['index'] if message['index'] in (1, 6, 7) else -1)
                if message['index'] in (1, 6, 7):
                    image = session.stack.grab().toImage()
                    actual = image.pixelColor(1, 1)
                    assert actual == theme.qcolor(theme.BG), (message['index'], actual.name(), theme.BG, actual.alpha())
                    output = ROOT / 'work/test-artifacts/host/settings-pages'
                    output.mkdir(parents=True, exist_ok=True)
                    image.save(str(output / f"{theme.mode()}-{message['index']}.png"))
                if message['index'] == 7:
                    session.dialog.update_page.auto.setChecked(True)
                    if action == 'embed-install':
                        page = session.dialog.update_page
                        page.plan_path = str(Path(temporary) / 'synthetic-update-plan.json')
                        page._busy(False)
                        page.action.click()
            client.received.connect(observed)
        try:
            client.open(window.settings, window.shortcuts)
            # Host changes made while the editor is open must survive its save.
            window.settings['skin_mask'] = 29
            window.shortcuts['fullscreen'] = 'Ctrl+F10'
            wait(app, lambda: window._closing if action == 'embed-install' else
                 any(message['kind'] == 'result' for message in messages), timeout=25)
            assert window.settings['seen_update_versions'] == {'app': '0.5.1'}
            if action == 'embed-install':
                assert window._update_plan == str(Path(temporary) / 'synthetic-update-plan.json')
                assert window.settings['default_volume'] == 17 and not errors
                return
            if action.startswith('logos-'):
                assert plugin_saves == ({'domestic_live': False, 'global_live': True} if action == 'logos-save' else {})
                assert window.settings['sidebar_platform_logos'] is (action == 'logos-save')
                assert window.settings['default_volume'] == (17 if action == 'logos-save' else initial_volume)
                return
            if action.startswith('embed-'):
                shells = [message for message in messages if message['kind'] == 'shell']
                assert [message['index'] for message in shells] == [1, 0, 6, 2, 7, 5, 1, 0]
                assert len({message['hwnd'] for message in shells}) == 1, 'Shell was recreated'
                assert len({tuple(message['size']) for message in shells}) == 1, 'Shell geometry changed'
                assert getattr(window, '_settings_host', None) is None, 'Host pages leaked after close'
                assert window.settings['default_volume'] == (17 if action == 'embed-save' else initial_volume)
                assert window.settings['auto_update'] is (action == 'embed-save')
                assert window.settings['skin_mask'] == 29 and window.shortcuts['fullscreen'] == 'Ctrl+F10'
                assert not errors, errors
                return
            assert window.settings['default_volume'] == 17
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


def restart_host_fixture(action, path):
    """Actual host event-loop exit, with only an owned synthetic plugin."""
    import ctypes
    from PySide6.QtCore import Qt
    from ddm import app as host, online_ui, plugins
    from ddm.dialogs import PluginRemovePrompt
    app = QApplication([])
    root = Path(path).parent
    (root / 'main.py').write_text(
        "from pathlib import Path\nPath(__file__).with_name('restarted.txt').write_text('restarted')\n",
        encoding='utf-8')
    plugin_dir = root / 'plugins'
    plugin_id = 'restart_fixture'
    state = {'pid': os.getpid(), 'worker_pid': None}
    def report(**fields):
        state.update(fields)
        Path(path).write_text(json.dumps(state), encoding='utf-8')
    def create_plugin():
        folder = plugin_dir / plugin_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'plugin.json').write_text(json.dumps({'id': plugin_id, 'name': '重启测试插件',
            'version': '1.0', 'description': 'isolated fixture'}), encoding='utf-8')
        (folder / 'plugin.py').write_text("raise RuntimeError('Never load this fixture')", encoding='utf-8')
    if action == 'delete':
        create_plugin()
    with ExitStack() as patches:
        patches.enter_context(patch.object(config, 'REPO', str(root)))
        patches.enter_context(patch.object(config, 'CONFIG_PATH', str(root / 'config.json')))
        patches.enter_context(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(plugin_dir)))
        patches.enter_context(patch.object(online_ui.OnlinePage, 'start'))
        for name in ('start_all', 'refresh_account', 'refresh_status', 'refresh_stats',
                     'load_cached_covers', 'load_cached_avatars', 'load_room_avatars'):
            patches.enter_context(patch.object(host.MainWindow, name))
        with patch.object(host.QTimer, 'singleShot'):
            window = host.MainWindow([], [], state={'plugins_enabled': []})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        window.setGeometry(-10000, -10000, 900, 650)
        window.show()
        client = window._get_settings_process()
        patches.enter_context(patch.object(settings_process, 'worker_command', return_value=(sys.executable,
            [str(Path(__file__).resolve()), '--worker-check', 'embed-restart-' + action])))
        original_apply = window._apply_settings_dialog
        source_handle = [None]
        def apply(adapter, before):
            user32 = ctypes.windll.user32
            user32.GetAncestor.restype = ctypes.c_void_p
            ancestor = user32.GetAncestor(ctypes.c_void_p(source_handle[0]), 2)
            report(embedded_at_close=ancestor == state.get('shell_hwnd'))
            return original_apply(adapter, before)
        window._apply_settings_dialog = apply
        def observed(message):
            if message['kind'] == 'ready':
                report(worker_pid=message['pid'])
            elif message['kind'] == 'shell':
                session = window._settings_host
                page = session.dialog.plugin_page
                source_handle[0] = int(session.stack.winId())
                report(shell_hwnd=message['hwnd'])
                if action == 'install':
                    create_plugin()
                    page.store_page._installed((plugin_id, True))
                elif action == 'delete':
                    execute = PluginRemovePrompt.exec
                    def confirm(prompt):
                        prompt.setAttribute(Qt.WA_ShowWithoutActivating)
                        prompt.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
                        prompt.move(-10000, -10000)
                        QTimer.singleShot(0, prompt.delete_button.click)
                        return execute(prompt)
                    with patch.object(PluginRemovePrompt, 'exec', confirm):
                        page._remove(plugin_id, page.cards.itemAt(0).widget())
                    assert window.isVisible(), 'Delete confirmation must not close the main window'
                else:
                    window.close()
                    return
                session.sync()
        client.received.connect(observed)
        def timed_out():
            report(timed_out=True, main_hidden=not window.isVisible(),
                   host_alive=getattr(window, '_settings_host', None) is not None)
            app.quit()
        QTimer.singleShot(10000, timed_out)
        QTimer.singleShot(0, lambda: client.open(window.settings, window.shortcuts))
        app.exec()
        report(restart_requested=window._restart_requested,
               restart_launched=host._launch_restart() if window._restart_requested else False)
        # Match the real host's immediate process exit after requesting restart.
        os._exit(0)


def check_restart_native():
    import subprocess
    import psutil
    for action in ('install', 'delete', 'close'):
        with tempfile.TemporaryDirectory(prefix='ddm-settings-restart-') as temporary:
            path = Path(temporary) / 'result.json'
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                '--restart-host-fixture', action, str(path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            worker = None
            try:
                output, _ = process.communicate(timeout=20)
                data = json.loads(path.read_text(encoding='utf-8'))
                print('Native restart:', action, data, flush=True)
                try:
                    worker = psutil.Process(data['worker_pid'])
                    worker.wait(timeout=4)
                except psutil.NoSuchProcess:
                    pass
                assert process.returncode == 0, output.decode('utf-8', errors='replace')
                assert not data.get('timed_out'), data
                if action == 'close':
                    assert not data.get('restart_requested') and not data.get('restart_launched'), data
                else:
                    assert data.get('restart_requested') and data.get('restart_launched'), data
                    assert data.get('embedded_at_close') is False, 'Host closed while owning a foreign child'
                    deadline = time.monotonic() + 4
                    while not (Path(temporary) / 'restarted.txt').exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    assert (Path(temporary) / 'restarted.txt').exists(), 'Replacement process did not run'
            finally:
                if process.poll() is None:
                    for child_process in psutil.Process(process.pid).children(recursive=True):
                        child_process.kill()
                    process.kill()
                    process.wait()
                if path.exists():
                    pid = json.loads(path.read_text(encoding='utf-8')).get('worker_pid')
                    try:
                        orphan = psutil.Process(pid)
                        if '--worker-check' in orphan.cmdline() and 'embed-restart-' + action in orphan.cmdline():
                            orphan.kill()
                            orphan.wait(timeout=4)
                    except psutil.NoSuchProcess:
                        pass
    print('PASS: install/delete restart releases foreign pages before host exit; no settings process remains')


def main():
    if sys.argv[1:2] == ['--worker-check']:
        return child(sys.argv[2])
    if sys.argv[1:2] == ['--restart-host-fixture']:
        return restart_host_fixture(sys.argv[2], sys.argv[3])
    if sys.argv[1:] == ['--restart-native']:
        return check_restart_native()
    app = QApplication.instance() or QApplication([])
    os.environ['DDM_SETTINGS_TEST_QT'] = qVersion()
    app.setQuitOnLastWindowClosed(False)
    if sys.argv[1:] == ['--native-focus']:
        check_native_focus(app)
        return 0
    if sys.argv[1:] == ['--embedded-native']:
        assert app.platformName() == 'windows'
        check_host_application(app, 'embed-save')
        check_host_application(app, 'embed-cancel')
        check_host_application(app, 'embed-install')
        print('PASS: same worker HWND after 10s and all page switches, native embedding/DPI, save/cancel and cleanup')
        return 0
    if sys.argv[1:] == ['--installed-logo-controls']:
        check_host_application(app, 'logos-save', installed_controls=True)
        check_host_application(app, 'logos-cancel', installed_controls=True)
        print('PASS: installed domestic/global logo control classes bridged without importing plugin runtimes')
        return 0
    for action in ('clean-appearance', 'clean-plugins', 'clean-updates', 'revert-appearance',
                   'save', 'cancel', 'busy'):
        check_worker(app, action)
    check_failure(app)
    check_windowed_worker(app)
    check_close_during_edit(app)
    check_host_adapter()
    check_host_save_validation()
    check_host_application(app)
    check_host_application(app, 'logos-save')
    check_host_application(app, 'logos-cancel')
    print('PASS: isolated settings save/cancel, unchanged shell on page switch, validation, reuse, retry and GUI isolation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
