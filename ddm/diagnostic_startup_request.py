"""One-shot handoff from the local MCP server to the next source application start."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import time
from uuid import uuid4


SESSION_MODES = ('folders', 'responsiveness', 'notices', 'danmaku', 'drag',
                 'douyu', 'douyu-deep', 'theme', 'fullscreen', 'tiles', 'dock-hover')
SOURCE_MODES = ('responsiveness-profile', 'fullscreen-input', 'settings-scroll',
                'settings-performance', 'control-swap', 'wall-replacement', 'sc',
                'danmaku-motion', 'window-resize', 'window-dpi-profile', 'live-elapsed')
MATCH_MODES = ('match-d3d11', 'match-d3d11-quick')
REQUEST_NAME = 'mcp-startup-diagnostics.sqlite3'
REQUEST_TTL_SECONDS = 600
SCHEMA = '''CREATE TABLE IF NOT EXISTS pending (
    slot INTEGER PRIMARY KEY CHECK (slot = 1),
    mode TEXT NOT NULL,
    request_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL
)'''


def available_modes(root):
    modes = SESSION_MODES + SOURCE_MODES
    presenter = root / 'work/match-d3d11-prototype'
    if all(path.is_file() for path in (root / 'dev/match_gui_dispatch.py',
                                       presenter / 'presenter.exe', presenter / 'mailbox.dll')):
        modes += MATCH_MODES
    try:
        monitor = json.loads((root / 'work/development-hang-monitor.json').read_text(encoding='utf-8'))
        if monitor.get('enabled') is True and all(Path(monitor[key]).is_file() for key in ('py_spy', 'native_sampler')):
            modes += ('development-hang',)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        pass
    return modes


def prepare(root: Path, mode: str):
    if mode not in available_modes(root):
        raise ValueError('Startup mode is unavailable in this source checkout')
    path = root / 'work' / REQUEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    request = dict(mode=mode, request_id=uuid4().hex, expires_at=int(time.time()) + REQUEST_TTL_SECONDS)
    with closing(sqlite3.connect(path, timeout=2)) as db, db:
        db.execute(SCHEMA)
        db.execute('INSERT OR REPLACE INTO pending VALUES (1, :mode, :request_id, :expires_at)', request)
    return request


def consume(root: Path):
    path = root / 'work' / REQUEST_NAME
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path, timeout=2)) as db, db:
            db.execute(SCHEMA)
            row = db.execute('DELETE FROM pending RETURNING mode, request_id, expires_at').fetchone()
    except sqlite3.Error as error:
        raise OSError('Could not claim the local MCP diagnostic request') from error
    if row is None:
        return None
    mode, request_id, expires_at = row
    if (mode not in available_modes(root) or type(expires_at) is not int
            or not 0 < expires_at - time.time() <= REQUEST_TTL_SECONDS):
        return None
    return dict(mode=mode, request_id=request_id, expires_at=expires_at)
