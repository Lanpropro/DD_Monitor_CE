"""Isolated settings shell with embedded host-owned pages and JSON commands."""
import json
from copy import deepcopy
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

PREFIX = 'DDM_SETTINGS:'
HOST_PAGES = {1: 'appearance', 6: 'plugins', 7: 'updates'}


def _allow_foreground(pid):
    if sys.platform == 'win32' and pid:
        import ctypes
        # A prewarmed process did not receive the user's click. The foreground
        # host must grant permission to the real worker, not the venv launcher.
        return ctypes.windll.user32.AllowSetForegroundWindow(ctypes.c_ulong(pid))


def _activate_dialog(dialog):
    from PySide6.QtWidgets import QApplication
    if dialog.isMinimized():
        dialog.showNormal()
    else:
        dialog.show()
    target = QApplication.activeModalWidget() or dialog
    target.raise_()
    target.activateWindow()
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(int(target.winId())))


def worker_command():
    args = ['--settings-worker']
    if not getattr(sys, 'frozen', False):
        args.insert(0, str(Path(__file__).resolve().parents[1] / 'main.py'))
    return sys.executable, args


class SettingsProcess(QObject):
    saved = Signal(dict)
    hostRequest = Signal(dict)
    closed = Signal()
    failed = Signal(str)
    received = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.buffer = b''
        self.ready = self.visible = self.closing = False
        self.pending = None
        self.worker_pid = None
        self.start_timer = QTimer(self)
        self.start_timer.setSingleShot(True)
        self.start_timer.timeout.connect(self.process.kill)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self.process.kill)

    def warm(self):
        if self.closing or self.process.state() != QProcess.NotRunning:
            return
        program, args = worker_command()
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('DDM_NO_SAVE', '1')
        environment.insert('PYTHONUTF8', '1')
        self.process.setProcessEnvironment(environment)
        self.process.setProgram(program)
        self.process.setArguments(args)
        self.process.start()
        self.start_timer.start(10000)

    def open(self, settings, shortcuts):
        if self.closing:
            return
        if self.visible:
            _allow_foreground(self.worker_pid)
            self._send({'kind': 'focus'})
            return
        if self.pending is not None:
            return
        from .config import DEFAULT_SETTINGS
        self.pending = {'kind': 'open', 'settings': {
            key: settings.get(key, value) for key, value in DEFAULT_SETTINGS.items()},
            'shortcuts': dict(shortcuts)}
        if self.ready:
            self._open_pending()
        else:
            self.warm()

    def _send(self, message):
        self.process.write((json.dumps(message) + '\n').encode('utf-8'))

    def _open_pending(self):
        if self.pending is not None:
            _allow_foreground(self.worker_pid)
            self._send(self.pending)
            self.pending = None
            self.visible = True

    def _read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line.startswith(PREFIX.encode()):
                continue
            message = json.loads(line[len(PREFIX):])
            self.received.emit(message)
            kind = message.get('kind')
            if kind == 'ready':
                self.start_timer.stop()
                self.worker_pid = message['pid']
                self.ready = True
                if not self.closing:
                    self._open_pending()
            elif kind == 'result':
                self.visible = False
                if not self.closing and message.get('accepted'):
                    self.saved.emit(message['changes'])
                self.closed.emit()
            elif kind in ('host-general', 'host-page', 'host-save', 'host-reset', 'host-attached', 'host-hidden') and not self.closing:
                self.hostRequest.emit(message)

    def _stderr(self):
        text = bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace')
        if text:
            print('[独立设置] ' + text.rstrip(), file=sys.stderr, flush=True)

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self._finished()

    def _finished(self, *_args):
        self.start_timer.stop()
        self.kill_timer.stop()
        was_open = self.visible or self.pending is not None
        self.ready = self.visible = False
        self.pending = None
        self.buffer = b''
        self.worker_pid = None
        self.closed.emit()
        if was_open and not self.closing:
            self.failed.emit(self.process.errorString())

    def stop(self):
        self.closing = True
        self.start_timer.stop()
        self.pending = None
        if self.process.state() != QProcess.NotRunning:
            self._send({'kind': 'quit'})
            self.process.closeWriteChannel()
            self.kill_timer.start(1000)


