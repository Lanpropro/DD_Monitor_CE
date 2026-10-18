"""通过实际 PCM 样本验收 libmpv 音量、静音和左右路由。"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PySide6.QtWidgets import QApplication, QWidget

from ddm.player import EMBEDDED_OPTIONS, TilePlayer, mpv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "FFmpeg must be on PATH for PCM verification"
    app = QApplication([])
    widget = QWidget()
    records = []
    with tempfile.TemporaryDirectory(prefix="ddm-mpv-audio-") as temporary:
        root = Path(temporary)
        source = root / "source.wav"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
            "aevalsrc=0.1*sin(2*PI*440*t)|0.15*sin(2*PI*880*t):s=48000:d=2",
            str(source)], check=True, capture_output=True)
        for name, volume, muted, channel in (("stereo", 100, False, 0),
                ("left", 100, False, 3), ("right", 100, False, 4),
                ("reverse", 100, False, 2), ("half", 50, False, 0),
                ("muted", 100, True, 0), ("zero", 0, False, 0),
                ("dolby-downmix", 100, False, 5)):
            output = root / (name + ".wav")
            player = TilePlayer(widget)
            player.player = mpv.MPV(vo="null", vid="no", ao="pcm", ao_pcm_file=str(output),
                audio_format="s16", audio_samplerate=48000, audio_channels="stereo", **EMBEDDED_OPTIONS)
            try:
                player.set_volume(volume)
                player.set_muted(muted)
                player.set_audio_channel(channel)
                with player.player.prepare_and_wait_for_event("end-file", timeout=15):
                    player.player.play(str(source))
            finally:
                player.release()
            raw = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(output),
                "-f", "f32le", "-ac", "2", "-"], timeout=10)
            pcm = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)[4800:-4800]
            assert len(pcm) > 48000
            rms = np.sqrt(np.mean(pcm.astype(np.float64) ** 2, axis=0))
            if name == "stereo":
                reference = rms
            if name == "left":
                assert rms[0] > 0.02 and rms[1] < 1e-6
            if name == "right":
                assert rms[1] > 0.02 and rms[0] < 1e-6
            if name == "reverse":
                assert np.max(np.abs(rms - reference[::-1])) < 0.001
            if name == "half":
                assert np.max(np.abs(rms / reference - 0.5)) < 0.005
            if name in ("muted", "zero"):
                assert max(rms) < 1e-6
            records.append({"case": name, "rms": rms.tolist(), "pass": True})
            print(name, "PASS", flush=True)
    if args.output:
        args.output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    widget.close()
    app.processEvents()


if __name__ == "__main__":
    main()
