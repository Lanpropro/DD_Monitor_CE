"""一次性验证：真的能收到直播间的弹幕（需要联网）。

从配置里的关注列表挑一个正在直播、人气最高的房间，接上弹幕跑 25 秒，
收到消息就算通过。也可以手动指定房间号。
"""
import os
import sys
import time

from PySide6.QtCore import QCoreApplication, QTimer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import bili, config as config_module  # noqa: E402
from ddm.danmaku import DanmakuClient, IMPORT_ERROR, blivedm  # noqa: E402


def pick_room() -> tuple[str, str]:
    if len(sys.argv) > 1:
        room_id = sys.argv[1]
        info = bili.room_info(room_id) or {}
        return room_id, info.get("uname", "")
    state = config_module.load()
    best = ("", "", -1.0)
    for room_id in (state.get("rooms") or [])[:20]:
        info = bili.room_info(str(room_id)) or {}
        if not info.get("live"):
            continue
        viewers = str(info.get("viewers") or "0")
        try:
            score = float(viewers.replace("万", "e4"))
        except ValueError:
            score = 0.0
        print(f"  {info.get('uname')}: 直播中，人气 {viewers}")
        if score > best[2]:
            best = (str(room_id), info.get("uname", ""), score)
    return best[0], best[1]


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if blivedm is None:
        print(f"blivedm 不可用：{IMPORT_ERROR}")
        return 1

    # 跟程序启动时一样：把配置里的登录态装上，否则服务端会说"未登录"
    state = config_module.load()
    bili.set_sessdata(state.get("sessdata", ""))
    print(f"登录态：{'已带上 SESSDATA' if bili.SESSION_DATA else '未登录（用户名会被打码）'}")

    print("挑一个正在直播的房间…")
    room_id, uname = pick_room()
    if not room_id:
        print("关注列表里现在没有直播中的房间，可以手动传房间号")
        return 1
    print(f"用 {uname}（房间 {room_id}）试弹幕")

    received: list = []
    statuses: list = []
    app = QCoreApplication(sys.argv)
    client = DanmakuClient(room_id)
    client.message.connect(lambda kind, user, text: received.append((kind, user, text)))
    client.status.connect(lambda text: (statuses.append(text), print(f"  状态：{text}")))
    client.start()

    started = time.time()
    QTimer.singleShot(25000, app.quit)
    app.exec()
    client.stop()
    client.wait(3000)

    seconds = int(time.time() - started)
    print(f"\n状态变化：{statuses}")
    print(f"{seconds} 秒内共收到 {len(received)} 条消息")
    for kind, user, text in received[:15]:
        print(f"  [{kind}] {user}：{text}")
    if not received:
        print("没收到任何弹幕")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
