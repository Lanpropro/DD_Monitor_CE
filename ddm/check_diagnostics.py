"""Per-process evidence for isolated checks; no Qt imports or configuration reads."""
import atexit
import ctypes
import faulthandler
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NATIVE_STACK = ROOT / 'work/check-native-crash.dll'
_stack = None
_stack_path = None
_current = None


def install_native_stack():
    global _stack, _stack_path
    if sys.platform != 'win32':
        return None
    path = os.environ.get('DDM_CHECK_NATIVE_STACK_DLL')
    if not path:
        if (os.environ.get('DDM_CHECK_NATIVE_CAPTURE') == '0'
                or os.environ.get('DDM_CHECK_MODE') == 'repository'
                or not DEFAULT_NATIVE_STACK.is_file()):
            return None
        path = str(DEFAULT_NATIVE_STACK)
    path = str(Path(path).resolve())
    if _stack is not None and path == _stack_path:
        return _stack
    helper = ctypes.CDLL(path)
    helper.install.argtypes = []
    helper.install.restype = ctypes.c_int
    if not helper.install():
        raise RuntimeError('Could not install check-process native stack capture')
    _stack, _stack_path = helper, path
    return helper


class CheckEvidence:
    def __init__(self, script, role):
        self.pid = os.getpid()
        directory = os.environ.get('DDM_CHECK_EVIDENCE_DIR')
        if not directory:
            base = Path(os.environ.get('DDM_CHECK_LOG_DIR') or ROOT / 'work/checks/native-evidence')
            directory = str(base / f'{time.time_ns()}-{self.pid}')
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        os.environ['DDM_CHECK_EVIDENCE_DIR'] = str(self.directory)
        os.environ['DDM_DIAGNOSTIC_LOG_DIR'] = str(self.directory)
        self.output = (self.directory / f'check-process-{self.pid}.jsonl').open('a', encoding='utf-8', buffering=1)
        self.fault_output = (self.directory / f'python-crash-{self.pid}.log').open('a', encoding='utf-8')
        self.count = self.exceptions = 0
        self.closed = False
        self.original_hook = sys.excepthook
        self.hook = self.exception_hook
        sys.excepthook = self.hook
        faulthandler.enable(file=self.fault_output, all_threads=True)
        atexit.register(self.close)
        self.record('start', parent_pid=os.getppid(), script=Path(script).name, role=role,
                    cases=[arg for arg in sys.argv[1:] if re.fullmatch(r'[A-Za-z_]\w*\.test_\w+', arg)])
        self.native_stack = install_native_stack()
        if sys.platform == 'win32':
            kernel = ctypes.windll.kernel32
            kernel.GetErrorMode.restype = ctypes.c_uint
            kernel.SetErrorMode(kernel.GetErrorMode() | 2)  # Per-process SEM_NOGPFAULTERRORBOX.
            from . import native_diagnostics
            native_diagnostics.install(self.directory)
            native_diagnostics.set_dump_enabled(False)
            self.record('native-ready', stack=bool(self.native_stack),
                        fatal_capture=native_diagnostics.available(),
                        dump_requested=os.environ.get('DDM_CHECK_MINIDUMP') == '1')

    def record(self, stage, **values):
        if not self.closed and self.count < 128:
            self.count += 1
            self.output.write(json.dumps(dict(time=time.time(), pid=self.pid,
                                             stage=stage, **values), ensure_ascii=False) + '\n')

    def error(self, stage, kind, trace):
        self.record(stage, exception=kind.__name__, frames=[
            dict(file=Path(frame.filename).name, function=frame.name, line=frame.lineno)
            for frame in traceback.extract_tb(trace)[-16:]])

    def exception_hook(self, kind, value, trace):
        self.exceptions += 1
        if self.exceptions <= 3:
            self.error('python-excepthook', kind, trace)
        self.original_hook(kind, value, trace)

    def close(self):
        if self.closed:
            return
        self.record('atexit', callback_exceptions=self.exceptions)
        self.closed = True
        self.output.close()
        if sys.excepthook is self.hook:
            sys.excepthook = self.original_hook
        # Keep faulthandler's file alive through interpreter/Qt teardown.


def start(script, role='check'):
    global _current
    if _current is not None:
        return _current
    if (os.environ.get('DDM_CHECK_NATIVE_CAPTURE') == '0'
            or os.environ.get('DDM_CHECK_MODE') == 'repository'):
        return None
    _current = CheckEvidence(script, role)
    return _current
