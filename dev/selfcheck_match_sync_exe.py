"""Load the ZIP and decode a local fixture in an isolated copy of the v0.2 EXE."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import plugins, recording  # noqa: E402
from dev.build_match_sync import build  # noqa: E402
from dev.selfcheck_match_sync_media import generate  # noqa: E402

PROBE = '''
import json
import os
import time
import threading
import traceback
from pathlib import Path
from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame
from ddm import bili, plugins as api


class LocalChat(QThread):
    message = Signal(dict)
    status = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.stopped = threading.Event()

    def run(self):
        self.status.emit("已连接")
        self.message.emit({"uname": "跨平台观众", "text": "本地平台弹幕"})
        self.stopped.wait()

    def stop(self):
        self.stopped.set()


class LocalPlatform(api.Platform):
    kind = "local"
    label = "本地平台"
    playback_mode = "stream"

    def matches(self, text):
        return text.startswith("local:")

    def room_info(self, room_id):
        return api.RoomInfo(room_id, uname="合成跨平台二路", platform=self.kind)

    def play_url(self, room_id, quality):
        return os.environ["MATCH_SYNC_TEST_MEDIA"], quality, "local", {}

    def room_quality_options(self, room_id):
        return [{"qn": 10000, "desc": "原画"}]

    def danmaku_client(self, room_id, parent=None):
        return LocalChat(parent)


class Probe(api.Plugin):
    def on_load(self, context):
        self.context = context
        context.window.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.deadline = time.monotonic() + 18
        self.workers = []
        self.checks = {"loaded": False, "local_media": False, "rendered": False, "cleaned": False}
        self.finishing = False
        self.timer = QTimer(context.window)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        try:
            bili.room_info = lambda *_args, **_kwargs: None
            def forbidden(*_args, **_kwargs):
                raise RuntimeError("Test forbids external stream requests")
            bili.play_url = forbidden
            context.register_platform(LocalPlatform())
            match = next(p for p in context.manager.plugins if p.context.name == "match_sync")
            self.match = match
            match.sources["1"] = {"url": os.environ["MATCH_SYNC_TEST_MEDIA"], "headers": {},
                                  "uname": "合成主画面", "title": "本地比赛直播标题"}
            assert match.button is not None
            match.button.trigger()
            self.viewer = match.viewer
            assert self.viewer.embedded and self.viewer.parentWidget() is context.window._content
            self.viewer.setAttribute(Qt.WA_DontShowOnScreen, True)
            self.viewer.show()
            module = __import__(type(self.viewer).__module__, fromlist=["Chat"])
            module.Chat.start = lambda _self: None
            self.viewer.audio.start = lambda: None
            self.viewer.add_room("1", {"alias": "合成主画面"})
            self.viewer.toggle_running()
            self.workers.append(self.viewer.rows["1"].decoder)
            self.checks["loaded"] = True
        except Exception:
            self.finish(traceback.format_exc())

    def poll(self):
        try:
            if self.finishing:
                if all(w.thread is None or not w.thread.is_alive() for w in self.workers):
                    self.checks["cleaned"] = True
                    if os.environ.get("MATCH_SYNC_TEST_AUDIO") == "1" and "error" not in self.checks:
                        if not hasattr(self, "audio_probe"):
                            from ddm_plugin_match_sync.viewer import AudioPump
                            self.audio_probe = AudioPump(self.viewer)
                            self.audio_probe.start()
                            if self.audio_probe.sink is None:
                                self.write("Default audio device unavailable")
                            return
                        if self.audio_probe.sink is not None and self.audio_probe.sink.processedUSecs() >= 200000:
                            self.checks["audio_device"] = True
                            self.audio_probe.stop()
                            self.write()
                        elif time.monotonic() > self.deadline:
                            self.audio_probe.stop()
                            self.write("Silent audio output did not advance")
                    else:
                        self.write()
                elif time.monotonic() > self.deadline:
                    self.write("Decoder cleanup timeout")
                return
            worker = self.viewer.rows["1"].decoder
            if len(worker.history.snapshots()) >= 7 and worker.history.audio.end > 48000 * 2:
                if getattr(self, "reopening", False):
                    assert self.viewer.canvas.frame_key is not None
                    self.viewer.picture.pause_button.click()
                    assert self.viewer.rows["1"].paused
                    self.viewer.picture.pause_button.click()
                    assert not self.viewer.rows["1"].paused
                    self.viewer.render()
                    assert self.viewer.canvas.frame_key is not None
                    row = self.viewer.rows["local:2"]
                    row.delay.setValue(0)
                    row.main_button.click()
                    assert row.main_button.isChecked() and self.viewer.main.currentData() == "local:2"
                    self.viewer.render()
                    assert self.viewer.canvas.frame_key is not None
                    assert self.viewer.compare.isChecked() and self.viewer.comparison_panel.isVisible()
                    assert set(self.viewer.comparison_panel.cards) == {"1", "local:2"}
                    assert all(not card[2].image.isNull() for card in self.viewer.comparison_panel.cards.values())
                    self.viewer.comparison_panel.grab().save(str(Path(os.environ["MATCH_SYNC_TEST_PREVIEW"]).with_name("match-sync-comparison-preview.png")))
                    assert row.decoder.source_url == os.environ["MATCH_SYNC_TEST_MEDIA"]
                    assert row.platform.kind == "local" and row.chat.client is not None
                    for room_id in list(self.viewer.rows):
                        self.viewer.remove_room(room_id)
                    assert self.viewer.canvas.image.isNull() and not self.viewer.picture.room
                    assert not self.viewer.running and not self.viewer.panel._blocks
                    assert self.viewer._add_dragged("local:2") and self.viewer.running
                    self.workers.append(self.viewer.rows["local:2"].decoder)
                    self.checks["platform_and_empty"] = True
                    self.checks["reopened"] = True
                    self.finish()
                    return
                self.checks["local_media"] = True
                self.checks["rendered"] = self.viewer.canvas.frame_key is not None
                self.viewer.add_room("local:2", {"alias": "合成跨平台二路", "delay": 1.5})
                self.workers.append(self.viewer.rows["local:2"].decoder)
                self.viewer.rows["local:2"].show()
                self.viewer.rows_layout.activate()
                row = self.viewer.rows["1"]
                assert self.viewer.picture.title_badge.uname == "本地比赛直播标题"
                assert not self.viewer.picture.stream_badge.viewers
                self.viewer.picture.set_volume(67)
                assert row.volume_number.text() == "67" and row.volume.value() == 67
                self.viewer.picture.volume_button.click()
                self.viewer.render()
                assert self.viewer.picture.muted and not row.audible.isChecked()
                row.audible.setChecked(True)
                assert not self.viewer.picture.muted
                self.viewer.canvas.set_frame(None)
                self.viewer._show_buffering(True)
                assert self.viewer.canvas.waiting and self.viewer.picture._buffering
                assert not self.viewer.picture.spinner.isHidden()
                self.viewer.render()
                assert not self.viewer.canvas.waiting and not self.viewer.picture._buffering
                row.pending.append((time.monotonic() - 30, {"uname": "无牌观众", "text": "这波配合很漂亮"}))
                medal = {"name": "原粉丝团", "level": 5, "color": "#fbbf24"}
                row.pending.append((time.monotonic() - 30, {"uname": "有牌观众", "text": "携带其他主播的粉丝牌", "medal": medal}))
                self.viewer.render()
                entries = self.viewer.panel._blocks[-2:]
                assert entries[0]["uname"] == "【合成主画面】 无牌观众" and not entries[0]["medal"]
                assert "【合成主画面】" in self.viewer.panel._block_html(entries[0])
                assert entries[1]["uname"] == "【合成主画面】 有牌观众" and not entries[1]["medal"]
                self.checks["chat_badges"] = True
                self.context.window.grab().save(os.environ["MATCH_SYNC_TEST_PREVIEW"])
                row.delay.setValue(0)
                row.decrease.click()
                assert row.delay.value() == -0.1
                row.increase.click()
                assert row.delay.value() == 0
                assert not hasattr(row, "chat_delay") and row.color_choice.count() == 6
                assert self.match.entry.parentWidget() is self.context.window.sidebar.tool_row
                assert self.viewer.controls.isVisible() and not self.viewer.controls.isWindow()
                assert not hasattr(self.viewer, "start_button")
                panel = self.viewer.settings_panel
                assert self.viewer.body_split.widget(2) is panel
                assert self.viewer.main.isHidden() and panel.isAncestorOf(self.viewer.automatic)
                assert self.viewer.layout().itemAt(0).widget() is self.viewer.picture_split and self.viewer.controls.frameShape() == QFrame.NoFrame
                assert "正数" in row.increase.toolTip() and "延后本路" in row.increase.toolTip()
                assert "负数" in row.decrease.toolTip() and "相对提前本路" in row.decrease.toolTip()
                assert row.offset_hint.isVisible() and row.offset_hint.wordWrap()
                assert row.offset_hint.text() == "单位：秒 · + 正数延后本路 · − 负数相对提前本路"
                assert row.offset_hint.font().pixelSize() == 12
                assert row.offset_hint.geometry().top() > row.delay.geometry().bottom()
                assert abs(row.offset_hint.x() - row.control_widgets[8].x()) <= 1
                centers = [widget.geometry().center().y() for widget in row.control_widgets]
                assert max(centers) - min(centers) <= 1
                assert row.channel.width() == 100 and row.color_choice.width() == 82
                row.channel.setCurrentIndex(row.channel.findData(3))
                assert row.channel.currentData() == 3
                row.channel.setCurrentIndex(row.channel.findData(4))
                assert row.channel.currentData() == 4
                panel.grab().save(str(Path(os.environ["MATCH_SYNC_TEST_PREVIEW"]).with_name("match-sync-controls-preview.png")))
                assert not panel.isWindow() and not hasattr(panel, "detach")
                rendered = panel.grab().toImage()
                assert rendered.pixelColor(0, 0).alpha() == 0
                scale = rendered.devicePixelRatio()
                y = int(2 * scale)
                for x in (int(3 * scale), rendered.width() - 1 - int(3 * scale)):
                    assert rendered.pixelColor(x, y).alpha() > 180
                    assert rendered.pixelColor(x, rendered.height() - 1 - y).alpha() == 0
                assert row.control_widgets[-1].geometry().right() >= row.width() - 9
                assert self.viewer.picture_split.widget(0) is self.viewer.left_pane
                assert self.viewer.picture_split.widget(1) is self.viewer.panel
                assert self.viewer.body_split.widget(0) is self.viewer.picture
                assert self.viewer.panel.height() == self.viewer.height()
                assert panel.width() == self.viewer.picture.width()
                chat_geometry = self.viewer.panel.geometry()
                height, picture_height = panel.height(), self.viewer.picture.height()
                preferences = row.preferences()
                self.viewer.minimize_settings.click()
                QApplication.processEvents()
                assert panel.isHidden() and self.viewer.restore_settings.isVisible()
                assert self.viewer.picture.height() > picture_height
                assert self.viewer.running and row.decoder is worker
                assert self.viewer.panel.geometry() == chat_geometry
                assert self.viewer.restore_settings.parentWidget() is self.viewer.left_pane
                self.context.window.grab().save(str(Path(os.environ["MATCH_SYNC_TEST_PREVIEW"]).with_name("match-sync-minimized-preview.png")))
                self.viewer.restore_settings.click()
                QApplication.processEvents()
                assert panel.isVisible() and self.viewer.restore_settings.isHidden()
                assert abs(panel.height() - height) <= 1 and row.preferences() == preferences
                self.checks["ui_controls"] = True
                self.viewer.picture.pause_button.click()
                assert row.paused
                self.viewer.minimize_settings.click()
                self.match.button.setChecked(False)
                assert not panel.isWindow() and not panel.isVisible()
                self.match.button.setChecked(True)
                assert panel.isHidden() and self.viewer.restore_settings.isVisible()
                self.viewer.restore_settings.click()
                assert panel.isVisible()
                assert not row.paused and row.decoder is not worker
                self.workers.extend(r.decoder for r in self.viewer.rows.values())
                self.reopening = True
                self.deadline = time.monotonic() + 18
            elif time.monotonic() > self.deadline:
                self.finish("Local fixture decoding timeout")
        except Exception:
            self.finish(traceback.format_exc())

    def finish(self, error=None):
        if error:
            self.checks["error"] = error
        self.finishing = True
        if hasattr(self, "viewer"):
            self.match.button.setChecked(False)
            assert not self.viewer.running and self.viewer.isHidden()
        self.deadline = time.monotonic() + 5

    def write(self, error=None):
        if error:
            self.checks["error"] = error
        self.timer.stop()
        Path(os.environ["MATCH_SYNC_TEST_RESULT"]).write_text(json.dumps(self.checks), encoding="utf-8")
        self.context.window.close()
        QApplication.instance().quit()


plugin = Probe()
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, default=REPO / "results" / "DD监控室CE-v0.2-exe")
    parser.add_argument("--audio-device", action="store_true", help="Also play silent PCM through the default device")
    args = parser.parse_args()
    release = args.release.resolve()
    executable = release / "DD监控室CE-v0.2.exe"
    assert executable.is_file(), f"Release EXE not found: {executable}"
    with tempfile.TemporaryDirectory(prefix="ddm_match_exe_") as root:
        sandbox = Path(root).resolve()
        assert sandbox.is_relative_to(Path(tempfile.gettempdir()).resolve())
        app_dir = sandbox / "app"
        shutil.copytree(release, app_dir,
                        ignore=shutil.ignore_patterns("plugins_user", "utils", "cache", "logs", "recordings"))
        fixture = sandbox / "fixture.mkv"
        generate(recording.ffmpeg_path(), fixture)
        archive = build(sandbox / "plugin.zip")
        manager = plugins.PluginManager(plugins_dir=str(app_dir / "plugins_user"))
        manager.install_zip(str(archive))
        probe_dir = app_dir / "plugins_user" / "zz_match_probe"
        probe_dir.mkdir()
        (probe_dir / "plugin.py").write_text(PROBE, encoding="utf-8")
        (app_dir / "utils").mkdir()
        (app_dir / "utils" / "config.json").write_text(json.dumps({
            "version": 1, "rooms": [], "wall": [], "layout": "1x1", "plugins_enabled": None,
            "settings": {"recording_enabled": False, "recording_replay_enabled": False}}), encoding="utf-8")
        result = sandbox / "probe.json"
        preview = REPO / "work" / "match-sync-exe-preview.png"
        preview.parent.mkdir(exist_ok=True)
        environment = dict(os.environ, DDM_NO_SAVE="1", QT_QPA_PLATFORM="windows",
                           MATCH_SYNC_TEST_MEDIA=str(fixture), MATCH_SYNC_TEST_RESULT=str(result),
                           MATCH_SYNC_TEST_PREVIEW=str(preview),
                           MATCH_SYNC_TEST_AUDIO="1" if args.audio_device else "0",
                           PYTHON_VLC_LIB_PATH=str(app_dir / "_internal" / "libvlc.dll"))
        process = subprocess.Popen([str(app_dir / executable.name)], cwd=app_dir, env=environment,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise AssertionError("Frozen EXE test did not finish")
        assert result.is_file(), f"EXE produced no probe result (exit {process.returncode})"
        checks = json.loads(result.read_text(encoding="utf-8"))
        required = ["loaded", "local_media", "rendered", "cleaned", "ui_controls", "chat_badges", "reopened", "platform_and_empty"]
        if args.audio_device:
            required.append("audio_device")
        assert process.returncode == 0 and all(checks.get(key) for key in required) and "error" not in checks, {
            **checks, "exit_code": process.returncode}
        print("PASS: existing v0.2 EXE loads disk plugin helpers and Qt audio module, decodes local video/PCM, renders and cleans workers")
        if args.audio_device:
            print("PASS: frozen Qt audio output consumes silent mixed PCM and advances the common playback clock")
        print(f"Preview: {preview}")


if __name__ == "__main__":
    main()
