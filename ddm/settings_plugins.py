"""Settings plugins; owned page implementations with legacy exports in dialogs."""
import zipfile
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget
)
from . import theme
from .motion import AnimatedDialog, SlidingTabs
from .ui import SettingsSurface, ElidedLabel, page_header as _page_head


class PluginRemovePrompt(AnimatedDialog):
    def __init__(self, plugin_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle('删除插件')
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(20)
        layout.addLayout(_page_head('删除这个插件？',
            f'将删除插件“{plugin_name}”及其文件。\n已加载的插件将在重启后停止运行。'))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton('取消')
        self.cancel_button.setObjectName('IconButton')
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.delete_button = QPushButton('删除')
        self.delete_button.setObjectName('PrimaryButton')
        self.delete_button.setAutoDefault(False)
        self.delete_button.clicked.connect(self.accept)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)
        self.cancel_button.setFocus()


class PluginSettingsPage(QWidget):
    """按现有插件接口展示元数据和下次启动的启用选择。"""

    changed = Signal()

    def __init__(self, manager=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setAcceptDrops(True)
        self.setObjectName("SettingsPage")
        self.checks = {}
        self.card_details = {}
        self.update_buttons = {}
        self._installed_entries = {}
        self._installed_cards = {}
        self._installed_authors = {}
        self._available_update_ids = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(_page_head("插件", "拖入 ZIP 插件包或含插件 ZIP 的 EXE；安装和启用更改在重启后生效"))
        self.install_button = QPushButton("装载插件…")
        self.install_button.setObjectName("IconButton")
        self.install_button.clicked.connect(self._install)
        actions = QHBoxLayout()
        actions.addWidget(self.install_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        from .online_ui import PluginBrowserToolbar, PluginStorePage
        installed_page = QWidget()
        installed_page_layout = QVBoxLayout(installed_page)
        installed_page_layout.setContentsMargins(0, 10, 4, 8)
        self.installed_browser = PluginBrowserToolbar(installed_page, ('全部插件', '已启用', '已禁用', '可更新'))
        installed_page_layout.addWidget(self.installed_browser)
        self.installed_browser.search.textChanged.connect(self._filter_installed)
        self.installed_browser.filter.currentIndexChanged.connect(self._filter_installed)
        self.installed_browser.sort.currentIndexChanged.connect(self._filter_installed)
        scroll = QScrollArea(installed_page)
        self.installed_scroll = scroll
        scroll.setObjectName("PluginScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        installed_layout = QVBoxLayout(content)
        installed_layout.setContentsMargins(0, 0, 4, 12)
        self.cards = QGridLayout()
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setHorizontalSpacing(12)
        self.cards.setVerticalSpacing(12)
        self.cards.setColumnStretch(0, 1)
        self.cards.setColumnStretch(1, 1)
        installed_layout.addLayout(self.cards)
        self.empty = QLabel('未发现插件。可装载 ZIP 插件包', content)
        self.empty.setObjectName('SettingsHint')
        self.empty.setWordWrap(True)
        installed_layout.addWidget(self.empty)
        installed_layout.addStretch(1)
        entries = manager.catalog() if manager else []
        self._initial_enabled = {entry["id"]: entry["enabled"] for entry in entries}
        self._files_changed = any(entry["status"] == "待重启" for entry in entries) or bool(
            getattr(manager, "_removed", None))
        from .plugin_updates import pending_versions
        self._files_changed = self._files_changed or bool(manager and pending_versions(manager))
        for entry in entries:
            self._add_card(entry)
        scroll.setWidget(content)
        installed_page_layout.addWidget(scroll, 1)
        self.store_page = PluginStorePage(manager)
        self.tabs = SlidingTabs()
        self.tabs.setObjectName("PluginTabs")
        self.tabs.addTab(installed_page, "已安装")
        self.tabs.addTab(self.store_page, "插件商店")
        self.tabs.currentChanged.connect(self._store_tab_changed)
        self.store_page.installed.connect(self._store_installed)
        self.store_page.offersChanged.connect(self._show_update_notes)
        self.store_page.controlsChanged.connect(self._sync_update_buttons)
        self._show_update_notes(self.store_page.offers)
        layout.addWidget(self.tabs, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self.store_page.open_catalog()

    def _store_tab_changed(self, index):
        if index == 1:
            self.store_page.open_catalog()

    def _store_installed(self, plugin_id):
        previous = {key: check.isChecked() for key, check in self.checks.items()}
        self.checks = {}
        self.card_details = {}
        self.update_buttons = {}
        while self.cards.count():
            self.cards.takeAt(0)
        for card in self._installed_cards.values():
            card.deleteLater()
        self._installed_entries = {}
        self._installed_cards = {}
        self._installed_authors = {}
        from .plugin_updates import pending_versions
        pending = pending_versions(self.manager)
        for entry in self.manager.catalog():
            entry["enabled"] = previous.get(entry["id"], entry["enabled"])
            if entry["id"] in pending:
                entry["status"] = "更新至 " + pending[entry["id"]] + " · 待重启"
            self._add_card(entry)
        self._files_changed = True
        self._show_update_notes(self.store_page.offers)
        self.changed.emit()

    def _show_update_notes(self, offers):
        metadata = {offer['id']: offer for offer in offers}
        for plugin_id in self.card_details:
            author = str(metadata.get(plugin_id, {}).get('author') or '').strip().lstrip('@')
            self._installed_authors[plugin_id].setText('@' + author if author else '')
            self._installed_authors[plugin_id].setToolTip('@' + author if author else '')
            self._installed_authors[plugin_id].setVisible(bool(author))
        self._sync_update_buttons()

    def _sync_update_buttons(self):
        from .online_ui import plugin_update_offers
        from .plugin_updates import pending_versions
        offers = {offer['id']: offer for offer in
                  plugin_update_offers(self.manager, self.store_page.offers)}
        self._available_update_ids = set(offers)
        pending = pending_versions(self.manager) if self.manager else {}
        running = {task.key: task for task in self.store_page.jobs}
        for plugin_id, button in self.update_buttons.items():
            task = running.get(plugin_id)
            button.setVisible(plugin_id in offers or plugin_id in pending)
            button.setEnabled(plugin_id in offers and None not in running and task is None)
            button.setText(('校验/解压中' if task.percent >= 100 else f'下载 {task.percent}%')
                           if task else ('待重启' if plugin_id in pending else '更新'))
        self._filter_installed(reset_scroll=False)

    def _filter_installed(self, *_args, reset_scroll=True):
        terms = self.installed_browser.search.text().casefold().split()
        scope = self.installed_browser.filter.currentIndex()
        metadata = {offer['id']: offer for offer in self.store_page.offers}
        visible = []
        for plugin_id, entry in self._installed_entries.items():
            enabled = self.checks[plugin_id].isChecked()
            text = ' '.join(str(entry.get(key) or '') for key in ('id', 'name', 'description'))
            text += ' ' + str(metadata.get(plugin_id, {}).get('author') or '')
            matches = all(term in text.casefold() for term in terms)
            matches = matches and (scope == 0 or (scope == 1 and enabled)
                or (scope == 2 and not enabled) or (scope == 3 and plugin_id in self._available_update_ids))
            self._installed_cards[plugin_id].setVisible(matches)
            status = entry['status']
            if enabled != self._initial_enabled.get(plugin_id, entry['enabled']):
                status += ' · 已选择' + ('启用' if enabled else '禁用') + '，重启后生效'
            self.card_details[plugin_id][1].setText(status)
            self.card_details[plugin_id][1].setToolTip(status)
            if matches:
                visible.append(entry)
        order = self.installed_browser.sort.currentIndex()
        if order == 1:
            visible.sort(key=lambda entry: (entry['name'].casefold(), entry['id']))
        elif order == 2:
            visible.sort(key=lambda entry: (entry['id'] not in self._available_update_ids, entry['name'].casefold(), entry['id']))
        position = self.installed_scroll.verticalScrollBar().value()
        while self.cards.count():
            self.cards.takeAt(0)
        for index, entry in enumerate(visible):
            self.cards.addWidget(self._installed_cards[entry['id']], index // 2, index % 2)
        self.installed_browser.count.setText(f'{len(visible)} / {len(self._installed_entries)} 个插件')
        self.empty.setText('没有符合条件的已安装插件。' if self._installed_entries else '未发现插件。可装载 ZIP 插件包')
        self.empty.setVisible(not visible)
        self.installed_scroll.verticalScrollBar().setValue(0 if reset_scroll else position)

    def _installed_selection_changed(self):
        self._filter_installed(reset_scroll=False)
        self.changed.emit()

    def _show_installed_details(self, plugin_id):
        from .online_ui import PluginDetailsDialog
        entry = dict(self._installed_entries[plugin_id], enabled=self.checks[plugin_id].isChecked())
        offer = next((offer for offer in self.store_page.offers if offer['id'] == plugin_id), entry)
        dialog = PluginDetailsDialog(self, offer, installed_entry=entry)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.open()
        return dialog

    def _update_plugin(self, plugin_id):
        offer = next((offer for offer in self.store_page.offers if offer['id'] == plugin_id), None)
        if offer:
            self.update_buttons[plugin_id].clearFocus()
            self.store_page.install_offer(offer)

    def _add_card(self, entry):
        card = SettingsSurface()
        card.setObjectName("PluginCard")
        self._installed_entries[entry['id']] = dict(entry)
        self._installed_cards[entry['id']] = card
        body = QHBoxLayout(card)
        body.setContentsMargins(14, 10, 14, 10)
        body.setSpacing(12)
        summary = QVBoxLayout()
        summary.setSpacing(4)
        body.addLayout(summary, 1)
        title = ElidedLabel(entry["name"] + ("  v" + entry["version"] if entry["version"] else ""))
        title.setObjectName("PluginName")
        title.setTextFormat(Qt.PlainText)
        title.setToolTip(entry['name'])
        summary.addWidget(title)
        controls = QGridLayout()
        controls.setSpacing(4)
        check = QCheckBox("启用")
        check.setChecked(entry["enabled"])
        self.checks[entry["id"]] = check
        check.toggled.connect(self._installed_selection_changed)
        controls.addWidget(check, 0, 0)
        update = QPushButton("更新")
        update.setObjectName("IconButton")
        update.setMinimumWidth(update.fontMetrics().horizontalAdvance('校验/解压中') + 28)
        update.hide()
        update.clicked.connect(lambda: self._update_plugin(entry["id"]))
        self.update_buttons[entry["id"]] = update
        controls.addWidget(update, 0, 1)
        remove = QPushButton("删除")
        remove.setObjectName("IconButton")
        remove.clicked.connect(lambda: self._remove(entry["id"], card))
        controls.addWidget(remove, 1, 1)
        details = QPushButton('详情', card)
        details.setObjectName('PluginDetailsButton')
        details.setAccessibleName('查看 ' + entry['name'] + ' 的详情')
        details.clicked.connect(lambda: self._show_installed_details(entry['id']))
        controls.addWidget(details, 1, 0)
        body.addLayout(controls)
        description = ElidedLabel(' '.join((entry["description"] or "暂无说明").split()))
        description.setObjectName('SettingsHint')
        description.setTextFormat(Qt.PlainText)
        description.setToolTip(entry['description'])
        summary.addWidget(description)
        status = ElidedLabel(entry['status'])
        status.setObjectName("SettingsHint")
        status.setTextFormat(Qt.PlainText)
        footer = QHBoxLayout()
        footer.addWidget(status, 1)
        author = ElidedLabel(parent=card)
        author.setObjectName('PluginAuthor')
        author.setTextFormat(Qt.PlainText)
        author.setStyleSheet(f'color: {theme.TEXT3}; font-size: {theme.FONT_CAPTION}px;')
        self._installed_authors[entry['id']] = author
        footer.addWidget(author)
        summary.addLayout(footer)
        self.card_details[entry["id"]] = (description, status, entry['description'])
        index = self.cards.count()
        self.cards.addWidget(card, index // 2, index % 2)

    def _remove(self, plugin_id, card):
        if self.manager is None:
            return
        name = next((entry['name'] for entry in self.manager.catalog() if entry['id'] == plugin_id), plugin_id)
        prompt = PluginRemovePrompt(name, self)
        try:
            if prompt.exec() != PluginRemovePrompt.Accepted:
                return
        finally:
            prompt.deleteLater()
        try:
            self.manager.remove_plugin(plugin_id)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "删除插件失败", str(error))
            return
        del self.checks[plugin_id]
        self.card_details.pop(plugin_id, None)
        self.update_buttons.pop(plugin_id, None)
        self._installed_entries.pop(plugin_id, None)
        self._installed_cards.pop(plugin_id, None)
        self._installed_authors.pop(plugin_id, None)
        self.cards.removeWidget(card)
        card.deleteLater()
        self.store_page.show_offers(self.store_page.offers)
        self.store_page.offersChanged.emit(self.store_page.offers)
        self._files_changed = True
        self.changed.emit()
        self._filter_installed(reset_scroll=False)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if (self.manager is not None and urls and all(
                url.isLocalFile() and url.toLocalFile().lower().endswith((".zip", ".exe"))
                for url in urls)):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        self.dragEnterEvent(event)
        if not event.isAccepted():
            return
        for url in event.mimeData().urls():
            self._install_archive(url.toLocalFile())

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def _install(self):
        archive, _ = QFileDialog.getOpenFileName(self, "装载插件", "", "插件包 (*.zip *.exe)")
        self._install_archive(archive)

    def _install_archive(self, archive):
        if not archive or self.manager is None:
            return
        if not zipfile.is_zipfile(archive):
            QMessageBox.warning(self, "装载插件失败",
                                "此文件不是兼容插件包。需要 ZIP，或内含 ZIP 的 EXE，且包含 plugin.json 和 plugin.py。")
            return
        try:
            plugin_id = self.manager.install_zip(archive)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            QMessageBox.warning(self, "装载插件失败", str(error))
            return
        entry = next(item for item in self.manager.catalog() if item["id"] == plugin_id)
        self._add_card(entry)
        self.store_page.show_offers(self.store_page.offers)
        self.store_page.offersChanged.emit(self.store_page.offers)
        self._files_changed = True
        self.changed.emit()
        from .online_ui import show_result
        show_result(self.window(), "插件已安装，重启后生效")

    def needs_restart(self):
        return self._files_changed or {
            key: check.isChecked() for key, check in self.checks.items()
        } != self._initial_enabled

    def enabled_plugins(self):
        return None if all(check.isChecked() for check in self.checks.values()) else [
            name for name, check in self.checks.items() if check.isChecked()]
