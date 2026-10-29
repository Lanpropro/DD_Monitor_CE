"""Bounded, redacted application logs, adapted from PR #61 (Soraray).
https://github.com/Lanpropro/DD_Monitor_CE/pull/61
Only standard-library imports: this module must work before Qt/mpv import.
"""
import atexit
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
RETENTION_DAYS = 14
_session = None
_OWN_LOG = re.compile(r"^ddm-(?:\d{4}-\d{2}-\d{2}|startup)\.log(?:\.[1-5])?$")
_SECRET = re.compile(
    r"""(?ix)(["']?\b(?:cookie|set-cookie|authorization|proxy-authorization|sessdata|bili_jct|dedeuserid|access_token|refresh_token|token|password|passwd)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\r\n,;}]+)""")
_URL_QUERY = re.compile(r"((?:https?|wss?|rtmps?)://[^\s?\"'<>]+)\?[^\s\"'<>]+")


def sanitize(text):
    text = _SECRET.sub(lambda match: match[1] + "[REDACTED]", str(text))
    text = _URL_QUERY.sub(r"\1?[REDACTED]", text)
    home = os.environ.get("USERPROFILE")
    if home:
        text = re.sub(re.escape(home), "%USERPROFILE%", text, flags=re.I)
    return text


class _Formatter(logging.Formatter):
    def format(self, record):
        return sanitize(super().format(record))


class _StreamMirror:
    """保留原控制台输出，同时把完整行写入日志。"""

    def __init__(self, stream, logger: logging.Logger, name: str) -> None:
        self._stream = stream
        self._logger = logger
        self._name = name
        self._buffer = ""
        self._lock = threading.Lock()
        self._local = threading.local()

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def buffer(self):
        return getattr(self._stream, "buffer", None)

    @property
    def errors(self) -> str:
        return "replace"

    def isatty(self) -> bool:
        try:
            return bool(self._stream and self._stream.isatty())
        except (AttributeError, OSError, ValueError):
            return False

    def writable(self) -> bool:
        return True

    def fileno(self) -> int:
        if self._stream is None:
            raise OSError("stream is not backed by a file descriptor")
        return self._stream.fileno()

    def write(self, data) -> int:
        text = str(data)
        if self._stream is not None:
            try:
                self._stream.write(text)
            except (OSError, ValueError):
                pass
        if getattr(self._local, "writing", False):
            return len(text)
        self._local.writing = True
        try:
            with self._lock:
                self._buffer += text
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    self._emit(line)
        finally:
            self._local.writing = False
        return len(text)

    def _emit(self, line: str) -> None:
        if not line.strip():
            return
        level = logging.WARNING if self._name == "stderr" else logging.INFO
        self._logger.log(level, "%s", line, extra={"ddm_console": False})

    def flush(self) -> None:
        if self._stream is not None:
            try:
                self._stream.flush()
            except (OSError, ValueError):
                pass
        with self._lock:
            pending, self._buffer = self._buffer, ""
        if pending.strip():
            self._emit(pending)

    def reconfigure(self, **kwargs) -> None:
        if self._stream is None:
            return
        try:
            self._stream.reconfigure(**kwargs)
        except (AttributeError, OSError, ValueError):
            pass

    def __getattr__(self, name):
        if self._stream is None:
            raise AttributeError(name)
        return getattr(self._stream, name)


class LogSession:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - RETENTION_DAYS * 86400
        for path in self.directory.iterdir():
            if _OWN_LOG.fullmatch(path.name) and path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        self.path = str(self.directory / time.strftime("ddm-%Y-%m-%d.log"))
        self.crash_path = str(self.directory / "ddm-crash.log")
        # The native crash descriptor must never be renamed while faulthandler uses it.
        crash = Path(self.crash_path)
        if crash.exists() and crash.stat().st_size > MAX_BYTES:
            crash.replace(crash.with_suffix(".log.1"))
        self.crash_handle = open(crash, "a", encoding="utf-8", buffering=1)
        self.handler = RotatingFileHandler(self.path, maxBytes=MAX_BYTES,
                                          backupCount=BACKUP_COUNT, encoding="utf-8")
        self.handler.setFormatter(_Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        self.logger = logging.getLogger("ddm.output")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.logger.addHandler(self.handler)
        self.root_level = logging.getLogger().level
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger().addHandler(self.handler)
        self.original_stdout, self.original_stderr = sys.stdout, sys.stderr
        sys.stdout = _StreamMirror(sys.stdout, self.logger, "stdout")
        sys.stderr = _StreamMirror(sys.stderr, self.logger, "stderr")
        self.stdout, self.stderr = sys.stdout, sys.stderr
        faulthandler.enable(file=self.crash_handle, all_threads=True)
        self.logger.info("[启动] 日志已开启")
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.stdout.flush()
        self.stderr.flush()
        if sys.stdout is self.stdout:
            sys.stdout = self.original_stdout
        if sys.stderr is self.stderr:
            sys.stderr = self.original_stderr
        logging.getLogger().removeHandler(self.handler)
        logging.getLogger().setLevel(self.root_level)
        self.logger.removeHandler(self.handler)
        self.handler.close()
        faulthandler.disable()
        self.crash_handle.close()
        self.closed = True


def start(directory):
    global _session
    if _session is None or _session.closed:
        try:
            _session = LogSession(directory)
        except OSError:
            # Logging failure must not prevent startup or change the configured data root.
            _session = LogSession(Path(tempfile.gettempdir()) / "DDMonitorCE-startup-logs")
    return _session


def get_session():
    return _session


def close():
    if _session is not None:
        _session.close()


atexit.register(close)
