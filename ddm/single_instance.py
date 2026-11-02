"""One main application per user, with local window activation messages."""
import hashlib
from pathlib import Path
import sys
import time

from PySide6.QtCore import QLockFile, QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from .data_paths import user_home


class SingleInstance(QObject):
    def __init__(self, parent=None, *, runtime_dir=None):
        super().__init__(parent)
        root = Path(runtime_dir) if runtime_dir is not None else user_home() / 'runtime'
        root.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(str(root.resolve()).lower().encode()).hexdigest()[:24]
        self.name = 'DDMonitorCE-' + identity
        self.lock = QLockFile(str(root / 'main-instance.lock'))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self._primary = False
        self._restore = None
        self._pending = False

    def start(self):
        """Return True for the owner; otherwise notify it and return False."""
        deadline = time.monotonic() + 3
        while True:
            if self.lock.tryLock(0):
                self._primary = True
                # Only the lock owner may remove an endpoint left by a crash.
                QLocalServer.removeServer(self.name)
                if not self.server.listen(self.name):
                    error = self.server.errorString()
                    self.close()
                    raise RuntimeError('无法创建单实例通信：' + error)
                return True
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(300):
                info = self.lock.getLockInfo()
                if sys.platform == 'win32' and info:
                    import ctypes
                    ctypes.windll.user32.AllowSetForegroundWindow(int(info[0]))
                socket.write(b'activate\n')
                socket.flush()
                # A fast peer may have drained the write already. Its reply,
                # rather than waitForBytesWritten(), confirms delivery.
                if not socket.bytesAvailable():
                    socket.waitForReadyRead(5000)
                if bytes(socket.readAll()) != b'ok\n':
                    raise RuntimeError('已运行的软件暂时未响应，请稍后重试。')
                socket.disconnectFromServer()
                return False
            if time.monotonic() >= deadline:
                raise RuntimeError('软件已在启动或退出中，暂时无法唤回窗口，请稍后重试。')
            time.sleep(0.05)

    def set_restore(self, callback):
        self._restore = callback
        if self._pending:
            self._pending = False
            callback()

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda socket=socket: self._read(socket))
            socket.disconnected.connect(socket.deleteLater)
            self._read(socket)

    def _read(self, socket):
        if socket.canReadLine():
            if bytes(socket.readLine(64)) == b'activate\n':
                socket.write(b'ok\n')
                if self._restore is None:
                    self._pending = True
                else:
                    self._restore()
            socket.disconnectFromServer()

    def close(self):
        if self._primary:
            self.server.close()
            self.lock.unlock()
            self._primary = False


def restore_main_window(window):
    if window._closing:
        return
    window._tray.restore()
    target = QApplication.activeModalWidget() or window
    target.raise_()
    target.activateWindow()
    if sys.platform == 'win32' and QApplication.platformName() == 'windows':
        import ctypes
        ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(int(target.winId())))
