"""Opt-in, read-only check of explicit Bilibili rooms; no playback or messages sent."""
import argparse
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("rooms", nargs="+", help="Explicit Bilibili room IDs to read")
    parser.add_argument("--seconds", type=float, default=25)
    args = parser.parse_args()
    state = json.loads((REPO / "utils" / "config.json").read_text(encoding="utf-8"))
    bili.set_sessdata(state.get("sessdata", ""))
    app = QApplication(sys.argv)
    workers = []
    results = {}
    try:
        for room in args.rooms:
            decoder, chat = Decoder(room), Chat(room)
            entry = results[room] = {"messages": 0, "video_status": "", "chat_status": ""}
            decoder.events.state.connect(lambda value, e=entry: e.update(video_status=value))
            chat.events.state.connect(lambda value, e=entry: e.update(chat_status=value))
            chat.events.message.connect(lambda _event, e=entry: e.update(messages=e["messages"] + 1))
            workers.append((room, decoder, chat))
            decoder.start()
            chat.start()
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        for room, decoder, _chat in workers:
            results[room].update(frames=len(decoder.history.frames),
                                 pcm_frames=decoder.history.audio.end)
    finally:
        for _room, decoder, chat in workers:
            decoder.stop()
            chat.stop()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(
                worker.thread.is_alive() for _, d, c in workers for worker in (d, c)):
            app.processEvents()
            time.sleep(0.02)
    print(json.dumps(results, ensure_ascii=False))
    assert all(e.get("frames", 0) > 20 and e.get("pcm_frames", 0) > 48000
               and e["messages"] > 0 for e in results.values()), "Live media/chat check incomplete"
    assert not any(worker.thread.is_alive() for _, d, c in workers for worker in (d, c))
    print("PASS: explicit live rooms received video, PCM and chat; workers stopped")


if __name__ == "__main__":
    main()
