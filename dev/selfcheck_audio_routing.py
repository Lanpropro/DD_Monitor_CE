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


def check_normalization(widget, root, ffmpeg):
    source = root / 'levels.wav'
    # Quiet, loud, silence and near-silence; use real PCM rather than filter strings.
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
        "aevalsrc='if(lt(t,3),0.05,if(lt(t,6),0.7,if(lt(t,9),0,0.0001)))*sin(2*PI*440*t)':s=48000:d=12",
        '-ac', '2', str(source)], check=True, capture_output=True)
    results = []
    for name, enabled, channel, muted, volume in (
            ('original', False, 0, False, 100), ('balanced', True, 0, False, 100),
            ('balanced-left', True, 3, False, 100), ('balanced-right', True, 4, False, 100),
            ('balanced-muted', True, 0, True, 100), ('balanced-zero', True, 0, False, 0),
            ('disabled-again', False, 0, False, 100)):
        output = root / (name + '.wav')
        player = TilePlayer(widget)
        player.player = mpv.MPV(vo='null', vid='no', ao='pcm', ao_pcm_file=str(output),
            audio_format='s16', audio_samplerate=48000, audio_channels='stereo', **EMBEDDED_OPTIONS)
        try:
            player.set_volume(volume)
            player.set_muted(muted)
            player.set_volume_normalization(True)
            player.set_audio_channel(channel)
            player.set_volume_normalization(enabled)
            with player.player.prepare_and_wait_for_event('end-file', timeout=15):
                player.player.play(str(source))
        finally:
            player.release()
        raw = subprocess.check_output([ffmpeg, '-v', 'error', '-i', str(output),
            '-f', 'f32le', '-ac', '2', '-'], timeout=10)
        pcm = np.frombuffer(raw, dtype='<f4').reshape(-1, 2).astype(np.float64)
        assert len(pcm) >= 11.9 * 48000, 'Normalization must preserve audio duration'
        rms = lambda start, end: np.sqrt(np.mean(pcm[int(start*48000):int(end*48000)] ** 2, axis=0))
        quiet, loud = rms(1, 2), rms(4, 5)
        if name == 'original':
            reference = pcm
            original_ratio = loud[0] / quiet[0]
            assert original_ratio > 12
        elif name == 'balanced':
            assert loud[0] / quiet[0] < original_ratio / 2
            assert quiet[0] > rms(10, 11)[0] * 100
            assert max(rms(7, 8)) < 1e-6
            assert np.max(np.abs(pcm)) < 0.95
        elif name in ('balanced-left', 'balanced-right'):
            active = 0 if name.endswith('left') else 1
            assert quiet[active] > 0.02 and loud[active] > 0.02
            assert rms(1, 5)[1-active] < 1e-6
        elif name in ('balanced-muted', 'balanced-zero'):
            assert np.max(np.abs(pcm)) < 1e-6
        elif name == 'disabled-again':
            assert pcm.shape == reference.shape and np.max(np.abs(pcm - reference)) < 1e-4
        results.append({'case': name, 'quiet_rms': quiet.tolist(), 'loud_rms': loud.tolist(), 'pass': True})
        print(name, 'PASS', quiet, loud, flush=True)
    return results


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
        records.extend(check_normalization(widget, root, ffmpeg))
    if args.output:
        args.output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    widget.close()
    app.processEvents()


if __name__ == "__main__":
    main()
