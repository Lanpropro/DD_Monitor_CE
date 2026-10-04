"""退出只保存完整录制；主动保存的回放完成导出，未保存的缓存清理。"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.app import MainWindow  # noqa: E402
from ddm.config import DEFAULT_SETTINGS  # noqa: E402
from ddm.recording import RecordingManager, _Session, ffmpeg_path  # noqa: E402
from selfcheck_recording import FakeTile, until  # noqa: E402


def verify_outputs(folder, *, saved):
    files = list(folder.glob("*.mp4"))
    assert len(files) == 2, f"正在录制及等待重连的录制都应保存：{files}"
    assert all(path.stat().st_size > 500 for path in files)
    replays = list((folder / "replays").glob("*.mp4"))
    assert len(replays) == int(saved), f"退出不应额外保存即时回放：{replays}"
    assert all(path.stat().st_size > 500 for path in replays)
    assert not list((folder / ".ddm-parts").glob("*.mp4")), "已导出的分段及缓存应清理"
    probe = shutil.which("ffprobe")
    if probe:
        for path in files + replays:
            result = subprocess.run([probe, "-v", "error", "-show_entries",
                                     "stream=codec_type", "-of", "csv=p=0", str(path)],
                                    check=True, capture_output=True, text=True)
            assert "video" in result.stdout and "audio" in result.stdout


def main():
    app = QApplication(sys.argv)
    ffmpeg = ffmpeg_path(DEFAULT_SETTINGS)
    assert ffmpeg, "本机需有 FFmpeg"
    with tempfile.TemporaryDirectory(prefix="ddm-shutdown-check-") as temp:
        root = Path(temp)
        source = root / "source.mp4"
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=10",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                        "-t", "2", "-c:v", "mpeg4", "-c:a", "aac", str(source)],
                       check=True, stdout=subprocess.DEVNULL)
        for saved in (False, True):
            folder = root / ("requested" if saved else "unrequested")
            settings = dict(DEFAULT_SETTINGS, recording_dir=str(folder),
                            recording_replay_enabled=True, recording_min_free_mb=256)
            manager = RecordingManager(settings)
            record = FakeTile("完整录制", "1", str(source))
            cache = FakeTile("纯缓存", "2", str(source))
            try:
                with patch("ddm.recording.SEGMENT_SECONDS", 1), patch(
                        "ddm.recording.input_args", side_effect=lambda url, _headers:
                        ["-re", "-stream_loop", "-1", "-i", url]):
                    assert manager.start(record, recording=True)
                    assert manager.start(cache, recording=False)
                assert until(app, lambda: all(session.finished_parts()
                                             for session in manager.sessions.values()), 8)
                # 断流等待重连：进程已结束，但之前录到的分段仍需要保存。
                waiting = _Session(FakeTile("等待重连", "3", str(source)),
                                   settings, True, folder)
                part = folder / ".ddm-parts" / "waiting.mp4"
                shutil.copyfile(source, part)
                waiting.parts.append(part)
                manager.sessions[waiting.tile] = waiting
                if saved:
                    assert manager.save_replay(record)
                    assert any(not full for _p, _r, _parts, full in manager.exports)
                # 不再处理事件：验证关闭时会等待刚刚主动发起的导出完成。
                manager.shutdown()
                assert not manager.sessions and not manager.exports
                verify_outputs(folder, saved=saved)
            finally:
                manager.shutdown()

        # 真正走主窗口关闭事件，检查正在录制时不会额外保存回放。
        folder = root / "window"
        with patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
            window = MainWindow([], [], layout_id="1x1", state={"plugins_enabled": []})
        try:
            window.setGeometry(-9000, -9000, 900, 600)
            window.show()
            app.processEvents()
            window.settings.update(dict(DEFAULT_SETTINGS, recording_dir=str(folder),
                                        recording_min_free_mb=256))
            tile = window.wall.tiles[0]
            tile.set_room({"uname": "关窗录制", "room_id": "4", "live": False})
            tile.room["live"] = True
            tile.stream_url = str(source)
            tile.stream_headers = {}
            with patch("ddm.recording.SEGMENT_SECONDS", 1), patch(
                    "ddm.recording.input_args", side_effect=lambda url, _headers:
                    ["-re", "-stream_loop", "-1", "-i", url]):
                assert window.recorder.start(tile, recording=True)
            assert until(app, lambda: bool(window.recorder.sessions[tile].finished_parts()), 8)
            window.close()
            assert len(list(folder.glob("*.mp4"))) == 1
            assert not list((folder / "replays").glob("*.mp4"))
            assert not window.recorder.sessions and not window.recorder.exports
        finally:
            window.close()
    print("退出仅保存录制、断流收尾、主动回放导出与缓存清理：通过")


if __name__ == "__main__":
    main()
