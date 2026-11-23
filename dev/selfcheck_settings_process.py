"""独立设置进程回归；合成配置、离屏窗口，不启动用户客户端。"""
import os
from contextlib import ExitStack, redirect_stderr
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import threading
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QProcess, QTimer, qVersion
from PySide6.QtWidgets import QApplication
from ddm.settings_pages import PAGE_INDEX
from ddm import config, settings_process


def embedded_page_indices(action):
    sequences = {
        'embed-footer': ('plugins', 'general', 'plugins'),
        'embed-shutdown': ('appearance',),
        'embed-scroll': ('appearance', 'shortcuts', 'updates', 'appearance', 'updates'),
        'embed-coordinates': ('appearance', 'general', 'updates', 'general', 'plugins', 'appearance', 'updates'),
        'embed-update-retry': ('general', 'updates'),
        'embed-appearance': ('appearance', 'general', 'appearance', 'plugins', 'appearance'),
    }
    keys = ('plugins',) if action.startswith('embed-restart-') else sequences.get(action, (
        'appearance', 'general', 'tray', 'plugins', 'danmaku', 'recording', 'updates', 'shortcuts',
        'appearance', 'general'))
    return tuple(PAGE_INDEX[key] for key in keys)


def child(action):
    expected_qt = os.environ.get('DDM_SETTINGS_TEST_QT')
    assert expected_qt is None or qVersion() == expected_qt, 'Worker must use the host Qt runtime'
    from ddm import dialogs
    original = dialogs.SettingsDialog

    class AutomatedDialog(original):
        def nativeEvent(self, event_type, message):
            if action in ('embed-scroll', 'embed-update-retry'):
                import ctypes
                from ctypes import wintypes
                if wintypes.MSG.from_address(int(message)).message == 0x8051:
                    QTimer.singleShot(0, self, self.step)
                    return True, 0
            return super().nativeEvent(event_type, message)

        def showEvent(self, event):
            super().showEvent(event)
            if action != 'reuse-navigation':
                QTimer.singleShot(40, self.exercise)

        def exercise(self):
            if action == 'theme':
                from ddm import theme
                def report(mode):
                    print(settings_process.PREFIX + json.dumps({'kind': 'theme-state',
                        'mode': mode, 'light': theme.is_light(),
                        'visible': self.isVisible(), 'hwnd': int(self.winId()),
                        'accent': theme.ACCENT, 'font': theme.FONT_FAMILY, 'font_size': theme.FONT_CONTROL,
                        'columns': self.general_page.sections.columns,
                        'volume': self.general_page.volume_slider.value()}), flush=True)
                if not getattr(self, '_theme_report_connected', False):
                    self._theme_report_connected = True
                    self.general_page.volume_slider.setValue(17)
                    theme.signals().changed.connect(report)
                report(theme.mode())
                return
            if action == 'streamer-defaults':
                index = self.PAGE_INDEX['streamer_defaults']
                self.nav.setCurrentRow(index)
                page = self._loaded_pages[index]
                for room_id in ('1001', 'fixture:7'):
                    page.picker.buttons[room_id].click()

                def configure():
                    if page.requests:
                        QTimer.singleShot(5, page, configure)
                        return
                    for room_id, volume in (('1001', 57), ('fixture:7', 62)):
                        card = page.cards[(room_id,)]
                        wanted = (15000, 400) if room_id == '1001' else (2, 1)
                        for combo, quality in zip((card.playback, card.recording), wanted):
                            items = [combo.itemData(index) for index in range(combo.count())]
                            match, = [index for index, item in enumerate(items)
                                      if isinstance(item, dict)
                                      and isinstance(item.get(room_id), dict)
                                      and item[room_id]['qn'] == quality]
                            combo.setCurrentIndex(match)
                        card.volume.setValue(volume)
                    self.reject()

                configure()
                return
            if action in ('preview-save', 'preview-sync-save'):
                page = self.danmaku_page
                page.super_chat_position_sync.setChecked(False)
                assert not hasattr(page.super_chat_placement, 'frame')
                page.super_chat_preview_layout.button(1).click()
                assert page.super_chat_placement.layout_mode == 'panel'
                page.super_chat_placement.position = [1.0, .2]
                page.super_chat_preview_layout.button(0).click()
                page.super_chat_placement.position = [0.0, .6]
                page.super_chat_preview_layout.button(1).click()
                assert page.super_chat_placement.position == [1.0, .2]
                if action == 'preview-sync-save':
                    page.super_chat_position_sync.click()
                    assert page.super_chat_placement.position_sync
                assert page.super_chat_placement.preview_context['panel']['size'] == [800, 450]
                assert page.super_chat_collapse_delay.suffix() == ' 秒'
                page.super_chat_opacity.setValue(45)
                assert page.super_chat_placement.opacity == 45
                assert 'sc_preview_frame' not in self.settings()
                assert 'sc_preview_context' not in self.settings()
            assert self.general_page._checks['sidebar_platform_logos'].isHidden(), 'Generic logo switch must stay hidden in the worker'
            if action.startswith('logos-'):
                if len(self.plugin_checks) != 2:
                    QTimer.singleShot(10, self.exercise)
                    return
                assert {check.text() for check in self.plugin_checks.values()} == {'显示海外平台 Logo', '显示国内平台 Logo'}
                card = self.general_page.sections.section('extensions')
                assert all(card.isAncestorOf(check) for check in self.plugin_checks.values())
                assert self.general_page.plugin_controls() == self.plugin_checks
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
                if action == 'embed-update-retry':
                    assert self.nav.currentRow() == PAGE_INDEX['updates'], 'Update entry opened the wrong page'
                self.general_page.volume_slider.setValue(17)
                self.shell_hwnd = int(self.winId())
                self.sequence = iter(embedded_page_indices(action))
                QTimer.singleShot(10000 if action == 'embed-save' else 40, self.step)
                return
            if action in ('focus', 'zorder'):
                self.general_page.volume_slider.setValue(17)
                return
            if action == 'busy':
                print(settings_process.PREFIX + '{"kind":"busy"}', flush=True)
                until = time.perf_counter() + 0.6
                while time.perf_counter() < until:
                    pass  # Deliberately hold this process's GUI thread and GIL.
            self.general_page.volume_slider.setValue(17)
            self.general_page._checks['preview_on_hover'].setChecked(False)
            self.general_page._checks['volume_normalization'].setChecked(True)
            from ddm.audio_normalization import preset_curve
            self.general_page.normalization_editor.set_curve(preset_curve('netflix'))
            if action.startswith('tray-'):
                self.nav.setCurrentRow(self.PAGE_INDEX['tray'])
                page = self._loaded_pages[self.PAGE_INDEX['tray']]
                page.close_behavior_combo.setCurrentIndex(page.close_behavior_combo.findData('tray'))
                page.pause_playback.setChecked(False)
            if 'sidebar_platform_logos' in self.general_page._checks:
                self.general_page._checks['sidebar_platform_logos'].setChecked(False)
            if action in ('cancel', 'tray-cancel'):
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
            if action == 'embed-scroll' and index == PAGE_INDEX['shortcuts']:
                control = self.shortcut_page.wheel_speed
                control.setCurrentIndex(control.findData(3))
            if action == 'embed-coordinates':
                self.move(self.x() + 9, self.y() + 7)
                self.resize(self.width() + 8, self.height() + 4)
            def observed():
                if self.host_container is None or not self.host_surface_ready:
                    QTimer.singleShot(25, self, observed)
                    return
                assert int(self.winId()) == self.shell_hwnd and self.isVisible() and self.isEnabled()
                assert self.nav.currentRow() == index
                assert self.general_page.volume_slider.value() == 17
                if action == 'embed-scroll' and index == PAGE_INDEX['shortcuts']:
                    assert self.property('settings_wheel_speed') == 3, 'Wheel speed did not reach the worker shell'
                extra = {}
                if action in ('embed-footer', 'embed-appearance', 'embed-coordinates'):
                    import ctypes
                    from ctypes import wintypes
                    from PySide6.QtCore import QPoint
                    from PySide6.QtWidgets import QPushButton
                    origin = wintypes.POINT()
                    ctypes.windll.user32.ClientToScreen(ctypes.c_void_p(int(self.winId())), ctypes.byref(origin))
                    scale = self.devicePixelRatioF()
                    extra['header_bottom'] = origin.y + round((self.window_header.y() + self.window_header.height()) * scale)
                    extra['client_bottom'] = origin.y + round(self.height() * scale)
                    extra['scale'] = scale
                    start = self.host_container.mapTo(self, QPoint())
                    extra['container_geometry'] = list(self.host_container.geometry().getRect())
                    extra['stack_geometry'] = list(self.stack.geometry().getRect())
                    extra['foreign_geometry'] = [self.foreign.x(), self.foreign.y(), self.foreign.width(), self.foreign.height()]
                    extra['content_rect'] = [origin.x + round(start.x() * scale), origin.y + round(start.y() * scale),
                                             round(self.host_container.width() * scale), round(self.host_container.height() * scale)]
                print(settings_process.PREFIX + json.dumps({
                    'kind': 'shell', 'index': index, 'hwnd': int(self.winId()),
                    'glass': self._native_glass,
                    'embedded': self.host_container is not None,
                    'size': [self.width(), self.height()], **extra}), flush=True)
                if action not in ('embed-scroll', 'embed-shutdown', 'embed-update-retry'):
                    QTimer.singleShot(50, self.step)
            QTimer.singleShot(200, self, observed)

    dialogs.SettingsDialog = AutomatedDialog
    if action.startswith('embed-') or action in ('zorder', 'theme', 'reuse-navigation'):
        def background_activate(dialog):
            from PySide6.QtCore import Qt
            dialog.setAttribute(Qt.WA_ShowWithoutActivating)
            dialog.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
            dialog.setGeometry(-10000, -10000, 720 if action == 'embed-footer' else 980,
                               650 if action == 'embed-footer' else 720)
            if action == 'embed-coordinates':
                # Expose the layered child at the captured user's positive screen origin.
                # Off-screen windows never flush their backing store and missed this bug.
                dialog.setGeometry(670, 291, 1200, 800)
            dialog.show()
        settings_process._activate_dialog = background_activate
    if action == 'reuse-navigation':
        def report_navigation(dialog):
            if not dialog.isVisible():
                background_activate(dialog)
            print(settings_process.PREFIX + json.dumps({
                'kind': 'navigation', 'page': dialog.nav.currentRow(), 'hwnd': int(dialog.winId()),
                'visible': sum(isinstance(widget, original) and widget.isVisible()
                               for widget in QApplication.topLevelWidgets())}), flush=True)
        settings_process._activate_dialog = report_navigation
    if action == 'zorder':
        activate = settings_process._activate_dialog

        def report_window(dialog):
            activate(dialog)
            print(settings_process.PREFIX + json.dumps({
                'kind': 'zorder', 'hwnd': int(dialog.winId())}), flush=True)
        settings_process._activate_dialog = report_window
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
    client.autoSaveRequested.connect(lambda message: client._send({'kind': 'auto-saved', 'error': ''}))
    client.received.connect(messages.append)
    client.saved.connect(saves.append)
    client.autoSaveRequested.connect(lambda message: saves.append(message['changes']))
    def host_request(message):
        if message['kind'] == 'streamer-quality':
            room_id = message['room_id']
            options = ([{'qn': 15000, 'label': '2K'}, {'qn': 400, 'label': '蓝光'}]
                       if room_id == '1001' else [{'qn': 2, 'label': '超清'}, {'qn': 1, 'label': '原画'}])
            client._send({'kind': 'streamer-quality-result', 'room_id': room_id,
                          'token': message['token'], 'options': options})
        elif message['kind'] == 'host-page':
            pages.append(message['index'])
        elif message['kind'] == 'host-flush':
            client._send({'kind': 'host-flushed'})
        elif message['kind'] == 'host-save':
            saves.append(message['changes'])
            client._send({'kind': 'host-saved'})
    client.hostRequest.connect(host_request)
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
            context = {'panel': {'size': [800, 450], 'cards': [{'message': '', 'collapsed': False}]}}
            client.open(initial, {}, context, streamer_rooms={'1001': 'Fixture', 'fixture:7': 'Other'})
            client.open(initial, {})  # Pending/visible clicks must not recreate the window.
            assert grant.call_count == 2 and all(call.args == (pid,) for call in grant.call_args_list)
            wait(app, lambda: any(m['kind'] == 'result' for m in messages))
            assert not failures and not client.visible
            assert sum(m['kind'] == 'painted' for m in messages) == 1
            clean = action.startswith(('clean-', 'revert-'))
            assert bool(saves) == (not clean)
            if saves:
                combined = {}
                for saved in saves:
                    combined.update(saved.get('settings', {}))
                if action == 'streamer-defaults':
                    assert combined == {'streamer_defaults': {
                        '1001': {'name': 'Fixture', 'playback': {'qn': 15000, 'label': '2K'},
                                 'recording': {'qn': 400, 'label': '蓝光'}, 'volume': 57},
                        'fixture:7': {'name': 'Other', 'playback': {'qn': 2, 'label': '超清'},
                                      'recording': {'qn': 1, 'label': '原画'}, 'volume': 62},
                    }}
                else:
                    assert combined['default_volume'] == 17
                    if action == 'preview-save':
                        assert combined['super_chat_position'] == [0.0, .6]
                        assert combined['super_chat_panel_position'] == [1.0, .2]
                        assert combined['super_chat_position_sync'] is False
                    if action == 'preview-sync-save':
                        assert combined['super_chat_position'] == [1.0, .2]
                        assert combined['super_chat_panel_position'] == [1.0, .2]
                        assert combined.get('super_chat_position_sync', True) is True
                    assert combined['volume_normalization'] is True
                    assert combined['volume_normalization_curve']['preset'] == 'netflix'
                    if action == 'tray-save':
                        assert combined['close_behavior'] == 'tray'
                        assert combined['tray_pause_playback'] is False
                    assert 'appearance_mode' not in combined
                    assert 'seen_update_versions' not in combined, 'Worker must not clear host update history'
            expected = ([3, PAGE_INDEX[action.split('-')[1]]]
                        if clean else [] if action in ('cancel', 'tray-cancel', 'streamer-defaults') else [3])
            assert pages == expected, (pages, expected)
            if action == 'busy':
                maximum = max(b - a for a, b in zip(ticks, ticks[1:]))
                assert maximum < 0.15, maximum
                assert len(ticks) > 60, len(ticks)
                print(f'Worker busy 600ms: host maximum heartbeat gap {maximum * 1000:.1f}ms')
            # Closing and reopening uses the same prewarmed process.
            messages.clear()
            client.open(initial, {}, context, streamer_rooms={'1001': 'Fixture', 'fixture:7': 'Other'})
            wait(app, lambda: any(m['kind'] == 'result' for m in messages))
            assert client.process.processId() == process_pid
            assert next(m['pid'] for m in messages if m['kind'] == 'painted') == pid
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)
            timer.stop()
    assert not failures


