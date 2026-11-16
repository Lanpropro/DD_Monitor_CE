"""本机 HLS 转发：使用与取流相同的 HTTP/TLS 栈和代理下载清单及分片。"""
import base64
import itertools
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading
import time
from urllib.parse import urljoin, urlsplit
import uuid

import requests


# One-use transfer from source probing to playback; abandoned results expire.
_FLV_HANDOFFS = {}
_FLV_LOCK = threading.Lock()
FLV_HANDOFF_HEADER = "X-DDM-FLV-Handoff"


def retain_flv_response(response, prefix, chunks):
    token = uuid.uuid4().hex
    def expire():
        item = take_flv_response(token)
        if item is not None:
            item[0].close()
    timer = threading.Timer(20, expire)
    timer.daemon = True
    with _FLV_LOCK:
        _FLV_HANDOFFS[token] = (response, prefix, chunks, timer)
    timer.start()
    return token


def take_flv_response(token):
    with _FLV_LOCK:
        item = _FLV_HANDOFFS.pop(token, None)
    if item is not None:
        item[3].cancel()
    return item


class HlsProxy:
    def __init__(self, source, headers, proxy=None, *, diagnostic=None, forward_range=True,
                 initial_response=None, stream_observer=None, session_factory=None):
        self._initial_response = initial_response
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._responses = set()
        self._samples = deque(maxlen=12)
        self.playback_diagnostic = None  # One opt-in numeric observer, detached when capture ends.
        self._idle_sessions = []
        self.refresh_required = threading.Event()
        self.live_ended = threading.Event()
        prefix = "/" + uuid.uuid4().hex + "/"
        relay = self
        proxies = {"http": proxy, "https": proxy} if proxy else None

        def report(url, status, started, attempt, *, local=False, error="", received_bytes=None, last_data_age=None):
            if diagnostic is not None:
                host = urlsplit(url).hostname or ""
                host = host if re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host) else "other"
                metrics = {} if received_bytes is None else {"received_bytes": received_bytes,
                                                              "last_data_age": last_data_age}
                diagnostic(host=host, resource="playlist" if urlsplit(url).path.endswith(".m3u8") else "media",
                    status=status, elapsed=round(time.monotonic() - started, 2), attempt=attempt,
                    local=local, error=error, **metrics)

        def local_url(url):
            if urlsplit(url).scheme not in ("http", "https"):
                raise ValueError("Unsupported HLS resource")
            token = base64.urlsafe_b64encode(url.encode()).decode()
            path = urlsplit(url).path
            suffix = next((extension for extension in (".m3u8", ".mp4", ".m4s", ".aac", ".key")
                           if path.endswith(extension)), ".ts")
            return f"http://127.0.0.1:{relay._server.server_port}{prefix}{token}/resource{suffix}"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # 不记录临时媒体地址

            def do_GET(self):
                if relay._stopped.is_set() or not self.path.startswith(prefix):
                    self.send_error(404)
                    return
                if relay.refresh_required.is_set():
                    report(source, 503, time.monotonic(), 0, local=True, error="refresh_required")
                    self.send_error(503)
                    return
                try:
                    token = self.path[len(prefix):].rsplit("/", 1)[0]
                    url = base64.b64decode(token, altchars=b"-_", validate=True).decode()
                    if urlsplit(url).scheme not in ("http", "https"):
                        raise ValueError("Invalid HLS URL")
                except (ValueError, UnicodeError):
                    self.send_error(404)
                    return
                request_headers = dict(headers)
                if forward_range and self.headers.get("Range"):
                    request_headers["Range"] = self.headers["Range"]
                response = None
                session = None
                observer = None
                outcome = 'closed'
                def observe(event, **values):
                    nonlocal observer
                    capture = relay.playback_diagnostic
                    if capture is not None:
                        numeric = {key: value for key, value in values.items()
                                   if key in ('status', 'elapsed_ms', 'read_ms', 'write_ms', 'bytes')
                                   and isinstance(value, (int, float))}
                        if event == 'chunk':
                            numeric['bytes'] = len(values.get('data', b''))
                        try:
                            capture(event, **numeric)
                        except Exception:
                            if relay.playback_diagnostic is capture:
                                relay.playback_diagnostic = None
                    if observer is not None:
                        try:
                            observer(event, **values)
                        except Exception as error:
                            observer = None  # Diagnostic failure must not alter forwarded bytes.
                            report(url, 0, started, 0, error='Observer_' + type(error).__name__)
                try:
                    # 每个并行请求独占 Session；完成后归还，跨分片复用代理/TLS 连接。
                    with relay._lock:
                        if relay._stopped.is_set():
                            return
                        session = (relay._idle_sessions.pop() if relay._idle_sessions else
                                   session_factory() if session_factory is not None else requests.Session())
                    started = time.monotonic()
                    observed_start = time.perf_counter()
                    if stream_observer is not None:
                        observer = stream_observer(url)
                    observe('request', range=request_headers.get('Range'),
                            user_agent_present=bool(request_headers.get('User-Agent')),
                            referer_present=bool(request_headers.get('Referer')))
                    initial = None
                    with relay._lock:
                        if url == source and relay._initial_response is not None:
                            initial, relay._initial_response = relay._initial_response, None
                    for attempt in range(3):
                        try:
                            response = initial[0] if initial is not None else session.get(
                                url, headers=request_headers, proxies=proxies, stream=True, timeout=(4, 8))
                            response.raise_for_status()
                            peer = tls_version = cipher = None
                            if observer is not None:
                                connection = getattr(response.raw, '_connection', None)
                                sock = getattr(connection, 'sock', None)
                                if sock is not None:
                                    try:
                                        peer = sock.getpeername()
                                        tls_version = sock.version() if hasattr(sock, 'version') else None
                                        cipher_info = sock.cipher() if hasattr(sock, 'cipher') else None
                                        cipher = cipher_info[0] if cipher_info else None
                                    except OSError:
                                        pass  # Some HTTP backends do not expose a live socket.
                            observe('response', status=response.status_code, attempt=attempt + 1,
                                    elapsed_ms=(time.perf_counter() - observed_start) * 1000,
                                    peer=peer, tls_version=tls_version, cipher=cipher,
                                    redirects=[dict(status=item.status_code, host=urlsplit(item.url).hostname)
                                               for item in response.history] if observer is not None else [],
                                    headers={key: response.headers.get(key) for key in
                                             ('Content-Type', 'Content-Length', 'Content-Range',
                                              'Transfer-Encoding', 'Content-Encoding', 'Accept-Ranges', 'Date')})
                            break
                        except requests.RequestException as error:
                            observe('request-error', error=type(error).__name__, exception=error, attempt=attempt + 1,
                                    status=response.status_code if response is not None else 0,
                                    elapsed_ms=(time.perf_counter() - observed_start) * 1000)
                            status = response.status_code if response is not None else 0
                            report(url, status, started, attempt + 1, error=type(error).__name__)
                            playlist = (urlsplit(url).path.endswith(".m3u8") or response is not None and
                                        "mpegurl" in response.headers.get("Content-Type", "").lower())
                            if status in (401, 403) or playlist and status in (404, 410):
                                relay.refresh_required.set()  # 签名失效需重新解析，重试旧地址无效。
                            if 400 <= status < 500 and status not in (408, 429):
                                self.send_error(status)
                                return
                            if response is not None:
                                response.close()
                                response = None
                            if attempt == 2 or relay._stopped.wait(.5 * (attempt + 1)):
                                raise
                    elapsed = time.monotonic() - started  # 计入代理连接、首包等待和请求重试。
                    with relay._lock:
                        if relay._stopped.is_set():
                            return
                        relay._responses.add(response)
                    content_type = response.headers.get("Content-Type", "application/octet-stream")
                    playlist = "mpegurl" in content_type.lower() or urlsplit(response.url).path.endswith(".m3u8")
                    body = b""
                    if playlist:
                        chunks, size = [], 0
                        for chunk in response.iter_content(65536):
                            size += len(chunk)
                            if size > 1024 * 1024:
                                raise ValueError("HLS playlist too large")
                            chunks.append(chunk)
                        text = b"".join(chunks).decode("utf-8-sig")
                        if not text.startswith("#EXTM3U"):
                            raise ValueError("Invalid HLS playlist")
                        lines = []
                        for line in text.splitlines():
                            if line and not line.startswith("#"):
                                line = local_url(urljoin(response.url, line))
                            else:
                                line = re.sub(r'URI="([^"]+)"', lambda match:
                                    'URI="' + local_url(urljoin(response.url, match[1])) + '"', line)
                            lines.append(line)
                        body = ("\n".join(lines) + "\n").encode()
                    self.send_response(response.status_code)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Connection", "close")
                    chunked = not playlist and ("Content-Length" not in response.headers or "Content-Encoding" in response.headers)
                    if playlist:
                        self.send_header("Content-Length", str(len(body)))
                    elif chunked:
                        self.send_header("Transfer-Encoding", "chunked")
                    else:
                        self.send_header("Content-Length", response.headers["Content-Length"])
                    for key in ("Content-Range", "Accept-Ranges"):
                        if not playlist and key in response.headers:
                            self.send_header(key, response.headers[key])
                    self.end_headers()
                    if playlist:
                        self.wfile.write(body)
                    else:
                        size = 0
                        last_data = time.monotonic()
                        chunks = (itertools.chain([initial[1]], initial[2]) if initial is not None
                                  else response.iter_content(65536))
                        while True:
                            reading = time.perf_counter()
                            chunk = next(chunks, None)
                            read_ms = (time.perf_counter() - reading) * 1000
                            elapsed += read_ms / 1000
                            if chunk is None:
                                outcome = 'eof'
                                if initial is not None and not relay._stopped.is_set():
                                    relay.live_ended.set()
                                    report(url, 0, started, 1, error="LIVE_EOF", received_bytes=size,
                                           last_data_age=round(time.monotonic() - last_data, 2))
                                break
                            if relay._stopped.is_set():
                                break
                            if chunk:
                                last_data = time.monotonic()
                                size += len(chunk)
                                observed = time.perf_counter()
                                observe('chunk', data=chunk, read_ms=read_ms)
                                inspection_ms = (time.perf_counter() - observed) * 1000
                                writing = time.perf_counter()
                                self.wfile.write((f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n") if chunked else chunk)
                                observe('delivered', bytes=len(chunk), inspection_ms=inspection_ms,
                                        write_ms=(time.perf_counter() - writing) * 1000)
                        if chunked and not relay._stopped.is_set():
                            self.wfile.write(b"0\r\n\r\n")
                        if size >= 32768 and not relay._stopped.is_set():
                            with relay._lock:
                                relay._samples.append((time.monotonic(), size * 8 / max(elapsed, .001)))
                except (requests.RequestException, OSError, ValueError) as error:
                    outcome = type(error).__name__
                    observe('read-error', error=outcome, exception=error)
                    self.close_connection = True  # FFmpeg 在清单/分片层重试
                finally:
                    observe('end', outcome=outcome, stopped=relay._stopped.is_set())
                    if response is not None:
                        with relay._lock:
                            relay._responses.discard(response)
                        response.close()
                    if session is not None:
                        with relay._lock:
                            close = relay._stopped.is_set() or relay.refresh_required.is_set()
                            if not close:
                                relay._idle_sessions.append(session)
                        if close:
                            session.close()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._server.timeout = .05
        self.url = local_url(source)
        self._thread = threading.Thread(target=self._serve, name="live-hls-proxy", daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            while not self._stopped.is_set():
                self._server.handle_request()
        finally:
            # 监听和闲置连接由服务线程收尾，不让换台/预览等待网络资源关闭。
            try:
                with self._lock:
                    initial, self._initial_response = self._initial_response, None
                    sessions, self._idle_sessions = self._idle_sessions, []
                if initial is not None:
                    initial[0].close()
                for session in sessions:
                    session.close()
            finally:
                self._server.server_close()

    def network_speed(self):
        """最近 30 秒分片有效吞吐的下四分位值；包含连接等待，排除播放器背压。"""
        now = time.monotonic()
        with self._lock:
            rates = sorted(rate for when, rate in self._samples if now - when <= 30)
        return (rates[(len(rates) - 1) // 4], len(rates)) if rates else (0, 0)

    def stop(self):
        # 只发停止信号；服务循环至多等待一次监听超时后自行清理。
        # 活跃 response 仍由请求线程关闭，网络读取按既有超时退出。
        self._stopped.set()
