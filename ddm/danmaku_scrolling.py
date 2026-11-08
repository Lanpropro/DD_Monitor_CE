"""Chat viewport follow-tail and history scroll preservation; panel owns scroll state."""
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, QTimer, QUrl, Qt, Signal
from shiboken6 import isValid


class DanmakuScrolling:
    def __init__(self, host):
        self.host = host

    def scroll_state(self, removed_blocks: int = 0) -> tuple[bool, int, int]:
        host = self.host
        scroll_bar = host.body.verticalScrollBar()
        value = scroll_bar.value()
        if removed_blocks and not host._follow_tail:
            document = host.body.document()
            remaining = document.findBlockByNumber(removed_blocks)
            if remaining.isValid():
                layout = document.documentLayout()
                removed_height = (layout.blockBoundingRect(remaining).top()
                                  - layout.blockBoundingRect(document.firstBlock()).top())
                # 字体行高可能有小数，逐条取整会让阅读位置不断漂移。
                offset = removed_height + host._scroll_trim_remainder
                pixels = round(offset)
                host._scroll_trim_remainder = offset - pixels
                value = max(0, value - pixels)
        return host._follow_tail, value, host._scroll_revision

    def restore_scroll_state(self, state: tuple[bool, int, int]) -> None:
        """内容更新不能打断用户阅读；仍在末尾时才继续跟随。"""
        host = self.host
        follow_tail, value, revision = state
        host._follow_tail = follow_tail
        host._scroll_restore_id += 1
        restore_id = host._scroll_restore_id

        def restore() -> None:
            if (not isValid(host) or revision != host._scroll_revision
                    or restore_id != host._scroll_restore_id):
                return
            scroll_bar = host.body.verticalScrollBar()
            if host._follow_tail:
                scroll_bar.setValue(scroll_bar.maximum())
            else:
                scroll_bar.setValue(min(value, scroll_bar.maximum()))
            host._update_bottom_button()

        restore()
        # QTextDocument 可能到下一轮事件循环才完成重新排版，再校正一次。
        QTimer.singleShot(0, restore)

    def jump_to_bottom(self) -> None:
        host = self.host
        host._scroll_revision += 1
        host._scroll_trim_remainder = 0.0
        host._follow_tail = True
        host._scroll_to_bottom()
        host._update_bottom_button()

    def update_bottom_button(self) -> None:
        host = self.host
        host.bottom_button.setVisible(not host._follow_tail and host._has_content)
        host._position_bottom_button()

    def scroll_to_bottom(self) -> None:
        host = self.host
        if not host._follow_tail:
            return
        scroll_bar = host.body.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def at_scroll_tail(self) -> bool:
        host = self.host
        scroll_bar = host.body.verticalScrollBar()
        return scroll_bar.value() >= scroll_bar.maximum() - 1

    def on_user_scroll(self) -> None:
        """用户滚轮/键盘查看旧内容时暂停自动跟随；回到底部后恢复。"""
        host = self.host
        host._scroll_revision += 1
        host._scroll_trim_remainder = 0.0
        host._follow_tail = host._at_scroll_tail()
        host._update_bottom_button()

    def on_scroll_pressed(self) -> None:
        host = self.host
        host._scroll_revision += 1
        host._scroll_trim_remainder = 0.0
        host._scroll_dragging = True

    def on_scroll_released(self) -> None:
        host = self.host
        host._scroll_dragging = False
        host._follow_tail = host._at_scroll_tail()
        host._update_bottom_button()

    def on_scroll_value_changed(self, _value: int) -> None:
        host = self.host
        if host._scroll_dragging:
            host._follow_tail = host._at_scroll_tail()
            host._update_bottom_button()
