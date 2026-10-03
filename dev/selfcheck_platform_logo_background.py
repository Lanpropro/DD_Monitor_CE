"""离线回归：平台标识没有灰底，四种关注栏模式均保留图标。"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from ddm import theme  # noqa: E402
from ddm.widgets import NavItem  # noqa: E402


def edge_color(app, badge, background):
    parent, geometry = badge.parentWidget(), badge.geometry()
    host = QWidget()
    host.resize(badge.size())
    host.setStyleSheet(f"background: {background};")
    badge.setParent(host)
    badge.move(0, 0)
    badge.show()
    host.show()
    app.processEvents()
    color = host.grab().toImage().pixelColor(0, host.height() // 2)
    badge.setParent(parent)
    badge.setGeometry(geometry)
    badge.show()
    host.close()
    return color


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    for rid in ("1001", "huya:123", "douyu:123", "douyin:123", "twitch:test", "youtube:abcdefghijk"):
        item = NavItem({"room_id": rid, "live": True}, 0)
        item.resize(240, 128)
        item.show()
        for mode in ("card", "list", "compact", "portrait"):
            item.set_compact(mode == "compact")
            item.set_card_mode(mode == "card")
            item.set_portrait_strip(mode == "portrait")
            app.processEvents()
            badge = item.platform_badge
            assert not badge.pixmap().isNull() and badge.text() == ""
            assert badge.toolTip() and badge.isVisible()
            for background in ("#163440", "#1d2022"):
                assert edge_color(app, badge, background) == QColor(background), (rid, mode)
        item.close()
    print("PASS: six platform icons, transparent padding on two backgrounds, card/list/compact/portrait")


if __name__ == "__main__":
    main()
