"""Extract candidate recording times and their calendar labels from OCR boxes."""
from dataclasses import dataclass
from datetime import date, timedelta
import re
from statistics import median
from unicodedata import normalize


_CLOCK = r'([0-2]?\d):([0-5]\d)'
_TIMES = re.compile(r'(?<![\d:])' + _CLOCK + r'(?:[-–—~～一至到=]+' + _CLOCK + r')?(?!\d)')
_DATE = re.compile(r'(?<![\d.])(?:(\d{4})[年./-])?(1[0-2]|0?[1-9])[月./](3[01]|[12]\d|0?[1-9])日?(?![\d.:])')
_SEPARATOR = re.compile(r'[-–—~～一至到]+')
_WEEKDAYS = ('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')
_DAY_LABEL = re.compile(r'^(?:星期[一二三四五六日天]|周[一二三四五六日天]|[A-Z]+)(?=[^A-Z]|$)')
_CHINESE_DAYS = '一二三四五六日'
_UNCERTAIN = ('待定', '暂定', '可能', '随机', 'TBD')


@dataclass(frozen=True)
class CalendarEntry:
    day: date | int | None
    start: int
    end: int | None
    text: str
    review: bool = False


@dataclass(frozen=True)
class _Box:
    x: float
    y: float
    height: float


def _ocr_lines(passes):
    for scan in passes:
        for line in scan['lines']:
            boxes = []
            parts = []
            for word in line['words']:
                text = ''.join(normalize('NFKC', word['text']).split())
                if not text:
                    continue
                parts.append(text)
                box = _Box(word['x'] + word['width'] / 2, word['y'] + word['height'] / 2, word['height'])
                boxes.extend([box] * len(text))
            yield ''.join(parts), boxes


def _week_day(text):
    label = text.upper().strip(':.•!：')
    for index, weekday in enumerate(_WEEKDAYS):
        if label in (weekday, ('MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY',
                               'FRIDAY', 'SATURDAY', 'SUNDAY')[index]) or label == '周' + _CHINESE_DAYS[index] or (
                label == '星期' + _CHINESE_DAYS[index]):
            return index
    if label in ('THR', 'THUR', 'THURS'):
        return 3
    if label in ('周天', '星期天'):
        return 6
    return None


def next_monday(today):
    return today + timedelta(days=7 - today.weekday())


def _calendar_date(match, reference):
    year, month, day = match.groups()
    if year is not None:
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None
    options = []
    for year in range(max(1, reference.year - 1), min(9999, reference.year + 1) + 1):
        try:
            options.append(date(year, int(month), int(day)))
        except ValueError:
            continue
    return min(options, key=lambda day: abs(day - reference), default=None)


def _near(left, right):
    height = max(left.height, right.height)
    return abs(left.x - right.x) <= 1.5 * height and abs(left.y - right.y) <= .65 * height


def _label_columns(labels):
    columns = []
    for box, day in sorted(labels, key=lambda entry: entry[0].x):
        if columns and abs(box.x - columns[-1][0][0].x) <= 2 * max(box.height, columns[-1][0][0].height):
            columns[-1].append((box, day))
        else:
            columns.append([(box, day)])
    return columns


def _date_rows(labels):
    # A date repeated in the heading is distinct from the same date printed on a row.
    # Keep aligned day labels that form a plausible week, away from dates in program names.
    candidates = []
    for box, day in labels:
        week = [(other, value) for other, value in labels if abs(value - day) <= timedelta(days=6)]
        candidates.extend(
            [(other, value) for other, value in week if abs(getattr(other, axis) - getattr(box, axis))
             <= 2 * max(other.height, box.height)]
            for axis in ('x', 'y')
        )
    return max(candidates, key=lambda group: len({day for _, day in group}), default=[])


def _fill_label_gaps(column):
    filled = []
    for (first, day), (last, other) in zip(column, column[1:]):
        filled.append((first, day, False))
        distance = (other - day).days if isinstance(day, date) else other - day
        if not 1 < distance <= 4 or last.y - first.y < distance * first.height:
            continue
        for step in range(1, distance):
            y = first.y + (last.y - first.y) * step / distance
            value = day + timedelta(days=step) if isinstance(day, date) else day + step
            filled.append((_Box(first.x, y, first.height), value, True))
    return [*filled, (*column[-1], False)]


