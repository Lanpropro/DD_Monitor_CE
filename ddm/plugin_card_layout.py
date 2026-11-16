"""Equal-width plugin columns with independent card heights and row-major order."""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class PluginCardLayout(QLayout):
    def __init__(self):
        super().__init__()
        self._items = []
        self._columns = 2
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(12)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def set_columns(self, columns):
        if self._columns != columns:
            self._columns = columns
            self.invalidate()

    def expandingDirections(self):
        return Qt.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0))

    def sizeHint(self):
        width = max((item.sizeHint().width() for item in self._items), default=0)
        width = width * self._columns + self.spacing() * (self._columns - 1)
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self):
        width = max((item.minimumSize().width() for item in self._items), default=0)
        width = width * self._columns + self.spacing() * (self._columns - 1)
        return QSize(width, self.heightForWidth(width))

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def _arrange(self, rect, apply=False):
        gap = self.spacing()
        width = max(0, (rect.width() - gap * (self._columns - 1)) // self._columns)
        heights = [0] * self._columns
        for index, item in enumerate(self._items):
            column = index % self._columns
            height = item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
            height = max(height, item.minimumSize().height())
            if apply:
                item.setGeometry(QRect(rect.x() + column * (width + gap),
                                       rect.y() + heights[column], width, height))
            heights[column] += height + gap
        return max(0, max(heights) - gap)
