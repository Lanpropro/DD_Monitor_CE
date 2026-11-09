"""Attach a 60-second playback capture to the running root development app."""
import argparse
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket

ROOT = Path(__file__).resolve().parents[1]


def development_pid():
    import psutil
    candidates = []
    for process in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline', 'cwd']):
        try:
            info = process.info
            args = info['cmdline'] or []
            if (not (info['name'] or '').lower().startswith('python')
                    or Path(info['cwd'] or '').resolve() != ROOT
                    or any(arg.startswith('--settings-worker') for arg in args)):
                continue
            if any(arg.replace('\\', '/').endswith(('/main.py', '/diagnose_drag_windows.py')) for arg in args):
                candidates.append(info)
        except (psutil.Error, OSError):
            continue
    parents = {info['ppid'] for info in candidates}
    leaves = [info['pid'] for info in candidates if info['pid'] not in parents]
    if len(leaves) != 1:
        raise ValueError('Expected one running root app; pass --pid explicitly')
    return leaves[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--label', choices=('builtin', 'flclash', 'unknown'), default='unknown')
    args = parser.parse_args()
    app = QCoreApplication.instance() or QCoreApplication([])
    socket = QLocalSocket()
    try:
        pid = args.pid or development_pid()
        socket.connectToServer(f'DDMonitorCE-diagnostics-{pid}')
        if not socket.waitForConnected(3000):
            raise ValueError('Running app does not expose the capture endpoint; update and restart via run.cmd')
        socket.write(b'{"protocol":1,"mode":"playback"}\n')
        socket.flush()
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            app.processEvents()
            if not socket.canReadLine():
                socket.waitForReadyRead(250)
                continue
            message = json.loads(bytes(socket.readLine()))
            if message.get('status') == 'armed':
                print('Capturing actual playback for 60 seconds; reproduce the stall now.', flush=True)
            elif message.get('status') == 'complete':
                directory = ROOT / 'work/test-artifacts/playback-capture'
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f'{time.strftime("%Y%m%d-%H%M%S")}-{args.label}.json'
                path.write_text(json.dumps(dict(label=args.label, host=message), ensure_ascii=False, indent=2), encoding='utf-8')
                print(path, flush=True)
                return 0
            else:
                raise ValueError('Capture endpoint rejected the request: ' + message.get('reason', 'unknown'))
        raise ValueError('Playback capture timed out')
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        socket.abort()


if __name__ == '__main__':
    sys.exit(main())