def check_theme_sync(app):
    from ddm import theme
    messages = []
    client = settings_process.SettingsProcess()
    client.autoSaveRequested.connect(lambda message: client._send({'kind': 'auto-saved', 'error': ''}))
    client.received.connect(messages.append)
    command = (sys.executable, [str(Path(__file__).resolve()), '--worker-check', 'theme'])
    with patch.object(settings_process, 'worker_command', return_value=command), \
            patch.object(settings_process, '_allow_foreground'):
        try:
            theme.apply('dark')
            client.open(dict(config.DEFAULT_SETTINGS, appearance_mode='dark', appearance_accent='#8866ee',
                             appearance_font='Segoe UI', appearance_font_size=17, settings_card_layout='vertical'), {})
            theme.apply('light')  # Also sync a change while startup is still pending.
            wait(app, lambda: any(m['kind'] == 'theme-state' for m in messages))
            row = next(m for m in reversed(messages) if m['kind'] == 'theme-state')
            assert row['mode'] == 'light' and row['light'] and row['volume'] == 17, row
            assert 'Segoe UI' in row['font'] and row['accent'].lower() != '#007ba8' and row['columns'] == 1, row
            assert row['font_size'] == 17, row
            hwnd = row['hwnd']
            assert row['visible'], row
            messages.clear()
            for mode in ('dark', 'light'):
                theme.apply(mode)
                wait(app, lambda: any(m['kind'] == 'theme-state' and m['mode'] == mode for m in messages))
                row = next(m for m in reversed(messages) if m['kind'] == 'theme-state')
                assert row['light'] == (mode == 'light') and row['volume'] == 17, row
                assert 'Segoe UI' in row['font'] and row['columns'] == 1, row
                assert row['visible'] and row['hwnd'] == hwnd, row
                messages.clear()
            client._send({'kind': 'host-cancel'})
            wait(app, lambda: not client.visible)
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)
            client.deleteLater()
            theme.apply('dark')
    print('PASS: pending and visible settings follow host themes and preserve unsaved controls')


