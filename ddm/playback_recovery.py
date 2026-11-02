"""Per-tile retry and frozen-picture recovery; the host performs playback and UI events."""
import sys

from PySide6.QtCore import QObject, QTimer

RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 60
FREEZE_RETRY_SECONDS = 5


class PlaybackRecovery(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.retry_count: dict[object, int] = {}
        self.retry_timers: dict[object, QTimer] = {}
        self.freeze_refreshed: set[object] = set()
        self.freeze_retry_timers: dict[object, QTimer] = {}

    def cancel_retry(self, tile, *, reset_attempts=False):
        timer = self.retry_timers.pop(tile, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        if reset_attempts:
            self.retry_count.pop(tile, None)

    def reset_retry_after_playing(self, tile):
        if str(tile.room.get("room_id", "")).startswith(("huya:", "douyu:")):
            player = self.host.players.get(tile)
            if player is not None:
                generation = player.state_generation
                QTimer.singleShot(15000, self, lambda: self.reset_stable_retry(tile, player, generation))
        else:
            self.retry_count.pop(tile, None)

    def clear_tile(self, tile):
        self.cancel_retry(tile, reset_attempts=True)
        self.clear_freeze(tile)

    def shutdown(self):
        for tile in list(self.retry_timers):
            self.cancel_retry(tile)
        for tile in list(self.freeze_retry_timers):
            self.clear_freeze(tile)
        self.retry_count.clear()
        self.freeze_refreshed.clear()

    def reset_stable_retry(self, tile, player, generation):
        if (not self.host._closing and self.host.players.get(tile) is player and player.state == "playing"
                and player.state_generation == generation):
            self.retry_count.pop(tile, None)

    def picture_frozen(self, tile) -> None:
        """静止约 2 秒先立即刷新；仍静止则提示，并每 5 秒再次刷新。"""
        if not tile.room.get("room_id") or tile.paused:
            return
        if tile in self.host._resolvers or tile in self.retry_timers:
            return
        if tile not in self.freeze_refreshed:
            self.freeze_refreshed.add(tile)
            tile.set_status("画面停止更新，正在自动刷新…")
            print(f"[画面静止] {tile.room.get('uname')} 自动刷新",
                  file=sys.stderr, flush=True)
            self.host.refresh_status()           # 静止可能来自下播；接口确认后会同步清屏和侧栏
            self.host.start_tile(tile)
            return
        if tile in self.freeze_retry_timers:
            return
        tile.set_status(f"画面仍停止更新，{FREEZE_RETRY_SECONDS} 秒后再次刷新…")
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda t=tile: self.retry_frozen_picture(t))
        self.freeze_retry_timers[tile] = timer
        timer.start(FREEZE_RETRY_SECONDS * 1000)

    def retry_frozen_picture(self, tile) -> None:
        timer = self.freeze_retry_timers.pop(tile, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        if not tile.room.get("room_id") or tile.paused:
            return
        tile.set_status("画面仍停止更新，正在再次刷新…")
        print(f"[画面静止] {tile.room.get('uname')} 5 秒后再次刷新",
              file=sys.stderr, flush=True)
        self.host.start_tile(tile)

    def picture_activity(self, tile) -> None:
        """画面重新变化后结束静止恢复流程，不再执行排队中的刷新。"""
        if tile is None:
            return                        # 播放器已经不在任何格子上
        was_recovering = tile in self.freeze_refreshed
        self.clear_freeze(tile)
        if was_recovering:
            tile.set_status("")
            print(f"[画面恢复] {tile.room.get('uname')} 已恢复更新",
                  file=sys.stderr, flush=True)

    def clear_freeze(self, tile) -> None:
        timer = self.freeze_retry_timers.pop(tile, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self.freeze_refreshed.discard(tile)

    def schedule_retry(self, tile) -> None:
        """断流自动重连：5 秒起，逐次翻倍，最多 60 秒。"""
        if not tile.room.get("room_id"):
            return
        # A pending source request or retry already owns this recovery attempt.
        if tile in self.host._resolvers or tile in self.retry_timers:
            return
        attempt = self.retry_count.get(tile, 0) + 1
        self.retry_count[tile] = attempt
        delay = min(RETRY_BASE_SECONDS * (2 ** (attempt - 1)), RETRY_MAX_SECONDS)
        player = self.host.players.get(tile)
        if (str(tile.room.get("room_id", "")).startswith(("huya:", "douyu:")) and
                getattr(player, "source_failure", "") == "LIVE_EOF"):
            delay = min(attempt, 5)
        if str(tile.room.get("room_id", "")).startswith(("huya:", "douyu:")):
            print(f"[平台诊断] 阶段=recovery_schedule 房间={tile.room['room_id']} 次数={attempt} 等待秒数={delay}",
                  file=sys.stderr, flush=True)
        tile.set_status(f"断流，{delay} 秒后重连（第 {attempt} 次）")
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda t=tile: self.retry_now(t))
        self.retry_timers[tile] = timer
        timer.start(delay * 1000)

    def retry_now(self, tile) -> None:
        self.cancel_retry(tile)
        if tile.room.get("room_id"):
            print(f"[重连] {tile.room.get('uname')} 第 {self.retry_count.get(tile, 1)} 次",
                  file=sys.stderr, flush=True)
            self.host.start_tile(tile)
