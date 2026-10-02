"""离线自检：转封装只复制音视频、仅监听本机、结束与换流清理进程。"""
import io
import os
from pathlib import Path
import sys
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import stream_relay  # noqa: E402


class Process:
    def __init__(self):
        self.stdout = io.BytesIO(b"FLV" + b"test" * 100)
        self.returncode = None
        self.killed = 0

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed += 1
        self.returncode = -1

    def wait(self):
        return self.returncode


def main():
    process = Process()
    with patch.object(stream_relay, "ffmpeg_path", return_value="mock-ffmpeg"), \
            patch.object(stream_relay, "_adopt_process") as adopt, \
            patch.object(stream_relay.subprocess, "Popen", return_value=process) as start:
        relay = stream_relay.StreamRelay("https://cdn.test/live.m3u8", {"Referer": "https://www.huya.com/"})
        try:
            assert relay._server.server_address[0] == "127.0.0.1"
            bad = requests.get(relay.url + "-wrong", timeout=2)
            assert bad.status_code == 404 and not start.called
            good = requests.get(relay.url, timeout=2)
            assert good.content.startswith(b"FLV")
            command = start.call_args.args[0]
            assert command[command.index("-c") + 1] == "copy"
            assert command[command.index("-i") + 1] == "https://cdn.test/live.m3u8"
            assert "Referer: https://www.huya.com/\r\n" in command
            assert command[-1] == "pipe:1" and "-map" in command
            assert start.call_args.kwargs["stderr"] is stream_relay.subprocess.DEVNULL
            assert start.call_args.kwargs["stdin"] is stream_relay.subprocess.DEVNULL
            if os.name == "nt":
                assert start.call_args.kwargs["creationflags"] == stream_relay.subprocess.CREATE_NO_WINDOW
            adopt.assert_called_once_with(process)
            assert requests.get(relay.url, timeout=2).status_code == 404
        finally:
            relay.stop()
            relay.stop()
        assert process.killed == 1 and not relay._thread.is_alive()
        assert relay._server.socket.fileno() == -1
    with patch.object(stream_relay, "ffmpeg_path", return_value="mock-ffmpeg"), \
            patch.object(stream_relay.subprocess, "Popen") as start:
        relay = stream_relay.StreamRelay("https://cdn.test/live.m3u8", {})
        relay.stop()
        start.assert_not_called()
    process = Process()
    with patch.object(stream_relay, "ffmpeg_path", return_value="mock-ffmpeg"), \
            patch.object(stream_relay, "_adopt_process"), \
            patch.object(stream_relay.subprocess, "Popen", return_value=process) as start:
        relay = stream_relay.StreamRelay("https://cdn.test/live.m3u8", {},
                                        proxy="http://127.0.0.1:7890", hls_retry=True)
        try:
            assert requests.get(relay.url, timeout=2).content.startswith(b"FLV")
            command = start.call_args.args[0]
            assert command[command.index("-i") + 1] == relay._hls_proxy.url
            assert "-http_proxy" not in command
            for option, value in (("-http_persistent", "0"),
                    ("-http_multiple", "1"), ("-seg_max_retry", "3"), ("-reconnect_on_network_error", "1")):
                assert command[command.index(option) + 1] == value
        finally:
            relay.stop()
        assert not relay._thread.is_alive() and process.poll() is not None
        assert not relay._hls_proxy._thread.is_alive()
    with patch.object(stream_relay, "ffmpeg_path", return_value=""):
        try:
            stream_relay.StreamRelay("https://cdn.test/live.m3u8", {})
        except RuntimeError as error:
            assert "FFmpeg" in str(error)
        else:
            raise AssertionError("缺少 FFmpeg 必须明确提示")
    print("PASS: copy-only remux, loopback access, request headers, hidden process, idempotent cleanup")


if __name__ == "__main__":
    main()