def check_native_zorder(app):
    """Only use offscreen synthetic HWNDs; never move the user's pointer/focus."""
    import ctypes
    from ctypes import wintypes
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    user32 = ctypes.windll.user32
    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    host = QWidget()
    host.setAttribute(Qt.WA_ShowWithoutActivating)
    host.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    host.setGeometry(-10000, -10000, 1200, 900)
    host.show()
    overlay = QWidget(host)
    overlay.setAttribute(Qt.WA_NativeWindow)
    overlay.show()
    client = settings_process.SettingsProcess(host)
    messages = []
    client.received.connect(messages.append)
    command = (sys.executable, [str(Path(__file__).resolve()), '--worker-check', 'zorder'])

    def above(first, second):
        current = second
        while current:
            current = user32.GetWindow(current, 3)  # GW_HWNDPREV
            if current == first:
                return True
        return False

    with patch.object(settings_process, 'worker_command', return_value=command):
        try:
            for _ in range(2):  # Reopening must bind the replacement dialog too.
                messages.clear()
                client.open(config.DEFAULT_SETTINGS, {})
                wait(app, lambda: any(m['kind'] == 'zorder' for m in messages))
                hwnd = next(m['hwnd'] for m in messages if m['kind'] == 'zorder')
                owner = int(host.winId())
                assert user32.GetWindow(hwnd, 4) == owner, 'Worker settings must be owned by the host HWND'
                assert not user32.GetWindowLongW(hwnd, -20) & 8, 'Settings must not be globally TOPMOST'
                for _ in range(5):
                    host.raise_()
                    overlay.hide()
                    overlay.show()
                    overlay.raise_()
                    user32.SetWindowPos(owner, 0, 0, 0, 0, 0, 0x13)  # TOP, no activate/move/resize.
                    app.processEvents()
                    assert above(hwnd, owner), 'Host/overlay raises must not cover settings'
                client._send({'kind': 'host-cancel'})
                wait(app, lambda: not client.visible)
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)
            host.close()
    print('PASS: cross-process owner keeps settings above host after native overlay raises and reopen')


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
    client.autoSaveRequested.connect(lambda message: client._send({'kind': 'auto-saved', 'error': ''}))
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
    client.autoSaveRequested.connect(lambda message: client._send({'kind': 'auto-saved', 'error': ''}))
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
    client.autoSaveRequested.connect(lambda message: client._send({'kind': 'auto-saved', 'error': ''}))
    command = (str(executable), [str(ROOT / 'main.py'), '--settings-worker'])
    with patch.object(settings_process, 'worker_command', return_value=command):
        try:
            client.warm()
            wait(app, lambda: client.ready)
        finally:
            client.stop()
            wait(app, lambda: client.process.state() == QProcess.NotRunning)


