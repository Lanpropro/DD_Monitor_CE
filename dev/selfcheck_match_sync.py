"""Deterministic plugin checks; optional silent device test, no account/network."""
import os
from pathlib import Path
import random
import sys
import tempfile
import time
from array import array
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QWidget  # noqa: E402
from ddm import plugins  # noqa: E402
from dev.build_match_sync import build  # noqa: E402
from plugins_user._match_sync.engine import (Alignment, AudioRing, History,
    Match, RATE, Sample, match_scenes, mix_pcm)  # noqa: E402
from plugins_user._match_sync.media import Events, fingerprint  # noqa: E402


def engine_checks():
    randomizer = random.Random(1947)
    samples = [Sample(100 + i * 0.5, randomizer.getrandbits(128), 20) for i in range(36)]
    delayed = [Sample(s.time + 5.3, s.signature, s.texture) for s in samples]
    match = match_scenes(samples, delayed)
    assert match.lag is not None and abs(match.lag - 5.3) < 0.001, match
    assert match.confidence > 0.8
    earlier = [Sample(s.time - 4.2, s.signature ^ ((1 << 8) - 1), s.texture) for s in samples]
    assert abs(match_scenes(samples, earlier).lag + 4.2) < 0.001
    assert match_scenes(samples[:5], delayed).lag is None
    unrelated = [Sample(s.time, randomizer.getrandbits(128), 20) for s in samples]
    assert match_scenes(samples, unrelated).lag is None
    flat = [Sample(100 + i * 0.5, 0, 0) for i in range(40)]
    assert match_scenes(flat, flat).lag is None
    still = [Sample(100 + i * 0.5, samples[0].signature, 20) for i in range(40)]
    assert match_scenes(still, still).lag is None
    repeated = [Sample(100 + i * 0.5, samples[i % 16].signature, 20) for i in range(64)]
    assert match_scenes(repeated, repeated).lag is None, "Repeated replay must be ambiguous"

    alignment = Alignment()
    alignment.select_reference("1")
    assert not alignment.accept("2", Match(5, 1, "ok"))
    assert alignment.accept("2", Match(5.2, 1, "ok"))
    shifts = alignment.shifts({"1": 0, "2": 0})
    assert abs(shifts["1"] + 7.2) < 0.001 and shifts["2"] == -2
    assert alignment.shifts({"1": 3, "2": 0})["1"] == shifts["1"] - 3
    alignment.select_reference("2")
    assert alignment.shifts({"1": 0, "2": 0}) == shifts, "Changing main picture keeps the same shared content"
    alignment.automatic = False
    assert alignment.shifts({"1": 3, "2": 0}) == {"1": -5, "2": -2}

    ring = AudioRing(seconds=4 / RATE)
    ring.append(array("h", [100, -100, 200, -200, 300, -300]).tobytes())
    assert list(array("h", ring.read(-1, 5))) == [0, 0, 100, -100, 200, -200, 300, -300, 0, 0]
    ring.append(array("h", [400, -400, 500, -500, 600, -600]).tobytes())
    assert list(array("h", ring.read(0, 6))) == [0, 0, 0, 0, 300, -300, 400, -400, 500, -500, 600, -600]
    ring.append(array("h", [700, -700] * 6).tobytes())
    assert list(array("h", ring.read(6, 6))) == [0, 0] * 2 + [700, -700] * 4
    try:
        ring.append(b"bad")
    except ValueError:
        pass
    else:
        raise AssertionError("Incomplete PCM frames must be rejected")

    pcm = array("h", [12000, -12000] * 4).tobytes()
    assert list(array("h", mix_pcm([(pcm, 50)], 4))) == [6000, -6000] * 4
    assert mix_pcm([(pcm, 0)], 4) == bytes(16)
    assert mix_pcm([(pcm, 100), (pcm, 100)], 4) == pcm, "Headroom prevents duplicated match audio from clipping"
    assert mix_pcm([], 4) == bytes(16)

    history = History(seconds=2, byte_limit=6)
    history.append(10, b"aaa", Sample(10, 1, 10))
    history.append(11, b"bbb", Sample(11, 2, 10))
    history.append(12, b"ccc", Sample(12, 3, 10))
    assert history.byte_size == 6 and history.frame_at(10) is None
    assert history.frame_at(11.5) == (11, b"bbb")
    assert history.frame_at(14) is None
    history.append(15, b"ddd", Sample(15, 4, 10))
    assert list(history.frames) == [(15, b"ddd")]
    assert len(history.snapshots()) == 1
    print("PASS: matching sign, ambiguity rejection, stable offsets, audio ring, gain and bounded history")


