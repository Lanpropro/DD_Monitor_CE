"""Bounded specialist captures attached to the already-running host."""
from contextlib import ExitStack

from PySide6.QtCore import QObject, QTimer


SPECIALTIES = ('douyu', 'fullscreen', 'notices')


def replace_hook(cleanup, owner, name, replacement):
    original = getattr(owner, name)
    if cleanup is not None:
        inherited = name not in vars(owner)
        def restore():
            if getattr(owner, name) is replacement:
                if inherited:
                    delattr(owner, name)
                else:
                    setattr(owner, name, original)
        cleanup.callback(restore)
    setattr(owner, name, replacement)


class LiveDiagnostics(QObject):
    def __init__(self, window, directory, mode, seconds, emit, done):
        super().__init__(window)
        self.window, self.directory, self.mode = window, directory, mode
        self.emit, self.done = emit, done
        self.cleanup = ExitStack()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(seconds * 1000)
        self.timer.timeout.connect(lambda: self.done('timeout'))

    def start(self):
        if self.mode == 'douyu':
            from .douyu_diagnostics import install
            name = 'douyu-on-demand.jsonl'
            capture = install(self.directory / name, window=self.window, cleanup=self.cleanup)
            self.emit('specialty-start', log=name, log_session=capture.run)
        elif self.mode == 'fullscreen':
            from .fullscreen_diagnostics import install
            name = 'fullscreen-on-demand.jsonl'
            probe = install(self.directory / name, window=self.window, cleanup=self.cleanup,
                            profile_calls=True, native_windows=True)
            self.emit('specialty-start', log=name, log_session=probe.session)
        else:
            from .notice_diagnostics import NoticeCloseTrace
            trace = NoticeCloseTrace(self.directory / 'on-demand.jsonl', emit=self.emit)
            self.cleanup.callback(trace.deleteLater)
            self.cleanup.callback(trace.stop)
            trace.install(window=self.window, cleanup=self.cleanup)
            self.emit('specialty-start', log='on-demand.jsonl', log_session=trace.session)
        self.timer.start()

    def stop(self):
        self.timer.stop()
        try:
            self.cleanup.close()
        finally:
            self.deleteLater()