def check_finish_without_event_loop(app):
    client = settings_process.SettingsProcess()
    client.autoSaveRequested.connect(lambda message: client._send({'kind': 'auto-saved', 'error': ''}))
    command = (getattr(sys, '_base_executable', sys.executable), ['-c', 'import time; time.sleep(30)'])
    with patch.object(settings_process, 'worker_command', return_value=command):
        try:
            client.warm()
            assert client.process.waitForStarted(5000)
            client.stop()
            # Do not pump Qt events: the GUI loop has already returned on this path.
            assert client.finish(timeout=100)
            assert client.process.state() == QProcess.NotRunning
            assert not client.kill_timer.isActive()
            assert client.finish(timeout=100), 'final shutdown must be idempotent'
        finally:
            client.process.kill()
            client.process.waitForFinished(5000)


def check_close_during_edit(app):
    client = settings_process.SettingsProcess()
    client.autoSaveRequested.connect(lambda message: client._send({'kind': 'auto-saved', 'error': ''}))
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
    from ddm.settings_control import SettingsControl
    applied = []
    host = SimpleNamespace(shortcuts={'keep': 'K'}, plugins=SimpleNamespace(
        enabled={'fixture'}, _platform_owner={}, _removed=set()),
        _apply_settings_dialog=lambda dialog, before: applied.append(
            (dialog.settings(), dialog.shortcuts(), dialog.enabled_plugins())))
    host.settings_control = SettingsControl(host)
    MainWindow._remote_settings_saved(host, {'settings': {'default_volume': 17}, 'shortcuts': {'edit': 'E'}})
    assert applied == [({'default_volume': 17}, {'keep': 'K', 'edit': 'E'}, {'fixture'})]
    MainWindow._remote_settings_saved(host, {'settings': {}, 'shortcuts': {}})
    host._closing = True
    MainWindow._remote_settings_saved(host, {'settings': {'default_volume': 33}})
    assert len(applied) == 1
    host._create_settings_dialog = lambda: applied.append('unexpected dialog')
    with patch.dict(os.environ, {'DDM_SETTINGS_PROCESS': '0'}):
        assert not MainWindow._open_sidebar_settings(host)
    assert len(applied) == 1, 'Shutdown must ignore new settings requests'