def _assign_day(box, columns):
    if not columns:
        return None, True
    if all(len(column) == 1 for column in columns):
        label, day = min((column[0] for column in columns), key=lambda value: abs(value[0].x - box.x))
        return (day, False) if box.y >= label.y - label.height else (None, True)
    left = [column for column in columns if column[0][0].x <= box.x + box.height]
    column = left[-1] if left else columns[0]
    rows = _fill_label_gaps(sorted(column, key=lambda value: value[0].y))
    spacing = median([b[0].y - a[0].y for a, b in zip(rows, rows[1:])]) if len(rows) > 1 else 0
    for label, day, inferred in reversed(rows):
        if -label.height <= box.y - label.y <= max(1.25 * spacing, 3 * label.height):
            return day, inferred
    first, first_day, _ = rows[0]
    if type(first_day) is int and first_day > 0 and len(rows) >= 3 and (
            first.y - 1.25 * spacing <= box.y < first.y - first.height):
        return first_day - 1, True
    return None, True


def extract_calendar(passes, reference):
    dates, weekdays, found = [], [], []
    dated_week = None
    for text, boxes in _ocr_lines(passes):
        label = _DAY_LABEL.match(text.upper())
        if label and (day := _week_day(label[0])) is not None:
            if not any(day == previous and _near(boxes[0], box) for box, previous in weekdays):
                weekdays.append((boxes[0], day))
        matches = [(match, _calendar_date(match, reference)) for match in _DATE.finditer(text)]
        if len(matches) == 2:
            (first, first_date), (last, last_date) = matches
            if (first_date and last_date and last_date - first_date == timedelta(days=6)
                    and _SEPARATOR.fullmatch(text[first.end():last.start()])):
                dated_week = first_date
                matches = []
        for match, day in matches:
            if day:
                box = boxes[match.start()]
                if not any(day == previous and _near(box, last) for last, previous in dates):
                    dates.append((box, day))
        for match in _TIMES.finditer(text):
            hour, minute, end_hour, end_minute = match.groups()
            start = 60 * int(hour) + int(minute)
            end = 60 * int(end_hour) + int(end_minute) if end_hour is not None else None
            if start >= 48 * 60 or (end is not None and (end >= 48 * 60 or start % 1440 == end % 1440)):
                continue
            box = boxes[match.start()]
            uncertain = any(word in text.upper() for word in _UNCERTAIN)
            if end is None and re.match(r'[-–—~～一至到=]+\d', text[match.end():]):
                uncertain = True
            for index, (last_box, previous_start, previous_end, source, review) in enumerate(found):
                if _near(last_box, box):
                    conflict = start != previous_start or (end is not None and previous_end not in (None, end))
                    found[index] = (box, start, end, text, uncertain or review or conflict) if (
                        previous_end is None and end is not None
                    ) else (last_box, previous_start, previous_end, source, uncertain or review or conflict)
                    break
            else:
                found.append((box, start, end, text, uncertain))
    date_rows = _date_rows(dates)
    columns = _label_columns(date_rows if len({day for _, day in date_rows}) >= 2 else weekdays)
    entries = []
    for box, start, end, source, review in sorted(found, key=lambda item: (item[0].y, item[0].x)):
        day, inferred = _assign_day(box, columns)
        if dated_week is not None and type(day) is int:
            day = dated_week + timedelta(days=(day - dated_week.weekday()) % 7)
        shift, start = divmod(start, 1440)
        if shift and day is not None:
            day = day + timedelta(days=shift) if isinstance(day, date) else day + shift
        entries.append(CalendarEntry(day, start, end % 1440 if end is not None else None, source,
                                     review or inferred))
    return tuple(sorted(entries, key=lambda entry: (
        entry.day is None, entry.day if isinstance(entry.day, date) else reference + timedelta(days=entry.day or 0),
        entry.start)))
