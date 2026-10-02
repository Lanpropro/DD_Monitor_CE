"""联网验收：三平台真实弹幕、持续心跳与及时退出；不修改用户配置。"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
from PySide6.QtCore import QCoreApplication  # noqa: E402
from ddm.plugins import PluginManager  # noqa: E402


def main():
    app = QCoreApplication([])
    manager = PluginManager(enabled=["huya_watch"])
    manager.load()
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 70
    room_ids = sys.argv[2:] or ["huya:998", "douyu:36252", "douyin:557481980778"]
    clients, counts, statuses = [], {}, {}
    try:
        for room_id in room_ids:
            counts[room_id], statuses[room_id] = 0, []
            client = manager.platform_for(room_id).danmaku_client(room_id)
            def on_message(event, room_id=room_id):
                assert event["kind"] == "danmaku" and event["text"] and "uname" in event
                counts[room_id] += 1
            def on_status(text, room_id=room_id):
                statuses[room_id].append(text)
                print(room_id, text, flush=True)
            client.message.connect(on_message)
            client.status.connect(on_status)
            clients.append(client)
            client.start()
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
    finally:
        started = time.monotonic()
        for client in clients:
            client.stop()
        for client in clients:
            assert client.wait(2000), f"连接未及时退出：{client.room_id}"
            assert client._loop is None and client._task is None
        print(f"停止耗时：{time.monotonic() - started:.3f}s", flush=True)
    for room_id in room_ids:
        assert counts[room_id] > 0, f"没有收到真实弹幕：{room_id}"
        assert statuses[room_id].count("已连接") == 1, statuses[room_id]
        assert not any("重连" in text or "出错" in text for text in statuses[room_id]), statuses[room_id]
        print(f"PASS: {room_id}, {duration:g}s, {counts[room_id]} 条真实弹幕", flush=True)


if __name__ == "__main__":
    main()
