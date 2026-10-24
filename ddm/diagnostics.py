"""统一诊断日志：文件、控制台、异常钩子、Qt 消息和崩溃转储。

只依赖标准库，必须在导入 Qt、mpv 和业务模块之前启动。调用方只需要
``start()``、``LogSession.phase()``、``get_logger()`` 和 ``close()``。
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import sys
import threading
import time
from typing import Iterator
import uuid

try:
    import winreg
except ImportError:  # pragma: no cover - 非 Windows
    winreg = None

LOG_NAME = "ddm.log"
CRASH_NAME = "ddm-crash.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
RETENTION_DAYS = 14
DEDUPE_SECONDS = 5.0
LEVEL_ENV = "DDM_LOG_LEVEL"
DIR_ENV = "DDM_LOG_DIR"

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(sessdata|bili_jct|dedeuserid|access_token|refresh_token|token|"
    r"password|passwd|authorization|proxy-authorization)"
    r"(\s*[=:]\s*)([^\s&,;]+)")
_COOKIE_HEADER = re.compile(r"(?i)\b(cookie\s*:\s*)([^\r\n]+)")
_AUTH_HEADER = re.compile(r"(?i)\b((?:proxy-)?authorization\s*:\s*)([^\r\n]+)")
_SIGNED_URL = re.compile(r"(?i)\b(https?://[^\s?#]+)\?[^\s#]*")

_SESSION: "LogSession | None" = None
_SESSION_LOCK = threading.Lock()


def program_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def sanitize(text: str) -> str:
    """移除日志中不应携带的凭证、签名查询串和用户目录。"""
    value = str(text)
    value = _COOKIE_HEADER.sub(r"\1<redacted>", value)
    value = _AUTH_HEADER.sub(r"\1<redacted>", value)
    value = _SENSITIVE_ASSIGNMENT.sub(r"\1\2<redacted>", value)
    value = _SIGNED_URL.sub(r"\1?<redacted>", value)
    for variable in ("USERPROFILE", "HOME"):
        home = os.environ.get(variable)
        if home and len(home) > 2:
            value = value.replace(home, "%USERPROFILE%")
            value = value.replace(home.replace("\\", "/"), "%USERPROFILE%")
    return value


def _cpu_details() -> dict:
    details = {"cpu": platform.processor() or platform.machine(),
               "cpu_logical": os.cpu_count() or 0}
    if os.name != "nt":
        return details
    try:
        import winreg as registry
        path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with registry.OpenKey(registry.HKEY_LOCAL_MACHINE, path) as key:
            details["cpu"] = registry.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except OSError:
        pass
    try:
        class _Cache(ctypes.Structure):
            _fields_ = [("Level", ctypes.c_ubyte), ("Associativity", ctypes.c_ubyte),
                        ("LineSize", ctypes.c_ushort), ("CacheSize", ctypes.c_ulong),
                        ("Type", ctypes.c_ulong)]

        class _Processor(ctypes.Structure):
            _fields_ = [("ProcessorMask", ctypes.c_size_t), ("Relationship", ctypes.c_ulong),
                        ("Union", ctypes.c_byte * 16)]

        relation_processor_core = 0
        count = ctypes.c_ulong(0)
        kernel = ctypes.windll.kernel32
        kernel.GetLogicalProcessorInformation.argtypes = [ctypes.c_void_p,
                                                         ctypes.POINTER(ctypes.c_ulong)]
        kernel.GetLogicalProcessorInformation.restype = ctypes.c_int
        kernel.GetLogicalProcessorInformation(None, ctypes.byref(count))
        if count.value:
            buffer = ctypes.create_string_buffer(count.value)
            if kernel.GetLogicalProcessorInformation(buffer, ctypes.byref(count)):
                entry_size = ctypes.sizeof(_Processor)
                physical = sum(
                    1 for offset in range(0, count.value - entry_size + 1, entry_size)
                    if ctypes.cast(ctypes.byref(buffer, offset),
                                   ctypes.POINTER(_Processor)).contents.Relationship
                    == relation_processor_core)
                if physical:
                    details["cpu_physical"] = physical
    except (AttributeError, OSError, ValueError):
        pass
    return details


def _memory_details() -> dict:
    if os.name != "nt":
        return {}
    try:
        class _MemoryStatus(ctypes.Structure):
            _fields_ = [("Length", ctypes.c_ulong), ("MemoryLoad", ctypes.c_ulong),
                        ("TotalPhys", ctypes.c_ulonglong),
                        ("AvailPhys", ctypes.c_ulonglong),
                        ("TotalPageFile", ctypes.c_ulonglong),
                        ("AvailPageFile", ctypes.c_ulonglong),
                        ("TotalVirtual", ctypes.c_ulonglong),
                        ("AvailVirtual", ctypes.c_ulonglong),
                        ("AvailExtendedVirtual", ctypes.c_ulonglong)]

        status = _MemoryStatus()
        status.Length = ctypes.sizeof(_MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {"memory_total_mb": round(status.TotalPhys / 1024 ** 2),
                    "memory_available_mb": round(status.AvailPhys / 1024 ** 2),
                    "memory_load_pct": status.MemoryLoad}
    except (AttributeError, OSError, ValueError):
        pass
    return {}


def _display_details() -> list[dict]:
    if os.name != "nt":
        return []
    devices: list[dict] = []
    try:
        class _DisplayDevice(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("DeviceName", ctypes.c_wchar * 32),
                        ("DeviceString", ctypes.c_wchar * 128),
                        ("StateFlags", ctypes.c_ulong),
                        ("DeviceID", ctypes.c_wchar * 128),
                        ("DeviceKey", ctypes.c_wchar * 128)]

        user32 = ctypes.windll.user32
        user32.EnumDisplayDevicesW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong,
                                               ctypes.POINTER(_DisplayDevice),
                                               ctypes.c_ulong]
        index = 0
        while len(devices) < 8:
            device = _DisplayDevice()
            device.cb = ctypes.sizeof(_DisplayDevice)
            if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
                break
            if device.StateFlags & 0x1:
                devices.append({"gpu": device.DeviceString.strip(),
                                "gpu_device_id": device.DeviceID.strip()})
            index += 1
    except (AttributeError, OSError, ValueError):
        pass
    return devices


def _registry_gpu_details() -> list[dict]:
    if winreg is None:
        return []
    result: list[dict] = []
    path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as root:
            for index in range(32):
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                if not name.isdigit():
                    continue
                with winreg.OpenKey(root, name) as key:
                    values = {}
                    for field, registry_name in (("gpu", "DriverDesc"),
                                                 ("gpu_driver", "DriverVersion")):
                        try:
                            values[field] = str(winreg.QueryValueEx(key, registry_name)[0])
                        except OSError:
                            pass
                    try:
                        memory = int(winreg.QueryValueEx(
                            key, "HardwareInformation.qwMemorySize")[0])
                        values["gpu_memory_mb"] = round(memory / 1024 ** 2)
                    except (OSError, TypeError, ValueError):
                        pass
                    if values.get("gpu"):
                        result.append(values)
    except OSError:
        pass
    return result


def _collect_optional(collector, default, label: str) -> object:
    try:
        return collector()
    except Exception as error:  # noqa: BLE001
        get_logger("diagnostics").warning(
            "event=system_info_collector_failed collector=%s reason=%s:%s",
            label, type(error).__name__, error)
        return default


def collect_system_info(app=None) -> dict:
    """尽力采集软硬件信息；单项失败不抛异常。"""
    details: dict = {}
    basic = _collect_optional(lambda: {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "python_bits": platform.architecture()[0],
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
    }, {}, "platform")
    if isinstance(basic, dict):
        details.update(basic)
    details.update(_collect_optional(_cpu_details, {}, "cpu"))
    details.update(_collect_optional(_memory_details, {}, "memory"))

    def disk() -> dict:
        import shutil
        usage = shutil.disk_usage(program_dir())
        return {"disk_total_gb": round(usage.total / 1024 ** 3, 1),
                "disk_free_gb": round(usage.free / 1024 ** 3, 1)}

    details.update(_collect_optional(disk, {}, "disk"))
    gpus = _collect_optional(_registry_gpu_details, [], "gpu_registry")
    devices = _collect_optional(_display_details, [], "display_devices")
    if gpus:
        details["gpus"] = "; ".join(
            f"{item.get('gpu', '')} driver={item.get('gpu_driver', '?')} "
            f"vram={item.get('gpu_memory_mb', '?')}MB" for item in gpus)
    elif devices:
        details["gpus"] = "; ".join(item.get("gpu", "") for item in devices)

    def qt_details() -> dict:
        from PySide6.QtCore import qVersion
        from PySide6.QtGui import QGuiApplication
        result = {"qt": qVersion()}
        application = app if app is not None else QGuiApplication.instance()
        if application is not None:
            screens = []
            for screen in application.screens():
                geometry = screen.geometry()
                screens.append(
                    f"{screen.name()} {geometry.width()}x{geometry.height()} "
                    f"dpr={screen.devicePixelRatio():.2f} "
                    f"hz={screen.refreshRate():.1f}")
            result["screens"] = "; ".join(screens)
        return result

    details.update(_collect_optional(qt_details, {}, "qt"))

    def audio_details() -> dict:
        from PySide6.QtMultimedia import QMediaDevices
        if app is None:
            return {}
        default = QMediaDevices.defaultAudioOutput().description()
        outputs = [device.description() for device in QMediaDevices.audioOutputs()]
        return {"audio_default": default, "audio_outputs": "; ".join(outputs)}

    details.update(_collect_optional(audio_details, {}, "audio"))
    return details


class _SanitizingFormatter(logging.Formatter):
    def __init__(self, prefix: str = "") -> None:
        super().__init__("%(message)s")
        self.prefix = prefix

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            message = f"{message}\n{record.exc_text}"
        if getattr(record, "ddm_suppressed", 0):
            message += f" [此前 {record.ddm_suppressed} 条相同错误已合并]"
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        millis = int(record.msecs)
        prefix = f"{stamp}.{millis:03d} {record.levelname:<8} {record.name}"
        if self.prefix:
            prefix = f"{self.prefix} {prefix}"
        return sanitize(f"{prefix} {message}")


class _ConsoleFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return bool(getattr(record, "ddm_console", True))


class _DedupeFilter(logging.Filter):
    """短时间内的相同错误只保留第一条，合并计数。"""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._seen: dict[tuple, tuple[float, int]] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.ERROR:
            return True
        exception_type = ""
        if record.exc_info and record.exc_info[0] is not None:
            exception_type = record.exc_info[0].__name__
        key = (record.name, record.pathname, record.lineno, record.getMessage(),
               exception_type)
        now = time.monotonic()
        with self._lock:
            last, suppressed = self._seen.get(key, (0.0, 0))
            if last and now - last < DEDUPE_SECONDS:
                self._seen[key] = (last, suppressed + 1)
                return False
            if suppressed:
                record.ddm_suppressed = suppressed
            self._seen[key] = (now, 0)
        return True


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

    def close_pending(self) -> None:
        self.flush()

    def __getattr__(self, name):
        if self._stream is None:
            raise AttributeError(name)
        return getattr(self._stream, name)


class LogSession:
    """一次进程运行的日志会话；由 ``start()`` 创建。"""

    def __init__(self, log_dir: Path, level: int) -> None:
        self.log_dir = log_dir
        self.log_path = log_dir / LOG_NAME
        self.crash_path = log_dir / CRASH_NAME
        self.level = level
        self.run_id = uuid.uuid4().hex[:8]
        self.failed_phase = ""
        self._closed = False
        self._lock = threading.Lock()
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._crash_handle = None
        self._logger = logging.getLogger("ddm")
        self._root = logging.getLogger()
        self._previous_level = self._root.level
        self._previous_handlers = list(self._root.handlers)
        self._previous_ddm_handlers = list(self._logger.handlers)
        self._previous_ddm_level = self._logger.level
        self._previous_ddm_propagate = self._logger.propagate
        self._handlers: list[logging.Handler] = []
        self._stdout_mirror = None
        self._stderr_mirror = None
        self._qt_handler = None
        self._previous_hooks = (sys.excepthook, getattr(threading, "excepthook", None),
                                getattr(sys, "unraisablehook", None))
        self._configure()

    def _configure(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._remove_expired()
        self._logger.setLevel(self.level)
        self._logger.propagate = False
        for handler in list(self._logger.handlers):
            self._logger.removeHandler(handler)
        self._root.setLevel(self.level)

        file_handler = RotatingFileHandler(
            self.log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
            encoding="utf-8", delay=False)
        file_handler.setFormatter(_SanitizingFormatter())
        file_handler.addFilter(_DedupeFilter())
        self._handlers.append(file_handler)
        self._logger.addHandler(file_handler)

        console_stream = self._original_stderr
        if console_stream is not None:
            console = logging.StreamHandler(console_stream)
            console.setFormatter(_SanitizingFormatter())
            console.addFilter(_ConsoleFilter())
            console.addFilter(_DedupeFilter())
            self._handlers.append(console)
            self._logger.addHandler(console)

        self._root.addHandler(file_handler)
        if len(self._handlers) > 1:
            self._root.addHandler(self._handlers[1])

        sys.excepthook = self._handle_uncaught
        threading.excepthook = self._handle_thread_exception
        if hasattr(sys, "unraisablehook"):
            sys.unraisablehook = self._handle_unraisable

        sys.stdout = _StreamMirror(self._original_stdout, self._logger, "stdout")
        sys.stderr = _StreamMirror(self._original_stderr, self._logger, "stderr")
        self._stdout_mirror = sys.stdout
        self._stderr_mirror = sys.stderr
        self._open_crash_file()
        self._logger.info(
            "event=log_started run=%s pid=%s version=%s frozen=%s log=%s level=%s",
            self.run_id, os.getpid(), _version(), bool(getattr(sys, "frozen", False)),
            self.log_path, logging.getLevelName(self.level))

    def _open_crash_file(self) -> None:
        try:
            self._crash_handle = open(self.crash_path, "a", encoding="utf-8",
                                      buffering=1)
            self._crash_handle.write(
                f"\n===== run {self.run_id} {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            self._crash_handle.flush()
            import faulthandler
            faulthandler.enable(file=self._crash_handle, all_threads=True)
        except (OSError, RuntimeError, ValueError) as error:
            self._logger.warning("event=crash_log_unavailable reason=%s", error)

    @property
    def crash_file(self):
        return self._crash_handle

    def install_qt_messages(self) -> None:
        """安装 Qt 消息钩子；Qt 尚未安装时只记一条警告。"""
        try:
            from PySide6.QtCore import QtMsgType, qInstallMessageHandler
        except ImportError as error:
            self._logger.warning("event=qt_message_handler_unavailable reason=%s", error)
            return

        levels = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }

        def handler(kind, context, message):
            text = str(message)
            if context is not None:
                category = str(getattr(context, "category", "") or "")
                if category:
                    text = f"[{category}] {text}"
            self._logger.log(levels.get(kind, logging.INFO), "event=qt_message %s",
                             text, extra={"ddm_console": True})
            if kind == QtMsgType.QtFatalMsg:
                self.dump_crash("Qt fatal")

        self._qt_handler = handler
        qInstallMessageHandler(handler)
        self._logger.info("event=qt_message_handler_installed")

    def log_startup_context(self, *, first_run: bool, argv) -> None:
        """记录不依赖 Qt 的最小启动现场。"""
        arguments = " ".join(argv or ())
        self._logger.info(
            "event=startup_context first_run=%s executable=%s cwd=%s "
            "python=%s bits=%s system=%s release=%s machine=%s argv=%s",
            first_run, sys.executable, os.getcwd(), platform.python_version(),
            platform.architecture()[0], platform.system(), platform.release(),
            platform.machine(), arguments)

    def dump_crash(self, reason: str) -> None:
        """把当前所有线程调用栈写入崩溃文件。"""
        handle = getattr(self, "_crash_handle", None)
        if handle is None:
            return
        try:
            import faulthandler
            handle.write(f"[崩溃] {reason} run={self.run_id} "
                         f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            handle.flush()
            faulthandler.dump_traceback(file=handle, all_threads=True)
            handle.write("[崩溃] 调用栈结束\n")
            handle.flush()
        except (OSError, RuntimeError, ValueError) as error:
            self._logger.error("event=crash_dump_failed reason=%s", error)

    @contextmanager
    def phase(self, name: str, **fields) -> Iterator[None]:
        """记录启动阶段的开始、耗时和失败现场。"""
        started = time.perf_counter()
        context = " ".join(f"{key}={value}" for key, value in fields.items())
        self._logger.info("event=phase_start phase=%s%s run=%s", name,
                          f" {context}" if context else "", self.run_id)
        try:
            yield
        except BaseException as error:
            if isinstance(error, (SystemExit, KeyboardInterrupt)):
                code = getattr(error, "code", None)
                if isinstance(error, SystemExit) and code in (None, 0):
                    self._logger.info("event=phase_ok phase=%s elapsed_ms=%.0f",
                                      name, (time.perf_counter() - started) * 1000)
                else:
                    self.failed_phase = name
                    self._logger.exception("event=phase_interrupted phase=%s", name)
                raise
            self.failed_phase = name
            self._logger.exception("event=phase_failed phase=%s elapsed_ms=%.0f",
                                   name, (time.perf_counter() - started) * 1000)
            raise
        else:
            self._logger.info("event=phase_ok phase=%s elapsed_ms=%.0f",
                              name, (time.perf_counter() - started) * 1000)

    def log_system_info(self, details: dict | None = None) -> None:
        for key, value in (details or {}).items():
            self._logger.info("event=system_info %s=%s", key, value)

    def _handle_uncaught(self, exc_type, value, traceback_object) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            self._previous_hooks[0](exc_type, value, traceback_object)
            return
        self._logger.critical("event=uncaught_exception", exc_info=(
            exc_type, value, traceback_object))

    def _handle_thread_exception(self, args) -> None:
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else "?"
        self._logger.error("event=thread_exception thread=%s", name,
                           exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    def _handle_unraisable(self, args) -> None:
        self._logger.error("event=unraisable_exception object=%r",
                           getattr(args, "object", None),
                           exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    def _remove_expired(self) -> None:
        cutoff = time.time() - RETENTION_DAYS * 86400
        candidates = [self.log_path, self.crash_path]
        candidates.extend(self.log_dir.glob("ddm.log.*"))
        candidates.extend(self.log_dir.glob("ddm-*.log"))
        for path in candidates:
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError as error:
                self._logger.warning("event=expired_log_cleanup_failed path=%s reason=%s",
                                     path, error)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._logger.info("event=log_closed run=%s", self.run_id)
        for mirror in (self._stdout_mirror, self._stderr_mirror):
            if mirror is not None:
                mirror.close_pending()
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        sys.excepthook = self._previous_hooks[0]
        if self._previous_hooks[1] is not None:
            threading.excepthook = self._previous_hooks[1]
        if self._previous_hooks[2] is not None and hasattr(sys, "unraisablehook"):
            sys.unraisablehook = self._previous_hooks[2]
        for handler in self._handlers:
            try:
                self._logger.removeHandler(handler)
                self._root.removeHandler(handler)
                handler.close()
            except (OSError, ValueError):
                pass
        self._logger.handlers = self._previous_ddm_handlers
        self._logger.setLevel(self._previous_ddm_level)
        self._logger.propagate = self._previous_ddm_propagate
        self._root.setLevel(self._previous_level)
        handle, self._crash_handle = getattr(self, "_crash_handle", None), None
        if handle is not None:
            try:
                import faulthandler
                faulthandler.disable()
                handle.close()
            except OSError:
                pass


def _version() -> str:
    try:
        from .version import VERSION
        return VERSION
    except (ImportError, AttributeError, ValueError):
        return "?"


def _parse_level(value: str | None) -> int:
    text = (value or "").strip().upper()
    if text:
        level = logging.getLevelName(text)
        if isinstance(level, int):
            return level
    return logging.INFO


def start(argv=None, log_dir=None, level=None) -> LogSession:
    """启动诊断会话；重复调用返回同一个实例。"""
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is not None and not _SESSION._closed:
            return _SESSION
        configured = log_dir if log_dir is not None else os.environ.get(DIR_ENV)
        directory = Path(configured) if configured else program_dir() / "logs"
        chosen = _parse_level(level if level is not None else os.environ.get(LEVEL_ENV))
        try:
            _SESSION = LogSession(directory, chosen)
        except OSError as error:
            fallback = Path(os.environ.get("TEMP", ".")) / "ddm-logs"
            _SESSION = LogSession(fallback, chosen)
            _SESSION._logger.error("event=log_dir_fallback requested=%s reason=%s",
                                   directory, error)
        _SESSION._logger.debug("event=bootstrap argv=%s", list(argv or sys.argv))
        return _SESSION


def get_logger(name: str = "") -> logging.Logger:
    suffix = f".{name}" if name else ""
    return logging.getLogger(f"ddm{suffix}")


def crash_path() -> str:
    session = _SESSION
    return str(session.crash_path) if session is not None else ""


def close() -> None:
    global _SESSION
    session, _SESSION = _SESSION, None
    if session is not None:
        session.close()


def get_session() -> LogSession | None:
    session = _SESSION
    return session if session is not None and not session._closed else None


def show_startup_failure(message: str, log_path: str = "") -> None:
    """启动失败的兜底提示：Qt 已就绪用 QMessageBox，否则用 Windows 原生对话框。"""
    title = "DD监控室CE 启动失败"
    body = message
    if log_path:
        body += f"\n\n日志文件：{log_path}"
    logger = get_logger("diagnostics")
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(None, title, body)
            return
    except Exception as error:  # noqa: BLE001 - 启动失败提示不能再次中断退出流程
        logger.warning("event=startup_failure_dialog_failed backend=qt reason=%s:%s",
                       type(error).__name__, error, exc_info=True)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, body, title, 0x10)
            return
        except Exception as error:  # noqa: BLE001 - 同上，Qt 与本机对话框都不可用
            logger.warning("event=startup_failure_dialog_failed backend=win32 reason=%s:%s",
                           type(error).__name__, error, exc_info=True)
    try:
        print(f"{title}: {body}", file=sys.stderr)
    except (OSError, ValueError):
        pass


def _reset_for_tests() -> None:
    """仅供离屏自检：结束当前会话并恢复全局状态。"""
    close()