def check_host_save_validation():
    from unittest.mock import Mock
    from ddm.dialogs import SettingsDialog
    from ddm.settings_host import SettingsHost
    default_dialog = SettingsDialog(config.DEFAULT_SETTINGS, {}, preview=True)
    available = default_dialog.screen().availableGeometry()
    assert default_dialog.width() == min(1200, available.width() - 48)
    assert default_dialog.height() == min(800, available.height() - 72)
    default_dialog.deleteLater()
    dialog = Mock()
    dialog.confirm_button.isEnabled.return_value = True
    dialog.result.return_value = SettingsDialog.Accepted
    dialog.enabled_plugins.return_value = {'fixture'}
    dialog._loaded_pages = {8: SimpleNamespace(install_requested=False)}
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
        if action != 'embed-update-retry':
            stack.enter_context(patch.object(online_ui.OnlinePage, 'start'))
        for name in ('start_all', 'refresh_account', 'refresh_status', 'refresh_stats',
                     'load_cached_covers', 'load_cached_avatars', 'load_room_avatars'):
            stack.enter_context(patch.object(host.MainWindow, name))
        with patch.object(host.QTimer, 'singleShot'):
            window = host.MainWindow([], [], layout_id='1x1', state={
                'plugins_enabled': [], 'settings': {'seen_update_versions': {'app': '0.5.1'},
                                                   'close_behavior': 'exit',
                                                   'settings_glass_enabled': action == 'embed-appearance',
                                                   'appearance_mode': 'light' if action == 'embed-cancel' else 'dark',
                                                   'sidebar_platform_logos': not action.startswith('logos-')}})
        plugin_saves = {}
        if action == 'embed-footer':
            entries = [dict(id=f'footer_{index}', name=f'插件 {index}', description='插件说明',
                            version='1.0', enabled=True, status='已加载', reason='') for index in range(12)]
            stack.enter_context(patch.object(window.plugins, 'catalog', return_value=entries))
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
                    source = ROOT / 'plugins_user' / name / 'platform_logo.py'
                    if not source.is_file():
                        source = source.with_name('plugin.py')
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
        if action in ('embed-appearance', 'embed-coordinates'):
            from PySide6.QtCore import Qt
            window.setAttribute(Qt.WA_ShowWithoutActivating)
            window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
            window.setGeometry(-14000, -12000, 1100, 800)
            window.show()
        client = window._get_settings_process()
        initial_volume = window.settings['default_volume']
        messages = []
        client.received.connect(messages.append)
        command = (sys.executable, [str(Path(__file__).resolve()), '--worker-check', action])
        stack.enter_context(patch.object(settings_process, 'worker_command', return_value=command))
        if action.startswith('embed-'):
            errors = []
            def report_error(kind, error, trace):
                import traceback
                traceback.print_exception(kind, error, trace)
                errors.append(error)
            stack.enter_context(patch.object(sys, 'excepthook', report_error))
            from ddm.dialogs import SettingsDialog
            stack.enter_context(patch.object(SettingsDialog, 'exec', side_effect=AssertionError('Settings reopened')))
            if action in ('embed-install', 'embed-update-retry'):
                stack.enter_context(patch.object(sys, 'frozen', True, create=True))
            if action == 'embed-update-retry':
                stack.enter_context(patch.dict(os.environ, DDM_SETTINGS_PROCESS='1'))

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
                assert int(session.stack.windowHandle().parent().winId()) == message['hwnd'], 'Host Qt must retain the worker parent across repaints'
                assert session.stack.width() > 400 and session.stack.height() > 300, (session.stack.width(), session.stack.height(), message)
                assert message['embedded']
                if action == 'embed-appearance':
                    assert message['glass'], 'Worker must use live composition blur while host pages are embedded'
                    assert session.stack.property('settings_glass_enabled')
                assert session.dialog.nav.currentRow() == (message['index'] if message['index'] in settings_process.HOST_PAGES else -1)
                if message['index'] in settings_process.HOST_PAGES:
                    if action == 'embed-scroll':
                        from ctypes import wintypes
                        from PySide6.QtCore import QPoint
                        page = session.dialog._loaded_pages[message['index']]
                        page.scroll.widget().setMinimumHeight(1400)
                        app.processEvents()
                        bar = page.scroll.verticalScrollBar()
                        assert bar.maximum() > 0
                        rect = wintypes.RECT()
                        assert user32.GetWindowRect(handle, ctypes.byref(rect))
                        # Inject only into isolated fixture HWNDs, never desktop input.
                        local = page.scroll.viewport().mapTo(session.stack, QPoint(8, 8))
                        scale = session.stack.devicePixelRatioF()
                        x, y = rect.left + round(local.x() * scale), rect.top + round(local.y() * scale)
                        point = (y & 0xffff) << 16 | (x & 0xffff)
                        def verify_wheel_distance(speed):
                            for receiver in (int(session.stack.winId()), message['hwnd']):
                                for _ in range(3):
                                    bar.setValue(0)
                                    user32.PostMessageW(ctypes.c_void_p(receiver), 0x20A, 0xff880000, point)
                                    wait(app, lambda: bar.value() > 0, timeout=3)
                                    assert bar.value() == speed * bar.singleStep(), (receiver, bar.value(), speed)
                        verify_wheel_distance(session.stack.property('settings_wheel_speed'))
                        bar.setValue(0)  # Preserve the existing top-of-page rendering assertions.
                        app.processEvents()
                    if action in ('embed-footer', 'embed-appearance', 'embed-coordinates'):
                        if action == 'embed-coordinates':
                            from PySide6.QtCore import QEvent
                            assert session.stack.windowHandle().isExposed()
                            handle_window = session.stack.windowHandle()
                            assert not handle_window.isTopLevel()
                            assert handle_window.geometry() == session.stack.geometry(), 'Qt must retain child coordinates before a layered flush'
                            session.stack.repaint()
                            QCoreApplication.sendPostedEvents(None, QEvent.UpdateRequest)
                        from ctypes import wintypes
                        rect = wintypes.RECT()
                        assert user32.GetWindowRect(handle, ctypes.byref(rect))
                        x, y, width, height = message['content_rect']
                        assert all(abs(actual - expected) <= 2 for actual, expected in zip(
                            (rect.left, rect.top, rect.right, rect.bottom), (x, y, x + width, y + height))), ('Host must fit the content area', (rect.left, rect.top, rect.right, rect.bottom), message)
                        assert rect.top >= message['header_bottom'], message
                        assert 0 <= message['client_bottom'] - rect.bottom <= 40 * message['scale'], ('Content must use the former footer space', message)
                    image = session.stack.grab().toImage()
                    actual = image.pixelColor(1, 1)
                    assert actual.alpha() == 0, (message['index'], actual.name(), actual.alpha())
                    assert max(image.pixelColor(x, y).alpha() for x in range(0, min(96, image.width()), 2)
                               for y in range(0, min(48, image.height()), 2)) > 200, 'Embedded text must still render'
                    output = ROOT / 'work/test-artifacts/host/settings-pages'
                    output.mkdir(parents=True, exist_ok=True)
                    image.save(str(output / f"{theme.mode()}-{message['index']}.png"))
                if message['index'] == PAGE_INDEX['updates']:
                    session.dialog.update_page.auto.setChecked(True)
                    if action == 'embed-install':
                        page = session.dialog.update_page
                        page.plan_path = str(Path(temporary) / 'synthetic-update-plan.json')
                        page._busy(False)
                        page.action.click()
                if action == 'embed-scroll' and message['index'] == PAGE_INDEX['shortcuts']:
                    wait(app, lambda: session.stack.property('settings_wheel_speed') == 3, timeout=3)
                if action == 'embed-scroll':
                    # Acknowledge this step only after both process endpoints pass.
                    user32.PostMessageW(ctypes.c_void_p(message['hwnd']), 0x8051, 0, 0)
                if action == 'embed-update-retry':
                    page = session.dialog.update_page
                    if message['index'] == PAGE_INDEX['general']:
                        with patch.object(window, '_unread_app_update', return_value={'version': '9.1'}):
                            window.app_updates.show_update_notice()
                        window._update_notice.settings_action.click()
                        wait(app, lambda: session.stack.currentWidget() is page, timeout=5)
                    else:
                        from ddm import online
                        page.offer = {'size': 4096, 'version': '9.1'}
                        page._busy(False)
                        with patch.object(online, 'download', side_effect=online.requests.ReadTimeout) as download:
                            for attempt in (1, 2):
                                page.action.click()
                                wait(app, lambda: not page.jobs, timeout=5)
                                assert download.call_count == attempt and page.download_state['phase'] == 'failed'
                                assert session.stack.currentWidget() is page and page.isVisible()
                                assert user32.GetAncestor(handle, 2) == message['hwnd']
                                assert page.version_section.isVisible() and page.notes_section.isVisible()
                        offer = {'id': 'fixture', 'name': '测试插件', 'version': '1.0'}
                        with patch.object(window, '_unread_plugin_updates', return_value=[offer]), \
                                patch.object(online_ui.PluginStorePage, 'refresh_catalog'):
                            window.app_updates.show_update_notice()
                            window._update_notice.settings_action.click()
                            wait(app, lambda: session.dialog.nav.currentRow() == PAGE_INDEX['plugins'] and
                                 session.dialog.plugin_page.tabs.currentIndex() == 1, timeout=5)
                        assert user32.GetAncestor(handle, 2) == message['hwnd']
                    user32.PostMessageW(ctypes.c_void_p(message['hwnd']), 0x8051, 0, 0)
                if action == 'embed-shutdown':
                    from ctypes import wintypes
                    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
                    shell = message['hwnd']
                    original_hide = window.hide
                    def hide_host():
                        assert client.closing, 'Settings stop must precede the host hide'
                        assert window._closing
                        original_hide()
                    def blocked_host_cleanup():
                        # Only the worker's own loop is allowed to process the hide.
                        deadline = time.perf_counter() + .3
                        while user32.IsWindowVisible(shell) and time.perf_counter() < deadline:
                            time.sleep(.002)
                        assert not user32.IsWindowVisible(shell), 'Settings remained visible during host cleanup'
                    with patch.object(window, 'hide', side_effect=hide_host), \
                            patch.object(window, '_wait_background', side_effect=blocked_host_cleanup):
                        window.close()
            client.received.connect(observed)
        try:
            if action == 'reuse-navigation':
                check_navigation_reuse(app, window, client, messages)
                return
            if action == 'embed-update-retry':
                window.open_settings('updates')
            else:
                client.open(window.settings, window.shortcuts)
            # Host changes made while the editor is open must survive its save.
            window.settings['skin_mask'] = 29
            window.shortcuts['fullscreen'] = 'Ctrl+F10'
            wait(app, lambda: window._closing if action in ('embed-install', 'embed-shutdown') else
                 any(message['kind'] == 'result' for message in messages), timeout=25)
            assert window.settings['seen_update_versions'] == {'app': '0.5.1'}
            if action == 'embed-shutdown':
                assert client.finish() and not errors, errors
                assert not window.isVisible() and window._settings_host is None
                return
            if action == 'embed-install':
                assert window._update_plan == str(Path(temporary) / 'synthetic-update-plan.json')
                assert window.settings['default_volume'] == 17 and not errors
                return
            if action.startswith('logos-'):
                assert plugin_saves == {'domestic_live': False, 'global_live': True}
                assert window.settings['sidebar_platform_logos'] is True
                assert window.settings['default_volume'] == 17
                return
            if action.startswith('embed-'):
                shells = [message for message in messages if message['kind'] == 'shell']
                assert [message['index'] for message in shells] == list(embedded_page_indices(action))
                assert len({message['hwnd'] for message in shells}) == 1, 'Shell was recreated'
                if action == 'embed-coordinates':
                    assert len({tuple(message['size']) for message in shells}) == len(shells)
                else:
                    assert len({tuple(message['size']) for message in shells}) == 1, 'Shell geometry changed'
                if action == 'embed-scroll':
                    assert window.settings['settings_wheel_speed'] == 3
                assert getattr(window, '_settings_host', None) is None, 'Host pages leaked after close'
                assert window.settings['default_volume'] == 17
                assert window.settings['auto_update'] is (action not in ('embed-footer', 'embed-appearance'))
                assert window.settings['skin_mask'] == 29 and window.shortcuts['fullscreen'] == 'Ctrl+F10'
                if action in ('embed-footer', 'embed-coordinates'):
                    process_pid = client.process.processId()
                    messages.clear()
                    client.open(window.settings, window.shortcuts)
                    wait(app, lambda: any(message['kind'] == 'result' for message in messages), timeout=25)
                    assert client.process.processId() == process_pid, 'Reopen must reuse the worker'
                    assert [message['index'] for message in messages if message['kind'] == 'shell'] == list(embedded_page_indices(action))
                    assert getattr(window, '_settings_host', None) is None
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


