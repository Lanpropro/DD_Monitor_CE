"""One connected bottom operation panel with an interruptible slide-away handle."""
from PySide6.QtCore import QAbstractAnimation, QEvent, Qt, QVariantAnimation
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout

from . import motion


class SidebarFooter(QFrame):
    HANDLE_HEIGHT = 24

    def __init__(self, sidebar):
        super().__init__(sidebar)
        self.setObjectName('SidebarFooter')
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.minimized = False
        self._refreshing = False
        self._keyboard_activation = False
        self._full_height = self.HANDLE_HEIGHT
        self.body = QFrame(self)
        self.body.setObjectName('SidebarFooterBody')
        self.content_box = QVBoxLayout(self.body)
        self.content_box.setContentsMargins(6, 8, 6, 8)
        self.content_box.setSpacing(8)
        header = QFrame(self.body)
        header.setObjectName('SidebarFooterHeader')
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel('工作区', header)
        self.title.setObjectName('SectionLabel')
        row.addWidget(self.title, 1)
        self.toggle_button = QToolButton(header)
        self.toggle_button.setObjectName('FooterHandle')
        self.toggle_button.setArrowType(Qt.DownArrow)
        self.toggle_button.setAccessibleName('收起底部操作区')
        self.toggle_button.setToolTip('向下收起底部操作区')
        self.toggle_button.setFixedSize(24, 22)
        row.addWidget(self.toggle_button)
        self.content_box.addWidget(header)
        self.restore_button = QToolButton(self)
        self.restore_button.setObjectName('FooterHandle')
        self.restore_button.setText('展开操作区')
        self.restore_button.setArrowType(Qt.UpArrow)
        self.restore_button.setAccessibleName('展开底部操作区')
        self.restore_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.restore_button.hide()
        for button in (self.toggle_button, self.restore_button):
            button.clicked.connect(self.toggle)
            button.installEventFilter(self)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(motion.FOOTER_SLIDE_MS)
        self.animation.setEasingCurve(motion.THEME_WAVE_EASING)
        self.animation.valueChanged.connect(lambda value: self.setFixedHeight(round(value)))
        self.animation.finished.connect(self._settle)
        self.body.installEventFilter(self)

    def toggle(self):
        self.set_minimized(not self.minimized, animate=not self._keyboard_activation)
        self._keyboard_activation = False

    def set_minimized(self, minimized, *, animate=True):
        self.animation.stop()
        self.minimized = bool(minimized)
        self.body.show()
        self.restore_button.show()
        self.restore_button.setToolTip('展开底部操作区' if self.minimized else '再次点击收起')
        self.refresh(keep_height=True)
        target = self.HANDLE_HEIGHT if self.minimized else self._full_height
        if animate and motion.enabled() and self.isVisible() and self.height() != target:
            self.animation.setStartValue(self.height())
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self._settle()

    def refresh(self, *, keep_height=False):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self.content_box.activate()
            self._full_height = max(self.HANDLE_HEIGHT, self.body.sizeHint().height())
            self.body.setGeometry(0, 0, self.width(), self._full_height)
            # Keep the body at full size; the outer panel clips it as it slides down.
            self.restore_button.setGeometry(2, max(0, self.height() - self.HANDLE_HEIGHT),
                                            max(0, self.width() - 4), self.HANDLE_HEIGHT)
            self.restore_button.raise_()
            if not keep_height and self.animation.state() != QAbstractAnimation.Running:
                self.setFixedHeight(self.HANDLE_HEIGHT if self.minimized else self._full_height)
        finally:
            self._refreshing = False

    def _settle(self):
        self.setFixedHeight(self.HANDLE_HEIGHT if self.minimized else self._full_height)
        self.body.setVisible(not self.minimized)
        self.restore_button.setVisible(self.minimized)
        self.restore_button.setToolTip('展开底部操作区')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def hideEvent(self, event):
        self.animation.stop()
        self._settle()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.body and event.type() == QEvent.LayoutRequest:
            self.refresh()
        elif watched in (self.toggle_button, self.restore_button):
            if event.type() == QEvent.KeyPress:
                self._keyboard_activation = True
            elif event.type() == QEvent.MouseButtonPress:
                self._keyboard_activation = False
        return super().eventFilter(watched, event)
