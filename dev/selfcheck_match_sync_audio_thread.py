"""The actual Qt audio worker keeps feeding while the GUI is blocked."""
import os
from pathlib import Path
import sys
import time
from array import array
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('DDM_NO_SAVE', '1')
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QWidget
from plugins_user._match_sync import viewer as module


class Sink:
    def __init__(self, output, fmt, parent):
        self.owner = QThread.currentThread()
        self.stateChanged = Mock()
        self.written = 0
        self.started = time.perf_counter()
        self.underruns = 0
        self.nonzero = False
        self.error_value = 0

    def assert_owner(self):
        assert QThread.currentThread() == self.owner

    def setBufferSize(self, size):
        self.assert_owner()
        self.capacity = size // 4

    def start(self):
        self.assert_owner()
        return self

    def processedUSecs(self):
        self.assert_owner()
        return int((time.perf_counter() - self.started) * 1_000_000)

    def bytesFree(self):
        self.assert_owner()
        elapsed = time.perf_counter() - self.started
        queued = self.written - int(elapsed * module.RATE)
        if elapsed > .05 and queued < -240:
            self.underruns += 1
        return max(0, min(self.capacity, self.capacity - queued)) * 4

    def write(self, data):
        self.assert_owner()
        self.written += len(data) // 4
        self.nonzero |= any(data)
        return len(data)

    def stop(self):
        self.assert_owner()

    def error(self):
        self.assert_owner()
        return SimpleNamespace(value=self.error_value)

    def deleteLater(self):
        self.assert_owner()


def main():
    app = QApplication([])
    gui = QThread.currentThread()
    reads = []
    def control(value):
        def get():
            assert QThread.currentThread() == gui, 'Worker read a GUI control'
            return value
        return get
    def pcm_at(timestamp, frames):
        assert QThread.currentThread() != gui, 'PCM supply still runs on GUI thread'
        reads.append(timestamp)
        return array('h', [1000, -1000] * frames).tobytes()
    host = QWidget()
    host.running = True
    host.shifts = lambda: {'1': -2}
    host.playback_rate = 1
    host.relative_rates = {}
    host.sync_waiting = False
    host.rows = {'1': SimpleNamespace(decoder=SimpleNamespace(history=SimpleNamespace(pcm_at=pcm_at)),
        audible=SimpleNamespace(isChecked=control(True)), paused=False, sync_state='已同步',
        channel=SimpleNamespace(currentData=control(0)), volume=SimpleNamespace(value=control(42)), mix_gain=1)}
    output = Mock()
    output.id.return_value = b'test'
    output.isNull.return_value = False
    output.isFormatSupported.return_value = True
    pump = module.AudioPump(host)
    try:
        with patch.object(module.QMediaDevices, 'defaultAudioOutput', return_value=output), patch.object(module, 'QAudioSink', Sink):
            for _ in range(2):
                pump.start()
                deadline = time.perf_counter() + 2
                while pump.sink is None or pump.written < 1000:
                    assert time.perf_counter() < deadline, 'Audio worker did not start'
                    app.processEvents()
                    time.sleep(.005)
                sink, thread = pump.sink, pump.thread
                before, written = pump.clock(), sink.written
                # Deliberately do not pump Qt GUI events for longer than the audio buffer.
                time.sleep(.55)
                assert sink.written - written > module.RATE * .4
                assert pump.clock() - before > .45
                assert sink.owner != gui and not sink.underruns and sink.nonzero
                pump.stop()
                assert not thread.isRunning() and pump.sink is None
            assert len(reads) > 20
            pump.start()
            deadline = time.perf_counter() + 2
            while pump.sink is None or pump.written == 0:
                assert time.perf_counter() < deadline
                app.processEvents()
                time.sleep(.005)
            pump.sink.error_value = 1
            module.QMetaObject.invokeMethod(pump.feed, 'state_changed', module.Qt.BlockingQueuedConnection)
            assert pump.sink is None
            pump.stop()
            pump.start()
            pump.stop()  # Closing immediately after start must also join the output thread.
    finally:
        pump.stop()
        host.close()
        app.processEvents()
    print('PASS: Qt worker feeds nonzero PCM through two 550ms GUI stalls; widget access stays on GUI; restart/immediate stop release the thread')


if __name__ == '__main__':
    main()
