"""Opt-in, read-only receive/picture check of explicit rooms; no messages sent."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DDM_NO_SAVE", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import bili  # noqa: E402
from plugins_user._match_sync.media import Chat, Decoder  # noqa: E402
from plugins_user._match_sync.viewer import Canvas  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("rooms", nargs="+", help="Explicit Bilibili IDs or huya:/douyu: IDs to read")
    parser.add_argument("--seconds", type=float, default=25)
    parser.add_argument("--video-only", action="store_true", help="Measure pictures/PCM without opening chat")
    parser.add_argument("--saved-login", action="store_true", help="Read saved Douyu login cookies without changing them")
    args = parser.parse_args()
    state = json.loads((REPO / "utils" / "config.json").read_text(encoding="utf-8"))
    bili.set_sessdata(state.get("sessdata", ""))
    app = QApplication(sys.argv)
    workers = []
    results = {}
    spec = importlib.util.spec_from_file_location("match_sync_live_platforms", REPO / "plugins_user/domestic_live/plugin.py")
    platforms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(platforms)
    canvases = {}
    try:
        for room in args.rooms:
            platform = platforms.HuyaPlatform() if room.startswith("huya:") else platforms.DouyuPlatform() if room.startswith("douyu:") else None
            if platform is not None and platform.kind == "douyu" and args.saved_login:
                no_save = os.environ.pop("DDM_NO_SAVE", None)
                try:
                    jar = platform._playback_cookies()
                finally:
                    if no_save is not None:
                        os.environ["DDM_NO_SAVE"] = no_save
                platform._playback_cookies = lambda: jar
            assert platform is None or args.video_only, "Platform chat uses the separate chat regression check"
            decoder = Decoder(room, {"highest_quality": True}, platform)
            chat = None if args.video_only else Chat(room)
            entry = results[room] = {"messages": 0, "video_status": "", "chat_status": ""}
            decoder.events.state.connect(lambda value, e=entry: e.update(video_status=value))
            if chat is not None:
                chat.events.state.connect(lambda value, e=entry: e.update(chat_status=value))
                chat.events.message.connect(lambda _event, e=entry: e.update(messages=e["messages"] + 1))
            workers.append((room, decoder, chat))
            canvases[room] = Canvas()
            decoder.start()
            if chat is not None:
                chat.start()
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            app.processEvents()
            for room, decoder, _chat in workers:
                canvases[room].show_at(decoder, time.monotonic() - 2)
            time.sleep(.004)
        for room, decoder, _chat in workers:
            results[room].update(frames=len(decoder.history.frames),
                                 pcm_frames=decoder.history.audio.end,
                                 presented=canvases[room].presented,
                                 diagnostics=decoder.diagnostics())
    finally:
        for _room, decoder, chat in workers:
            decoder.stop()
            if chat is not None:
                chat.stop()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(
                worker.thread.is_alive() for _, d, c in workers for worker in (d, c) if worker is not None):
            app.processEvents()
            time.sleep(0.02)
    print(json.dumps(results, ensure_ascii=False))
    assert all(e.get("frames", 0) > 20 and e.get("pcm_frames", 0) > 48000
               and (args.video_only or e["messages"] > 0) for e in results.values()), "Live media/chat check incomplete"
    assert not any(worker.thread.is_alive() for _, d, c in workers for worker in (d, c) if worker is not None)
    print("PASS: explicit live rooms received video/PCM and any requested chat; workers stopped")


if __name__ == "__main__":
    main()
