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
import traceback
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from ddm import bili, plugins as api


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
            match = next(p for p in context.manager.plugins if p.context.name == "match_sync")
            self.match = match
            match.sources["1"] = {"url": os.environ["MATCH_SYNC_TEST_MEDIA"], "headers": {}, "uname": "合成主画面"}
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
                    self.checks["reopened"] = True
                    self.finish()
                    return
                self.checks["local_media"] = True
                self.checks["rendered"] = self.viewer.canvas.frame_key is not None
                self.viewer.add_room("2", {"alias": "合成二路", "delay": 1.5})
                self.workers.append(self.viewer.rows["2"].decoder)
                self.viewer.rows["2"].show()
                self.viewer.rows_layout.activate()
                self.context.window.grab().save(os.environ["MATCH_SYNC_TEST_PREVIEW"])
                row = self.viewer.rows["1"]
                row.delay.setValue(0)
                row.decrease.click()
                assert row.delay.value() == -0.1
                row.increase.click()
                assert row.delay.value() == 0
                assert not hasattr(row, "chat_delay") and row.color_choice.count() == 6
                assert self.match.entry.parentWidget() is self.context.window.sidebar.tool_row
                assert self.viewer.controls.isVisible() and not self.viewer.controls.isWindow()
                assert not hasattr(self.viewer, "start_button")
                row.channel.setCurrentIndex(row.channel.findData(3))
                assert row.channel.currentData() == 3
                row.channel.setCurrentIndex(row.channel.findData(4))
                assert row.channel.currentData() == 4
                self.viewer.controls.grab().save(str(Path(os.environ["MATCH_SYNC_TEST_PREVIEW"]).with_name("match-sync-controls-preview.png")))
                self.checks["ui_controls"] = True
                self.viewer.picture.pause_button.click()
                assert row.paused
                self.match.button.setChecked(False)
                self.match.button.setChecked(True)
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
        required = ["loaded", "local_media", "rendered", "cleaned", "ui_controls", "reopened"]
        if args.audio_device:
            required.append("audio_device")
        assert process.returncode == 0 and all(checks.get(key) for key in required) and "error" not in checks, {
            **checks, "exit_code": process.returncode, "stderr_tail": process.stderr[-1500:]}
        print("PASS: existing v0.2 EXE loads disk plugin helpers and Qt audio module, decodes local video/PCM, renders and cleans workers")
        if args.audio_device:
            print("PASS: frozen Qt audio output consumes silent mixed PCM and advances the common playback clock")
        print(f"Preview: {preview}")


if __name__ == "__main__":
    main()
