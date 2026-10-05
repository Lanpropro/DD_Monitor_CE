"""真实本地 HLS/FFmpeg 验收海外二路代理、旧地址刷新和停止清理。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication  # noqa: E402
from ddm import global_danmaku, hls_proxy, plugins, recording  # noqa: E402
from plugins_user._match_sync import media  # noqa: E402


def main():
    app = QCoreApplication([])
    executable = recording.ffmpeg_path()
    assert executable
    captured, requests_seen = [], []
    original_proxy = hls_proxy.HlsProxy

    def proxy(*args):
        result = original_proxy(*args)
        captured.append(result)
        return result

    with tempfile.TemporaryDirectory(prefix="ddm_overseas_hls_") as root:
        subprocess.run([executable, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
            "-c:a", "aac", "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
            str(Path(root) / "live.m3u8")], capture_output=True, check=True,
            timeout=25, creationflags=recording._FFMPEG_FLAGS)

        class Origin(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def handle(self):
                try:
                    super().handle()
                except ConnectionError:
                    pass

            def do_GET(self):
                requests_seen.append(self.path)
                path = urlsplit(self.path).path
                if path == "/expired.m3u8":
                    self.send_error(403)
                    return
                if path == "/live.m3u8" and requests_seen.count(self.path) == 1:
                    self.send_error(503)
                    return
                body = (Path(root) / path.lstrip("/")).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl" if path.endswith(".m3u8") else "video/mp2t")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for kind in ("twitch", "youtube"):
                platform = plugins.Platform()
                platform.kind = kind
                rid = kind + ":test"
                platform.room_info = lambda _rid: plugins.RoomInfo(_rid, uname="合成海外直播")
                platform.play_url = lambda _rid, qn: ("http://cdn.invalid/live.m3u8", qn, kind, {})
                decoder = media.Decoder(rid, {"url": "http://cdn.invalid/expired.m3u8", "quality": 10000}, platform)
                resets, states = [], []
                decoder.events.reset.connect(lambda: resets.append(True))
                decoder.events.state.connect(states.append)
                with patch.object(global_danmaku, "request_proxy", return_value=f"http://127.0.0.1:{server.server_port}"), \
                        patch.object(hls_proxy, "HlsProxy", side_effect=proxy), \
                        patch.object(platform, "play_url", wraps=platform.play_url) as resolve:
                    try:
                        decoder.start()
                        deadline = time.monotonic() + 8
                        while time.monotonic() < deadline:
                            app.processEvents()
                            if len(decoder.history.frames) >= 30 and decoder.history.audio.end > 48000:
                                break
                            time.sleep(.02)
                        assert len(decoder.history.frames) >= 30 and decoder.history.audio.end > 48000
                        assert resets == [True] and resolve.call_count == 1
                        assert any("地址已失效" in state for state in states), states
                        assert captured[-2].refresh_required.is_set()
                        assert decoder.source_url == "http://cdn.invalid/live.m3u8", "Crop fallback must retain the original source"
                        assert decoder.process.poll() is None
                    finally:
                        decoder.stop()
                        decoder.thread.join(4)
                        assert not decoder.thread.is_alive() and decoder.process is None
                assert all(not relay._thread.is_alive() and not relay._idle_sessions for relay in captured)
                print(f"PASS: {kind} real HLS/PCM/JPEG via explicit proxy, expired address refresh and cleanup")
            assert all(url.startswith("http://cdn.invalid/") for url in requests_seen)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    main()
