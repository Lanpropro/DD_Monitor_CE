"""Windows native WASAPI teardown regression; local silence, no account or drag."""
import argparse
import ctypes
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget
from ddm.player import TilePlayer


def apartment():
    kind, qualifier = ctypes.c_ulong(), ctypes.c_ulong()
    result = ctypes.windll.ole32.CoGetApartmentType(ctypes.byref(kind), ctypes.byref(qualifier))
    return result, kind.value, qualifier.value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=30)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('This check requires Windows and a working WASAPI output device')
    app = QApplication.instance() or QApplication([])
    faulthandler.enable()
    widget = QWidget()
    widget.setAttribute(Qt.WA_ShowWithoutActivating)
    widget.setGeometry(-9000, 40, 320, 180)
    widget.show()
    baseline = apartment()
    assert baseline[0] == 0 and baseline[1] in (0, 3), f'Expected Qt STA, got {baseline}'
    print(f'BASELINE COM apartment {baseline}', flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix='ddm-com-lifetime-') as directory:
            source = Path(directory) / 'silence.wav'
            with wave.open(str(source), 'wb') as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(48000)
                output.writeframes(b'\0' * (48000 * 4 * 8))
            for mode in ('terminate', 'release', 'preview'):
                for cycle in range(args.cycles):
                    player = TilePlayer(widget, silent=mode == 'preview')
                    try:
                        player.set_muted(True)
                        if mode == 'preview':
                            player.bind()
                            app.processEvents()
                        else:
                            player.play(str(source), options=('hwdec=no',))
                            deadline = time.monotonic() + 10
                            while (player._prop('time-pos', 0) or 0) < .1:
                                if time.monotonic() > deadline:
                                    raise AssertionError('Local playback did not start')
                                app.processEvents()
                                time.sleep(.01)
                            assert player._prop('current-ao') == 'wasapi', 'WASAPI was not initialized'
                        if mode == 'terminate':
                            player.player.terminate()
                            player.player = None
                        player.release()
                        current = apartment()
                        assert current == baseline, f'{mode} cycle {cycle}: COM changed {baseline} -> {current}'
                        app.processEvents()
                    finally:
                        player.release()
                print(f'PASS {mode}: {args.cycles} cycles, COM apartment {baseline}', flush=True)
    finally:
        if apartment() == baseline:
            widget.close()
            app.processEvents()
            app.shutdown()


if __name__ == '__main__':
    main()
