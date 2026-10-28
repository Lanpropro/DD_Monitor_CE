"""离线真实 HTTP 验证 HLS 清单重写、分片、请求头、重试和本机清理。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import gzip
from pathlib import Path
import sys
import threading
import time

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm.hls_proxy import HlsProxy, retain_flv_response, take_flv_response  # noqa: E402


def main():
    attempts, headers, connections = [], [], []
    class Origin(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def handle(self):
            try:
                super().handle()
            except ConnectionError:
                pass  # 测试主动关闭持久连接，Windows 会报告连接重置。
        def log_message(self, *_args):
            pass
        def do_GET(self):
            attempts.append(self.path)
            headers.append(dict(self.headers))
            connections.append(self.client_address)
            if self.path == "/late.m3u8":
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                body = b'#EXTM3U\n#EXTINF:6,\nvideo.ts\n#EXTINF:6,\ndenied.ts?private-signature=never-log\n'
            elif self.path.startswith("/denied.ts"):
                self.send_response(403)
                body = b"forbidden"
            elif self.path.startswith("/dir/live.m3u8"):
                if attempts.count(self.path) == 1:
                    self.send_response(503)
                    body = b"temporary"
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    body = b'#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-KEY:METHOD=AES-128,URI="../key.bin?key=public"\n#EXTINF:6,\n../video.ts?signature=public\n'
            else:
                self.send_response(206 if self.headers.get("Range") else 200)
                self.send_header("Content-Type", "application/octet-stream")
                body = b"key" if self.path.startswith("/key.bin") else b"transport stream"
                if self.path.startswith("/large.ts"):
                    body = b"x" * 65536
                    time.sleep(.08)
                if self.path.startswith("/gzip.ts"):
                    body = gzip.compress(body)
                    self.send_header("Content-Encoding", "gzip")
                if self.headers.get("Range"):
                    self.send_header("Content-Range", "bytes 0-15/16")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.path.startswith("/large.ts"):
                self.wfile.write(body[:32768])
                self.wfile.flush()
                time.sleep(.08)
                self.wfile.write(body[32768:])
            else:
                self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    proxy = HlsProxy(base + "/dir/live.m3u8?session=public", {"Referer": "https://www.twitch.tv/"})
    try:
        assert proxy._server.server_address[0] == "127.0.0.1"
        response = requests.get(proxy.url, timeout=3)
        response.raise_for_status()
        text = response.text
        assert text.startswith("#EXTM3U") and base not in text
        assert attempts.count("/dir/live.m3u8?session=public") == 2
        key = text.split('URI="', 1)[1].split('"', 1)[0]
        segment = next(line for line in text.splitlines() if line.startswith("http"))
        assert segment.endswith(".ts")
        assert requests.get(key, timeout=3).content == b"key"
        response = requests.get(segment, headers={"Range": "bytes=0-15"}, timeout=3)
        assert response.status_code == 206 and response.content == b"transport stream"
        assert response.headers["Content-Range"] == "bytes 0-15/16"
        compressed = segment.replace(segment.split("/")[-2],
            base64.urlsafe_b64encode((base + "/gzip.ts").encode()).decode())
        response = requests.get(compressed, timeout=3)
        assert response.content == b"transport stream" and response.headers["Transfer-Encoding"] == "chunked"
        assert connections[-3] == connections[-2] == connections[-1], "Sequential resources must reuse TCP"
        assert proxy.network_speed() == (0, 0)  # 清单、密钥和小响应不充当测速
        large = segment.replace(segment.split("/")[-2],
            base64.urlsafe_b64encode((base + "/large.ts").encode()).decode())
        assert len(requests.get(large, timeout=3).content) == 65536
        speed, count = proxy.network_speed()
        assert count == 1 and 0 < speed < 65536 * 8 / .14  # 首包及载荷等待都计入，不能高估网速
        with proxy._lock:
            proxy._samples.clear()
            proxy._samples.extend([(time.monotonic() - 31, 1), (time.monotonic(), 100),
                                   (time.monotonic(), 200), (time.monotonic(), 300)])
        assert proxy.network_speed() == (100, 3)  # 丢弃旧样本，取保守分位值
        assert "/key.bin?key=public" in attempts and "/video.ts?signature=public" in attempts
        assert all(item["Referer"] == "https://www.twitch.tv/" for item in headers)
        assert requests.get(proxy.url.replace(proxy.url.split("/")[3], "wrong", 1), timeout=3).status_code == 404
        assert requests.get(proxy.url.rsplit("/", 2)[0] + "/%%%/resource.ts", timeout=3).status_code == 404
        live = HlsProxy(base + "/video.ts?signature=public", {}, forward_range=False)
        try:
            result = requests.get(live.url, headers={"Range": "bytes=0-"}, timeout=3)
            assert result.status_code == 200
            assert "Range" not in headers[-1], "Live FLV must omit player range requests upstream"
        finally:
            live.stop()
        # The source is opened exactly once, including bytes consumed by probing.
        source = base + "/handoff.flv"
        opened = requests.get(source, stream=True, timeout=3)
        chunks = opened.iter_content(4)
        prefix = next(chunks)
        token = retain_flv_response(opened, prefix, chunks)
        initial = take_flv_response(token)
        assert take_flv_response(token) is None
        transferred = HlsProxy(source, {}, forward_range=False, initial_response=initial)
        try:
            result = requests.get(transferred.url, headers={"Range": "bytes=0-"}, timeout=3)
            assert result.content == b"transport stream", result.content
            assert attempts.count("/handoff.flv") == 1
            assert transferred.live_ended.is_set(), "Live EOF must be visible to the player"
        finally:
            transferred.stop()
        opened = requests.get(source, stream=True, timeout=3)
        token = retain_flv_response(opened, b"", iter(()))
        initial = take_flv_response(token)
        abandoned = HlsProxy(source, {}, initial_response=initial)
        abandoned.stop()
        assert opened.raw.closed
        events = []
        late = HlsProxy(base + '/late.m3u8', {}, diagnostic=lambda **event: events.append(event))
        try:
            segments = [line for line in requests.get(late.url, timeout=3).text.splitlines() if line.startswith('http')]
            assert requests.get(segments[0], timeout=3).status_code == 200
            assert requests.get(segments[1], timeout=3).status_code == 403
            assert late.refresh_required.is_set()
            assert requests.get(late.url, timeout=3).status_code == 503
            assert [(e['status'], e['local']) for e in events] == [(403, False), (503, True)]
            assert events[0]['resource'] == 'media' and events[0]['host'] == '127.0.0.1'
            assert 'private-signature' not in str(events) and 'never-log' not in str(events)
            # 一路拒绝不应污染其他转发实例，也不重试已失效的签名。
            assert not proxy.refresh_required.is_set()
            assert requests.get(segment, timeout=3).status_code == 200
            assert attempts.count('/denied.ts?private-signature=never-log') == 1
        finally:
            late.stop()
    finally:
        proxy.stop()
        proxy.stop()
        server.shutdown()
        server.server_close()
        thread.join()
    assert not proxy._thread.is_alive() and proxy._server.socket.fileno() == -1
    assert not proxy._responses
    assert not proxy._idle_sessions
    print("PASS: loopback HLS, persistent TCP, first-byte throughput, retry, URLs/headers/ranges and cleanup")


if __name__ == "__main__":
    main()
