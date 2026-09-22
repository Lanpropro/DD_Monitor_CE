"""回归自检：音量 / 静音 / 声道到底跟着谁走。

用户报的两件事：
  1. 开这一格的静音，旁边格子的声音也不对了（但那格的静音标志还亮着）；
  2. 声音应该跟着**格子**，不该跟着画面（主播）走。

根因：音量、静音、声道这几个回调以前都用 ``_tile_of(room_id)`` 反查格子。
同一个直播间占两个格子时（配置里存重了、或同一张卡片被拖上两次），反查只会
命中列表里第一个 —— 于是「静音这一格」静音了另一格，这一格反倒还在出声，
而标志画在自己身上、照样亮着。现在改成用信号来源（``_sender_tile()``）定位。

这里钉住四件事：
  1. 静音一格不波及其他格；
  2. 同一个直播间占两格时，静音只影响**操作的那一格**；
  3. 秒切（两格互换）后，音量 / 静音留在**位置**上，不跟着主播跑；
  4. 换台时音量 / 静音 / **声道**都留在格子上（声道以前会被新房间覆盖）。
"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


class FakeVlc:
    """假 media_player：只回答静音 / 音量，用来制造「走散」。"""

    def __init__(self):
        self.mute = 0
        self.volume = 0

    def audio_get_mute(self):
        return self.mute

    def audio_get_volume(self):
        return self.volume


class FakePlayer:
    """只记调用，不碰真实 libvlc（自检不联网）。"""

    silent = False
    uses_pcm_routing = False
    _released = False

    def __init__(self, tag: str):
        self.tag = tag
        self.calls: list = []
        self.volume = 0
        self.muted = False
        self.audio_channel = 0
        self.player = FakeVlc()

    def set_volume(self, value):
        self.calls.append(("volume", int(value)))
        self.volume = int(value)

    def set_muted(self, muted):
        self.calls.append(("mute", bool(muted)))
        self.muted = bool(muted)

    def set_audio_channel(self, channel):
        self.calls.append(("channel", int(channel)))
        self.audio_channel = int(channel)

    def reapply_audio_channel(self):
        pass

    def stop(self):
        pass

    def release(self):
        pass


def settle(app, seconds: float = 0.2) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": f"93{index:02d}", "uname": f"主播{index}", "title": "t",
              "live": False, "muted": False, "volume": 40 + index * 10}
             for index in range(1, 5)]
    window = MainWindow([dict(room) for room in rooms],
                        [dict(room) for room in rooms],
                        layout_id="2x2", state={})
    window.setGeometry(-9000, -9000, 1200, 700)
    window.show()
    settle(app, 0.5)
    try:
        for tile in window.wall.tiles:
            tile.room["live"] = True
            window.players[tile] = FakePlayer(str(tile.room.get("room_id")))

        print("=== 1. 静音一格：别的格子和它们的播放器都不该动 ===")
        for tile in window.wall.tiles:
            window.players[tile].calls.clear()
        second = window.wall.tiles[1]
        second.set_muted(True)
        settle(app)
        others = [tile for tile in window.wall.tiles if tile is not second]
        print(f"  操作格 muted={second.muted}　"
              f"其他格 muted={[tile.muted for tile in others]}　"
              f"其他格播放器 muted={[window.players[t].muted for t in others]}")
        assert second.muted
        assert all(not tile.muted for tile in others), "静音不该波及其他格子"
        assert all(not window.players[t].muted for t in others), \
            "静音不该下发到其他格子的播放器"
        assert window.players[second].muted, "操作的那一格必须真的静音"

        print("\n=== 2. 同一个直播间占两个格子：静音只影响操作的那一格 ===")
        head, twin = window.wall.tiles[0], window.wall.tiles[1]
        twin.room = dict(head.room)                    # 人为造出重复的房间号
        twin.room["room_id"] = head.room.get("room_id")
        for index, tile in enumerate(window.wall.tiles):
            window.players[tile] = FakePlayer(f"p{index}")
        head.muted = twin.muted = False
        print(f"  两格 room_id：{head.room.get('room_id')} / {twin.room.get('room_id')}"
              f"（故意一样）")
        twin.set_muted(True)
        settle(app)
        print(f"  静音第 2 格后：第1格播放器 muted={window.players[head].muted}（该是 False）　"
              f"第2格播放器 muted={window.players[twin].muted}（该是 True）")
        assert not window.players[head].muted, \
            "房间号撞车时，静音被下发到了别的格子（用户报的串台）"
        assert window.players[twin].muted, \
            "房间号撞车时，操作的那一格反而没被静音（标志亮着却还在出声）"

        print("\n=== 3. 秒切：音量 / 静音留在位置上，不跟着主播跑 ===")
        for tile in window.wall.tiles:
            window.players[tile] = FakePlayer("x")
        first, second = window.wall.tiles[0], window.wall.tiles[1]
        first.room["room_id"], second.room["room_id"] = "9401", "9402"
        first.volume, first.muted = 30, True
        second.volume, second.muted = 70, False
        before = (first.volume, second.volume)
        ok = window._hot_swap(first, second)           # noqa: SLF001
        settle(app, 0.3)
        after = (window.wall.tiles[0].volume, window.wall.tiles[1].volume)
        ids = (window.wall.tiles[0].room.get("room_id"),
               window.wall.tiles[1].room.get("room_id"))
        print(f"  秒切={ok}　位置上的音量 {before} -> {after}　位置上的主播 {ids}")
        assert ok, "两边都在播且有播放器时该走秒切"
        assert after == before, "音量该留在位置上，不该跟着主播换位"
        assert ids == ("9402", "9401"), "画面该换到了对面"
        # 位置 1 原本是静音的（first.muted=True），换完之后「位置 1」还得是静音
        assert window.wall.tiles[0].muted is True, "位置 1 的静音状态该留在位置上"
        assert window.wall.tiles[1].muted is False, "位置 2 的静音状态该留在位置上"

        print("\n=== 4. 换台：音量 / 静音 / 声道都留在格子上 ===")
        head = window.wall.tiles[0]
        head.volume, head.muted, head.audio_channel = 50, True, 4
        head.sync_audio_ui()
        fresh = {"room_id": "9499", "uname": "新主播", "title": "t", "live": False,
                 "muted": False, "volume": 5, "audio_channel": 3, "quality": 250}
        head.set_room(fresh)
        settle(app)
        got = (head.volume, head.muted, head.audio_channel)
        print(f"  换台前 (vol, muted, ch)=(50, True, 4)　换台后={got}"
              f"　（新房间自带 volume=5 muted=False ch=3）")
        assert got == (50, True, 4), \
            "换台后音量/静音/声道该全部留在格子上，不能被新房间覆盖"
        assert head.room.get("volume") == 50 and head.room.get("muted") is True
        assert head.room.get("audio_channel") == 4, "声道也要写回格子自己的房间"

        print("\n=== 5. 巡检：格子和播放器走散了，要按**格子**拉回来 ===")
        # 用户报的「静音标志亮着、声音却还在」就是这两边走散：标志画在格子上，
        # 声音由播放器决定。audio_set_mute 作用在 aout 上，错过那个窗口就会这样。
        head = window.wall.tiles[0]
        head.room["room_id"] = "9501"
        player = window.players[head] = FakePlayer("audit")
        head.muted, head.volume = False, 60
        player.muted, player.player.mute, player.player.volume = True, 1, 0
        print(f"  制造「格子没静音、播放器静音了」："
              f"tile.muted={head.muted} player.muted={player.muted}")
        window._audit_audio()                          # noqa: SLF001
        print(f"  巡检后 player.muted={player.muted}（该被拉回 False）")
        assert player.muted is False, "巡检该按格子的值重新下发静音"

        player.muted, player.player.mute, player.player.volume = False, 0, 5
        print(f"\n  制造「音量走散」：tile.volume={head.volume} "
              f"player.player.volume={player.player.volume}")
        window._audit_audio()                          # noqa: SLF001
        print(f"  巡检后 player.volume={player.volume}（该被拉回 {head.volume}）")
        assert player.volume == head.volume, "巡检该按格子的音量重新下发"

        print("\n  两边一致时不该乱下发：")
        from ddm.audio_output import linear_to_vlc_volume
        player.calls.clear()
        player.muted = False
        player.player.mute = 0
        player.player.volume = linear_to_vlc_volume(head.volume)   # 和格子对得上
        window._audit_audio()                          # noqa: SLF001
        print(f"    一致时收到的调用={player.calls}（应该是空）")
        assert player.calls == [], "两边一致时巡检不该再发一遍"
    finally:
        window.close()
        settle(app, 0.2)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