def check_navigation_reuse(app, window, client, messages):
    from ddm.dialogs import SettingsDialog

    def navigation():
        return [message for message in messages if message['kind'] == 'navigation']

    def assert_page(count, page):
        wait(app, lambda: len(navigation()) == count)
        current = navigation()[-1]
        assert current['page'] == PAGE_INDEX[page] and current['visible'] == 1, current
        return current['hwnd']

    monitor = window.sidebar.navigation.monitor_menu.settings_button
    gear = window.sidebar.settings_button
    with patch.dict(os.environ, DDM_SETTINGS_PROCESS='1'), \
            patch.object(settings_process, '_allow_foreground'), \
            patch.object(SettingsDialog, 'exec', side_effect=AssertionError('Second settings window')) as local:
        gear.click()
        assert client.pending is not None
        monitor.click()
        gear.click()
        assert client.pending['page'] == 'streamer_defaults'
        hwnd = assert_page(1, 'streamer_defaults')
        worker_pid = client.worker_pid
        window.open_settings('danmaku')
        assert assert_page(2, 'danmaku') == hwnd
        gear.click()
        assert assert_page(3, 'danmaku') == hwnd
        monitor.click()
        assert assert_page(4, 'streamer_defaults') == hwnd
        assert sum(message['kind'] == 'window' for message in messages) == 1

        # Queue another click before the host can receive the old window's close result.
        client._send({'kind': 'host-cancel'})
        monitor.click()
        assert_page(5, 'streamer_defaults')
        assert sum(message['kind'] == 'window' for message in messages) == 2
        assert client.worker_pid == worker_pid and client.visible
        local.assert_not_called()


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
            window = host.MainWindow([], [], state={'plugins_enabled': [],
                                                    'settings': {'close_behavior': 'exit'}})
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
        report(settings_stopped=client.finish())
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
                assert data['settings_stopped'], 'worker must finish before a new process is launched'
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


