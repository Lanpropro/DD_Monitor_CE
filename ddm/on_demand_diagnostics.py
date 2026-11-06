"""User-requested snapshots over a local pipe; no idle polling or capture."""
import ctypes
from ctypes import wintypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication


def folder_snapshot(sidebar):
    from .sidebar_diagnostics import SidebarEvidence
    evidence = SidebarEvidence(sidebar, SimpleNamespace(stopped=threading.Event()))
    try:
        return evidence.inspect(detail=True)
    finally:
        evidence.stop()
        evidence.deleteLater()


def native_snapshot():
    if sys.platform != 'win32' or QApplication.platformName() != 'windows':
        return {'available': False}
    from .drag_diagnostics import ole32, user32, windows
    apartment, qualifier = wintypes.DWORD(), wintypes.DWORD()
    result = ole32.CoGetApartmentType(ctypes.byref(apartment), ctypes.byref(qualifier))
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    rows = windows()
    for row in rows[:256]:
        rect = wintypes.RECT()
        if user32.GetWindowRect(int(row['hwnd'], 16), ctypes.byref(rect)):
            row['rect'] = [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]
    return dict(available=True, apartment=[result, apartment.value, qualifier.value],
                cursor=[point.x, point.y], hit=hex(user32.WindowFromPoint(point) or 0),
                windows=rows[:256], truncated=len(rows) > 256)


