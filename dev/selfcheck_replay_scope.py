"""回归自检：即时回放的开关语义。

用户要求：
  1. 即时回放**跟着格子的直播自动开启**，不需要手动点；
  2. 没手动保存的话，缓存文件在停播/下播时**自动清理**（不留垃圾）；
  3. 右键菜单里**只保留「保存最近 N 分钟」**，不再有开启/关闭缓存两个开关；
  4. 适用范围（所有格子 / 只跟着录制走）放在**设置 → 录制**里。

清理那条由 `RecordingManager._finalize()` 负责：非录制的会话走 `_discard_cache()`，
录制的才 `_export()`。这里把其余三条钉住。
"""
import ctypes
import os
import subprocess
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

        print("\n=== 1. 默认范围：只跟着录制走，不自动铺开缓存 ===")
        assert config_module.DEFAULT_SETTINGS.get("recording_replay_scope") == "recorded", \
            "默认范围该是「只跟着录制走」——「所有格子」会一次拉起一堆 ffmpeg"
        assert config_module.DEFAULT_SETTINGS.get("recording_replay_max_tiles") == 3, \
            "缓存格子数要有默认上限"
        window.settings["recording_replay_scope"] = "recorded"
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  默认范围下开的格子={recorder.started}（该是空）")
        assert recorder.started == [], "「只跟着录制走」不该给没录制的格子开缓存"

        print("\n=== 1b. 范围设成「所有格子」：在播格子自动开缓存 ===")
        window.settings["recording_replay_scope"] = "all"
        window.settings["recording_replay_max_tiles"] = 0     # 先不设限，测「都开」
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  自动开的格子={recorder.started}")
        assert len(recorder.started) == len(live_tiles), \
            f"所有在播格子都该自动开缓存：{recorder.started}"
        assert all(recording is False for _rid, recording in recorder.started), \
            "自动开的只是回放缓存，不该顺带开始录制"
        # 已经有会话的格子不该重复开
        recorder.started.clear()
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  再跑一次（应该不重复开）：{recorder.started}")
        assert recorder.started == [], "已经有缓存的格子不该重复开"

        print("\n=== 1c. 缓存格子数上限：超出的格子不开 ===")
        recorder.sessions.clear()
        recorder.started.clear()
        window.settings["recording_replay_max_tiles"] = 2
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  上限 2 时开的格子={recorder.started}")
        assert len(recorder.started) == 2, \
            f"上限 2 就该只开 2 格，实际 {recorder.started}"
        # 额度按「已经在缓存的」现数：停掉一格之后要能补上，否则先开的会一直占着
        first_id = recorder.started[0][0]
        first_tile = next(tile for tile in tiles
                          if str(tile.room.get("room_id")) == first_id)
        recorder.stop(first_tile)
        recorder.started.clear()
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  停掉一格后再跑：新开的={recorder.started}")
        assert len(recorder.started) == 1, \
            f"让出额度后该补开一格，实际 {recorder.started}"
        # 用户手动录制的那格不占缓存额度
        recorder.sessions.clear()
        recorder.started.clear()
        window.settings["recording_replay_max_tiles"] = 1
        manual_tile = next(tile for tile in tiles if tile.room.get("room_id"))
        recorder.sessions[manual_tile] = FakeSession(recording=True)
        window._sync_replay_scope()                # noqa: SLF001
        print(f"  上限 1、另有一格在手动录制时开的缓存={recorder.started}")
        assert len(recorder.started) == 1, \
            f"录制不占缓存额度，仍该开满 1 格，实际 {recorder.started}"

        print("\n=== 2. 范围收窄成「只跟着录制走」：纯缓存的会话要被停掉 ===")
        recorder.sessions.clear()
        recorder.started.clear()
        recorder.stopped.clear()
        window.settings["recording_replay_max_tiles"] = 0      # 先铺满
        window.settings["recording_replay_scope"] = "all"
        window._sync_replay_scope()                # noqa: SLF001
        assert len(recorder.started) == len(live_tiles), "先决条件：缓存已经铺满"
        recorder.started.clear()
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
              f"上限={values.get('recording_replay_max_tiles')!r}　"
              f"选项={[page.replay_scope.itemData(i) for i in range(page.replay_scope.count())]}")
        assert "recording_replay_scope" in values, "设置页要交出这一项"
        assert "recording_replay_max_tiles" in values, "设置页要交出缓存格子上限"
        assert set(page.replay_scope.itemData(i)
                   for i in range(page.replay_scope.count())) == {"all", "recorded"}
        page._load({"recording_replay_scope": "recorded"})     # noqa: SLF001
        assert page.replay_scope.currentData() == "recorded", "设置页要能读回已存的值"
        page._load({"recording_replay_scope": "all",
                    "recording_replay_max_tiles": 5})          # noqa: SLF001
        print(f"  「所有格子」时上限控件：值={page.replay_max.value()} "
              f"可编辑={page.replay_max.isEnabled()}")
        assert page.replay_max.value() == 5, "上限要能读回已存的值"
        assert page.replay_max.isEnabled(), "「所有格子」时上限该可编辑"
        page._load({"recording_replay_scope": "recorded"})     # noqa: SLF001
        print(f"  「只跟着录制走」时上限控件可编辑={page.replay_max.isEnabled()}（该 False）")
        assert not page.replay_max.isEnabled(), \
            "「只跟着录制走」时上限不起作用，该置灰"

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
            # 有分段才会去导回放（没分段自然什么都不导）
            record_session.finished_parts = lambda: [f"part{i}" for i in range(5)]
            manager.sessions[object()] = cache_session
            manager._finalize(cache_session)       # noqa: SLF001
            manager.sessions[object()] = record_session
            manager._finalize(record_session)      # noqa: SLF001
        print(f"  被丢弃的（recording 标志）={discarded}　被导出的={exported}")
        assert discarded == [False], "纯缓存会话结束时该直接丢弃、不留文件"
        assert exported == [False, True], \
            f"结束录制要导两份：先即时回放（full=False）再完整录制（full=True），实际 {exported}"

        print("\n=== 6. 结束录制时会额外存一份「最近 N 分钟」 ===")
        manager2 = RecordingManager(dict(settings), None)
        exported2: list = []
        with patch.object(RecordingManager, "_export",
                          lambda _self, session, parts, full: exported2.append(
                              (full, len(parts)))), \
             patch.object(RecordingManager, "_end_process", lambda _self, _s: None):
            session = FakeSession(recording=True)
            session.finished_parts = lambda: [f"part{i}" for i in range(30)]  # noqa: E731
            manager2.sessions[object()] = session
            manager2._finalize(session)            # noqa: SLF001
        print(f"  两次导出 (full, 分段数)={exported2}")
        assert len(exported2) == 2, f"该导两份（回放 + 完整录制），实际 {exported2}"
        assert exported2[0][0] is False and exported2[1][0] is True, \
            "先导即时回放、再导完整录制"
        assert exported2[0][1] < exported2[1][1], \
            "即时回放只取最近一段，不该等于完整录制的分段数"
        manager2.timer.stop()

        print("\n=== 7. 录制时长 / ffmpeg 优先级 / 孤儿兜底 / 蓝框重设 ===")
        from ddm import recording as recording_module
        from ddm.recording import _FFMPEG_FLAGS
        if os.name == "nt":
            print(f"  ffmpeg 创建标志=0x{_FFMPEG_FLAGS:08X}"
                  f"（CREATE_NO_WINDOW + BELOW_NORMAL_PRIORITY_CLASS）")
            assert _FFMPEG_FLAGS & 0x00004000, \
                "ffmpeg 要跑在「低于正常」优先级，别跟游戏抢 CPU"
            assert _FFMPEG_FLAGS & 0x08000000, "别弹控制台窗口"
            # 起来之后还要再切到「后台模式」：连**磁盘 IO** 优先级一起降
            # （创建标志里的优先级类只管 CPU）
            assert recording_module._PROCESS_MODE_BACKGROUND_BEGIN == 0x00100000
            assert recording_module._kernel32 is not None, "kernel32 该能加载"
            # 真起一个进程，验证它确实进了 Job —— ctypes 的结构体版面或句柄宽度
            # 写错的话，这里是唯一会露馅的地方（自检之外没法验证「连坐」）
            job = recording_module._ensure_job()           # noqa: SLF001
            print(f"  Job Object 句柄={'有' if job else '无'}")
            assert job, "要有 Job Object 兜住孤儿 ffmpeg（主进程一死连坐）"
            probe = subprocess.Popen(
                [os.environ.get("COMSPEC", "cmd.exe"), "/c",
                 "ping -n 5 127.0.0.1 > nul"],
                creationflags=_FFMPEG_FLAGS)
            try:
                recording_module._adopt_process(probe)     # noqa: SLF001
                recording_module._kernel32.IsProcessInJob.restype = ctypes.c_int
                recording_module._kernel32.IsProcessInJob.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                inside = ctypes.c_int()
                ok = recording_module._kernel32.IsProcessInJob(
                    ctypes.c_void_p(int(probe._handle)), ctypes.c_void_p(job),
                    ctypes.byref(inside))
                print(f"  真起一个进程验证：IsProcessInJob={ok} inside={inside.value}")
                assert ok and inside.value == 1, \
                    "子进程必须真的进 Job，否则孤儿兜底是空的"
            finally:
                probe.kill()
                probe.wait(timeout=5)
            # http 流带内建重连（少一次整段重启就少一个分段接缝）；非 http 不能带
            http_args = recording_module.input_args(       # noqa: SLF001
                "https://example.invalid/live.flv", {})
            rtmp_args = recording_module.input_args(       # noqa: SLF001
                "rtmp://example.invalid/live", {})
            print(f"  http 输入参数={http_args}")
            assert "-reconnect" in http_args, "http 流该带内建重连"
            assert "-reconnect" not in rtmp_args, "非 http 流不能带 http 协议选项"

        tile = live_tiles[0]
        tile.set_recording_elapsed("12:34")
        print(f"  录制时长标签：{tile.recording_time.text()!r} "
              f"可见={tile.recording_time.isVisible()}")
        assert tile.recording_time.text() == "12:34" and tile.recording_time.isVisible()
        tile.set_recording_elapsed("")
        assert not tile.recording_time.isVisible(), "不在录制时要把时长收起来"

        # 蓝框：列表动过之后按当前墙面重设（用户报的「刚加进关注栏就被标成在墙上」）
        sidebar = window.sidebar
        sidebar.set_wall_rooms(["9601"])
        settle(app, 0.15)
        sidebar.add_room({"room_id": "9699", "uname": "新来的", "title": "t",
                          "live": True, "muted": True, "volume": 40, "quality": 250})
        settle(app, 0.15)
        fresh = next(item for item in sidebar.items()
                     if str(item.room.get("room_id")) == "9699")
        print(f"  新加的 9699 蓝框={bool(fresh.property('onWall'))}（该 False）")
        assert not fresh.property("onWall"), "新加的卡片不该带「已在画面墙」的蓝框"
        sidebar.set_wall_rooms(["9601", "9699"])
        settle(app, 0.15)
        print(f"  上墙后 9699 蓝框={bool(fresh.property('onWall'))}（该 True）")
        assert fresh.property("onWall"), "真上墙了就该有蓝框"
        sidebar.set_wall_rooms(["9601"])
        sidebar.remove_room({"room_id": "9699"})
        settle(app, 0.15)
        sidebar.add_room({"room_id": "9699", "uname": "又来了", "title": "t",
                          "live": True, "muted": True, "volume": 40, "quality": 250})
        settle(app, 0.15)
        again = next(item for item in sidebar.items()
                     if str(item.room.get("room_id")) == "9699")
        print(f"  下墙后再加 9699 蓝框={bool(again.property('onWall'))}（该 False）")
        assert not again.property("onWall"), "下墙之后再加，不该还留着蓝框"
        manager.timer.stop()

        print("\n=== 8. 纯缓存会话边录边裁（不再无限堆积） ===")

        class FakePart:
            def __init__(self, index):
                self.index = index
                self.removed = False

            def unlink(self, missing_ok=False):
                self.removed = True

            def __repr__(self):
                return f"part{self.index}"

        manager3 = RecordingManager(dict(settings), None)
        manager3.timer.stop()
        session = FakeSession(recording=False)
        session.settings = {"recording_replay_minutes": 1}
        session.pruned_at = 0.0
        parts = [FakePart(index) for index in range(20)]
        session.parts = list(parts)
        session.finished_parts = lambda: list(parts)
        manager3._prune_cache(session)                 # noqa: SLF001
        kept = [part for part in parts if not part.removed]
        print(f"  20 段裁完剩 {len(kept)} 段（最近 1 分钟 = 6 段，再加 2 段余量）")
        assert len(kept) == 8, f"该留 8 段，实际留下 {len(kept)}"
        assert all(part.removed for part in parts[:-8]), "裁掉的该是最早那些分段"
        # 紧接着再调用要节流：finished_parts() 要 glob 整个 .ddm-parts 目录，
        # 跟着 2 秒一轮的巡检每次都扫，反而变成新的开销
        scans: list = []
        session.finished_parts = lambda: scans.append(1) or list(parts)
        manager3._prune_cache(session)                 # noqa: SLF001
        print(f"  节流窗口内再调用：扫目录 {len(scans)} 次（该 0）")
        assert scans == [], "同一个会话的裁剪要节流"
        session.pruned_at = 0.0                        # 假装过了节流窗口
        manager3._prune_cache(session)                 # noqa: SLF001
        print(f"  过了节流窗口再调用：扫目录 {len(scans)} 次（该 1）")
        assert len(scans) == 1, "过了节流窗口要能再裁一次"
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
