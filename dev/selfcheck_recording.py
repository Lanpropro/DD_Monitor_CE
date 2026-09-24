"""FFmpeg 本体录制：双格独立、格式/请求头、设置、回放及收尾。"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.config import DEFAULT_SETTINGS  # noqa: E402
from ddm.dialogs import SettingsDialog  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.recording import (RecordingManager, ffmpeg_path, input_args, output_path,
                           safe_name, segment_args)  # noqa: E402


class FakeTile:
    def __init__(self, name: str, room_id: str, url: str):
        self.room = {"uname": name, "room_id": room_id, "live": True}
        self.stream_url = url
        self.stream_headers = {}
        self.visible = True

    def isVisible(self):
        return self.visible


def until(app, condition, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.05)
    return False


def main():
    app = QApplication(sys.argv)
    assert safe_name('A:/\\*?<>|"B').startswith("A_")
    assert all(char not in safe_name('A:/\\*?<>|"B') for char in ':/*?<>|"\\')
    assert "12345" not in output_path(Path.cwd(), "主播", "mp4").name
    assert input_args("x", {"User-Agent": "A", "Referer": "B"})[-3:] == [
        "-headers", "User-Agent: A\r\nReferer: B\r\n", "-i", "x"][-3:]
    assert "-c" in segment_args(DEFAULT_SETTINGS, Path("x_%05d.mp4"))
    assert "6000k" in segment_args({"recording_codec": "h264"}, Path("x_%05d.mp4"))

    dialog = SettingsDialog(DEFAULT_SETTINGS, {})
    assert dialog.recording_page.values()["recording_format"] == "mp4"
    assert dialog.recording_page.bitrate.isEnabled() and dialog.recording_page.fps.isEnabled()
    assert dialog.recording_page.codec.currentData() == "copy"
    dialog.recording_page.fps.setValue(50)
    assert dialog.recording_page.codec.currentData() == "h264", \
        "用户直接调帧率时应自动启用重编码"
    dialog.recording_page.format.setCurrentIndex(1)
    dialog.recording_page.bitrate.setValue(8500)
    assert dialog.settings()["recording_format"] == "mkv"
    assert dialog.settings()["recording_bitrate"] == 8500
    assert dialog.recording_page.fps.isEnabled()
    dialog.recording_page.reset()
    assert dialog.recording_page.fps.isEnabled()
    assert dialog.recording_page.codec.currentData() == "copy"
    dialog.nav.setCurrentRow(2)
    dialog.show()
    app.processEvents()
    assert dialog.recording_page.min_free.geometry().bottom() <= dialog.recording_page.height(), \
        "录制设置页所有选项应留在窗口内"
    dialog.close()

    ffmpeg = ffmpeg_path(DEFAULT_SETTINGS)
    assert ffmpeg, "本机需有 FFmpeg 才能完成录制自检"
    with tempfile.TemporaryDirectory(prefix="ddm-record-check-") as temp:
        root = Path(temp)
        source = root / "source.mp4"
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=10",
                   "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                   "-t", "2", "-c:v", "mpeg4", "-c:a", "aac", str(source)]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        settings = dict(DEFAULT_SETTINGS, recording_dir=str(root / "out"),
                        recording_ffmpeg=ffmpeg, recording_min_free_mb=256)
        manager = RecordingManager(settings)
        first = FakeTile("主播甲", "10001", str(source))
        second = FakeTile("主播乙", "20002", str(source))
        assert manager.start(first, recording=True)
        assert manager.start(second, recording=True)
        assert len(manager.sessions) == 2
        assert manager.sessions[first].process.pid != manager.sessions[second].process.pid
        assert until(app, lambda: not manager.sessions and not manager.exports), \
            "两格应分别完成录制/无损封装"
        files = sorted((root / "out").glob("*.mp4"))
        assert len(files) == 2, files
        assert all(path.stat().st_size > 500 for path in files)
        assert all("10001" not in path.name and "20002" not in path.name for path in files)
        probe = shutil.which("ffprobe")
        if probe:
            for path in files:
                result = subprocess.run([probe, "-v", "error", "-show_entries",
                                         "stream=codec_type", "-of", "csv=p=0", str(path)],
                                        check=True, capture_output=True, text=True)
                assert "video" in result.stdout and "audio" in result.stdout

        transcoded = FakeTile("主播转码", "25002", str(source))
        manager.settings = dict(settings, recording_format="mkv", recording_codec="h264",
                                recording_bitrate=8500, recording_fps=12)
        assert manager.start(transcoded, recording=True)
        assert until(app, lambda: transcoded not in manager.sessions and
                     not manager.exports)
        mkv_files = list((root / "out").glob("主播转码*.mkv"))
        assert len(mkv_files) == 1 and mkv_files[0].stat().st_size > 500
        if probe:
            result = subprocess.run([probe, "-v", "error", "-show_entries",
                                     "stream=codec_name", "-of", "csv=p=0", str(mkv_files[0])],
                                    check=True, capture_output=True, text=True)
            assert "h264" in result.stdout and "aac" in result.stdout
        manager.settings = settings

        # 缓存模式不生成完整文件；结束时只删它自己创建的临时分段。
        third = FakeTile("主播丙", "30003", str(source))
        assert manager.start(third, recording=False)
        assert until(app, lambda: third not in manager.sessions)
        assert not list((root / "out").glob("主播丙*.mp4"))

        replay = FakeTile("主播丁", "40004", str(source))
        with patch("ddm.recording.SEGMENT_SECONDS", 1), patch(
                "ddm.recording.input_args",
                side_effect=lambda url, _headers: ["-re", "-stream_loop", "-1", "-i", url]):
            assert manager.start(replay, recording=False)
        assert until(app, lambda: bool(manager.sessions[replay].finished_parts()), 8)
        primary, backup = root / "out", root / "backup"
        backup.mkdir()
        with patch.object(manager, "_dirs", return_value=(primary, backup)), patch.object(
                manager, "_free_enough", side_effect=lambda folder: folder == backup):
            manager._check_space(manager.sessions[replay])
        assert until(app, lambda: manager.sessions[replay].folder == backup and
                     manager.sessions[replay].process.poll() is None, 8), \
            "空间不足后应在备用目录续录，不影响另一格"
        assert manager.save_replay(replay)
        assert until(app, lambda: not manager.exports, 8)
        replay_files = list((backup / "replays").glob("*.mp4"))
        assert len(replay_files) == 1 and replay_files[0].stat().st_size > 500
        assert manager.start(replay, recording=True)  # 缓存升级为持续录制
        manager.stop(replay)
        assert not manager.start(replay, recording=True), "正在封装时不能误报新录制成功"
        assert until(app, lambda: replay not in manager.sessions and not manager.exports)
        assert len(list((primary).glob("主播丁*.mp4"))) == 1, \
            "主盘腾出空间后完整录制应自动从临时目录导回主目录"

        # 首次拉流失败后会保留录制意图；新流地址到来时自动续录。
        reconnect = FakeTile("主播戊", "50005", str(root / "missing.mp4"))
        assert manager.start(reconnect, recording=True)
        assert until(app, lambda: reconnect in manager.sessions and
                     manager.sessions[reconnect].process is None, 8)
        reconnect.stream_url = str(source)
        manager.on_resolved(reconnect)
        assert until(app, lambda: reconnect not in manager.sessions and
                     not manager.exports, 8)
        assert len(list((root / "out").glob("主播戊*.mp4"))) == 1
        manager.shutdown()

        room = {"uname": "格子录制", "room_id": "60006", "live": False,
                "muted": True, "volume": 42, "quality": 250}
        window = MainWindow([dict(room)], [dict(room)], layout_id="main2", state={})
        window.setGeometry(-9000, -9000, 1200, 700)
        window.show()
        app.processEvents()
        tile = window.wall.tiles[0]
        window.settings.update(settings)
        assert tile.recording_button.text() == "● 录制"
        assert tile.recording_button.x() < tile.status_label.x(), \
            "录制按钮应常驻在格子底栏暂停键旁"
        tile.room["live"] = True
        tile.stream_url = str(source)
        tile.stream_headers = {}
        tile.recording_button.click()
        assert tile in window.recorder.sessions
        assert tile.recording_button.text() == "● REC"
        assert tile.recording_button.property("recording") is True
        window._fill_plugin_menu(tile)
        labels = [label for label, _callback in tile.plugin_actions]
        assert any("停止录制" in label for label in labels)
        assert any("保存最近" in label for label in labels)
        window._offline_tile(tile)
        assert until(app, lambda: tile not in window.recorder.sessions and
                     not window.recorder.exports)
        assert tile.recording_button.property("recording") is False
        hidden = window.wall.tiles[1]
        hidden.set_room({"uname": "隐藏格子", "room_id": "60007", "live": False})
        hidden.room["live"] = True
        hidden.stream_url = str(source)
        assert window.recorder.start(hidden, recording=True)
        window._on_layout_changed("1x1")
        app.processEvents()
        assert not hidden.isVisible() and window.recorder.sessions[hidden].stopping
        assert until(app, lambda: hidden not in window.recorder.sessions and
                     not window.recorder.exports)
        window.close()
    print("FFmpeg 双格独立录制、音视频、设置、即时回放、换盘与断流续录：通过")


if __name__ == "__main__":
    main()
