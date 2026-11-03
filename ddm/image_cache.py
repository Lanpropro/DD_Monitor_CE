"""Avatar/cover ownership and cleanup, shared by app and settings processes."""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

KINDS = ('avatars', 'covers')
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif'}


def ticket():
    # Windows wall clocks can return the same value for consecutive requests.
    return f'{time.time_ns():020d}:{time.perf_counter_ns():020d}'


def _inside(root, path):
    root, path = Path(os.path.abspath(root)), Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        raise ValueError('Image cache path is outside the data directory')
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Image cache links are not supported')
    return path


@contextmanager
def _state(root):
    cache = _inside(root, Path(root) / 'cache')
    cache.mkdir(parents=True, exist_ok=True)
    path = _inside(root, cache / 'images.sqlite')
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS cleared (kind TEXT PRIMARY KEY, stamp TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS rooms (kind TEXT, room TEXT, path TEXT, '
                   'wanted TEXT, stamp TEXT, PRIMARY KEY(kind, room))')
        db.execute('CREATE TABLE IF NOT EXISTS retired (kind TEXT, path TEXT, PRIMARY KEY(kind, path))')
        db.execute('BEGIN IMMEDIATE')
        yield db


def _valid(db, kind, stamp):
    row = db.execute('SELECT stamp FROM cleared WHERE kind=?', (kind,)).fetchone()
    return row is None or stamp > row[0]


def begin(root, kind, requests, stamp):
    """Register candidates before downloading; later scheduled requests win."""
    with _state(root) as db:
        if not _valid(db, kind, stamp):
            return False
        for room, candidates in requests.items():
            db.execute('INSERT INTO rooms VALUES (?, ?, NULL, ?, ?) '
                       'ON CONFLICT(kind, room) DO UPDATE SET wanted=excluded.wanted, stamp=excluded.stamp '
                       'WHERE excluded.stamp >= rooms.stamp',
                       (kind, str(room), json.dumps(candidates), stamp))
    return True


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.image-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def store(root, kind, path, data, stamp, *, room=None):
    """A download started before manual clearing must not recreate its file."""
    with _state(root) as db:
        if not _valid(db, kind, stamp):
            return False
        if room is not None:
            current = db.execute('SELECT stamp FROM rooms WHERE kind=? AND room=?',
                                 (kind, str(room))).fetchone()
            if current is not None and current[0] > stamp:
                return False
        _write(_inside(root, path), data)
    return True


def remember(root, kind, room, source, target, stamp):
    """Commit a usable room snapshot before removing its unreferenced predecessor."""
    source, target = _inside(root, source), _inside(root, target)
    relative = source.relative_to(Path(root).absolute()).as_posix()
    with _state(root) as db:
        row = db.execute('SELECT path, stamp FROM rooms WHERE kind=? AND room=?',
                         (kind, str(room))).fetchone()
        if not _valid(db, kind, stamp) or row is None or row[1] != stamp:
            return False
        _write(target, source.read_bytes())
        db.execute('UPDATE rooms SET path=?, wanted=? WHERE kind=? AND room=?',
                   (relative, json.dumps([relative]), kind, str(room)))
        if row[0] and row[0] != relative:
            db.execute('INSERT OR IGNORE INTO retired VALUES (?, ?)', (kind, row[0]))
        protected = set()
        for path, wanted in db.execute('SELECT path, wanted FROM rooms WHERE kind=?', (kind,)):
            protected.update(json.loads(wanted or '[]'))
            if path:
                protected.add(path)
        for (old,) in db.execute('SELECT path FROM retired WHERE kind=?', (kind,)).fetchall():
            if old in protected:
                continue
            try:
                candidate = _inside(root, Path(root) / old)
                if not candidate.is_relative_to(Path(root).absolute() / 'cache' / kind):
                    continue
                candidate.unlink(missing_ok=True)
            except (OSError, ValueError):
                continue
            db.execute('DELETE FROM retired WHERE kind=? AND path=?', (kind, old))
    return True


def _files(root, kind):
    directory = _inside(root, Path(root) / 'cache' / kind)
    if not directory.is_dir():
        return
    for folder, directories, files in os.walk(directory, followlinks=False):
        directories[:] = [name for name in directories
                          if not (Path(folder) / name).is_symlink()
                          and not (hasattr(Path, 'is_junction') and (Path(folder) / name).is_junction())]
        for name in files:
            path = Path(folder) / name
            if path.suffix.lower() in EXTENSIONS and not path.is_symlink():
                yield _inside(root, path)


def usage(root):
    result = {}
    for kind in KINDS:
        size = count = 0
        for path in _files(root, kind):
            try:
                size += path.stat().st_size
                count += 1
            except FileNotFoundError:
                pass
        result[kind] = {'bytes': size, 'files': count}
    return result


def clear(root, kinds):
    kinds = set(kinds)
    if not kinds or not kinds.issubset(KINDS):
        raise ValueError('Select avatars and/or covers')
    for kind in kinds:
        _inside(root, Path(root) / 'cache' / kind)
    size = count = skipped = 0
    with _state(root) as db:
        for kind in kinds:
            db.execute('INSERT OR REPLACE INTO cleared VALUES (?, ?)', (kind, ticket()))
            db.execute('DELETE FROM rooms WHERE kind=?', (kind,))
            db.execute('DELETE FROM retired WHERE kind=?', (kind,))
            for path in _files(root, kind):
                try:
                    length = path.stat().st_size
                    path.unlink()
                    size += length
                    count += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    skipped += 1
    return {'bytes': size, 'files': count, 'skipped': skipped}
