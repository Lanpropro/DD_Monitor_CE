"""真实 B站2K测试：读取本机登录状态但不保存配置，不输出 Cookie/CDN 地址。"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import bili, config, theme  # noqa: E402
from ddm.player import TilePlayer  # noqa: E402
from ddm.recording import ffmpeg_path  # noqa: E402
from ddm.widgets import Tile  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", default="27183290")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--anonymous", action="store_true")
    args = parser.parse_args()
    bili.set_sessdata("" if args.anonymous else config.load().get("sessdata", ""))
    report = {"time": datetime.now().isoformat(), "room_id": args.room,
              "session_present": bool(bili.SESSION_DATA), "stages": []}
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    tile = Tile({"room_id": args.room, "uname": "B站2K取流测试", "live": True})
    tile.setWindowTitle("DD监控室CE · 2K 测试")
    tile.resize(960, 600)
    player = None
    try:
        info = bili.room_info(args.room) or {}
        report["live"] = bool(info.get("live"))
        assert report["live"], "Room is offline; retry while live"
        options = bili.room_quality_options(args.room)
        report["options"] = options
        print(json.dumps({"options": options}, ensure_ascii=False), flush=True)
        # 不能假设2K的编号固定为15000：目前该房间实际用25000。
        two_k = next(item["qn"] for item in options if "2K" in item["desc"].upper())
        tile.set_quality_options(options)
        tile.show()
        app.processEvents()
        player = TilePlayer(tile.video, tile)
        player.set_muted(True)
        for requested, seconds in ((10000, 10), (two_k, args.seconds), (10000, 10)):
            url, actual, profile, headers = bili.play_url(args.room, requested)
            stage = {"requested": requested, "actual": actual, "profile": profile, "states": []}
            report["stages"].append(stage)
            assert actual == requested, "Server downgraded requested quality"
            probe = subprocess.run([
                str(Path(ffmpeg_path()).with_name("ffprobe.exe")), "-v", "error",
                "-rw_timeout", "15000000", "-headers",
                "".join(f"{key}: {value}\r\n" for key, value in headers.items()), "-i", url,
                "-show_entries", "stream=codec_name,codec_type,width,height,r_frame_rate",
                "-of", "json"], capture_output=True, text=True, timeout=30)
            assert probe.returncode == 0, "FFprobe failed (CDN address omitted)"
            stage["streams"] = json.loads(probe.stdout)["streams"]
            video = next(s for s in stage["streams"] if s["codec_type"] == "video")
            expected = (video["width"], video["height"])
            if requested == two_k:
                assert expected == (2560, 1440), expected
            tile.set_quality(requested)
            tile.set_actual_quality(actual)
            callback = lambda state: stage["states"].append(state)
            player.stateChanged.connect(callback)
            try:
                player.play(url, profile=profile, headers=headers)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    app.processEvents()
                    signature = player._picture_signature()
                    if player.player.video_get_size(0) == expected and signature and signature[1] > 5:
                        break
                    QTest.qWait(50)
                else:
                    raise AssertionError("VLC did not display requested resolution")
                start = player._picture_signature()
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    app.processEvents()
                    QTest.qWait(50)
                finish = player._picture_signature()
                stage["vlc_size"] = player.player.video_get_size(0)
                stage["decoded_delta"] = finish[0] - start[0]
                stage["displayed_delta"] = finish[1] - start[1]
                stage["observed_seconds"] = seconds
                assert stage["displayed_delta"] > seconds * 15, stage
                assert not any(s in ("error", "frozen", "ended") for s in stage["states"]), stage
                print(json.dumps(stage, ensure_ascii=False), flush=True)
            finally:
                player.stateChanged.disconnect(callback)
        report["passed"] = True
    finally:
        if player:
            player.release()
        tile.close()
        app.processEvents()
        output = REPO / "logs" / ("bili-2k-live-" + datetime.now().strftime("%Y-%m-%d-%H%M%S") + ".json")
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("REPORT", output, flush=True)
    print("PASS: live 1080P -> 2K -> 1080P, FFprobe and native VLC", flush=True)


if __name__ == "__main__":
    main()
