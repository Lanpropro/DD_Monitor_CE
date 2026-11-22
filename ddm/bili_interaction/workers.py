"""Bounded request lifetime independent of transient popup/tile widgets."""
import threading
import requests
from PySide6.QtCore import QThread, Signal, Qt
from . import bili_api

_active_requests = set()

def start_worker(worker, priority=QThread.InheritPriority):
    _active_requests.add(worker)
    def retire():
        # finished precedes native thread_local destruction. Join before
        # dropping our last reference or allowing QApplication to shut down.
        worker.wait()
        _active_requests.discard(worker)
    worker.finished.connect(retire, Qt.QueuedConnection)
    worker.finished.connect(worker.deleteLater)
    worker.start(priority)

def wait_for_requests():
    for worker in tuple(_active_requests):
        worker.wait()
        _active_requests.discard(worker)

def request_message(error, *, sending=False):
    if isinstance(error, requests.Timeout):
        return '发送请求超时，结果可能未确认，请确认后再试' if sending else '请求超时，请稍后重试'
    if isinstance(error, requests.RequestException):
        return '网络请求失败，请检查网络后重试'
    return str(error) or '请求失败，请重试'

class Request(QThread):
    completed = Signal(object, object)
    failed = Signal(object, object)
    deviceReady = Signal(int, str)

    def __init__(self, context, operation, *, cookies, account_generation, require_device=False):
        super().__init__()
        self.context, self.operation = context, operation
        self.cookies = dict(cookies)
        self.account_generation = account_generation
        self.require_device = require_device
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def still_current(self):
        return not self.cancelled.is_set()

    def run(self):
        try:
            if not self.still_current():
                return
            cookies = bili_api.prepare_cookies(self.cookies) if self.require_device else dict(self.cookies)
            if cookies.get('buvid3') and cookies.get('buvid3') != self.cookies.get('buvid3'):
                self.deviceReady.emit(self.account_generation, cookies['buvid3'])
            if not self.still_current():
                return
            result = self.operation(cookies)
        except Exception as error:
            self.failed.emit(self.context, error)
        else:
            self.completed.emit(self.context, result)