def jpeg():
    image = QImage(90, 90, QImage.Format_RGB32)
    for y in range(90):
        for x in range(90):
            image.setPixelColor(x, y, QColor(x * 2, y * 2, (x + y) % 255))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "JPEG")
    return bytes(buffer.data())


class FakeDecoder:
    def __init__(self, room_id, seed=None):
        self.events = Events()
        self.history = History()
        self.seed = seed
        self.stopped = False
        self.crop = None

    def set_crop(self, crop):
        self.crop = crop

    def start(self):
        pass

    def stop(self):
        self.stopped = True


class FakeChat:
    def __init__(self, room_id):
        self.events = Events()
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True


class FakeTile:
    def __init__(self, room_id):
        self.room = {"room_id": room_id, "muted": False}
        self.muted = False


class FakePlayer:
    _released = False

    def __init__(self):
        self.muted = False

    def set_muted(self, value):
        self.muted = bool(value)


class FakeSink:
    def __init__(self):
        self.free = 480 * 4

    def bytesFree(self):
        return self.free

    def stop(self):
        pass

    def deleteLater(self):
        pass


class FakeDevice:
    def __init__(self, sink):
        self.sink = sink
        self.data = b""

    def write(self, data):
        self.data += bytes(data)
        self.sink.free -= len(data)
        return len(data)