def run_worker():
    # The worker receives a settings snapshot; it must not read/write the
    # portable installation's account, configuration or installed plugins.
    os.environ['DDM_NO_SAVE'] = '1'
    import tempfile
    import threading
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QWindow
    from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QVBoxLayout, QWidget
    from . import config, theme
    from .dialogs import SettingsDialog, SHORTCUT_ACTIONS

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    from .localization import install_chinese_translations
    install_chinese_translations(app)
    for icon_path in (Path(config.REPO) / 'assets/favicon.ico', Path(config.REPO) / 'favicon.ico'):
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    def send(message):
        print(PREFIX + json.dumps(message), flush=True)

    class RemoteDialog(SettingsDialog):
        def __init__(self, snapshot):
            self.host_requested = False
            self.host_values = {}
            self.host_container = None
            self.foreign = None
            self.plugin_checks = {}
            self.painted = False
            super().__init__(snapshot['settings'], snapshot['shortcuts'], preview=True)
            # Compare against the values shown by the controls, not raw input.
            # settings() adds metadata such as an empty seen_update_versions map.
            self.initial_settings = deepcopy(self.settings())
            self.initial_shortcuts = {
                **{key: default for key, _label, default in SHORTCUT_ACTIONS},
                **self.shortcuts()}

        def changes(self):
            return {'settings': {key: value for key, value in self.settings().items()
                                 if value != self.initial_settings.get(key)},
                    'shortcuts': {key: value for key, value in self.shortcuts().items()
                                  if value != self.initial_shortcuts.get(key)},
                    'plugin_controls': {name: check.isChecked() for name, check in self.plugin_checks.items()}}

        def set_plugin_controls(self, controls):
            if self.plugin_checks:
                return
            page = self.general_page
            grid = page.layout().itemAt(1).layout()
            anchor = page._checks['sidebar_platform_logos']
            row = grid.getItemPosition(grid.indexOf(anchor))[0] + 1
            for control in reversed(controls):
                for index in range(grid.count() - 1, -1, -1):
                    old_row, column, rows, columns = grid.getItemPosition(index)
                    if old_row >= row:
                        item = grid.takeAt(index)
                        grid.addItem(item, old_row + 1, column, rows, columns)
                check = QCheckBox(control['label'], page)
                check.setObjectName(control['name'])
                check.setChecked(control['checked'])
                grid.addWidget(check, row, 0, 1, 2)
                self.plugin_checks[control['name']] = check
            if any(name.endswith('_show_platform_logo') for name in self.plugin_checks):
                grid.removeWidget(anchor)
                anchor.hide()
                anchor.setChecked(True)  # Per-plugin switches now decide which platforms are visible.

        def settings(self):
            return {**super().settings(), **self.host_values}

        def _on_page_changed(self, index):
            if index not in HOST_PAGES:
                super()._on_page_changed(index)
                if self.host_container is not None:
                    self.stack.finish_transition()  # Native child windows cannot use opacity effects.
                if self.host_requested:
                    send({'kind': 'host-hidden'})
                return
            self.host_requested = True
            self.stack.finish_transition()
            if self.host_container is None:
                placeholder = self.stack.widget(index)
                if placeholder.layout() is None:
                    layout = QVBoxLayout(placeholder)
                    label = QLabel('正在加载设置…')
                    label.setAlignment(Qt.AlignCenter)
                    layout.addWidget(label)
                self.stack.setCurrentIndex(index)
            else:
                self.stack.setCurrentWidget(self.host_container)
            self.reset_button.setVisible(index == 1)
            self.reset_button.setText('恢复本页默认')
            send({'kind': 'host-page', 'index': index,
                  'settings': self.settings(), 'shortcuts': self.shortcuts()})

        def embed_host(self, hwnd):
            if self.host_container is None:
                self.foreign = QWindow.fromWinId(hwnd)
                if self.foreign is None:
                    raise RuntimeError('The platform cannot embed the host settings page')
                self.host_container = QWidget.createWindowContainer(self.foreign, self.stack)
                self.host_container.setFocusPolicy(Qt.StrongFocus)
                self.stack.addWidget(self.host_container)
                send({'kind': 'host-attached'})
            if self.nav.currentRow() in HOST_PAGES:
                self.stack.setCurrentWidget(self.host_container)

        def _reset_current(self):
            if self.nav.currentRow() in HOST_PAGES:
                send({'kind': 'host-reset'})
            else:
                super()._reset_current()

        def _save(self):
            if self.host_requested or self.plugin_checks:
                self.confirm_button.setEnabled(False)
                send({'kind': 'host-save', 'changes': self.changes()})
            else:
                super()._save()

        def done(self, result):
            if self.foreign is not None:
                self.foreign.hide()
                self.foreign.setParent(None)
                self.foreign = None
            super().done(result)

        def paintEvent(self, event):
            super().paintEvent(event)
            if not self.painted:
                self.painted = True
                send({'kind': 'painted', 'pid': os.getpid()})
                send({'kind': 'host-general', 'settings': self.settings(), 'shortcuts': self.shortcuts()})

    class Worker(QObject):
        request = Signal(dict)

        def __init__(self):
            super().__init__()
            self.dialog = None
            self.request.connect(self.handle)

        def handle(self, message):
            kind = message.get('kind')
            if kind == 'quit':
                app.quit()
            elif kind == 'host-ready' and self.dialog is not None:
                self.dialog.embed_host(message['hwnd'])
            elif kind == 'host-state' and self.dialog is not None:
                self.dialog.host_values = message['values']
                self.dialog.confirm_button.setEnabled(message['save_enabled'])
                self.dialog.confirm_button.setText(message['save_text'])
                for key, active in message['marks'].items():
                    self.dialog._mark_update_page(key, active)
            elif kind == 'host-general-controls' and self.dialog is not None:
                self.dialog.set_plugin_controls(message['controls'])
            elif kind == 'host-theme' and self.dialog is not None:
                theme.apply(message['mode'])
            elif kind == 'host-save-blocked' and self.dialog is not None:
                self.dialog.confirm_button.setEnabled(True)
                self.dialog.nav.setCurrentRow(message['index'])
            elif kind == 'host-saved' and self.dialog is not None:
                self.dialog.reject()  # Host has applied both groups of settings.
            elif kind == 'host-request-save' and self.dialog is not None:
                self.dialog._save()
            elif kind == 'host-cancel' and self.dialog is not None:
                self.dialog.reject()
            elif kind == 'focus' and self.dialog is not None:
                _activate_dialog(self.dialog)
            elif kind == 'open' and self.dialog is None:
                mode = theme.normalize_mode(message['settings'].get('appearance_mode'))
                theme.apply(mode)
                dialog = RemoteDialog(message)
                self.dialog = dialog
                dialog.finished.connect(self.finished)
                _activate_dialog(dialog)

        def finished(self, accepted):
            dialog, self.dialog = self.dialog, None
            send({'kind': 'result', 'accepted': accepted == SettingsDialog.Accepted,
                  'changes': dialog.changes() if accepted == SettingsDialog.Accepted else {}})
            dialog.deleteLater()

    with tempfile.TemporaryDirectory(prefix='ddm_settings_') as temporary:
        config.REPO = temporary
        config.CONFIG_PATH = str(Path(temporary) / 'config.json')
        theme.apply('dark')
        warm = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        warm.ensurePolished()
        warm.deleteLater()
        worker = Worker()

        def read_requests():
            for line in sys.stdin:
                message = json.loads(line)
                worker.request.emit(message)
                if message.get('kind') == 'quit':
                    return
            worker.request.emit({'kind': 'quit'})

        threading.Thread(target=read_requests, name='settings-input', daemon=True).start()
        QTimer.singleShot(0, lambda: send({'kind': 'ready', 'pid': os.getpid()}))
        result = app.exec()
    app.shutdown()
    return result
