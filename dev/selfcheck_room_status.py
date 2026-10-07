"""离线回归：批量状态必须按房间号刷新，下播状态不能沿用旧值。"""
import os
import sys
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import bili  # noqa: E402


class Response:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def main() -> None:
    app = QCoreApplication([])
    calls = []

    def get(_url, *, params, **_kwargs):
        calls.append(params)
        return Response({"code": 0, "data": {"by_room_ids": {
            "3990387": {"live_status": 0, "uname": "皮特174", "title": "上次直播"},
            "8001": {"live_status": 1, "uname": "其他主播", "online": 12000},
        }}})

    with patch.object(bili.requests, "get", side_effect=get), \
         patch.object(bili.requests, "post", side_effect=AssertionError("不应按 UID 查状态")):
        status = bili.rooms_status(["3990387", "8001"])
    assert len(calls) == 1
    assert ("room_ids", "3990387") in calls[0]
    assert ("room_ids", "8001") in calls[0]
    assert status["3990387"]["live"] is False
    assert status["3990387"]["viewers"] == ""
    assert status["8001"]["live"] is True
    assert status["8001"]["viewers"] == "1.2万"

    with patch.object(bili.requests, "get", return_value=Response({"code": 0, "data": {
            "by_room_ids": {"8001": {"live_status": 1, "uid": 123, "uname": "test"}}}})), \
            patch.object(bili, "_faces_by_room", return_value={"8001": "https://test/avatar.jpg"}) as faces:
        assert bili.rooms_status(["8001"])["8001"]["face"] == "https://test/avatar.jpg"
        faces.assert_called_once_with([123])
    assert bili.rooms_status([]) == {}

    with patch.object(bili.requests, "get", return_value=Response({"code": -412})):
        try:
            bili.rooms_status(["3990387"])
        except RuntimeError as error:
            assert "-412" in str(error)
        else:
            raise AssertionError("接口失败时不能静默保留旧的直播状态")
    events = []
    poller = bili.StatusPoller(["8001"])
    poller.updated.connect(lambda data: events.append(("updated", data)))
    poller.status_ready.connect(lambda: events.append(("ready", None)))
    def fill_faces(data, uids):
        assert events[-1][0] == "ready", "状态完成信号必须先于头像补充"
        data["8001"]["face"] = "test-avatar"
    with patch.object(bili, "_rooms_status_base", return_value=({"8001": {"live": True}}, {"8001": 123})), \
            patch.object(bili, "_fill_faces", side_effect=fill_faces):
        poller.run()
    assert [kind for kind, data in events] == ["updated", "ready", "updated"]
    assert "face" not in events[0][1]["8001"] and events[2][1]["8001"]["face"] == "test-avatar"
    events.clear()
    with patch.object(bili, "_rooms_status_base", side_effect=RuntimeError("test failure")), \
            patch.object(bili, "_fill_faces"):
        poller.run()
    assert events == [("ready", None)], "查询失败也必须结束刷新阶段"
    print("按房间号刷新、下播/失败提示及头像补充前结束状态刷新：通过")


if __name__ == "__main__":
    main()
