"""Actual three-stream receive, automatic alignment and comparison admission."""
import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DDM_NO_SAVE", "1")
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins, recording
from dev.selfcheck_match_sync import FakeDecoder, FakeChat
from plugins_user._match_sync import media, viewer as module


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root, \
            patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda _self: None):
        source = Path(root) / "scene.mkv"
        subprocess.run([recording.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "nullsrc=size=320x180:rate=60,geq=lum='128+40*sin(X*0.03+N*0.13)+40*sin(Y*0.04+N*0.061)+25*sin((X+Y)*0.02+N*0.027)':cb=128:cr=128",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "14", "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast",
            "-c:a", "pcm_s16le", str(source)], check=True, capture_output=True, timeout=30,
            creationflags=recording._FFMPEG_FLAGS)
        host = QWidget()
        host.settings = {}
        context = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), "session_check")
        viewer = module.Viewer(context, {})
        decoders = []
        try:
            viewer.show()
            for key in ("1", "2", "3"):
                viewer.add_room(key, {"alias": key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            for key, row in viewer.rows.items():
                row.decoder.stop()
                row.decoder = media.Decoder(key, {"url": str(source)})
                decoders.append(row.decoder)
            begin = time.monotonic()
            decoders[0].start()
            started = 1
            next_match = 0
            matched_at = None
            while time.monotonic() - begin < 11:
                elapsed = time.monotonic() - begin
                if started < 3 and elapsed >= started * .8:
                    decoders[started].start()
                    started += 1
                viewer.render()
                if elapsed >= next_match:
                    viewer.analyse()
                    next_match = elapsed + .5
                app.processEvents()
                if all(row.sync_state == "已同步" for row in viewer.rows.values()):
                    if matched_at is None:
                        matched_at = time.monotonic()
                        viewer.show_comparison("2")
                    if time.monotonic() - matched_at > 1:
                        break
                time.sleep(.005)
            assert matched_at is not None, {key: (row.sync_state, row.match_text) for key, row in viewer.rows.items()}
            for key in ("2", "3"):
                expected = viewer.rows[key].decoder.history.origin - decoders[0].history.origin
                assert abs(viewer.alignment.lags[key] - expected) <= .08, (key, expected, viewer.alignment.lags)
            actual = viewer.rows["2"].actual_position - viewer.rows["1"].actual_position
            expected = decoders[1].history.origin - decoders[0].history.origin
            assert abs(actual - expected) <= .1, (actual, expected)
            print(f"MEASURE: three real pipelines confirmed in {matched_at-begin:.2f}s; visible scene error {abs(actual-expected)*1000:.0f}ms")
            assert all(row.mix_gain == 1 for row in viewer.rows.values())
            assert viewer.compare.isChecked() and viewer.alignment.automatic
        finally:
            viewer.close()
            for decoder in decoders:
                if decoder.thread is not None:
                    decoder.thread.join(4)
                    assert not decoder.thread.is_alive()
            host.close()
            app.processEvents()
    print("PASS: independent stream starts, actual frame alignment/admission, comparison tracking and cleanup")


if __name__ == "__main__":
    faulthandler.dump_traceback_later(50, exit=True)
    try:
        main()
    finally:
        faulthandler.cancel_dump_traceback_later()
