"""回归自检：格子之间的音量/静音必须互不影响（录制最容易触发这条）。

用户报的：录了一路之后，静音的格子开始出声、有声的格子声音断了。

查出来的链路（work/probe_record_audio*.py 一路复现过来）：
  1. `audio_set_mute` / `audio_set_volume` 在该 player 的 **aout 还没建好**时调用，
     写进去的是 **VLC 实例级默认值**，之后每个 player 建 aout 都会继承它；
  2. 更狠的是：**只要有一个 player stop→play 重启过**，之后它再下发音量（0 也好、
     1 也好，任何值），都会落到**共享的 aout** 上，把同实例里别的格子一起改掉。
     录制「锁定原画」正好会重启那一格（start_tile），所以录完就开始串。
  3. 于是巡检来回下发、两个格子交替翻转 —— 用户听到的就是「静音的格子出声、
     有声的格子断续」。

修法：所有格子一律走 **PCM 回调**（每个 TilePlayer 自己的 StereoOutput），
音量/静音在样本上自己算，完全不碰 VLC 的共享 aout。

这里钉住：重启任意一格（含静音的那格）之后，另一格的输出状态不许被动到。
"""
import os
import struct
import sys
import time
import wave
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QWidget

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("PYTHON_VLC_LIB_PATH", os.path.join(REPO, "libvlc.dll"))

from ddm.audio_output import StereoOutput  # noqa: E402
from ddm.player import TilePlayer  # noqa: E402

WAV = os.path.join(os.environ.get("TEMP") or REPO, "ddm_audio_isolation.wav")
RATE = 48_000
FAIL: list = []


class FakeStream:
    """顶掉 sounddevice 的输出流：自检不出声，只记有没有东西被写进来。"""

    def __init__(self):
        self.active = False
        self.writes = 0

    def start(self):
        self.active = True

    def write(self, _data):
        self.writes += 1

    def stop(self):
        self.active = False

    def abort(self):
        self.active = False

    def close(self):
        pass


def make_wav() -> None:
    with wave.open(WAV, "wb") as handle:
        handle.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
        handle.writeframes(struct.pack("<hh", 6000, -6000) * RATE)


def settle(app, seconds: float = 0.6) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def start(player) -> None:
    """模拟 start_tile：先下发音量/静音，再走真实入口 play()。"""
    player.set_volume(player.volume)
    player.set_muted(player.muted)
    player.play(WAV)


def check(tag: str, first, second) -> None:
    a, b = first._audio_output, second._audio_output          # noqa: SLF001
    ok = (a.enabled == (not first.muted) and a.volume == first.volume
          and b.enabled == (not second.muted) and b.volume == second.volume)
    print(f"  {tag}")
    print(f"    A(静音): muted={first.muted} pcm={first.uses_pcm_routing} "
          f"输出enabled={a.enabled} 输出音量={a.volume}")
    print(f"    B(有声): muted={second.muted} pcm={second.uses_pcm_routing} "
          f"输出enabled={b.enabled} 输出音量={b.volume}")
    print(f"    → {'两边都对 ✓' if ok else '串了 ✗'}")
    if not ok:
        FAIL.append(tag)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    make_wav()
    app = QApplication(sys.argv)
    streams: list = []
    original = StereoOutput._new_stream                     # noqa: SLF001

    def factory(_self):
        stream = FakeStream()
        streams.append(stream)
        return stream

    first = TilePlayer(QWidget())
    second = TilePlayer(QWidget())
    first.volume, first.muted = 80, True          # A：静音
    second.volume, second.muted = 50, False       # B：有声
    try:
        with patch.object(StereoOutput, "_new_stream", factory):
            start(first)
            start(second)
            settle(app, 1.4)
            check("初始：A 静音、B 有声", first, second)
            assert first.uses_pcm_routing and second.uses_pcm_routing, \
                "所有格子都该走 PCM 回调（不再用 VLC 的共享 aout）"

            print("\n--- 重启 B（录制锁原画会这么做）---")
            second.stop()
            settle(app, 0.4)
            start(second)
            settle(app, 1.4)
            check("重启 B 之后", first, second)

            print("\n--- 重启 A（静音的那格，最容易污染邻居）---")
            first.stop()
            settle(app, 0.4)
            start(first)
            settle(app, 1.4)
            check("重启 A 之后", first, second)

            print("\n--- 交替翻转 A 的静音 3 次 ---")
            for index in range(3):
                first.set_muted(not first.muted)
                settle(app, 0.4)
                check(f"第{index + 1}次翻转 A", first, second)
            first.set_muted(True)                 # 复原成静音
            settle(app, 0.4)

            print("\n--- 稳定复查 3 次 ---")
            for index in range(3):
                settle(app, 0.4)
                check(f"第{index + 1}次", first, second)
    finally:
        with patch.object(StereoOutput, "_new_stream", original):
            for player in (first, second):
                try:
                    player.release()
                except Exception:  # noqa: BLE001
                    pass
        try:
            os.remove(WAV)
        except OSError:
            pass
    assert not FAIL, f"格子之间仍然串音：{FAIL}"
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
