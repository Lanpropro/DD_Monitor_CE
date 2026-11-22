"""Private plugin readers delivered as local HTTP; the player owns playback lifetime."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import uuid


_sources = {}
_lock = threading.Lock()


class MediaSource:
    def __init__(self, factory, prepared, owner):
        self.owner = owner
        self._factory, self._prepared = factory, prepared
        self._readers = set()
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self.refresh_required = threading.Event()
        self.live_ended = threading.Event()
        self.playback_diagnostic = None
        source = self
        path = '/media/' + uuid.uuid4().hex

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path != path or source._stopped.is_set():
                    self.send_error(404)
                    return
                reader = None
                try:
                    with source._lock:
                        reader, source._prepared = source._prepared, None
                    if reader is None:
                        reader = source._factory(source._stopped.is_set)
                    with source._lock:
                        if source._stopped.is_set():
                            return
                        source._readers.add(reader)
                    self.send_response(200)
                    self.send_header('Content-Type', 'video/x-matroska')
                    self.send_header('Accept-Ranges', 'none')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    while not source._stopped.is_set():
                        data = reader.read(65536)
                        if not data:
                            source.refresh_required.set()
                            break
                        self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # This consumer stopped; other consumers keep their readers.
                except (OSError, ValueError):
                    if not source._stopped.is_set():
                        source.refresh_required.set()
                finally:
                    if reader is not None:
                        with source._lock:
                            source._readers.discard(reader)
                        reader.close()

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self._server.daemon_threads = True
        self._server.timeout = .05
        self.url = f'http://127.0.0.1:{self._server.server_port}{path}'
        self._thread = threading.Thread(target=self._serve, name='plugin-media-source', daemon=True)
        self._timer = threading.Timer(20, self.stop)
        self._timer.daemon = True

    def start(self):
        with _lock:
            _sources[self.url] = self
        self._thread.start()
        self._timer.start()
        return self.url

    def _serve(self):
        try:
            while not self._stopped.is_set():
                self._server.handle_request()
        finally:
            self._server.server_close()

    def network_speed(self):
        with self._lock:
            readers = tuple(self._readers)
        values = [reader.network_speed() for reader in readers if hasattr(reader, 'network_speed')]
        usable = [(rate, count) for rate, count in values if count]
        return min(usable) if usable else (0, 0)

    def stop(self):
        with self._lock:
            if self._stopped.is_set():
                return
            self._stopped.set()
            prepared, self._prepared = self._prepared, None
            readers = self._readers | ({prepared} if prepared is not None else set())
        self._timer.cancel()
        with _lock:
            _sources.pop(self.url, None)
        # A reader may be blocked in network IO; never wait on the Qt thread.
        def close():
            for reader in readers:
                reader.close()
        threading.Thread(target=close, name='plugin-media-close', daemon=True).start()


def retain(factory, prepared, owner):
    if not owner._active:
        prepared.close()
        raise RuntimeError('Plugin context is inactive')
    source = MediaSource(factory, prepared, owner)
    url = source.start()
    if not owner._active:
        source.stop()
        raise RuntimeError('Plugin context is inactive')
    return url


def take(url):
    with _lock:
        source = _sources.get(url)
    if source is not None:
        source._timer.cancel()
    return source


def discard(url):
    with _lock:
        source = _sources.get(url)
    if source is not None:
        source.stop()


def revoke(owner):
    with _lock:
        sources = [source for source in _sources.values() if source.owner is owner]
    for source in sources:
        source.stop()
