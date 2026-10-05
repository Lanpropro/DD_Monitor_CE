"""本机 HTTP 代理验收：并发连接复用、故障分类、播放器重连和停止清理。"""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(REPO / "libvlc.dll"))
from ddm import hls_proxy, player, stream_relay  # noqa: E402


def main():
    requests_seen, sessions, closed = [], [], set()
    parallel = threading.Barrier(2)
    reading, release = threading.Event(), threading.Event()
    body = b"x" * 65536
    original_session = requests.Session

    class Session(original_session):
        def __init__(self):
            super().__init__()
            self.busy = False
            sessions.append(self)

        def get(self, *args, **kwargs):
            assert not self.busy, "Concurrent requests must not share a mutable Session"
            self.busy = True
            try:
                response = super().get(*args, **kwargs)
                original_close = response.close
                def close():
                    original_close()
                    self.busy = False
                response.close = close
                return response
            except Exception:
                self.busy = False
                raise

        def close(self):
            closed.add(id(self))
            super().close()

    class Origin(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle(self):
            try:
                super().handle()
            except ConnectionError:
                pass  # 停止转发及拒绝响应后关闭连接属于预期行为。

        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests_seen.append(self.path)
            path = urlsplit(self.path).path
            status = {"/expired.m3u8": 403, "/gone.m3u8": 410, "/missing.ts": 404}.get(path, 200)
            if path == "/busy.ts" and requests_seen.count(self.path) == 1:
                status = 429
            if path == "/failure.ts" and requests_seen.count(self.path) == 1:
                status = 503
            if path.startswith("/parallel"):
                parallel.wait(3)
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if path == "/blocked.ts":
                self.wfile.flush()
                reading.set()
                release.wait(3)
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy_address = f"http://127.0.0.1:{server.server_port}"

    def make(path):
        # cdn.invalid 无法直连；请求成功证明显式代理没有被本机 HLS 转发丢掉。
        return hls_proxy.HlsProxy("http://cdn.invalid" + path, {}, proxy_address)

    try:
        with patch.object(hls_proxy.requests, "Session", Session):
            for path in ("/busy.ts", "/failure.ts"):
                relay = make(path)
                try:
                    assert requests.get(relay.url, timeout=4).content == body
                    assert requests_seen.count("http://cdn.invalid" + path) == 2
                    assert not relay.refresh_required.is_set()
                    assert relay.network_speed()[0] < len(body) * 8 / .45, "Retry backoff must affect throughput"
                finally:
                    relay.stop()
            for path, status, refresh in (("/expired.m3u8", 403, True),
                    ("/gone.m3u8", 410, True), ("/missing.ts", 404, False)):
                relay = make(path)
                try:
                    assert requests.get(relay.url, timeout=3).status_code == status
                    assert requests_seen.count("http://cdn.invalid" + path) == 1
                    assert relay.refresh_required.is_set() == refresh
                    if refresh:
                        assert requests.get(relay.url, timeout=3).status_code == 503
                        assert requests_seen.count("http://cdn.invalid" + path) == 1
                        remux = SimpleNamespace(_lock=threading.Lock(), _stopped=False,
                            _process=None, _hls_proxy=relay)
                        remux.needs_restart = lambda: stream_relay.StreamRelay.needs_restart(remux)
                        states = []
                        tile = SimpleNamespace(paused=False, _relay=remux, _set_state=states.append)
                        player.TilePlayer._check(tile)
                        assert states == ["error"], "Expired URL must enter the existing re-resolve path immediately"
                        tile.paused = True
                        player.TilePlayer._check(tile)
                        assert states == ["error"], "Paused playback must not reconnect"
                finally:
                    relay.stop()
            relays = [make("/parallel1.ts"), make("/parallel2.ts")]
            # 一路内的不同分片也可能同时下载；两个请求必须分别借用 Session。
            first, second = relays
            second_url = second.url.replace(second.url.split("/")[3], first.url.split("/")[3])
            second_url = second_url.replace(str(second._server.server_port), str(first._server.server_port), 1)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    responses = list(pool.map(lambda url: requests.get(url, timeout=4), (first.url, second_url)))
                assert all(response.content == body for response in responses)
                assert len(first._idle_sessions) == 2
            finally:
                for relay in relays:
                    relay.stop()
            relay = make("/blocked.ts")
            def fetch():
                try:
                    requests.get(relay.url, timeout=4)
                except requests.RequestException:
                    pass  # 停止中途断开，不能留下借出的 Session。
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(fetch)
                try:
                    assert reading.wait(2)
                    started = time.monotonic()
                    relay.stop()
                    assert time.monotonic() - started < .5, "Stop must not close active network reads on the GUI thread"
                finally:
                    release.set()
                    relay.stop()
                future.result(timeout=3)
            deadline = time.monotonic() + 2
            while relay._responses and time.monotonic() < deadline:
                time.sleep(.01)
            assert not relay._responses and not relay._idle_sessions
            assert {id(session) for session in sessions} == closed
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)
    print("PASS: explicit proxy, 429/503 recovery, expired URL refresh, missing segment, concurrent Sessions and nonblocking cleanup")


if __name__ == "__main__":
    main()