def check_nonblocking_online_close(app):
    from unittest.mock import Mock
    from ddm.dialogs import SettingsDialog
    from ddm import online_ui
    from shiboken6 import isValid
    for update in (False, True):
        entered, release = threading.Event(), threading.Event()
        callback = Mock()
        dialog = SettingsDialog(config.DEFAULT_SETTINGS, {})
        page = online_ui.AppUpdatePage(config.DEFAULT_SETTINGS, dialog) if update else online_ui.OnlinePage(dialog)
        if not update:
            dialog._loaded_pages[PAGE_INDEX['plugins']] = SimpleNamespace(store_page=page)
        def operation(cancelled, progress):
            entered.set()
            release.wait(3)
            progress(1, 1)
            return '/fixture/late-update-plan.json' if update else ['late-catalog']
        ticks = []
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: ticks.append(1))
        heartbeat.start()
        fallback = threading.Timer(1.5, release.set)
        fallback.daemon = True
        fallback.start()
        with patch.object(online_ui.update_install, 'discard_plan') as discard:
            page.start(operation, callback)
            task = page.jobs[0]
            assert entered.wait(1)
            try:
                started = time.monotonic()
                page.stop() if update else dialog.reject()
                assert time.monotonic() - started < .2, 'Closing settings must not wait for a network response'
                assert task.isInterruptionRequested() and task.parent() is None
                assert task in online_ui._retired_online_tasks
                dialog.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                assert not isValid(page), 'Settings page must be releasable while the request is pending'
                wait(app, lambda: len(ticks) >= 3)
                assert not callback.called
                release.set()
                wait(app, lambda: task not in online_ui._retired_online_tasks)
                assert not callback.called, 'Cancelled results must not touch destroyed settings pages'
                if update:
                    discard.assert_called_once_with('/fixture/late-update-plan.json', config.REPO)
                else:
                    discard.assert_not_called()
            finally:
                release.set()
                fallback.cancel()
                heartbeat.stop()
                if isValid(task):
                    task.wait(3000)
                app.processEvents()
    print('PASS: slow online settings close immediately, GUI heartbeat continues, late results cleaned safely')


