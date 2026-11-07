"""Shared eliding label without aggregate-widget or player imports."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel


class ElidedLabel(QLabel):
    """超出宽度自动省略的标签。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        super().setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        super().setText(self._full_text)
        self._apply_elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elide()

    def sizeHint(self) -> QSize:
        """用完整文本计算期望宽度，否则省略后的文本会让标签越缩越窄。"""
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self._full_text) + 2, metrics.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.fontMetrics().height())

    def _apply_elide(self) -> None:
        if not self._full_text:
            return
        # 隐藏或还没排版时宽度是 0，省略后文本会变成空串（下一条状态读出来就是 ""），
        # 所以先保留原文，等真正有宽度再按实际宽度省略。
        if self.width() <= 0:
            if super().text() != self._full_text:
                super().setText(self._full_text)
            return
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, max(0, self.width()))
        # 宽度比省略号还窄时 Qt 也给空串：这时文本是被裁掉而不是没有，
        # 保留原文，别让状态读出来变成 ""。
        if not elided:
            elided = self._full_text
        if elided != super().text():
            super().setText(elided)
