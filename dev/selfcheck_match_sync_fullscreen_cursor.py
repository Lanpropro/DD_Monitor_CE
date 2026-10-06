"""Match fullscreen reuses the host idle cursor and restores it on every exit."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from ddm import fullscreen_cursor, plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as root, \
            patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda self: None):
        host = QWidget()
        host.settings = {}
        manager = plugins.PluginManager(window=host, plugins_dir=root)
        viewer = module.Viewer(plugins.PluginContext(manager, "cursor_check"), {})
        try:
            viewer.add_room("1")
            viewer.show()
            for exit_mode in ("toggle", "escape", "stop", "close"):
                viewer._fullscreen_picture()
                app.processEvents()
                dialog = viewer.fullscreen_dialog
                cursor = getattr(dialog, "_fullscreen_cursor", None)
                assert isinstance(cursor, fullscreen_cursor.FullscreenCursor), "Match fullscreen has no host idle cursor"
                assert cursor.timer.isActive()
                point = viewer.picture.video.mapToGlobal(viewer.picture.video.rect().center())
                now = [100.0]
                active = [True]
                with patch.object(dialog, "isActiveWindow", side_effect=lambda: active[0]), \
                        patch.object(fullscreen_cursor.QCursor, "pos", return_value=point) as position, \
                        patch.object(fullscreen_cursor.time, "monotonic", side_effect=lambda: now[0]):
                    cursor.start()
                    now[0] += 3.1
                    cursor.update_cursor()
                    assert cursor.hidden and QApplication.overrideCursor().shape() == Qt.BlankCursor
                    assert viewer.picture._fullscreen_controls_hidden
                    viewer.sync_picture()
                    viewer.picture.set_controls_visible(True)
                    assert not viewer.picture.controls.isVisible()
                    position.return_value = point + type(point)(10, 0)
                    cursor.update_cursor()
                    assert not cursor.hidden and QApplication.overrideCursor() is None
                    now[0] += 3.1
                    cursor.update_cursor()
                    assert cursor.hidden
                    active[0] = False
                    cursor.update_cursor()
                    assert not cursor.hidden, "Losing focus must restore cursor"
                    active[0] = True
                    now[0] += 3.1
                    cursor.update_cursor()
                    assert cursor.hidden
                    with patch.object(QApplication, "activePopupWidget", return_value=viewer.picture):
                        cursor.update_cursor()
                        assert not cursor.hidden, "Menus must keep their cursor"
                    now[0] += 3.1
                    cursor.update_cursor()
                    assert cursor.hidden
                    with patch.object(QApplication, "activeModalWidget", return_value=dialog):
                        cursor.update_cursor()
                        assert not cursor.hidden, "Modal dialogs must keep their cursor"
                    now[0] += 3.1
                    cursor.update_cursor()
                    assert cursor.hidden
                    if exit_mode == "toggle":
                        viewer._fullscreen_picture()
                    elif exit_mode == "escape":
                        QTest.keyClick(dialog, Qt.Key_Escape)
                    elif exit_mode == "stop":
                        viewer.stop()
                    else:
                        viewer.close()
                    assert viewer.fullscreen_dialog is None
                    assert not cursor.hidden and not cursor.timer.isActive()
                    assert QApplication.overrideCursor() is None
                    assert not viewer.picture._fullscreen_controls_hidden
                    assert viewer.body_split.widget(0) is viewer.picture
            print("PASS: host cursor idle/move/focus/menu/modal behavior; toggle/Esc/stop/close restore cursor, controls and picture")
        finally:
            viewer.close()
            host.close()
            app.processEvents()


if __name__ == "__main__":
    main()
