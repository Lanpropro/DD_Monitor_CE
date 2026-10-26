"""Two native mixed-resolution streams, real PCM mixing and full-scene matching."""
import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('DDM_NO_SAVE', '1')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins, recording
from dev.selfcheck_match_sync import FakeDecoder, FakeChat
from plugins_user._match_sync import media, viewer as module


class Sink:
    def __init__(self):
        self.started = time.monotonic()
        self.written = 0
        self.silent = False
    def processedUSecs(self):
        return int((time.monotonic() - self.started) * 1_000_000)
    def bytesFree(self):
        return min(4096, max(0, int(self.processedUSecs() * .048) + 480 - self.written)) * 4
    def write(self, pcm):
        self.written += len(pcm) // 4
        self.silent = not any(pcm)
        return len(pcm)
    def stop(self):
        pass
    def deleteLater(self):
        pass


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory, \
            patch.object(module, 'Decoder', FakeDecoder), patch.object(module, 'Chat', FakeChat), \
            patch.object(module.AudioPump, 'start', lambda _: None):
        sources = []
        for size, fps in (('1280x720', 30), ('854x480', 60)):
            source = Path(directory) / f'{fps}.mkv'
            scene = f"nullsrc=size={size}:rate={fps},geq=lum='128+40*sin(X/W*10+T*7.8)+40*sin(Y/H*7+T*3.66)+25*sin((X/W+Y/H)*4+T*1.62)':cb=128:cr=128"
            subprocess.run([recording.ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-nostdin',
                '-f', 'lavfi', '-i', scene, '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                '-t', '20', '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast',
                '-g', str(fps * 4), '-bf', '2', '-c:a', 'pcm_s16le', str(source)],
                check=True, capture_output=True, timeout=30, creationflags=recording._FFMPEG_FLAGS)
            sources.append(source)
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'two_stream_check'), {})
        decoders = []
        try:
            viewer.show()
            for key in ('1', '2'):
                viewer.add_room(key, {'alias': key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            for row, source in zip(viewer.rows.values(), sources):
                row.decoder.stop()
                row.decoder = media.Decoder(row.room_id, {'url': str(source)})
                decoders.append(row.decoder)
            sink = Sink()
            viewer.audio.sink = sink
            viewer.audio.device = sink
            viewer.audio.anchor = sink.started
            begin = time.monotonic()
            decoders[0].start()
            second_started = False
            next_match = 0
            matched = None
            cropped = False
            pause = None
            pause_started = None
            pause_done = False
            recropped = None
            checks = 0
            while time.monotonic() - begin < 17:
                elapsed = time.monotonic() - begin
                if not second_started and elapsed >= .7:
                    decoders[1].start()
                    second_started = True
                viewer.render()
                viewer.audio.fill()
                if elapsed >= next_match:
                    viewer.analyse()
                    next_match = elapsed + .5
                app.processEvents()
                row = viewer.rows['2']
                if row.awaiting_confirmation and row.match_confirmed:
                    assert row.mix_gain == 0, 'First alignment must remain muted until human approval'
                    viewer.admit_pending('2')
                if row.match_confirmed and row.sync_state == '已同步':
                    matched = elapsed if matched is None else matched
                    if cropped:
                        recropped = elapsed if recropped is None else recropped
                if matched is not None and elapsed - matched >= 1:
                    main_row = viewer.rows['1']
                    assert not viewer.sync_waiting and not viewer.canvas.waiting, (elapsed, main_row.sync_state, viewer.notice.text())
                    assert main_row.mix_gain == 1 and main_row.sync_state == '已同步', (elapsed, main_row.sync_state)
                    assert not sink.silent, 'The real PCM mix must remain audible after startup'
                    checks += 1
                    if pause_started is None:
                        viewer.show_comparison('2')
                        pause = patch.object(decoders[1], 'picture_at', return_value=None)
                        pause.start()
                        pause_started = elapsed
                    if not pause_done and elapsed - pause_started >= .8:
                        pause.stop()
                        pause_done = True
                    if not cropped and elapsed - matched >= 2 and pause_done:
                        for target in viewer.rows.values():
                            target.crop = (.1, .1, .8, .8)
                            assert target.decoder.crop == (0, 0, 1, 1)
                        viewer.show_comparison('2')
                        cropped = True
                if recropped is not None and elapsed - recropped >= 2:
                    break
                time.sleep(.005)
            assert matched is not None and recropped is not None, [(r.sync_state, r.match_text) for r in viewer.rows.values()]
            expected = decoders[1].history.origin - decoders[0].history.origin
            assert abs(viewer.alignment.lags['2'] - expected) <= .1
            assert checks >= 100
            print(f'PASS: two native streams matched at {matched:.2f}s; comparison crop at {recropped:.2f}s keeps full-scene matching; {checks} continuity checks')
        finally:
            if 'pause' in locals() and pause is not None:
                pause.stop()
            viewer.close()
            for decoder in decoders:
                if decoder.thread is not None:
                    decoder.thread.join(4)
                    assert not decoder.thread.is_alive()
            host.close()


if __name__ == '__main__':
    faulthandler.dump_traceback_later(55, exit=True)
    try:
        main()
    finally:
        faulthandler.cancel_dump_traceback_later()
