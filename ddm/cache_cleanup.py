"""Explicit additional-cache categories; never scan user documents or temporary roots."""
import os
from pathlib import Path
import re
import time

from . import image_cache


IMAGE_KINDS = ('emoticons', 'sc-avatars', 'banners')
KINDS = (*IMAGE_KINDS, 'plugin-catalog', 'web-login', 'logs')
_REQUEST = 'web-login-clear.request'
_DAILY_LOG = re.compile(r'ddm-(\d{4}-\d{2}-\d{2})\.log(?:\.[1-5])?$')
_PID_LOG = re.compile(r'(?:qt-lifecycle-(\d+)\.jsonl(?:\.[12])?|'
                      r'(?:ddm|settings)-crash-(\d+)\.log(?:\.1)?|'
                      r'native-crash-(\d+)-[0-9a-f]+\.(?:json|dmp))$')


def _path(root, *parts):
    return image_cache._inside(root, Path(root).absolute().joinpath(*parts))


def http_request(root):
    path = _path(root, 'cache', _REQUEST)
    try:
        return path.read_text(encoding='ascii').strip()
    except FileNotFoundError:
        return ''


def request_http_clear(root):
    token = image_cache.ticket()
    with image_cache._state(root):
        image_cache._write(_path(root, 'cache', _REQUEST), token.encode('ascii'))
    return token


def complete_http_clear(root, token):
    with image_cache._state(root):
        if http_request(root) == token:
            _path(root, 'cache', _REQUEST).unlink(missing_ok=True)


def store_catalog(path, data, stamp):
    """Preserve the catalog API's custom paths while coordinating the canonical cache."""
    path = Path(path).absolute()
    root = path.parent.parent if path.parent.name == 'cache' else path.parent
    with image_cache._state(root) as db:
        if not image_cache._valid(db, 'plugin-catalog', stamp):
            return False
        image_cache._write(image_cache._inside(root, path), data)
    return True


def _pid_running(pid):
    if pid == os.getpid():
        return True
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return ctypes.get_last_error() != 87  # Unknown/access-denied processes are retained.
    try:
        return kernel.WaitForSingleObject(handle, 0) != 0
    finally:
        kernel.CloseHandle(handle)


def _historical_log(path, today):
    daily = _DAILY_LOG.fullmatch(path.name)
    if daily:
        return daily[1] < today
    if path.name == 'ddm-crash.log.1':
        return True
    match = _PID_LOG.fullmatch(path.name)
    return bool(match and not _pid_running(int(next(value for value in match.groups() if value))))


def _files(root, kind):
    if kind == 'plugin-catalog':
        for name in ('plugin-catalog.json', 'plugin-catalog-preview.json'):
            path = _path(root, 'cache', name)
            if path.is_file():
                yield path
        return
    directory = _path(root, 'logs') if kind == 'logs' else _path(root, 'cache', 'web-login')
    if not directory.is_dir():
        return
    if kind == 'web-login':
        for folder, directories, files in os.walk(directory, followlinks=False):
            directories[:] = [name for name in directories
                              if not image_cache._is_link(Path(folder) / name)]
            for name in files:
                path = Path(folder) / name
                if not image_cache._is_link(path):
                    yield image_cache._inside(root, path)
    else:
        today = time.strftime('%Y-%m-%d')
        for path in directory.iterdir():
            if (not image_cache._is_link(path) and path.is_file()
                    and time.strftime('%Y-%m-%d', time.localtime(path.stat().st_mtime)) < today
                    and _historical_log(path, today)):
                yield image_cache._inside(root, path)


def usage(root):
    values = image_cache.usage(root, IMAGE_KINDS)
    for kind in ('plugin-catalog', 'web-login', 'logs'):
        size = count = 0
        for path in _files(root, kind):
            try:
                size += path.stat().st_size
                count += 1
            except FileNotFoundError:
                pass
        values[kind] = dict(bytes=size, files=count)
    values['web-login']['pending'] = bool(http_request(root))
    return values


def _delete_inactive(path):
    """An exclusive delete handle rejects files still owned by logging/diagnostic writers."""
    if os.name != 'nt':
        raise OSError('Historical log clearing requires Windows exclusive-file checks')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x10000, 0, None, 3, 0x04000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    kernel.CloseHandle(handle)


def clear(root, kinds):
    kinds = set(kinds)
    if not kinds or not kinds.issubset(KINDS):
        raise ValueError('Select a known additional-cache category')
    result = dict(bytes=0, files=0, skipped=0, deferred=False)
    selected_images = kinds.intersection(IMAGE_KINDS)
    if selected_images:
        result.update(image_cache.clear(root, selected_images))
    if 'plugin-catalog' in kinds:
        with image_cache._state(root) as db:
            db.execute('INSERT OR REPLACE INTO cleared VALUES (?, ?)', ('plugin-catalog', image_cache.ticket()))
            for path in _files(root, 'plugin-catalog'):
                try:
                    size = path.stat().st_size
                    path.unlink()
                    result['bytes'] += size
                    result['files'] += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    result['skipped'] += 1
    if 'web-login' in kinds:
        request_http_clear(root)
        result['deferred'] = True
    if 'logs' in kinds:
        for path in _files(root, 'logs'):
            try:
                size = path.stat().st_size
                _delete_inactive(path)
                result['bytes'] += size
                result['files'] += 1
            except FileNotFoundError:
                pass
            except OSError:
                result['skipped'] += 1
    return result
