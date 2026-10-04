"""Tile bottom controls: left volume, right recording, working signals."""
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.widgets import Tile


def main():
    app = QApplication(sys.argv)
    tile = Tile({"room_id": "1000", "uname": "Test", "live": False})
    events = []
    tile.recordingRequested.connect(lambda: events.append("record"))
    tile.muteToggled.connect(lambda room, muted: events.append("mute"))
    tile.volumeChanged.connect(lambda room, volume: events.append(volume))
    tile.show()
    try:
        for width, height in ((900, 500), (360, 210), (300, 500)):
            tile.resize(width, height)
            app.processEvents()
            controls = [tile.pause_button, tile.volume_button, tile.volume_slider,
                        tile.volume_label, tile.status_label, tile.danmaku_button,
                        tile.danmaku_settings_button, tile.recording_button,
                        tile.fullscreen_button]
            visible = [widget for widget in controls if widget.isVisible()]
            assert [widget.x() for widget in visible] == sorted(widget.x() for widget in visible)
            assert tile.danmaku_settings_button.isVisible()
            assert tile.fullscreen_button.geometry().right() < tile.bottom.width()
            tile.set_recording_state("record")
            tile.set_recording_elapsed("0:00:10")
            app.processEvents()
            if tile.recording_time.isVisible():
                assert tile.recording_button.x() < tile.recording_time.x() < tile.fullscreen_button.x()
            tile.set_recording_state("")
            tile.set_recording_elapsed("")
            tile.set_recording_available(False)
            app.processEvents()
            assert not tile.recording_button.isVisible()
            assert tile.volume_button.isVisible() and tile.volume_slider.isVisible()
            tile.set_recording_available(True)
        QTest.mouseClick(tile.recording_button, Qt.LeftButton)
        QTest.mouseClick(tile.volume_button, Qt.LeftButton)
        tile.volume_slider.setValue(55)
        assert "record" in events and "mute" in events and 55 in events
    finally:
        tile.close()
    print("Tile bottom: wide/narrow/portrait, recording time, disabled recording and signals passed")


if __name__ == "__main__":
    main()
