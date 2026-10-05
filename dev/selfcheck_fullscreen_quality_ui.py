"""Qt integration for temporary fullscreen quality and its independent setting."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from ddm import config
from ddm.app import MainWindow
from ddm.dialogs import GeneralSettingsPage


def main():
    app = QApplication.instance() or QApplication([])
    requested = []
    rooms = [{"room_id": str(1000 + i), "uname": f"Test {i}", "live": False,
              "quality": 400, "muted": bool(i % 2)} for i in range(6)]
    with patch.object(MainWindow, "start_all", lambda self: None), \
            patch.object(MainWindow, "refresh_status", lambda self: None), \
            patch.object(MainWindow, "refresh_stats", lambda self: None), \
            patch.object(MainWindow, "refresh_account", lambda self: None), \
            patch.object(MainWindow, "load_room_avatars", lambda self: None), \
            patch.object(MainWindow, "_hold_fullscreen_frame", lambda self: None), \
            patch.object(MainWindow, "start_tile",
                         lambda self, tile, **kw: requested.append((tile, tile.quality))):
        window = MainWindow(rooms, [dict(r) for r in rooms], layout_id="corner",
                            state={"plugins_enabled": [], "settings": {
                                "fullscreen_solo_audio": False, "auto_quality": False}})
        window.resize(1400, 900)
        window.show()
        app.processEvents()
        tiles = list(window.wall.tiles)
        target = tiles[1]
        for tile in tiles:
            tile.room["live"] = True
            tile.set_quality(400)
        requested.clear()
        original_muted = [tile.muted for tile in tiles]

        def key(code):
            app.sendEvent(window, QKeyEvent(QEvent.KeyPress, code, Qt.NoModifier))

        def setting(enabled, accept=True):
            errors = []
            dialogs = []

            def edit():
                dialog = app.activeModalWidget()
                dialogs.append(dialog)
                try:
                    dialog.general_page._checks["fullscreen_original_quality"].setChecked(enabled)
                    dialog.accept() if accept else dialog.reject()
                except Exception as error:
                    errors.append(error)
                    dialog.reject()

            QTimer.singleShot(0, edit)
            assert window.open_settings() == accept
            assert not errors, errors
            for dialog in dialogs:
                dialog.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)

        try:
            page = GeneralSettingsPage({})
            assert page.values()["fullscreen_original_quality"] is True
            page._checks["fullscreen_original_quality"].setChecked(False)
            assert GeneralSettingsPage(page.values()).values()["fullscreen_original_quality"] is False
            page.reset()
            assert page.values()["fullscreen_original_quality"] is True
            page.close()

            target.fullscreen_button.click()
            assert target.quality == 10000 and requested == [(target, 10000)]
            assert window.current_state()["wall"][1]["quality"] == 400
            assert [t.muted for t in tiles] == original_muted
            assert all(t.quality == 400 for t in tiles if t is not target)
            setting(False, accept=False)
            assert target.quality == 10000
            setting(False)
            assert target.quality == 400
            setting(True)
            assert target.quality == 10000
            window.settings["auto_quality"] = True
            window.apply_quality_policy()
            assert target.quality == 10000, "main/sub quality policy must not override fullscreen"
            key(Qt.Key_Escape)
            assert target.quality == 400
            assert window._fullscreen_tile is None

            window._tile_under_cursor = lambda: target
            key(Qt.Key_F)
            assert target.quality == 10000
            key(Qt.Key_F)
            assert target.quality == 400
            del window._tile_under_cursor

            # Recording started while fullscreen must defer restore until recording ends.
            target.fullscreenRequested.emit(target)
            window._capture_quality[target] = (str(target.room["room_id"]), 10000)
            target.quality_locked = True
            key(Qt.Key_Escape)
            assert target.quality == 10000
            assert window._capture_quality[target][1] == 400
            window._restore_capture_quality(target)
            assert target.quality == 400 and not target.quality_locked

            # Recording started before fullscreen; stopping it keeps fullscreen original.
            window._capture_quality[target] = (str(target.room["room_id"]), 400)
            target.set_quality(10000)
            target.quality_locked = True
            target.fullscreen_button.click()
            window._restore_capture_quality(target)
            assert target.quality == 10000
            key(Qt.Key_Escape)
            assert target.quality == 400

            # New streams label 25000 as 2K original, not the legacy 10000 tier.
            target.set_quality_options([
                {"qn": 25000, "desc": "2K 原画"},
                {"qn": 10000, "desc": "1080P 高码率"}])
            target.fullscreen_button.click()
            assert target.quality == 25000
            key(Qt.Key_Escape)
            assert target.quality == 400
            target.set_quality_options([])

            setting(False)
            window.settings["fullscreen_solo_audio"] = True
            target.fullscreen_button.click()
            assert target.quality == 400 and not target.muted
            assert all(t.muted for t in tiles if t is not target)
            key(Qt.Key_Escape)
            setting(True)
            target.fullscreen_button.click()
            with patch.object(config, "save") as save:
                window.close()
                assert save.call_args.args[0]["wall"][1]["quality"] == 400
        finally:
            if not window._closing:
                window.close()
            window._fullscreen_quality.saved.clear()
            requested.clear()
            app.processEvents()
        print("PASS: fullscreen original quality, buttons/keys, setting save/cancel/reset, "
              "audio independence, policy/recording interactions, saved state")


if __name__ == "__main__":
    main()
    # Match app.main and the existing Qt/VLC selfchecks: closeEvent above is
    # verified first; avoid Windows Qt wrapper teardown during interpreter GC.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
