"""回归自检：即时回放的开关语义。

用户要求：
  1. 即时回放**跟着格子的直播自动开启**，不需要手动点；
  2. 没手动保存的话，缓存文件在停播/下播时**自动清理**（不留垃圾）；
  3. 右键菜单里**只保留「保存最近 N 分钟」**，不再有开启/关闭缓存两个开关；
  4. 适用范围（所有格子 / 只跟着录制走）放在**设置 → 录制**里。

清理那条由 `RecordingManager._finalize()` 负责：非录制的会话走 `_discard_cache()`，
录制的才 `_export()`。这里把其余三条钉住。
"""
import os
import sys
import time
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config as config_module  # noqa: E402
from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import RecordingSettingsPage  # noqa: E402

ROOMS = [{"room_id": f"96{index:02d}", "uname": f"主播{index}", "title": "t",
          "live": True, "muted": True, "volume": 40, "quality": 250}
         for index in range(1, 4)]


class FakeSession:
    def __init__(self, recording: bool):
        self.recording = recording
        self.stopping = False
        self.settings = {"recording_replay_minutes": 3}
        self.tile = object()          # _finalize 要拿它去 pop / emit

    def finished_parts(self) -> list:
        return []                     # 导出/丢弃都被 mock 掉了，这里只要别炸


class FakeRecorder:
    """只记调用，不起真的 FFmpeg。"""

    def __init__(self):
        self.sessions: dict = {}
        self.started: list = []
        self.stopped: list = []

    def start(self, tile, *, recording):
        self.started.append((str(tile.room.get("room_id")), recording))
        self.sessions[tile] = FakeSession(recording)
        return True

    def stop(self, tile):
        self.stopped.append(str(tile.room.get("room_id")))
        self.sessions.pop(tile, None)

    def save_replay(self, _tile):
        pass

    def shutdown(self):
        pass

    def on_resolved(self, _tile):
        pass


def settle(app, seconds: float = 0.3) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def menu_texts(window, tile) -> list:
    window._fill_plugin_menu(tile)                 # noqa: SLF001
    return [label for label, _cb in tile.plugin_actions]


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    settings = dict(config_module.DEFAULT_SETTINGS)
    settings["recording_dir"] = os.environ.get("TEMP") or REPO
    window = MainWindow([dict(room) for room in ROOMS],
                        [dict(room) for room in ROOMS],
                        layout_id="2x2", state={"settings": dict(settings)})
    window.setGeometry(-9000, -9000, 1200, 700)
    window.show()
    settle(app, 0.5)
    recorder = FakeRecorder()
    window.recorder = recorder
    try:
        tiles = [tile for tile in window.wall.tiles if tile.isVisible()]
        for tile in tiles:
            tile.room["live"] = True
            tile.stream_url = "https://example.invalid/live.flv"
        # 2x2 有四个格子、但只有三个房间，空格子不该被开缓存
        live_tiles = [tile for tile in tiles if tile.room.get("room_id")]
        print(f"可见格子 {len(tiles)} 个，其中有直播的 {len(live_tiles)} 个")

        print("\n=== 1. 默认范围：跟着直播自动开缓存 ===")
        window.settings["recording_replay_scope"] = "all"
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  自动开的格子={recorder.started}")
        assert len(recorder.started) == len(live_tiles), \
            f"所有在播格子都该自动开缓存：{recorder.started}"
        assert all(recording is False for _rid, recording in recorder.started), \
            "自动开的只是回放缓存，不该顺带开始录制"
        assert config_module.DEFAULT_SETTINGS.get("recording_replay_scope") == "all", \
            "默认范围该是「所有格子」（用户要求跟着直播开启）"
        # 已经有会话的格子不该重复开
        recorder.started.clear()
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  再跑一次（应该不重复开）：{recorder.started}")
        assert recorder.started == [], "已经有缓存的格子不该重复开"

        print("\n=== 2. 范围收窄成「只跟着录制走」：纯缓存的会话要被停掉 ===")
        window.settings["recording_replay_scope"] = "recorded"
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  停掉的格子={recorder.stopped}")
        assert len(recorder.stopped) == len(live_tiles), "收窄范围该停掉纯缓存"
        # 录制中的会话要留着（它本来就在写分段）
        recorder.sessions.clear()
        recorder.stopped.clear()
        recording_tile = tiles[0]
        recorder.sessions[recording_tile] = FakeSession(recording=True)
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  录制中的格子被停了吗={recorder.stopped}（应该是空）")
        assert recorder.stopped == [], "录制中的格子要留着，它本来就在写分段"
        assert recorder.started == [], "「只跟着录制走」不该给别的格子开缓存"

        print("\n=== 3. 右键菜单：只留「保存最近 N 分钟」 ===")
        window.settings["recording_replay_scope"] = "all"
        plain = tiles[1]
        recorder.sessions.pop(plain, None)
        texts = menu_texts(window, plain)
        print(f"  没有会话时：{texts}")
        assert not any("开启即时回放缓存" in text for text in texts), \
            "不该再有「开启即时回放缓存」——它现在跟着直播自动开"
        assert not any("关闭即时回放缓存" in text for text in texts)
        assert any("开始录制这一路" in text for text in texts)

        recorder.sessions[plain] = FakeSession(recording=False)
        texts = menu_texts(window, plain)
        print(f"  有缓存时：{texts}")
        assert any("保存最近约" in text for text in texts), "要有保存即时重放"
        assert not any("关闭即时回放缓存" in text for text in texts), \
            "不该再有「关闭即时回放缓存」"
        assert not any("开启即时回放缓存" in text for text in texts)

        print("\n=== 4. 范围设置进了「设置 → 录制」页 ===")
        page = RecordingSettingsPage(dict(settings))
        values = page.values()
        print(f"  读出的值={values.get('recording_replay_scope')!r}　"
              f"选项={[page.replay_scope.itemData(i) for i in range(page.replay_scope.count())]}")
        assert "recording_replay_scope" in values, "设置页要交出这一项"
        assert set(page.replay_scope.itemData(i)
                   for i in range(page.replay_scope.count())) == {"all", "recorded"}
        page._load({"recording_replay_scope": "recorded"})     # noqa: SLF001
        assert page.replay_scope.currentData() == "recorded", "设置页要能读回已存的值"

        print("\n=== 5. 没保存就清理：非录制会话走丢弃、录制才导出 ===")
        from ddm.recording import RecordingManager
        manager = RecordingManager(dict(settings), None)
        discarded, exported = [], []
        with patch.object(RecordingManager, "_discard_cache",
                          lambda _self, session: discarded.append(session.recording)), \
             patch.object(RecordingManager, "_export",
                          lambda _self, session, parts, full: exported.append(full)), \
             patch.object(RecordingManager, "_end_process", lambda _self, _s: None):
            cache_session = FakeSession(recording=False)
            record_session = FakeSession(recording=True)
            manager.sessions[object()] = cache_session
            manager._finalize(cache_session)       # noqa: SLF001
            manager.sessions[object()] = record_session
            manager._finalize(record_session)      # noqa: SLF001
        print(f"  被丢弃的（recording 标志）={discarded}　被导出的={exported}")
        assert discarded == [False], "纯缓存会话结束时该直接丢弃、不留文件"
        assert exported == [True], "录制会话结束时该导出保存"
        manager.timer.stop()
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
