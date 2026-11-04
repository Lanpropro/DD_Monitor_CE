"""External watchdog for this machine's development launcher; no Qt access in target."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.diagnostics import sanitize


def start_for_current_process(root=ROOT):
    config_path = root / 'work/development-hang-monitor.json'
    if (sys.platform != 'win32' or os.environ.get('DDM_NO_SAVE')
            or os.environ.get('DDM_CHECK_MODE') or not config_path.exists()):
        return None
    try:
        settings = json.loads(config_path.read_text(encoding='utf-8'))
        if not settings.get('enabled'):
            return None
        return subprocess.Popen([sys.executable, str(root / 'dev/watch_development_hang.py'),
            '--pid', str(os.getpid())], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, ValueError) as error:
        print(f'External hang monitor unavailable: {error}', file=sys.stderr)
        return None


def prepare_windows():
    global user32, kernel32, CALLBACK
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [CALLBACK, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
        wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def targets(target_pid):
    result = []

    @CALLBACK
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == target_pid:
            kind = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, kind, len(kind))
            if kind.value.startswith('Qt'):
                result.append((target_pid, int(hwnd), tid))
        return True

    user32.EnumWindows(visit, 0)
    return result


def responsive(hwnd):
    value = ctypes.c_size_t()
    return bool(user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 3, 600, ctypes.byref(value)))


def record(phase, **values):
    row = dict(time=time.strftime('%Y-%m-%d %H:%M:%S'), phase=phase, **values)
    with (OUT / 'monitor.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def capture(pid, hwnd, tid):
    record('hang-trigger', pid=pid, hwnd=hex(hwnd), thread=tid)
    # No locals, messages, credentials or memory dump. Only Python/native call stacks.
    with (OUT / f'native-{pid}.log').open('w', encoding='utf-8') as native_log:
        native = subprocess.Popen([str(NATIVE), str(pid)], stdout=native_log,
            stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        for index in range(2):
            try:
                result = subprocess.run([str(SPY), 'dump', '--pid', str(pid),
                    '--full-filenames', '--nonblocking'], capture_output=True, timeout=12,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                text = result.stdout.decode('utf-8', errors='replace') + result.stderr.decode('utf-8', errors='replace')
                (OUT / f'python-{pid}-{index}.log').write_text(sanitize(text), encoding='utf-8')
                record('python-stack', pid=pid, index=index, returncode=result.returncode)
            except subprocess.TimeoutExpired:
                record('python-stack-timeout', pid=pid, index=index)
            time.sleep(2)
        try:
            code = native.wait(timeout=20)
        except subprocess.TimeoutExpired:
            # Let the bounded native sampler finish and resume threads itself.
            # Never kill a sampler that may currently be walking a suspended thread.
            record('native-sampler-still-running', pid=pid, sampler_pid=native.pid)
        else:
            record('native-stack-finished', pid=pid, returncode=code)


def main():
    global OUT, SPY, NATIVE
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', required=True, type=int)
    args = parser.parse_args()
    settings = json.loads((ROOT / 'work/development-hang-monitor.json').read_text(encoding='utf-8'))
    OUT = ROOT / 'logs/development-hang' / f'{time.strftime("%Y%m%d-%H%M%S")}-{args.pid}'
    OUT.mkdir(parents=True, exist_ok=True)
    SPY, NATIVE = Path(settings['py_spy']), Path(settings['native_sampler'])
    prepare_windows()
    process = kernel32.OpenProcess(0x100000, False, args.pid)
    if not process:
        record('target-already-exited', pid=args.pid)
        return
    record('armed', pid=args.pid, trigger_timeouts=3, grace_seconds=15)
    began, streak, captured = time.monotonic(), 0, False
    try:
        while kernel32.WaitForSingleObject(process, 0) == 258:
            windows = targets(args.pid)
            if windows and time.monotonic() - began >= 15:
                # All Qt windows belong to the known parent; no other apps are inspected.
                pid, hwnd, tid = windows[0]
                if responsive(hwnd):
                    if captured:
                        record('recovered', pid=pid)
                    streak, captured = 0, False
                elif not captured:
                    streak += 1
                    if streak >= 3:
                        incident = OUT / time.strftime('incident-%H%M%S')
                        session = OUT
                        OUT = incident
                        OUT.mkdir(exist_ok=True)
                        try:
                            capture(pid, hwnd, tid)
                        finally:
                            OUT = session
                        captured = True
            time.sleep(2)
    finally:
        kernel32.CloseHandle(process)
        record('monitor-stopped', pid=args.pid)


if __name__ == '__main__':
    main()
