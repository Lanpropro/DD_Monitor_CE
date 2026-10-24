"""本机常看记录：主动观看满一分钟，每日一次，历史分数七天减半。"""
from copy import deepcopy
from datetime import date, datetime
import math
import time

MIN_SECONDS = 60
HALF_LIFE_SECONDS = 7 * 86400
SORT_TIP = ("开播在前，同一状态下常看的主播靠前。启用后仅记录本机主动观看，"
            "实际播放满 60 秒，每位主播每天最多一次。悬停、自动恢复和重连不计次。"
            "新排名在手动刷新、重启或主动选择此排序时应用。")


class WatchHistory:
    def __init__(self, records=None):
        self.records = {}
        for rid, record in (records.items() if isinstance(records, dict) else ()):
            if not isinstance(rid, str) or not rid or not isinstance(record, dict):
                continue
            score, updated, day = record.get('score'), record.get('updated'), record.get('day')
            if not all(type(value) in (int, float) and math.isfinite(value) and value >= 0
                       for value in (score, updated)) or not isinstance(day, str):
                continue
            try:
                date.fromisoformat(day)
            except ValueError:
                continue
            self.records[rid] = dict(score=score, updated=updated, day=day)
        self.enabled = False
        self._seconds = {}
        self._previous_active = set()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self._seconds.clear()
            self._previous_active.clear()

    def select(self, room_id):
        if self.enabled and room_id:
            self._seconds.setdefault(str(room_id), 0.0)

    def scores(self, now=None):
        now = time.time() if now is None else now
        return {rid: record['score'] * 2 ** (-max(0, now - record['updated']) / HALF_LIFE_SECONDS)
                for rid, record in self.records.items()}

    def sample(self, present, active, elapsed, now=None):
        """只累计相邻两次采样都在实际播放的房间；休眠或界面阻塞不补记。"""
        if not self.enabled:
            return False
        now = time.time() if now is None else now
        today = datetime.fromtimestamp(now).date().isoformat()
        self._seconds = {rid: seconds for rid, seconds in self._seconds.items() if rid in present}
        eligible = set(active).intersection(self._seconds)
        changed = False
        for rid in eligible.intersection(self._previous_active):
            record = self.records.get(rid)
            if record and record['day'] >= today:
                continue
            self._seconds[rid] += elapsed if 0 < elapsed <= 2 else 0
            if self._seconds[rid] >= MIN_SECONDS:
                score = self.scores(now).get(rid, 0) + 1
                self.records[rid] = dict(score=score, updated=now, day=today)
                self._seconds[rid] = 0.0
                changed = True
        self._previous_active = eligible
        return changed

    def clear(self):
        self.records.clear()
        self._seconds.clear()
        self._previous_active.clear()

    def state(self):
        return deepcopy(self.records)
