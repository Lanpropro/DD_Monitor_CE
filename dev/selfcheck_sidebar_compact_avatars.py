"""收起关注栏时，默认头像和已下载头像都应留在窄栏中。"""
import os
import sys
from tempfile import TemporaryDirectory

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import images, theme  # noqa: E402
from ddm.widgets import Sidebar  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": "1001", "uname": "主播甲", "live": True},
             {"room_id": "1002", "uname": "主播乙", "live": False}]
    sidebar = Sidebar(rooms)
    sidebar.resize(300, 500)
    sidebar.show()
    app.processEvents()
    first, second = sidebar.items()
    assert first.thumb.face.text() == "主"

    face = QPixmap(64, 64)
    face.fill(QColor("#e52a6f"))
    first.thumb.set_face(face)
    sidebar.set_collapsed(True, animate=False)
    app.processEvents()
    assert first.thumb.face.isVisible() and not first.thumb.face.pixmap().isNull()
    assert second.thumb.face.isVisible() and second.thumb.face.text() == "主"
    assert first.thumb.face.geometry() == first.thumb.geometry()
    assert first.thumb.face.grab().toImage().pixelColor(16, 16).red() > 150
    second.set_uname("新主播")
    assert second.thumb.face.text() == "新"

    with TemporaryDirectory() as directory:
        original_repo = images.REPO
        try:
            images.REPO = directory
            url = "https://example.invalid/avatar.png"
            source = images._cache_path(url)
            os.makedirs(os.path.dirname(source), exist_ok=True)
            assert face.save(source)
            images.remember_room_avatar("1001", url)
            restored = images.load_room_avatar("1001")
            assert restored is not None and not restored.isNull()
            assert images.load_room_avatar("missing") is None
            loaded = []
            loader = images.CachedAvatarLoader(["1001", "missing"])
            loader.loaded.connect(lambda room_id, pixmap: loaded.append((room_id, pixmap)))
            loader.run()
            assert len(loaded) == 1 and loaded[0][0] == "1001"
        finally:
            images.REPO = original_repo

    sidebar.set_collapsed(False, animate=False)
    app.processEvents()
    assert first.thumb.face.isVisible() and second.thumb.face.isVisible()
    sidebar.close()
    print("sidebar compact avatars: OK")


if __name__ == "__main__":
    main()
