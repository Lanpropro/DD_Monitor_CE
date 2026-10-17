"""公开直播流转封装：只复制音视频，归一化时间戳后送入格子播放器。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import subprocess
import threading
import uuid

from .recording import _adopt_process, ffmpeg_path


class StreamRelay:
    def __init__(self, source: str, headers: dict, *, proxy=None, hls_retry=False):
        executable = ffmpeg_path()
        if not executable:
            raise RuntimeError("直播播放需要 FFmpeg，请检查程序目录中的 ffmpeg.exe")
        self._lock = threading.Lock()
        self._stopped = False
        self._process = None
        self._hls_proxy = None
        route = "/" + uuid.uuid4().hex + ".flv"
        relay = self
        # 海外本机 HLS 会重试分片；FFmpeg 要等到重试完成，避免提前断流。
        command = [executable, "-nostdin", "-hide_banner", "-loglevel", "error",
                   "-rw_timeout", "30000000" if hls_retry else "10000000"]
        if hls_retry:
            from .hls_proxy import HlsProxy
            self._hls_proxy = HlsProxy(source, headers, proxy)
            source = self._hls_proxy.url
        elif proxy:
            command += ["-http_proxy", proxy]
        if hls_retry:
            # 海外 HLS 经代理时 TLS 连接可能被中途关闭；在取片层恢复，避免刷新格子。
            command += ["-http_persistent", "0", "-http_multiple", "1", "-seg_max_retry", "3", "-reconnect", "1",
                        "-reconnect_streamed", "1", "-reconnect_on_network_error", "1",
                        "-reconnect_on_http_error", "429,5xx", "-reconnect_delay_max", "5"]
        if headers:
            command += ["-headers", "".join(f"{key}: {value}\r\n" for key, value in headers.items())]
        command += ["-i", source, "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                    "-f", "flv", "-flvflags", "no_duration_filesize", "-flush_packets", "1", "pipe:1"]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass                     # 不记录媒体 URL / 签名

            def do_GET(self):
                with relay._lock:
                    if self.path != route or relay._stopped or relay._process is not None:
                        self.send_error(404)
                        return
                    try:
                        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    except OSError:
                        self.send_error(502)
                        return
                    relay._process = process
                    _adopt_process(process)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "video/x-flv")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    while not relay._stopped:
                        chunk = process.stdout.read1(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (OSError, ValueError):
                    pass                 # 换台 / 关闭时 VLC 主动断开
                finally:
                    with relay._lock:
                        if process.poll() is None:
                            process.kill()
                    process.wait()
                    process.stdout.close()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._server.server_port}{route}"
        self._thread = threading.Thread(target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05}, name="live-stream-relay", daemon=True)
        self._thread.start()

    def needs_restart(self):
        """海外地址失效或转封装已退出时，不再等待播放器的缓冲超时。"""
        with self._lock:
            if self._stopped or self._hls_proxy is None:
                return False
            process = self._process
        return self._hls_proxy.refresh_required.is_set() or process is not None and process.poll() is not None

    def stop(self):
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            process = self._process
            if process is not None and process.poll() is None:
                process.kill()
        if process is not None:
            process.wait()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        if self._hls_proxy is not None:
            self._hls_proxy.stop()
