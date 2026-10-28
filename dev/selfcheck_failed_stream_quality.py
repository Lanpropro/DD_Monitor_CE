"""Failed plugin playback must leave a usable quality menu; synthetic data only."""
import os
import sys
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from ddm.bili import StreamResolver
from ddm.widgets import Tile

app = QApplication.instance() or QApplication([])
for menu in ([{"qn": 1014100, "desc": "2K HDR"}], RuntimeError("menu unavailable")):
    platform = Mock()
    platform.play_url.side_effect = RuntimeError("fixture HTTP 403")
    if isinstance(menu, Exception):
        platform.room_quality_options.side_effect = menu
    else:
        platform.room_quality_options.return_value = menu
    resolver = StreamResolver("huya:fixture", 1014100, platform=platform)
    errors = []
    resolver.failed.connect(lambda rid, reason: errors.append(reason))
    resolver.run()
    assert errors == ["fixture HTTP 403"], errors
    assert resolver.failure_quality_options[0]["qn"] == 10000
    tile = Tile({"room_id": "huya:fixture", "live": True, "quality": 1014100})
    tile.set_quality_options(resolver.failure_quality_options)
    assert ("最高可用", 10000) in tile._quality_choices()
    changed = []
    tile.qualityChanged.connect(lambda room, qn: changed.append(qn))
    tile.set_quality(10000)
    assert changed == [10000]
    assert "获取画质" not in tile.quality_button.text()
    tile.close()
platform = Mock()
resolver = StreamResolver("huya:fixture", platform=platform)
resolver.cancel()
resolver.run()
platform.room_quality_options.assert_not_called()
assert resolver.failure_quality_options == []
print("PASS: failed stream retains menu, menu failure preserves original error, highest quality selectable, cancellation ignored")
