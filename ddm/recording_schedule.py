"""Time windows and title filters for automatic recording plans."""
from datetime import date, datetime, time, timedelta
import re


WEEKDAYS = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')
DAY_MINUTES = 1440
ALL_WEEK = datetime.min, datetime.max


def split_title_keywords(value):
    if isinstance(value, str):
        value = re.split(r'[,，、;；\n]', value)
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(word.strip() for word in value if isinstance(word, str) and word.strip())


def normalize_title_keywords(value):
    return tuple(sorted({word.casefold() for word in split_title_keywords(value)}))


def matches_recording_title(title, keywords):
    folded_title = title.casefold() if isinstance(title, str) else ''
    return not keywords or any(word in folded_title for word in keywords)


def normalize_schedule(rows):
    if not isinstance(rows, (list, tuple)):
        return ()
    valid = set()
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            continue
        day, start, end = row
        if isinstance(day, str):
            try:
                day = date.fromisoformat(day).isoformat()
            except ValueError:
                continue
        elif type(day) is not int or not 0 <= day < 7:
            continue
        if (type(start) is int and 0 <= start < DAY_MINUTES
                and (end is None or (type(end) is int and 0 <= end < DAY_MINUTES and end != start))):
            valid.add((day, start, end))
    return tuple(sorted(valid, key=lambda row: (isinstance(row[0], str), row[0], row[1],
                                               -1 if row[2] is None else row[2])))


def plan_window(schedule, now, *, consumed_start=None):
    """Return (opening, exclusive start deadline, record_until_offline)."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = midnight - timedelta(days=midnight.weekday())
    intervals = []
    open_starts = set()
    for day, start, end in schedule:
        if isinstance(day, str):
            anchors = (datetime.combine(date.fromisoformat(day), time()),)
        else:
            anchors = (monday + timedelta(days=week * 7 + day) for week in (-1, 0, 1, 2))
        for anchor in anchors:
            opening = anchor + timedelta(minutes=start)
            if end is None:
                open_starts.add(opening)
            else:
                intervals.append((opening, anchor + timedelta(minutes=end + (DAY_MINUTES if end < start else 0))))
    windows = []
    for opening, closing in sorted(intervals):
        if windows and opening <= windows[-1][1]:
            windows[-1] = windows[-1][0], max(windows[-1][1], closing)
        else:
            windows.append((opening, closing))
    window = next((window for window in windows if now < window[1]), None)
    if window and window[1] - window[0] >= timedelta(days=7) and not any(
            isinstance(day, str) for day, _, _ in schedule):
        window = ALL_WEEK
    upcoming = None
    later = None
    for opening in sorted(open_starts, reverse=True):
        cutoff = datetime.combine(opening.date() + timedelta(days=1), time())
        if later is not None:
            cutoff = min(cutoff, later)
        if opening <= now < cutoff and opening != consumed_start:
            return opening, cutoff, True
        if now < opening:
            upcoming = opening, cutoff, True
        later = opening
    if upcoming and (window is None or upcoming[0] < window[0]):
        return upcoming
    return (*window, False) if window else None


def window_at_or_after(schedule, now):
    """Return the current or next interval, with an exclusive end."""
    window = plan_window(schedule, now)
    return window[:2] if window else None


def has_open_start(schedule, opening):
    when = opening.hour * 60 + opening.minute
    return any(day in (opening.weekday(), opening.date().isoformat()) and start == when and end is None
               for day, start, end in schedule)


def plan_hint(schedule, *, now=None, keywords=()):
    if not schedule and keywords:
        return '按标题匹配'
    window = plan_window(schedule, now := now or datetime.now())
    if window is None:
        return '计划时段已过' if schedule else '未设置录制条件'
    suffix = ' · 标题匹配' if keywords else ''
    if window[1] == datetime.max:
        return '每周全天' + suffix
    if window[2]:
        return f'{window[0]:%m/%d %H:%M} 起录至下播' + suffix
    if window[0] <= now:
        return f'当前时段至 {WEEKDAYS[window[1].weekday()]} {window[1]:%H:%M}' + suffix
    if any(day == window[0].date().isoformat() for day, _, _ in schedule):
        return f'下次计划 {window[0]:%m/%d %H:%M}' + suffix
    return f'下次计划 {WEEKDAYS[window[0].weekday()]} {window[0]:%H:%M}' + suffix
