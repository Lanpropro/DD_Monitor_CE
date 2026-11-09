"""Install native crash capture before Qt imports; never required for startup."""
import ctypes
import logging
import os
from pathlib import Path
import sys

_capture = None
_worker_crash = None


def install(directory):
    global _capture
    if sys.platform != 'win32' or _capture is not None:
        return
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    candidates = (root / 'native-diagnostics', root / 'work/native-diagnostics')
    folder = next((path for path in candidates if (path / 'DDMonitorNativeCapture.dll').is_file()), None)
    logger = logging.getLogger(__name__)
    if folder is None:
        logger.warning('[原生诊断] unavailable: capture binaries not installed')
        return
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        # Separate PID files avoid cross-process rotation of live handles.
        for pattern, keep in (('native-crash-*.json', 8), ('native-crash-*.dmp', 3),
                              ('qt-lifecycle-*.jsonl*', 12), ('settings-crash-*.log', 6)):
            files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
            for path in files[keep:]:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    # Another supported client/worker may still own this log.
                    logger.debug('Active diagnostic file retained: %s', path.name)
        dll = ctypes.WinDLL(str(folder / 'DDMonitorNativeCapture.dll'))
        dll.DdmInstall.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
        dll.DdmInstall.restype = ctypes.c_int
        dll.DdmSetDumpEnabled.argtypes = (ctypes.c_int,)
        dll.DdmSetDumpEnabled.restype = None
        if not dll.DdmInstall(str(folder / 'DDMonitorCrashWatcher.exe'), str(directory.resolve())):
            logger.warning('[原生诊断] unavailable: helper initialization failed')
            return
        _capture = dll
        logger.info('[原生诊断] ready pid=%s dumps=off', os.getpid())
    except (OSError, ValueError):
        logger.exception('[原生诊断] unavailable')


def set_dump_enabled(enabled):
    if _capture is not None:
        _capture.DdmSetDumpEnabled(bool(enabled))


def available():
    return _capture is not None


def start_worker(directory):
    """Inherited destination only; do not initialize the user's config in a worker."""
    global _worker_crash
    if not directory:
        return
    try:
        import faulthandler
        from . import qt_lifecycle
        install(directory)
        qt_lifecycle.start(directory)
        _worker_crash = open(Path(directory) / f'settings-crash-{os.getpid()}.log', 'a', encoding='utf-8')
        faulthandler.enable(file=_worker_crash, all_threads=True)
    except OSError:
        logging.getLogger(__name__).exception('[设置原生诊断] unavailable')