def package_and_ui_checks(app):
    with tempfile.TemporaryDirectory(prefix="ddm_match_sync_") as root:
        archive = build(Path(root) / "plugin.zip")
        host = QWidget()
        host.settings = {}
        participating, unrelated = FakeTile("1"), FakeTile("3")
        host.players = {participating: FakePlayer(), unrelated: FakePlayer()}
        manager = plugins.PluginManager(window=host, plugins_dir=str(Path(root) / "plugins"))
        assert manager.install_zip(str(archive)) == "match_sync"
        manager.load()
        assert len(manager.plugins) == 1
        assert manager.catalog()[0]["version"] == "0.1.3"
        assert manager.plugin_settings == {}, "Loading the plugin must not write defaults"
        plugin = manager.plugins[0]
        manager.emit(plugins.EVENT_STREAM_RESOLVED,
                     source=plugins.StreamSource("1", "http://127.0.0.1:9/fake.flv", headers={"X-Test": "preserved"}, uname="主播甲"),
                     tile=participating)
        assert plugin.sources["1"]["headers"] == {"X-Test": "preserved"}
        assert manager.tile_actions(participating)[0][0] == "比赛二路同步…"
        assert not plugin.tile_actions(FakeTile("other:1"))
        module = sys.modules["ddm_plugin_match_sync.viewer"]
        assert module.parse_room("https://live.bilibili.com/00042?from=share") == "42"
        assert module.parse_room("https://live.bilibili.com/h5/42/") == "42"
        for invalid in ("0", "https://example.com/42", "https://live.bilibili.com/no", "https://evil.live.bilibili.com/42"):
            try:
                module.parse_room(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError(invalid)
        with patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
                patch.object(module.AudioPump, "start", lambda self: None):
            plugin.open_viewer({"room_id": "1", "uname": "主播甲"})
            viewer = plugin.viewer
            assert viewer.add_room("2", {"alias": "主播乙"})
            assert not viewer.add_room("2")
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            clock = [100.0]
            viewer.audio.clock = lambda: clock[0]
            viewer.audio.sink = FakeSink()
            image = jpeg()
            signature, texture = fingerprint(image)
            assert 0 <= signature < (1 << 128) and texture > 0
            for row in viewer.rows.values():
                for timestamp in range(94, 100):
                    row.decoder.history.append(timestamp, image)
            row_a, row_b = viewer.rows["1"], viewer.rows["2"]
            row_a.delay.setValue(3)
            for row in (row_a, row_b):
                row.volume.setValue(100)
                for value in range(1, 7):
                    row.decoder.history.audio.append(array("h", [value * 1000, value * 1000] * RATE).tobytes())
            viewer.audio.device = FakeDevice(viewer.audio.sink)
            viewer.audio.anchor = 100
            viewer.audio.fill()
            assert set(array("h", viewer.audio.device.data)) == {3500}, "Audio must use the same per-room delayed timeline as video and chat"
            row_a.channel.setCurrentIndex(row_a.channel.findData(3))
            row_b.channel.setCurrentIndex(row_b.channel.findData(4))
            viewer.audio.sink.free = 480 * 4
            viewer.audio.device.data = b""
            viewer.audio.written = 0
            viewer.audio.fill()
            routed = array("h", viewer.audio.device.data)
            assert set(routed[::2]) == {1000} and set(routed[1::2]) == {2500}
            row_a.channel.setCurrentIndex(0)
            row_b.channel.setCurrentIndex(0)
            row_a.pending.append((96, {"uname": "A", "text": "甲延后"}))
            row_b.pending.append((96, {"uname": "B", "text": "乙即时"}))
            viewer.render()
            assert viewer.canvas.frame_key == 95
            assert viewer.panel._blocks[-1]["uname"] == "[主播乙] B"
            assert len(row_a.pending) == 1
            assert host.players[participating].muted and not host.players[unrelated].muted
            assert participating.room["muted"] is False and participating.muted is False
            clock[0] = 104
            viewer.render()
            assert viewer.panel._blocks[-1]["uname"] == "[主播甲] A"
            row_b.show_chat.setChecked(False)
            viewer._message(row_b, row_b.chat, {"text": "hidden"})
            assert not row_b.pending
            viewer.main.setCurrentIndex(viewer.main.findData("2"))
            assert viewer.alignment.reference == "2"
            assert viewer.picture.room["room_id"] == "2"
            viewer.picture.set_volume(65)
            assert row_b.volume.value() == 65
            viewer.picture.set_muted(True)
            assert not row_b.audible.isChecked()
            viewer.picture.set_muted(False)
            viewer.picture.set_audio_channel(3)
            assert row_b.channel.currentData() == 3
            viewer.picture.pause_button.click()
            assert row_b.paused
            viewer.picture.pause_button.click()
            assert not row_b.paused
            previous_decoder = row_b.decoder
            viewer.picture.set_quality(80)
            assert previous_decoder.stopped and row_b.decoder.seed["quality"] == 80
            assert not hasattr(row_a, "chat_delay")
            row_a.delay.setValue(0)
            row_a.decrease.click()
            assert row_a.delay.value() == -0.1
            row_a.increase.click()
            assert row_a.delay.value() == 0
            row_a.increase.click()
            assert row_a.delay.value() == 0.1
            assert row_a.color_choice.count() == len(module.COLORS)
            row_a.color_choice.setCurrentIndex(3)
            assert row_a.color == module.COLORS[3]
            viewer.save()
            saved = manager.plugin_settings["match_sync"]
            assert saved["main_room"] == "2" and "chat_delay" not in saved["rooms"][0]
            reopened = module.Viewer(plugin.context, plugin.sources)
            assert not reopened.rows and reopened.main.count() == 0, "Restart must not rejoin previous rooms"
            reopened.add_room("99", {"alias": "新加入主播"})
            assert list(reopened.rows) == ["99"] and reopened.main.currentData() == "99"
            reopened.close()
            # Large bursts remain queued instead of disappearing after a UI budget.
            row_a.pending.extend((95, {"uname": "A", "text": str(i)}) for i in range(210))
            before = len(row_a.pending)
            viewer.render()
            assert len(row_a.pending) == before - 80
            old_decoder, old_chat = row_a.decoder, row_a.chat
            participating.muted = True
            viewer.stop()
            assert old_decoder.stopped and old_chat.stopped
            assert host.players[participating].muted, "Restore current host mute preference"
            viewer._message(row_a, old_chat, {"text": "late"})
            assert not row_a.pending
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            viewer.audio.sink = FakeSink()
            viewer.render()
            player = host.players[participating]
            new_owner = FakeTile("3")
            host.players.pop(participating)
            host.players[new_owner] = player
            viewer.stop()
            assert not player.muted, "Restore the player's current tile after a host swap"
            viewer.remove_room("2")
            assert viewer.alignment.reference == "1"
            plugin.on_unload()
        manager.unload()
        host.close()
        app.processEvents()
    print("PASS: ZIP install, disk helper imports, optional menu, labelled delayed chat, main choice, controls and cleanup")


def embedded_checks(app):
    from plugins_user._match_sync.plugin import MatchSyncPlugin
    module = sys.modules[MatchSyncPlugin.__module__ + ".viewer"]
    from ddm.widgets import ROOM_MIME
    host = QMainWindow()
    host._content = QWidget()
    host.setCentralWidget(host._content)
    host.wall = QWidget(host._content)
    host.wall.show()
    host.settings = {}
    host.players = {}
    host.sidebar = QWidget()
    host.sidebar.tool_row = QWidget(host.sidebar)
    QHBoxLayout(host.sidebar.tool_row)
    host.rooms = [{"room_id": "42", "uname": "关注主播"}]
    host.resize(1200, 900)
    manager = plugins.PluginManager(window=host)
    context = plugins.PluginContext(manager, "match_sync_embedded_test")
    plugin = MatchSyncPlugin()
    plugin.on_load(context)
    assert plugin.entry.parentWidget() is host.sidebar.tool_row
    assert plugin.button is not None and not plugin.tile_actions(FakeTile("42"))
    with patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda self: None):
        host.show()
        plugin.button.trigger()
        viewer = plugin.viewer
        app.processEvents()
        assert viewer.embedded and viewer.parentWidget() is host._content
        assert host.wall.isHidden(), "Native host video must not cover the synced picture"
        host.wall.show()
        assert host.wall.isHidden(), "Host refresh must not expose native video during match mode"
        assert not viewer.isWindow() and not viewer.running
        assert all(widget.isHidden() for widget in viewer.add_controls)
        mime = QMimeData()
        mime.setData(ROOM_MIME, b"42")
        enter = QDragEnterEvent(QPoint(100, 100), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(viewer, enter)
        assert enter.isAccepted()
        drop = QDropEvent(QPointF(100, 100), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(viewer, drop)
        assert drop.isAccepted() and viewer.running and viewer.rows["42"].label() == "关注主播"
        mime.setData(ROOM_MIME, b"43")
        enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(viewer.panel, enter)
        drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(viewer.panel, drop)
        assert "43" in viewer.rows and viewer.rows["43"].decoder is not None
        assert not viewer.panel.body.acceptDrops() and not viewer.panel.body.viewport().acceptDrops()
        assert viewer.controls.isVisible() and viewer.body_split.widget(1) is viewer.controls
        assert not hasattr(viewer, "start_button") and not hasattr(viewer, "controls_button")
        for room_id in range(44, 51):
            viewer.add_room(str(room_id), {"alias": "额外主播"})
        before = viewer.canvas.geometry()
        app.processEvents()
        assert viewer.controls.isVisible() and len(viewer.rows) == 9
        assert viewer.canvas.geometry() == before
        assert viewer.controls.height() <= 240 and not viewer.controls.isWindow()
        assert all("42" not in viewer.main.itemText(i) for i in range(viewer.main.count()))
        worker = viewer.rows["42"].decoder
        host.resize(1400, 950)
        app.processEvents()
        assert viewer.geometry() == host._content.rect()
        plugin.button.trigger()
        assert viewer.isHidden() and not viewer.running and worker.stopped
        assert not host.wall.isHidden()
        assert host.centralWidget() is host._content
        plugin.button.trigger()
        viewer.rows["42"].paused = True
        plugin.button.trigger()
        plugin.button.trigger()
        assert not viewer.rows["42"].paused
        assert viewer.running and not viewer.isHidden()
        viewer.close()
        assert not plugin.button.isChecked() and not viewer.running
        plugin.on_unload()
        assert plugin.entry is None
    host.close()
    app.processEvents()
    print("PASS: independent button, embedded view, sidebar MIME drop, automatic start, resizing and original view restoration")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    engine_checks()
    package_and_ui_checks(app)
    embedded_checks(app)
    if "--audio-device" in sys.argv:
        from plugins_user._match_sync.viewer import Viewer
        host = QWidget()
        host.settings = {}
        host.players = {}
        manager = plugins.PluginManager(window=host)
        context = plugins.PluginContext(manager, "match_sync_audio_test")
        viewer = Viewer(context, {})
        viewer.running = True
        viewer.audio.start()
        assert viewer.audio.sink is not None, viewer.audio_status.text()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and viewer.audio.sink.processedUSecs() < 200000:
            app.processEvents()
            time.sleep(0.005)
        assert viewer.audio.sink is not None and viewer.audio.sink.processedUSecs() >= 200000
        assert viewer.audio.written > 0 and viewer.audio.clock() > viewer.audio.anchor
        previous = viewer.audio.sink
        viewer.audio.device_id = b"simulate-device-change"
        viewer.audio._device_changed()
        assert viewer.audio.sink is not None and viewer.audio.sink is not previous
        viewer.close()
        host.close()
        app.processEvents()
        print("PASS: default Qt audio device consumes silent mix, advances clock and rebuilds output safely")
    print("PASS: match-sync selfcheck")


if __name__ == "__main__":
    main()