def check_save_trace():
    output = io.StringIO()
    with redirect_stderr(output), patch.object(settings_process.time, 'perf_counter_ns',
                                               side_effect=(1_000_000, 5_000_000)):
        started = settings_process._save_trace('fixture.begin')
        finished = settings_process._save_trace('fixture.end', started)
    assert (started, finished) == (1_000_000, 5_000_000)
    lines = output.getvalue().splitlines()
    assert len(lines) == 2 and all(line.startswith('[设置保存] stage=fixture.') for line in lines)
    assert 'at_ns=1000000' in lines[0] and 'elapsed_ms=' not in lines[0]
    assert 'at_ns=5000000 elapsed_ms=4.000' in lines[1]


def main():
    if sys.argv[1:2] == ['--worker-check']:
        return child(sys.argv[2])
    if sys.argv[1:2] == ['--restart-host-fixture']:
        return restart_host_fixture(sys.argv[2], sys.argv[3])
    check_save_trace()
    if sys.argv[1:] == ['--restart-native']:
        return check_restart_native()
    app = QApplication.instance() or QApplication([])
    os.environ['DDM_SETTINGS_TEST_QT'] = qVersion()
    app.setQuitOnLastWindowClosed(False)
    if sys.argv[1:] == ['--shutdown-native']:
        assert app.platformName() == 'windows'
        check_host_application(app, 'embed-shutdown')
        check_finish_without_event_loop(app)
        print('PASS: settings hide before host cleanup; embedded surfaces and worker finish safely')
        return 0
    if sys.argv[1:] == ['--streamer-defaults-only']:
        check_worker(app, 'streamer-defaults')
        print('PASS: streamer defaults room snapshot and worker autosave')
        return 0
    if sys.argv[1:] == ['--reuse-navigation']:
        check_host_application(app, 'reuse-navigation')
        print('PASS: settings navigation reuses one window during startup, while open, and across close')
        return 0
    if sys.argv[1:] == ['--theme-sync-only']:
        check_theme_sync(app)
        return 0
    check_nonblocking_online_close(app)
    if sys.argv[1:] == ['--scroll-native']:
        assert app.platformName() == 'windows'
        check_host_application(app, 'embed-scroll')
        print('PASS: repeated native wheels in host and worker reach both embedded pages after switching')
        return 0
    if sys.argv[1:] == ['--coordinates-native']:
        assert app.platformName() == 'windows'
        check_host_application(app, 'embed-coordinates')
        print('PASS: exposed host repaints and all host page switches preserve native coordinates')
        return 0
    if sys.argv[1:] == ['--update-retry-native']:
        assert app.platformName() == 'windows'
        check_host_application(app, 'embed-update-retry')
        print('PASS: update entry and retry keep the same embedded settings page')
        return 0
    if sys.argv[1:] == ['--appearance-native']:
        assert app.platformName() == 'windows'
        check_host_application(app, 'embed-appearance')
        print('PASS: appearance entry and reentry keep the host inside the worker viewport')
        return 0
    if sys.argv[1:] == ['--footer-native']:
        assert app.platformName() == 'windows'
        check_host_application(app, 'embed-footer')
        print('PASS: first plugin entry, page switching and reopen keep native content inside the header and client bounds')
        return 0
    if sys.argv[1:] == ['--native-zorder']:
        assert app.platformName() == 'windows'
        check_native_zorder(app)
        return 0
    if sys.argv[1:] == ['--native-focus']:
        check_native_focus(app)
        return 0
    if sys.argv[1:] == ['--embedded-native']:
        assert app.platformName() == 'windows'
        check_host_application(app, 'embed-save')
        check_host_application(app, 'embed-cancel')
        check_host_application(app, 'embed-install')
        print('PASS: same worker HWND after 10s and all page switches, native embedding/DPI, autosave/close and cleanup')
        return 0
    if sys.argv[1:] == ['--installed-logo-controls']:
        check_host_application(app, 'logos-save', installed_controls=True)
        check_host_application(app, 'logos-cancel', installed_controls=True)
        print('PASS: installed domestic/global logo control classes bridged without importing plugin runtimes')
        return 0
    for action in ('clean-appearance', 'clean-plugins', 'clean-updates', 'revert-appearance',
                   'save', 'preview-save', 'preview-sync-save', 'cancel', 'tray-save', 'tray-cancel', 'streamer-defaults', 'busy'):
        check_worker(app, action)
    check_failure(app)
    check_windowed_worker(app)
    check_finish_without_event_loop(app)
    check_close_during_edit(app)
    check_host_adapter()
    check_host_save_validation()
    check_host_application(app)
    check_host_application(app, 'logos-save')
    check_host_application(app, 'logos-cancel')
    print('PASS: isolated settings save/cancel, unchanged shell on page switch, validation, reuse, retry and GUI isolation')
    return 0


if __name__ == '__main__':
    if sys.argv[1:]:
        raise SystemExit(main())
    # Native settings surfaces must be created and retired inside Qt's loop.
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    result = [1]
    def run_checks():
        try:
            result[0] = main()
        except BaseException:
            import traceback
            traceback.print_exc()
        finally:
            app.quit()
    QTimer.singleShot(0, run_checks)
    app.exec()
    raise SystemExit(result[0])
