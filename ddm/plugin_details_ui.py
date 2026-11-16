"""Card-owned plugin details; the outer plugin list owns scrolling."""
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout


class PluginDetailsPanel(QFrame):
    collapsed = Signal()

    def __init__(self, page, offer, *, installed_entry=None, parent=None):
        super().__init__(parent if parent is not None else page)
        self.page, self.plugin_id = page, offer['id']
        self.offer = dict(offer)
        self.installed_entry = installed_entry
        self.setObjectName('PluginInlineDetails')
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)
        self.document = QLabel(self)
        self.document.setTextFormat(Qt.PlainText)
        self.document.setWordWrap(True)
        self.document.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.document.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        text_policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_policy.setHeightForWidth(True)
        self.document.setSizePolicy(text_policy)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_document)
        self.document.installEventFilter(self)
        layout.addWidget(self.document)
        store = page.store_page if installed_entry is not None else page
        store.controlsChanged.connect(self.refresh_action)
        if installed_entry is not None:
            page.changed.connect(self.refresh_action)
        self.refresh_action()

    def refresh_action(self):
        store = self.page.store_page if self.installed_entry is not None else self.page
        current = next((offer for offer in store._display_offers if offer['id'] == self.plugin_id), None)
        if current is not None:
            self.offer = dict(current)
        author = str(self.offer.get('author') or '').strip().lstrip('@')
        parts = [self.offer.get('description') or '暂无说明']
        if author:
            parts.append('作者：@' + author)
        if self.installed_entry is not None:
            entry = self.page._installed_entries.get(self.plugin_id, self.installed_entry)
            check = self.page.checks.get(self.plugin_id)
            enabled = check.isChecked() if check is not None else entry['enabled']
            parts.extend(('插件 ID：' + entry['id'], '状态：' + entry.get('status', ''),
                          '本次选择：' + ('启用' if enabled else '禁用') + '（重启后生效）'))
            if entry.get('reason'):
                parts.append(entry['reason'])
        if self.offer.get('min_app_version'):
            parts.append('需要主程序版本：' + self.offer['min_app_version'] + ' 或更高')
        if self.offer.get('reason'):
            parts.append(self.offer['reason'])
        parts.extend(('更新日志 · v' + str(self.offer.get('version') or '—'),
                      self.offer.get('notes') or '暂无更新日志'))
        text = '\n\n'.join(parts)
        if self.document.text() != text:
            self.document.setText(text)
            self._fit_timer.start(0)

    def closeEvent(self, event):
        self.collapsed.emit()
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.document and event.type() in (QEvent.Resize, QEvent.FontChange):
            self._fit_timer.start(0)
        return super().eventFilter(watched, event)

    def _fit_document(self):
        height = self.document.heightForWidth(max(1, self.document.width()))
        if height >= 0 and self.document.minimumHeight() != height:
            self.document.setMinimumHeight(height)
            self.updateGeometry()
