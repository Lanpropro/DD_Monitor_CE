"""Editable title keyword tags for the recording plan."""
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from .recording_schedule import normalize_title_keywords, split_title_keywords
from .ui import ElidedLabel, NavigationButton


class _KeywordLineEdit(QLineEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _TagLayout(QLayout):
    def __init__(self):
        super().__init__()
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item):
        self.items.append(item)
        self.invalidate()

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def minimumSize(self):
        return QSize(0, max((item.minimumSize().height() for item in self.items), default=0))

    def sizeHint(self):
        return self.minimumSize()

    def hasHeightForWidth(self):
        return True

    def expandingDirections(self):
        return Qt.Horizontal

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), measure=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, measure=False)

    def _arrange(self, rect, *, measure):
        x, y, height, gap = rect.x(), rect.y(), 0, self.spacing()
        for item in self.items:
            size = item.sizeHint()
            width = min(rect.width(), size.width())
            if x != rect.x() and x + width > rect.x() + rect.width():
                x, y, height = rect.x(), y + height + gap, 0
            if not measure:
                item.setGeometry(QRect(x, y, width, size.height()))
            x += width + gap
            height = max(height, size.height())
        return y - rect.y() + height


class KeywordTags(QWidget):
    def __init__(self, keywords, parent):
        super().__init__(parent)
        self.tags = {}
        self.revealed = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        label = QLabel('直播间标题关键词', objectName='SettingsSectionTitle')
        outer.addWidget(label)
        self.tag_area = QWidget(self)
        self.tag_layout = _TagLayout()
        self.tag_area.setLayout(self.tag_layout)
        self.tag_area.hide()
        outer.addWidget(self.tag_area)
        self.input = _KeywordLineEdit(self)
        self.input.setAccessibleName(label.text())
        self.input.setPlaceholderText('输入关键词，按 Enter 添加')
        label.setBuddy(self.input)
        self.input.submitted.connect(self.commit_pending)
        outer.addWidget(self.input)
        for word in keywords:
            self._add(word)

    def _add(self, text):
        word = text.casefold()
        if word in self.tags:
            return
        tag = QFrame(self.tag_area, objectName='RecordingKeywordTag')
        tag.setToolTip(text + '\n右键显示删除按钮')
        tag.setContextMenuPolicy(Qt.CustomContextMenu)
        tag.customContextMenuRequested.connect(lambda _pos: self._show_remove(word))
        layout = QHBoxLayout(tag)
        layout.setContentsMargins(9, 2, 3, 2)
        layout.setSpacing(5)
        label = ElidedLabel(text, tag)
        label.setTextFormat(Qt.PlainText)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        label.setMinimumWidth(min(220, label.fontMetrics().horizontalAdvance(text) + 2))
        layout.addWidget(label, 1)
        remove = NavigationButton('删除关键词 ' + text, 'close', tag)
        remove.setAutoDefault(False)
        remove.setFixedSize(22, 22)
        policy = remove.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        remove.setSizePolicy(policy)
        remove.clicked.connect(lambda: self._remove(word))
        layout.addWidget(remove, 0, Qt.AlignTop)
        remove.hide()
        tag.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.tags[word] = tag, remove
        self.tag_layout.addWidget(tag)
        tag.show()
        self.tag_area.show()

    def _show_remove(self, word):
        if self.revealed is not None and self.revealed != word:
            self.tags[self.revealed][1].hide()
        self.revealed = word
        self.tags[word][1].show()

    def _remove(self, word):
        tag, _ = self.tags.pop(word)
        if self.revealed == word:
            self.revealed = None
        self.tag_layout.removeWidget(tag)
        tag.hide()
        tag.deleteLater()
        self.tag_area.setVisible(bool(self.tags))

    def commit_pending(self):
        if self.input.hasFocus():
            QGuiApplication.inputMethod().commit()
        for word in split_title_keywords(self.input.text()):
            self._add(word)
        self.input.clear()

    def keywords(self):
        return normalize_title_keywords([*self.tags, *split_title_keywords(self.input.text())])
