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
    assert panel.bottom_button.isVisible()
    for width in (180, 237, 340):
        panel.resize(width, 400)
        app.processEvents()
        viewport = panel.body.viewport()
        assert panel.bottom_button.parentWidget() is viewport
        assert panel.bottom_button.text() == ''
        assert viewport.rect().contains(panel.bottom_button.geometry())
        assert viewport.width() - panel.bottom_button.geometry().right() == 11
        assert viewport.height() - panel.bottom_button.geometry().bottom() == 11
        controls = (panel.font_slider, panel.font_value)
        assert panel.font_controls.parentWidget() is panel.header
        assert all(widget.parentWidget() is panel.font_controls for widget in controls)
        assert all(panel.font_controls.rect().contains(widget.geometry()) for widget in controls)
        assert all(not a.geometry().intersects(b.geometry()) for a, b in zip(controls, controls[1:]))
        assert not panel.font_controls.geometry().intersects(panel.count.geometry())
        title = panel.header.layout().itemAt(1).widget()
        assert panel.font_controls.x() == title.geometry().right() + 1 + panel.header.layout().spacing()
        assert abs(panel.font_controls.geometry().center().y() - panel.header.rect().center().y()) <= 1
        for widget in controls:
            assert abs(widget.geometry().center().y() - panel.font_controls.rect().center().y()) <= 1
        assert panel.body.y() == panel.header.height()
        assert panel.body.geometry().bottom() == panel.height() - 1
        assert panel.width() == width, "Header controls force the panel wider"
    panel.font_slider.setValue(17)
    app.processEvents()
    assert panel._font_size() == 17 and panel.font_value.text() == '17'
    panel.set_status('正在连接服务器，请稍候')
    app.processEvents()
    assert not panel.font_controls.geometry().intersects(panel.count.geometry())
    assert panel.header.rect().contains(panel.count.geometry())
    # A pending document correction must not undo an explicit jump.
    panel.add_message("before jump", "pending restore")
    panel.bottom_button.click()
    app.processEvents()
    assert panel._follow_tail and bar.value() == bar.maximum()
    assert panel.bottom_button.isHidden()
    panel.add_message("after jump", "follow new messages")
    app.processEvents()
    assert bar.value() == bar.maximum()
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
    assert panel._received == 1002
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
    assert panel.bottom_button.isHidden()
    panel.add_message("new room", "first message")
    app.processEvents()
    assert panel._received == 1 and panel.body.document().blockCount() == 1
    assert "user999" not in panel.body.toPlainText()
    panel.close()
    print("High-volume retention, reading anchor, tail follow and reset passed")


if __name__ == "__main__":
    main()
