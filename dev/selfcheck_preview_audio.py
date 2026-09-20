"""回归自检：预览（silent）播放器不碰任何 libvlc 音频接口。

预览用的是 ``--no-audio`` 实例（``PlayerPool.preview_instance()``），根本没有
音频输出模块（aout）。对这个不存在的 aout 调 set_track / set_mute / set_volume /
get_*，在用户机器上就是一次 access violation —— ``logs/ddm-2026-09-20.log`` 里
「[预览音频] mute=-1 …」之后紧跟 ``Windows fatal exception: access violation``。

这里钉住两条不变量：
1. silent 播放器的 ``set_muted`` / ``set_volume`` / ``_ensure_audio_settings``
   都不能触达 libvlc 的 ``audio_*`` 调用；
2. ``ddm/player.py`` 里不再有 ``audio_set_track``（它正是崩溃触发点）。
"""
import os
import sys

from PySide6.QtWidgets import QApplication, QWidget

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.player import TilePlayer  # noqa: E402


class AudioBomb:
    """替身播放器：任何 audio_* 调用都算失败（silent 播放器应该全部跳过）。"""

    def __getattr__(self, name):
        if name.startswith("audio_"):
            def _boom(*_args, **_kwargs):
                raise AssertionError(f"silent 播放器不该调 {name}")
            return _boom
        raise AttributeError(name)


class VideoRecorder:
    """替身播放器：只记录 stop / set_hwnd，验证 stop() 会把画面摘掉再收工。"""

    def __init__(self):
        self.stopped = False
        self.hwnd_calls: list = []
        self.events: list = []
        self.released = False

    def stop(self):
        self.stopped = True
        self.events.append("stop")

    def set_hwnd(self, hwnd):
        self.hwnd_calls.append(hwnd)
        self.events.append(f"set_hwnd({hwnd})")

    def release(self):
        self.released = True
        self.events.append("release")


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)

    print("=== 1. silent 播放器的静音/音量只改本地状态，不碰 libvlc 音频 ===")
    silent = TilePlayer(QWidget(), silent=True)
    silent.player = AudioBomb()
    silent.set_muted(True)
    silent.set_volume(0)
    assert silent.muted is True and silent.volume == 0, \
        "silent 播放器仍然要记住静音/音量状态（只是不下发到 libvlc）"
    print(f"  muted={silent.muted} volume={silent.volume}（没碰 audio_set_mute/volume）")

    print("\n=== 2. _ensure_audio_settings 对 silent 直接跳过 ===")
    silent._audio_ready = False            # noqa: SLF001
    silent._ensure_audio_settings()        # noqa: SLF001
    assert silent._audio_ready is True, "silent 播放器应把 aout 补丁标记为已完成"
    print("  _ensure_audio_settings 没碰音频，且已钉住 _audio_ready")

    print("\n=== 3. 源码钉住：player.py 不再有 audio_set_track ===")
    import io as _io
    src = _io.open(os.path.join(REPO, "ddm", "player.py"), encoding="utf-8").read()
    assert "audio_set_track" not in src, \
        "audio_set_track(-1) 在 --no-audio 实例上会 access violation，别再回来"

    print("\n=== 4. stop() 先把画面摘掉再收工（widget 隐藏前 set_hwnd(0)）===")
    # 预览反复 stop/play，widget 会在 stop 后立刻隐藏；VLC 还绑在那个 HWND 上
    # 就可能在用户机器上 access violation。钉住：stop() 要先 set_hwnd(0) 再重置绑定。
    silent2 = TilePlayer(QWidget(), silent=True)
    rec = VideoRecorder()
    silent2.player = rec
    silent2._bound = True          # noqa: SLF001
    silent2._bound_hwnd = 12345    # noqa: SLF001
    silent2.stop()
    assert rec.stopped is True, "stop() 要真的停掉播放"
    assert 0 in rec.hwnd_calls, "stop() 要在 widget 隐藏前 set_hwnd(0) 摘掉画面"
    assert rec.events[:2] == ["set_hwnd(0)", "stop"], \
        f"必须先摘 HWND 再进 libvlc_media_player_stop，实际顺序={rec.events}"
    assert silent2._bound is False, "stop() 后要重置绑定，下次 play 重新 bind"  # noqa: SLF001
    print(f"  调用顺序={rec.events}，并已重置绑定")

    print("\n=== 5. release() 也要先摘画面，再 stop / release ===")
    silent3 = TilePlayer(QWidget(), silent=True)
    rec = VideoRecorder()
    silent3.player = rec
    silent3._bound = True          # noqa: SLF001
    silent3._bound_hwnd = 54321    # noqa: SLF001
    silent3.release()
    assert rec.events == ["set_hwnd(0)", "stop", "release"], \
        f"释放时必须先摘 HWND，实际顺序={rec.events}"
    assert silent3._bound is False and silent3._bound_hwnd == 0  # noqa: SLF001
    print(f"  调用顺序={rec.events}")

    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
