"""离线真实 HTTP 验证 HLS 清单重写、分片、请求头、重试和本机清理。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import gzip
from pathlib import Path
import sys
import threading

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm.hls_proxy import HlsProxy  # noqa: E402


def main():
    attempts, headers = [], []
    class Origin(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_GET(self):
            attempts.append(self.path)
            headers.append(dict(self.headers))
            if self.path.startswith("/dir/live.m3u8"):
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
                if self.path.startswith("/gzip.ts"):
                    body = gzip.compress(body)
                    self.send_header("Content-Encoding", "gzip")
                if self.headers.get("Range"):
                    self.send_header("Content-Range", "bytes 0-15/16")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
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
        assert "/key.bin?key=public" in attempts and "/video.ts?signature=public" in attempts
        assert all(item["Referer"] == "https://www.twitch.tv/" for item in headers)
        assert requests.get(proxy.url.replace(proxy.url.split("/")[3], "wrong", 1), timeout=3).status_code == 404
        assert requests.get(proxy.url.rsplit("/", 2)[0] + "/%%%/resource.ts", timeout=3).status_code == 404
    finally:
        proxy.stop()
        proxy.stop()
        server.shutdown()
        server.server_close()
        thread.join()
    assert not proxy._thread.is_alive() and proxy._server.socket.fileno() == -1
    assert not proxy._responses
    print("PASS: loopback HLS, retry, relative/signed/key URLs, headers/ranges and idempotent cleanup")


if __name__ == "__main__":
    main()
