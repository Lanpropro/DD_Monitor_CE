"""真实 VLC 回调：1+5 换位、静音转有声不能提前播放 PCM。"""
import os
import struct
import sys
import tempfile
import threading
import time
import wave
from unittest.mock import patch

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import app as app_module
from ddm.app import MainWindow
from ddm.audio_output import StereoOutput
from ddm.player import TilePlayer
import vlc


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, *args):
        super().__init__(args[-1])

    def run(self):
        pass


class TimedPlayer(TilePlayer):
    def __init__(self, widget):
        super().__init__(widget)
        self.callback_pts = 0
        self.leads = []

    def _play_audio(self, opaque, samples, count, pts):
        self.callback_pts = pts
        super()._play_audio(opaque, samples, count, pts)


class Sink:
    def __init__(self, owner):
        self.owner = owner
        self.active = False

    def start(self):
        self.active = True

    def write(self, pcm):
        self.owner.leads.append((self.owner.callback_pts - vlc.libvlc_clock()) / 1000)
        # 模拟阻塞设备的样本消耗；不播放声音。
        time.sleep(len(pcm) / (48_000 * 4))

    def stop(self):
        self.active = False

    abort = stop
    close = stop


def settle(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def main():
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication([])
    rooms = [{"room_id": str(1000 + i), "live": False, "volume": 40,
              "muted": i != 0} for i in range(6)]
    window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="corner",
                        state={"plugins_enabled": []})
    window.start_tile = lambda _tile: None  # 本地媒体已就绪，不启动真实取流。
    window.show()
    players = []
    with tempfile.TemporaryDirectory(prefix="ddm_audio_timing_") as directory:
        path = os.path.join(directory, "timing.wav")
        with wave.open(path, "wb") as audio:
            audio.setparams((2, 2, 48_000, 0, "NONE", "not compressed"))
            audio.writeframes(struct.pack("<hh", 500, -500) * 48_000 * 12)
        try:
            for tile in window.wall.tiles:
                tile.room["live"] = True
                player = TimedPlayer(tile.video)
                player._audio_output = StereoOutput(lambda p=player: Sink(p))
                window.players[tile] = player
                players.append(player)
                player.freeze_watch = False  # WAV 无视频，不触发画面停滞重试。
                player.set_muted(tile.muted)
                player.play(path)
            settle(app, 1)
            for iteration in range(5):
                for player in players:
                    player.leads.clear()
                assert window._hot_swap(window.wall.tiles[0], window.wall.tiles[iteration + 1])
                settle(app, 0.5)
                audible = window.players[window.wall.tiles[0]]
                assert not audible.muted and audible.leads, "换位后必须有声音样本"
                lead = max(audible.leads)
                print(f"swap {iteration + 1}: maximum audio lead {lead:.1f} ms", flush=True)
                assert lead < 35, "PCM 在预定播放时间前输出，导致声音早于画面"
            player = players[0]
            player.set_muted(False)
            started = time.monotonic()
            player.set_paused(True)
            assert time.monotonic() - started < 0.5, "暂停不能等待未来样本"
            settle(app, 0.2)
            player.leads.clear()
            player.set_paused(False)
            settle(app, 0.6)
            assert player.leads and max(player.leads) < 35, "恢复播放仍须遵守时间戳"
            # 等待未来时间戳时，停止必须及时取消，不能卡住 GUI。
            done = threading.Event()
            worker = threading.Thread(target=lambda: (
                player._play_audio(None, 0, 1, vlc.libvlc_clock() + 5_000_000), done.set()))
            worker.start()
            time.sleep(0.05)
            started = time.monotonic()
            player.stop()
            worker.join(0.5)
            assert done.is_set() and time.monotonic() - started < 0.5
        finally:
            window.close()
            settle(app, 0.2)
    print("PASS: real VLC timestamps, repeated hot swaps and cancellable stop")


if __name__ == "__main__":
    main()
