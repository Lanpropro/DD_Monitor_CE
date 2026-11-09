"""Online operation workers and settings-page retirement lifecycle."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QLabel, QWidget


_retired_online_tasks = set()


def _release_online_task(task):
    if task not in _retired_online_tasks:
        return
    _retired_online_tasks.remove(task)
    if task.result_cleanup is not None:
        task.result_cleanup(task.result)
    task.deleteLater()


def _wait_online_tasks_on_exit():
    # Only final application exit waits; closing a settings page never does.
    for task in tuple(_retired_online_tasks):
        task.wait()
        _release_online_task(task)


class OnlineTask(QThread):
    succeeded = Signal(object)
    failed = Signal(object)
    progress = Signal(int)

    def __init__(self, operation, callback, parent):
        super().__init__(parent)
        self.operation = operation
        self.callback = callback
        self.result = None
        self.result_cleanup = None

    def run(self):
        try:
            result = self.operation(self.isInterruptionRequested,
                                    lambda done, total: self.progress.emit(int(done * 100 / max(total, 1))))
            self.result = result
            if not self.isInterruptionRequested():
                self.succeeded.emit((self, result))
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit((self, str(error)))


class OnlinePage(QWidget):
    busyChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('SettingsPage')
        self.jobs = []
        self.stopping = False
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setObjectName('SettingsHint')

    def start(self, operation, callback, *, key=None):
        from .online_ui import OnlineTask
        if self.stopping or (self.jobs and (key is None or any(
                task.key in (None, key) for task in self.jobs))):
            return
        task = OnlineTask(operation, callback, self)
        task.key = key
        task.percent = 0
        self.jobs.append(task)
        task.succeeded.connect(self._succeeded)
        task.failed.connect(self._failed)
        task.progress.connect(self._progress)
        task.finished.connect(self._finished)
        self.busyChanged.emit(True)
        task.start()

    def _succeeded(self, payload):
        task, result = payload
        if not self.stopping:
            try:
                task.callback(result)
            except Exception as error:
                self.status.setText(str(error))

    def _failed(self, payload):
        if not self.stopping:
            self.status.setText('操作失败：' + payload[1] + '。可重试。')

    def _progress(self, percent):
        if not self.stopping:
            self.status.setText(f'正在下载并校验… {percent}%')

    def _finished(self):
        if self.stopping:
            return
        task = self.sender()
        if task in self.jobs:
            self.jobs.remove(task)
        task.deleteLater()
        self.busyChanged.emit(bool(self.jobs))

    def stop(self, result_cleanup=None):
        self.stopping = True
        app = QApplication.instance()
        if not getattr(app, '_online_task_cleanup_connected', False):
            app.aboutToQuit.connect(_wait_online_tasks_on_exit)
            app._online_task_cleanup_connected = True
        tasks, self.jobs = self.jobs, []
        for task in tasks:
            task.requestInterruption()
            task.succeeded.disconnect(self._succeeded)
            task.failed.disconnect(self._failed)
            task.progress.disconnect(self._progress)
            task.finished.disconnect(self._finished)
            task.callback = None
            task.result_cleanup = result_cleanup
            task.setParent(None)
            _retired_online_tasks.add(task)
            task.finished.connect(lambda t=task: _release_online_task(t))
            if not task.isRunning():
                _release_online_task(task)
