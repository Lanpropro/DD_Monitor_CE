"""Async bridge to the same independent collector used by the recovery tool."""
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QObject, QProcess, Signal


def app_root():
    from . import config
    return Path(os.environ.get('DDM_DIAGNOSTIC_APP_ROOT', config.REPO)).resolve()


def collector_path():
    root = app_root()
    return next((path for path in (root / 'DDMonitorDiagnostics.exe',
        root / 'work/diagnostics-preview/DDMonitorDiagnostics.exe') if path.is_file()), None)


class DiagnosticExport(QObject):
    progress = Signal(int, str)
    completed = Signal(str)
    captured = Signal(object)
    failed = Signal(str)
    busyChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.buffer = b''
        self.request = None
        self.partial = None
        self.destination = None
        self.result = None
        self.error = ''
        self.busy = False

    def start(self, values, *, capture=False):
        if self.busy:
            return
        executable = collector_path()
        if executable is None:
            self.failed.emit('未找到独立诊断工具，请使用完整的软件包。')
            return
        self.buffer, self.result, self.error, self.partial = b'', None, '', None
        self.destination = Path(values['destination']).resolve() if not capture else None
        handle, name = tempfile.mkstemp(prefix='ddm-diagnostic-', suffix='.json')
        self.request = Path(name)
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump({**values, 'root': str(app_root())}, stream, ensure_ascii=False)
        self.busy = True
        self.busyChanged.emit(True)
        self.process.start(str(executable), ['--capture-json' if capture else '--collect-json', name])

    def _read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        if len(self.buffer) > 2 * 1024 * 1024:
            self.error = '诊断工具返回的数据过大。'
            self.process.kill()
            return
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                message = json.loads(line)
            except (ValueError, UnicodeError):
                self.error = '诊断工具返回了无效数据。'
                continue
            kind = message.get('kind')
            if kind == 'progress':
                self.progress.emit(int(message['percent']), message['message'])
            elif kind == 'staging':
                path = Path(message['path']).resolve()
                if path.parent == self.destination and path.name.startswith('DDMonitorCE-diagnostics-') and path.name.endswith('.zip.part'):
                    self.partial = path
            elif kind in ('result', 'capture'):
                self.result = message
            elif kind == 'error':
                self.error = message['message']

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self.error = '无法启动诊断工具：' + self.process.errorString()
            self._finished(-1, QProcess.CrashExit)

    def _finished(self, code, _status):
        if not self.busy:
            return
        self._read()
        self._cleanup()
        self.busy = False
        self.busyChanged.emit(False)
        if code != 0 or self.error or self.result is None:
            self.failed.emit(self.error or '诊断工具意外退出，未生成完整诊断包。')
        elif self.result['kind'] == 'capture':
            self.captured.emit(self.result['evidence'])
        else:
            self.completed.emit(self.result['path'])

    def _cleanup(self):
        for path in (self.request, self.partial):
            if path is not None:
                path.unlink(missing_ok=True)
        self.request = self.partial = None

    def stop(self):
        if self.process.state() != QProcess.NotRunning:
            self.error = '采集已取消。'
            self.process.kill()
            self.process.waitForFinished(1000)
        self._cleanup()
