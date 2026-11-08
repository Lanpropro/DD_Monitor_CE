"""Isolated settings shell with embedded host-owned pages and JSON commands."""
import json
from copy import deepcopy
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QRect, QTimer, Signal

PREFIX = 'DDM_SETTINGS:'
HOST_PAGES = {1: 'appearance', 7: 'plugins', 8: 'updates'}


def _save_trace(stage, started=None):
    now = time.perf_counter_ns()
    elapsed = '' if started is None else f' elapsed_ms={(now - started) / 1_000_000:.3f}'
    print(f'[设置保存] stage={stage} pid={os.getpid()} at_ns={now}{elapsed}',
          file=sys.stderr, flush=True)
    return now


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
    occlusionChanged = Signal()

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
        self.occlusion = QRect()
        self.start_timer = QTimer(self)
        self.start_timer.setSingleShot(True)
        self.start_timer.timeout.connect(self.process.kill)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self.process.kill)
        from . import theme
        theme.signals().changed.connect(self._theme_changed)

    def _theme_changed(self, mode):
        if self.closing:
            return
        if self.pending is not None:
            self.pending['settings']['appearance_mode'] = mode
        if self.ready and self.visible:
            self._send({'kind': 'host-theme', 'mode': mode})

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

    def open(self, settings, shortcuts, sc_preview_context=None):
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
        self.pending['sc_preview_context'] = sc_preview_context or {}
        from PySide6.QtWidgets import QWidget
        if isinstance(self.parent(), QWidget):
            self.pending['owner_hwnd'] = int(self.parent().window().winId())
        if self.ready:
            self._open_pending()
        else:
            self.warm()

    def _send(self, message):
        self.process.write((json.dumps(message) + '\n').encode('utf-8'))

    def _set_occlusion(self, rect):
        if rect != self.occlusion:
            self.occlusion = rect
            self.occlusionChanged.emit()

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
            elif kind == 'occlusion' and not self.closing:
                self._set_occlusion(QRect(*message['rect']) if message['rect'] else QRect())
            elif kind == 'result':
                started = _save_trace('host.result.received')
                self.visible = False
                self._set_occlusion(QRect())
                if not self.closing:
                    if message.get('host_saved'):
                        self.hostRequest.emit(message)
                    elif message.get('accepted'):
                        self.saved.emit(message['changes'])
                self.closed.emit()
                _save_trace('host.result.applied', started)
            elif kind in ('host-general', 'host-page', 'host-save', 'host-reset', 'host-attached', 'host-hidden') and not self.closing:
                started = _save_trace('host.save.received') if kind == 'host-save' else None
                self.hostRequest.emit(message)
                if started is not None:
                    _save_trace('host.save.dispatched', started)

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
        self._set_occlusion(QRect())
        self.closed.emit()
        if was_open and not self.closing:
            self.failed.emit(self.process.errorString())

    def stop(self):
        self.closing = True
        self._set_occlusion(QRect())
        self.start_timer.stop()
        self.pending = None
        if self.process.state() != QProcess.NotRunning:
            self._send({'kind': 'quit'})
            self.process.closeWriteChannel()
            self.kill_timer.start(1000)

    def finish(self, timeout=1000):
        """Final shutdown also works after the host event loop has stopped."""
        self.stop()
        self.kill_timer.stop()
        if self.process.state() == QProcess.NotRunning or self.process.waitForFinished(timeout):
            return True
        self.process.kill()
        return self.process.state() == QProcess.NotRunning or self.process.waitForFinished(timeout)


from .settings_worker import (run_worker)
