"""Shared reading window for official announcements and the first-run notice."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout

from . import theme
from .settings_window import SettingsWindow
from .ui import ActionButton, NavigationButton, SettingsSurface, TitleLabel
from .version import DISPLAY_NAME
from .widget_support import BRAND_ASSETS_DIR


class NoticeDialog(SettingsWindow):
    DEFAULT_WIDTH = 640
    DEFAULT_HEIGHT = 560

    def __init__(self, category, title, confirm, parent=None, *, settings=None, link=None):
        super().__init__(parent)
        self.setWindowTitle(f"{category} · {DISPLAY_NAME}")
        self.window_header.breadcrumb.setText(category)
        self.window_header.close_button.setAccessibleName("关闭" + category)
        self.window_header.close_button.setToolTip("关闭" + category)
        if link is not None and not link.isEmpty():
            original = NavigationButton("查看原文", "external_link", self.window_header)
            original.clicked.connect(lambda: QDesktopServices.openUrl(link))
            row = self.window_header.row
            row.insertWidget(row.indexOf(self.window_header.close_button), original)

        body = QVBoxLayout()
        body.setContentsMargins(16, 6, 16, 16)
        body.setSpacing(14)
        self.body_layout.addLayout(body, 1)

        header = QHBoxLayout()
        header.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(Path(BRAND_ASSETS_DIR) / "logo.png")).scaled(
            40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header.addWidget(logo, 0, Qt.AlignTop)
        self.heading = TitleLabel(title)
        self.heading.setTextFormat(Qt.PlainText)
        self.heading.setWordWrap(True)
        header.addWidget(self.heading, 1)
        body.addLayout(header)

        card = SettingsSurface(self)
        content_layout = QVBoxLayout(card)
        content_layout.setContentsMargins(16, 12, 16, 16)
        self.content = QTextBrowser(card)
        self.content.setAccessibleName(category + "正文")
        self.content.setOpenExternalLinks(True)
        self.content.setFrameShape(QTextBrowser.NoFrame)
        self.content.setStyleSheet("QTextBrowser { background: transparent; border: 0; }")
        self.content.document().setDefaultStyleSheet(f"a {{ color: {theme.ACCENT}; }}")
        content_layout.addWidget(self.content)
        body.addWidget(card, 1)

        self.confirm_button = ActionButton(confirm, self)
        self.confirm_button.setObjectName("PrimaryButton")
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self.accept)
        body.addWidget(self.confirm_button)
        self.content.setFocus()

        self.set_material(settings or {})
        screen = parent.screen() if parent is not None else self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(min(self.DEFAULT_WIDTH, area.width() - 24),
                        min(self.DEFAULT_HEIGHT, area.height() - 24))
            self.move(area.center() - self.rect().center())
