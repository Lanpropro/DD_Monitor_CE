"""本机 HLS 转发：使用与取流相同的 HTTP/TLS 栈和代理下载清单及分片。"""
import base64
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading
import time
from urllib.parse import urljoin, urlsplit
import uuid

import requests


class HlsProxy:
    def __init__(self, source, headers, proxy=None):
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._responses = set()
        self._samples = deque(maxlen=12)
        prefix = "/" + uuid.uuid4().hex + "/"
        relay = self
        proxies = {"http": proxy, "https": proxy} if proxy else None

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
                try:
                    token = self.path[len(prefix):].rsplit("/", 1)[0]
                    url = base64.b64decode(token, altchars=b"-_", validate=True).decode()
                    if urlsplit(url).scheme not in ("http", "https"):
                        raise ValueError("Invalid HLS URL")
                except (ValueError, UnicodeError):
                    self.send_error(404)
                    return
                request_headers = dict(headers)
                if self.headers.get("Range"):
                    request_headers["Range"] = self.headers["Range"]
                response = None
                try:
                    for attempt in range(3):
                        try:
                            response = requests.get(url, headers=request_headers, proxies=proxies,
                                stream=True, timeout=(4, 8))
                            response.raise_for_status()
                            break
                        except requests.RequestException:
                            if response is not None:
                                response.close()
                            if attempt == 2 or relay._stopped.wait(.5 * (attempt + 1)):
                                raise
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
                        size, elapsed = 0, 0
                        chunks = response.iter_content(65536)
                        while True:
                            reading = time.monotonic()
                            chunk = next(chunks, None)
                            elapsed += time.monotonic() - reading
                            if chunk is None:
                                break
                            if relay._stopped.is_set():
                                break
                            if chunk:
                                size += len(chunk)
                                self.wfile.write((f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n") if chunked else chunk)
                        if chunked and not relay._stopped.is_set():
                            self.wfile.write(b"0\r\n\r\n")
                        if size >= 32768 and not relay._stopped.is_set():
                            with relay._lock:
                                relay._samples.append((time.monotonic(), size * 8 / max(elapsed, .001)))
                except (requests.RequestException, OSError, ValueError):
                    self.close_connection = True  # FFmpeg 在清单/分片层重试
                finally:
                    if response is not None:
                        with relay._lock:
                            relay._responses.discard(response)
                        response.close()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = local_url(source)
        self._thread = threading.Thread(target=self._server.serve_forever,
            kwargs={"poll_interval": .05}, name="live-hls-proxy", daemon=True)
        self._thread.start()

    def network_speed(self):
        """最近 30 秒分片载荷的下四分位吞吐；排除连接等待和播放器背压。"""
        now = time.monotonic()
        with self._lock:
            rates = sorted(rate for when, rate in self._samples if now - when <= 30)
        return (rates[(len(rates) - 1) // 4], len(rates)) if rates else (0, 0)

    def stop(self):
        if self._stopped.is_set():
            return
        self._stopped.set()
        # 由请求线程关闭 response；跨线程 close 会等待读锁，阻塞窗口关闭。
        # 停止后不重试/不再写数据，正在进行的网络读取由上述有界超时退出。
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
