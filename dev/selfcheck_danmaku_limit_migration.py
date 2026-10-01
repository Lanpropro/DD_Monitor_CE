"""Upgrade the old 300 default once, preserving later choices and other settings."""
import os
import sys
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DDM_NO_SAVE"] = "1"
from ddm.app import MainWindow
from ddm.dialogs import DanmakuSettingsPage


def main():
    app = QApplication(sys.argv)
    with patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        for saved, expected in (({}, 3000), ({"danmaku_max_blocks": 300}, 3000),
                                ({"danmaku_max_blocks": 150}, 150),
                                ({"danmaku_max_blocks": 5000}, 5000),
                                ({"danmaku_max_blocks": 300, "danmaku_retention_version": 1}, 300)):
            saved = {**saved, "danmaku_font_size": 17}
            original_saved = dict(saved)
            window = MainWindow([], [], layout_id="1x2", state={"settings": saved})
            assert window.settings["danmaku_max_blocks"] == expected
            assert window.wall.danmaku.max_blocks == expected
            assert window.settings["danmaku_font_size"] == 17
            page = DanmakuSettingsPage(window.settings)
            assert page.keep_spin.value() == expected
            persisted = window.current_state()["settings"]
            assert persisted["danmaku_retention_version"] == 1
            assert persisted["danmaku_max_blocks"] == expected
            assert saved == original_saved, "Migration mutates the input state"
            window.close()
            window.deleteLater()
            app.processEvents()
    print("Old default migration, settings display and later custom preferences passed")


if __name__ == "__main__":
    main()
