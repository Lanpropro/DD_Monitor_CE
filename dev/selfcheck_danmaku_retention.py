"""High-volume danmaku must retain history without resetting the whole document."""
import os
import sys
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ddm import theme
from ddm.widgets import DanmakuPanel


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    panel = DanmakuPanel()
    panel.set_max_blocks(300)  # Exercise overflow quickly, independently of the default.
    panel.resize(340, 400)
    panel.show()
    app.processEvents()
    for index in range(300):
        panel.add_message(f"user{index}", f"message{index} " + "wrapped text " * (index % 3))
    app.processEvents()
    bar = panel.body.verticalScrollBar()
    assert bar.value() == bar.maximum()
    panel._on_scroll_pressed()
    bar.setValue(bar.maximum() * 3 // 4)
    panel._on_scroll_released()
    anchor = panel.body.cursorForPosition(QPoint(12, 12))
    anchor_text = anchor.block().text()
    anchor_y = panel.body.cursorRect(anchor).y()
    with patch.object(panel.body, "setHtml", wraps=panel.body.setHtml) as reset:
        for index in range(300, 320):
            panel.add_message(f"user{index}", f"message{index}")
        app.processEvents()
        assert reset.call_count == 0, "History limit triggers a full document reset per message"
    now = panel.body.cursorForPosition(QPoint(12, 12))
    assert now.block().text() == anchor_text, "Incoming messages move the message being read"
    assert abs(panel.body.cursorRect(now).y() - anchor_y) <= 1, "Reading anchor jumps vertically"
    assert not panel._follow_tail
    assert len(panel._blocks) == panel.body.document().blockCount() == 300
    text = panel.body.toPlainText()
    assert "user0：" not in text and "user319：message319" in text
    bar.setValue(bar.maximum())
    panel._on_user_scroll()
    for index in range(320, 1000):
        panel.add_message(f"user{index}", f"message{index}")
        if index % 20 == 0:
            app.processEvents()
    app.processEvents()
    assert bar.value() == bar.maximum(), "Tail following stops after pruning"
    assert panel._received == 1000
    assert len(panel._blocks) == panel.body.document().blockCount() == 300
    panel.set_max_blocks(20)
    app.processEvents()
    assert len(panel._blocks) == panel.body.document().blockCount() == 20
    # A user scroll that happens before a queued correction must win.
    panel.add_message("queued restore", "do not override the user scroll")
    bar.setValue(0)
    panel._on_user_scroll()
    app.processEvents()
    assert bar.value() == 0
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#7bc96f"))
    panel._on_emoticon_loaded("cached:test", pixmap)
    for index in range(40):
        panel.add_event({"uname": f"image{index}", "text": "[emoji]",
                         "emoticon": "cached:test",
                         "medal": {"name": "medal", "level": "1", "color": "#7bc96f"}})
    app.processEvents()
    assert panel.body.document().blockCount() == 20
    assert panel.body.toHtml().count("<img") == 40, "Pruning loses medal or emoji resources"
    panel.apply_style("", 22)
    app.processEvents()
    assert panel.body.document().blockCount() == 20
    assert panel.body.toHtml().count("<img") == 40
    panel._render_all()
    panel.add_message("after rebuild", "retention still works")
    app.processEvents()
    assert panel.body.document().blockCount() == 20
    panel.clear()
    panel.add_message("new room", "first message")
    app.processEvents()
    assert panel._received == 1 and panel.body.document().blockCount() == 1
    assert "user999" not in panel.body.toPlainText()
    panel.close()
    print("High-volume retention, reading anchor, tail follow and reset passed")


if __name__ == "__main__":
    main()
