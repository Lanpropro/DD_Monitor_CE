"""离线回归：批量状态必须按房间号刷新，下播状态不能沿用旧值。"""
import os
import sys
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import bili  # noqa: E402


class Response:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def main() -> None:
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

    with patch.object(bili.requests, "get", return_value=Response({"code": -412})):
        try:
            bili.rooms_status(["3990387"])
        except RuntimeError as error:
            assert "-412" in str(error)
        else:
            raise AssertionError("接口失败时不能静默保留旧的直播状态")
    print("按房间号批量刷新、下播状态和接口失败提示：通过")


if __name__ == "__main__":
    main()