class OneDrag(QObject):
    """Observe one native/internal drag, or stop after 60 seconds/cancel."""
    def __init__(self, window, emit, done):
        super().__init__(window)
        self.window, self.emit, self.done = window, emit, done
        self.originals, self.events = [], []
        self.closed = False
        self.started = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.finish('timeout'))

    def start(self):
        self.emit('drag-armed', native=self.native())
        original = QDrag.exec
        def execute(drag, *args, **kwargs):
            if drag.source() is None or drag.source().window() is not self.window:
                return original(drag, *args, **kwargs)
            self.emit('drag-before', native=self.native(),
                      formats=list(drag.mimeData().formats()) if drag.mimeData() is not None else [])
            try:
                action = original(drag, *args, **kwargs)
                self.emit('drag-return', action=str(action), native=self.native())
                return action
            finally:
                self.finish('attempt-finished')
        self.wrap(QDrag, 'exec', execute)
        session = self.window.sidebar.drag_session
        cleanup = session._cleanup
        def end_internal(*args, **kwargs):
            try:
                return cleanup(*args, **kwargs)
            finally:
                self.emit('internal-drag-ended', native=self.native())
                self.finish('attempt-finished')
        self.wrap(session, '_cleanup', end_internal)
        QApplication.instance().installEventFilter(self)
        self.timer.start(60000)

    @staticmethod
    def native():
        try:
            return native_snapshot()
        except Exception as error:
            return dict(available=False, error_type=type(error).__name__)

    def wrap(self, owner, name, wrapped):
        self.originals.append((owner, name, getattr(owner, name), wrapped))
        setattr(owner, name, wrapped)

    def eventFilter(self, watched, event):
        kinds = (QEvent.DragEnter, QEvent.DragMove, QEvent.DragLeave, QEvent.Drop)
        if (not self.closed and event.type() in kinds and hasattr(watched, 'window')
                and watched.window() is self.window and len(self.events) < 96):
            entry = dict(event=event.type().name, receiver=type(watched).__name__,
                         at_ms=round((time.monotonic() - self.started) * 1000, 3))
            if hasattr(event, 'mimeData'):
                entry['formats'] = list(event.mimeData().formats())
                entry['proposed_action'] = str(event.proposedAction())
            if event.type() in (QEvent.DragEnter, QEvent.Drop):
                entry['native'] = self.native()
            self.events.append(entry)
            self.emit('drag-event', **entry)
        return False

    def stop(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        QApplication.instance().removeEventFilter(self)
        for owner, name, original, wrapped in reversed(self.originals):
            if getattr(owner, name) is wrapped:
                setattr(owner, name, original)
        self.originals.clear()
        self.deleteLater()

    def finish(self, reason):
        if self.closed:
            return
        self.stop()
        self.done(reason)


class DiagnosticEndpoint(QObject):
    """A per-process, current-user pipe accepting only two fixed requests."""
    def __init__(self, window, directory, root, *, name=None):
        super().__init__(window)
        self.window, self.root = window, str(Path(root).resolve())
        self.directory = Path(directory)
        self.active = None
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.setMaxPendingConnections(2)
        self.server.newConnection.connect(self.accept)
        self.listening = self.server.listen(name or f'DDMonitorCE-diagnostics-{os.getpid()}')
        QApplication.instance().aboutToQuit.connect(self.close)

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.setReadBufferSize(4097)
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.abort)
            timer.start(3000)
            socket.readyRead.connect(lambda socket=socket, timer=timer: self.read(socket, timer))
            socket.disconnected.connect(lambda socket=socket: self.disconnected(socket))
            socket.disconnected.connect(socket.deleteLater)
            self.read(socket, timer)

    @staticmethod
    def send(socket, values):
        socket.write(json.dumps(values, ensure_ascii=False).encode('utf-8') + b'\n')
        socket.flush()

    def read(self, socket, timer):
        if socket.bytesAvailable() > 4096:
            socket.abort()
            return
        if not socket.canReadLine():
            return
        timer.stop()
        try:
            request = json.loads(bytes(socket.readLine()))
            if (not isinstance(request, dict) or request.get('protocol') != 1
                    or request.get('mode') not in ('folders', 'drag')
                    or set(request) != {'protocol', 'mode'}):
                raise ValueError('invalid-request')
        except (ValueError, TypeError):
            self.send(socket, dict(status='error', reason='invalid-request'))
            socket.disconnectFromServer()
            return
        if self.active is not None:
            self.send(socket, dict(status='error', reason='capture-busy'))
            socket.disconnectFromServer()
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(self.directory / 'on-demand.jsonl',
                                      maxBytes=512 * 1024, backupCount=1, encoding='utf-8')
        logger = logging.Logger('ddm.on-demand')
        logger.addHandler(handler)
        records = []
        identity = str(time.time_ns())
        self.active = dict(socket=socket, observer=None, handler=handler, records=records, identity=identity)
        def emit(stage, **values):
            if self.active is None or self.active['identity'] != identity:
                return
            record = dict(time=time.time(), session=identity, stage=stage, pid=os.getpid(), **values)
            if len(records) < 100:
                records.append(record)
            logger.warning(json.dumps(record, ensure_ascii=False))
        def done(reason):
            if self.active is None:
                return
            emit('capture-ended', reason=reason)
            self.send(socket, dict(protocol=1, status='complete', mode=request['mode'],
                                  pid=os.getpid(), root=self.root, reason=reason,
                                  history_available=False, records=records))
            self.release()
            socket.disconnectFromServer()
        try:
            emit('capture-request', mode=request['mode'], history_available=False)
            if request['mode'] == 'folders':
                emit('folder-snapshot', state=folder_snapshot(self.window.sidebar))
                done('snapshot-finished')
            else:
                observer = OneDrag(self.window, emit, done)
                self.active['observer'] = observer
                observer.start()
                self.send(socket, dict(status='armed', protocol=1, pid=os.getpid(),
                                      root=self.root, timeout_seconds=60))
        except Exception as error:
            emit('capture-error', error_type=type(error).__name__)
            done('capture-error')

    def release(self):
        active, self.active = self.active, None
        if active is not None:
            if active['observer'] is not None:
                active['observer'].stop()
            active['handler'].close()

    def disconnected(self, socket):
        if self.active is not None and self.active['socket'] is socket:
            self.release()

    def close(self):
        self.release()
        self.server.close()
