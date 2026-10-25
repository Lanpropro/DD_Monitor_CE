"""Opt-in settings worker: JSON messages only, no shared GUI or playback objects."""
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
    hostPage = Signal(str)
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
        self.handoff_geometry = None
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
                if self.closing:
                    continue
                if message.get('accepted'):
                    self.saved.emit(message['changes'])
                if message.get('page') in HOST_PAGES.values():
                    self.handoff_geometry = message['geometry']
                    self.hostPage.emit(message['page'])

    def complete_handoff(self):
        self.handoff_geometry = None
        self._send({'kind': 'handoff-complete'})

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
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from . import config, theme
    from .dialogs import SettingsDialog, SettingsSavePrompt, SHORTCUT_ACTIONS

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
            self.host_page = None
            self.last_page = 0
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
                                  if value != self.initial_shortcuts.get(key)}}

        def _on_page_changed(self, index):
            if index not in HOST_PAGES:
                self.last_page = index
                return super()._on_page_changed(index)
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(self.last_page)
            self.nav.blockSignals(False)
            changes = self.changes()
            accepted = False
            if any(changes.values()):
                prompt = SettingsSavePrompt(self)
                answer = prompt.exec()
                prompt.deleteLater()
                if answer == SettingsSavePrompt.CANCEL:
                    return
                accepted = answer == SettingsSavePrompt.SAVE
            self.host_page = HOST_PAGES[index]
            self.setEnabled(False)
            # Keep the original window painted until its replacement is ready.
            send({'kind': 'result', 'accepted': accepted,
                  'changes': self.changes() if accepted else {},
                  'page': self.host_page, 'geometry': self.geometry().getRect()})

        def paintEvent(self, event):
            super().paintEvent(event)
            if not self.painted:
                self.painted = True
                send({'kind': 'painted', 'pid': os.getpid()})

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
            elif kind == 'handoff-complete' and self.dialog is not None:
                dialog, self.dialog = self.dialog, None
                dialog.finished.disconnect(self.finished)
                dialog.reject()
                dialog.deleteLater()
                send({'kind': 'handoff-closed'})
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
                  'changes': dialog.changes() if accepted == SettingsDialog.Accepted else {},
                  'page': dialog.host_page})
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
                worker.request.emit(json.loads(line))
            worker.request.emit({'kind': 'quit'})

        threading.Thread(target=read_requests, name='settings-input', daemon=True).start()
        QTimer.singleShot(0, lambda: send({'kind': 'ready', 'pid': os.getpid()}))
        result = app.exec()
    app.shutdown()
    return result
