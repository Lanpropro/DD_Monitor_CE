"""Coarse/fine alignment and played-frame verification from altered actual videos."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from ddm import recording
from dev.selfcheck_match_sync_video import ready
from plugins_user._match_sync.media import Decoder, scene_feature
from plugins_user._match_sync.engine import Match, match_scenes, refine_match


def run(app):
    executable = recording.ffmpeg_path()
    with tempfile.TemporaryDirectory(prefix="ddm_refine_media_", ignore_cleanup_errors=True) as root:
        source, changed = Path(root) / "source.mkv", Path(root) / "changed.mkv"
        subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "nullsrc=size=640x360:rate=60,geq=lum='128+40*sin(X*0.03+N*0.13)+40*sin(Y*0.04+N*0.061)+25*sin((X+Y)*0.02+N*0.027)':cb=128:cr=128",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "13", "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast",
            "-c:a", "pcm_s16le", str(source)], check=True, capture_output=True, timeout=45,
            creationflags=recording._FFMPEG_FLAGS)
        cut = 2 + 14 / 60
        subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", str(cut), "-i", str(source), "-t", "10",
            "-vf", "scale=480:270,eq=brightness=0.08:contrast=1.15,drawbox=x=0:y=0:w=100:h=40:color=white:t=fill",
            "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "pcm_s16le", str(changed)], check=True, capture_output=True, timeout=30,
            creationflags=recording._FFMPEG_FLAGS)
        a, b = Decoder("1", {"url": str(source)}), Decoder("2", {"url": str(changed)})
        crop = (.1, .2, .8, .75)
        a.set_crop(crop)
        b.set_crop(crop)
        try:
            a.start()
            b.start()
            deadline = time.monotonic() + 11
            while time.monotonic() < deadline:
                app.processEvents()
                if min(len(a.history.snapshots()), len(b.history.snapshots())) >= 16:
                    break
                time.sleep(.01)
            expected = b.history.origin - a.history.origin - cut
            coarse = match_scenes(list(a.history.details)[::4], list(b.history.details)[::4])
            fine = refine_match(coarse, list(a.history.details), list(b.history.details))
            print(f"MEASURE: expected {expected:.4f}s, coarse {coarse}, refined {fine}")
            assert fine.lag is not None and abs(fine.lag - expected) <= .10
            # Verify the actually decoded pictures at a shared content time.
            position = a.history.origin + 5
            picture_a = ready(a, position)
            picture_b = ready(b, position + fine.lag)
            feature_a = scene_feature(picture_a[1], crop)
            feature_b = scene_feature(picture_b[1], crop)
            distance = sum(abs(x - y) for x, y in zip(feature_a, feature_b)) / (256 * 128)
            assert distance < .10, "Applied lag does not reproduce the same played scene"
            assert abs((picture_b[0] - picture_a[0]) - expected) <= .10
            # A residual computed over the already played window can detect 300ms error.
            played_a = [s for s in a.history.details if s.time <= position]
            played_b = [s for s in b.history.details if s.time <= position + expected + .3]
            verified = refine_match(Match(expected + .3, .9, "played"), played_a, played_b)
            assert verified.lag is not None and abs(verified.lag - expected) <= .1
            residual = verified.lag - (expected + .3)
            assert abs(residual + .3) <= .1
            print(f"PASS: altered resolution/tone/compression/overlay align within {abs(fine.lag - expected) * 1000:.0f}ms; actual pictures agree; 300ms residual detected")
        finally:
            for decoder in (a, b):
                decoder.stop()
                decoder.thread.join(4)
                assert not decoder.thread.is_alive()


if __name__ == "__main__":
    run(QApplication([]))
