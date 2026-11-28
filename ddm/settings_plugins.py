"""Settings plugins; owned page implementations with legacy exports in dialogs."""
import zipfile
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
)
from .plugin_card_layout import PluginCardLayout
from . import theme
from .motion import AnimatedDialog, SlidingTabs
from .settings_window import SettingsTitleBar
from .ui import ActionButton, SettingsSurface, DisclosureButton, ElidedLabel, HintLabel, TitleLabel, ToggleSwitch, page_header as _page_head
from .search import matches_query


class PluginRemovePrompt(AnimatedDialog):
    def __init__(self, plugin_name, parent=None, *, icon_png=''):
        super().__init__(parent)
        self.setWindowTitle('删除插件')
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName('PluginRemovePrompt')
        self.setStyleSheet('#PluginRemovePrompt {background: palette(window); '
                           'border: 1px solid palette(dark); border-radius: 22px;}')
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 18)
        layout.setSpacing(14)
        self.titlebar = SettingsTitleBar(self)
        self.titlebar.setMinimumHeight(38)
        self.titlebar.row.setContentsMargins(0, 0, 0, 0)
        self.titlebar.breadcrumb.setText(self.windowTitle())
        self.titlebar.close_button.setAccessibleName('关闭删除插件确认')
        self.titlebar.close_button.setToolTip('取消删除')
        layout.addWidget(self.titlebar)
        self.identity = QWidget(self)
        identity_layout = QHBoxLayout(self.identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(10)
        if icon_png:
            from .plugin_store_ui import PluginStoreLogo
            icon = PluginStoreLogo({'icon_png': icon_png}, self.identity)
            identity_layout.addWidget(icon)
            icon.setVisible(not icon.pixmap.isNull())
        self.plugin_title = TitleLabel(plugin_name, self.identity)
        self.plugin_title.setTextFormat(Qt.PlainText)
        self.plugin_title.setWordWrap(True)
        identity_layout.addWidget(self.plugin_title, 1)
        layout.addWidget(self.identity)
        self.detail = HintLabel('将删除此插件及其文件。\n已加载的插件将在重启后停止运行。')
        self.detail.setTextFormat(Qt.PlainText)
        layout.addWidget(self.detail)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = ActionButton('取消')
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.delete_button = ActionButton('删除')
        self.delete_button.setObjectName('DangerButton')
        self.delete_button.setAutoDefault(False)
        self.delete_button.clicked.connect(self.accept)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)
        self.cancel_button.setFocus()

    def show_error(self, error):
        self.setWindowTitle('删除插件失败')
        self.titlebar.breadcrumb.setText(self.windowTitle())
        self.titlebar.close_button.setAccessibleName('关闭删除失败提示')
        self.titlebar.close_button.setToolTip('关闭')
        self.identity.hide()
        self.detail.setText(str(error))
        self.delete_button.hide()
        self.cancel_button.setText('关闭')
        self.cancel_button.setFocus()
        self.exec()


class PluginSettingsPage(QWidget):
    """按现有插件接口展示元数据和下次启动的启用选择。"""

    changed = Signal()

    def __init__(self, manager=None, parent=None, *, include_preview=False):
        super().__init__(parent)
        self.manager = manager
        self.setAcceptDrops(True)
        self.setObjectName("SettingsPage")
        self.checks = {}
        self.card_details = {}
        self.update_buttons = {}
        self._installed_progress = {}
        self._detail_buttons = {}
        self._details = {}
        self._installed_entries = {}
        self._installed_cards = {}
        self._installed_authors = {}
        self._available_update_ids = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(_page_head("插件", ""))
        self.install_button = ActionButton("装载插件…")
        self.install_button.setToolTip('支持 ZIP 插件包及内含插件 ZIP 的 EXE，可拖入此页安装。')
        self.install_button.clicked.connect(self._install)
        actions = QHBoxLayout()
        actions.addWidget(self.install_button)
        self.drop_feedback = HintLabel('松开鼠标安装插件包')
        self.drop_feedback.setStyleSheet('color: palette(highlight); font-weight: 600;')
        self.drop_feedback.hide()
        actions.addWidget(self.drop_feedback)
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
        self.cards = PluginCardLayout()
        self.cards.setContentsMargins(0, 0, 0, 0)
        installed_layout.addLayout(self.cards)
        self.empty = QLabel('暂无已安装插件。', content)
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
        self.store_page = PluginStorePage(manager, include_preview=include_preview)
        self.tabs = SlidingTabs()
        self.tabs.setObjectName("PluginTabs")
        self.tabs.tabBar().setCursor(Qt.PointingHandCursor)
        self.tabs.addTab(installed_page, "已安装")
        self.tabs.addTab(self.store_page, "插件商店")
        self.tabs.currentChanged.connect(self._store_tab_changed)
        self.store_page.installed.connect(self._store_installed)
        self.store_page.offersChanged.connect(self._show_update_notes)
        self.store_page.controlsChanged.connect(self._sync_update_buttons)
        self._show_update_notes(self.store_page.offers)
        layout.addWidget(self.tabs, 1)
        self._package_drop_targets = (self.installed_scroll.viewport(), self.store_page.scroll.viewport(),
                                      self.installed_browser.search, self.store_page.search)
        for target in self._package_drop_targets:
            target.setAcceptDrops(True)
            target.installEventFilter(self)

    def showEvent(self, event):
        super().showEvent(event)
        self.store_page.open_catalog()

    def _store_tab_changed(self, index):
        if index == 1:
            self.store_page.open_catalog()

    def _store_installed(self, plugin_id):
        expanded = [key for key, button in self._detail_buttons.items() if button.isChecked()]
        previous = {key: check.isChecked() for key, check in self.checks.items()}
        self.checks = {}
        self.card_details = {}
        self.update_buttons = {}
        self._installed_progress = {}
        self._detail_buttons = {}
        self._details = {}
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
        for key in expanded:
            if key in self._detail_buttons:
                self._detail_buttons[key].setChecked(True)

    def _show_update_notes(self, offers):
        metadata = {offer['id']: offer for offer in offers}
        for plugin_id in self.card_details:
            author = str(metadata.get(plugin_id, {}).get('author') or '').strip().lstrip('@')
            self._installed_authors[plugin_id].setText('@' + author if author else '')
            self._installed_authors[plugin_id].setToolTip('@' + author if author else '')
            self._installed_authors[plugin_id].setVisible(bool(author))
        self._sync_update_buttons(refilter=True)

    def _sync_update_buttons(self, *, refilter=False):
        from .update_offers import available_plugin_updates
        from .plugin_updates import pending_versions
        pending = pending_versions(self.manager) if self.manager else {}
        offers = {offer['id'] for offer in
                  available_plugin_updates(self._installed_entries, pending, self.store_page.offers)}
        refilter = refilter or offers != self._available_update_ids
        self._available_update_ids = offers
        running = {task.key: task for task in self.store_page.jobs}
        for plugin_id, button in self.update_buttons.items():
            task = running.get(plugin_id)
            button.setVisible(plugin_id in offers or plugin_id in pending)
            button.setEnabled(plugin_id in offers and None not in running and task is None)
            button.setText(('校验/解压中' if task.percent >= 100 else '下载中…')
                           if task else ('待重启' if plugin_id in pending else '更新'))
            state = self.store_page.downloads.states.get(plugin_id)
            if state:
                self._installed_progress[plugin_id].set_state(state)
        if refilter:
            self._filter_installed(reset_scroll=False)

    def _filter_installed(self, *_args, reset_scroll=True):
        query = self.installed_browser.search.text()
        scope = self.installed_browser.filter.currentIndex()
        metadata = {offer['id']: offer for offer in self.store_page.offers}
        visible = []
        for plugin_id, entry in self._installed_entries.items():
            enabled = self.checks[plugin_id].isChecked()
            text = ' '.join(str(entry.get(key) or '') for key in ('id', 'name', 'description'))
            text += ' ' + str(metadata.get(plugin_id, {}).get('author') or '')
            matches = matches_query(text, query)
            matches = matches and (scope == 0 or (scope == 1 and enabled)
                or (scope == 2 and not enabled) or (scope == 3 and plugin_id in self._available_update_ids))
            self._installed_cards[plugin_id].setVisible(matches)
            status = entry['status']
            if enabled != self._initial_enabled.get(plugin_id, entry['enabled']):
                status += ' · 重启后' + ('启用' if enabled else '禁用')
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
        for entry in visible:
            self.cards.addWidget(self._installed_cards[entry['id']])
        self.cards.fit_columns(self.installed_scroll.viewport().width() - 4)
        self.installed_browser.count.setText(f'{len(visible)} / {len(self._installed_entries)} 个插件')
        self.empty.setText('没有符合条件的已安装插件。' if self._installed_entries else '暂无已安装插件。')
        self.empty.setVisible(not visible)
        self.installed_scroll.verticalScrollBar().setValue(0 if reset_scroll else position)

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.installed_scroll.viewport() and kind == QEvent.Resize:
            if event.size().width() != event.oldSize().width():
                self._filter_installed(reset_scroll=False)
        elif watched in self._package_drop_targets:
            if kind == QEvent.DragLeave and not self.drop_feedback.isHidden():
                self.dragLeaveEvent(event)
                return True
            if kind in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop) and event.mimeData().hasUrls():
                if kind == QEvent.Drop:
                    self.dropEvent(event)
                else:
                    self.dragEnterEvent(event)
                return True
        return super().eventFilter(watched, event)

    def _installed_selection_changed(self, _checked):
        self._filter_installed(reset_scroll=False)
        self.changed.emit()

    def _show_installed_details(self, plugin_id):
        self._detail_buttons[plugin_id].setChecked(True)
        return self._details[plugin_id]

    def _toggle_details(self, plugin_id, expanded):
        button = self._detail_buttons[plugin_id]
        button.setText('收起' if expanded else '详情')
        if expanded and plugin_id not in self._details:
            from .plugin_details_ui import PluginDetailsPanel
            entry = dict(self._installed_entries[plugin_id], enabled=self.checks[plugin_id].isChecked())
            offer = next((offer for offer in self.store_page.offers if offer['id'] == plugin_id), entry)
            card = self._installed_cards[plugin_id]
            panel = PluginDetailsPanel(self, offer, installed_entry=entry, parent=card)
            panel.collapsed.connect(lambda: button.setChecked(False))
            card.layout().insertWidget(1, panel)
            self._details[plugin_id] = panel
        panel = self._details.get(plugin_id)
        if panel is not None:
            if expanded:
                panel.refresh_action()
            panel.setVisible(expanded)
            panel.updateGeometry()

    def _update_plugin(self, plugin_id):
        offer = next((offer for offer in self.store_page.offers if offer['id'] == plugin_id), None)
        if offer:
            self.update_buttons[plugin_id].clearFocus()
            self.store_page.install_offer(offer)

    def _add_card(self, entry):
        card = SettingsSurface()
        card.setObjectName("PluginCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._installed_entries[entry['id']] = dict(entry)
        self._installed_cards[entry['id']] = card
        body = QVBoxLayout(card)
        body.setSizeConstraint(QLayout.SetMinimumSize)
        body.setAlignment(Qt.AlignTop)
        body.setContentsMargins(14, 10, 14, 10)
        body.setSpacing(12)
        summary = QVBoxLayout()
        summary.setSpacing(4)
        from .plugin_store_ui import PluginStoreLogo
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(PluginStoreLogo(entry, card), 0, Qt.AlignTop)
        header.addLayout(summary, 1)
        body.addLayout(header)
        title = ElidedLabel(entry["name"] + ("  v" + entry["version"] if entry["version"] else ""))
        title.setObjectName("PluginName")
        title.setTextFormat(Qt.PlainText)
        title.setToolTip(entry['name'])
        heading = QHBoxLayout()
        heading.addWidget(title, 1)
        summary.addLayout(heading)
        check = ToggleSwitch('启用 ' + entry['name'])
        check.setText('启用')
        check.setAccessibleDescription('启用或停用更改在重启后生效')
        check.setChecked(entry["enabled"])
        self.checks[entry["id"]] = check
        check.toggled.connect(self._installed_selection_changed)
        enabled_label = QLabel('启用')
        enabled_label.setBuddy(check)
        heading.addWidget(enabled_label)
        heading.addWidget(check)
        update = ActionButton("更新")
        update.setMinimumWidth(update.fontMetrics().horizontalAdvance('校验/解压中') + 28)
        update.hide()
        update.clicked.connect(lambda: self._update_plugin(entry["id"]))
        self.update_buttons[entry["id"]] = update
        remove = ActionButton("删除")
        remove.clicked.connect(lambda: self._remove(entry["id"], card))
        details = DisclosureButton(card)
        details.setText('详情')
        details.setObjectName('PluginDetailsButton')
        details.setAccessibleName('查看 ' + entry['name'] + ' 的详情')
        details.toggled.connect(lambda checked: self._toggle_details(entry['id'], checked))
        self._detail_buttons[entry['id']] = details
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
        from .update_progress_ui import UpdateProgress
        progress = UpdateProgress(card, button=update)
        self._installed_progress[entry['id']] = progress
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(progress, 1)
        actions.addWidget(details)
        actions.addWidget(remove)
        body.addLayout(actions)
        self.card_details[entry["id"]] = (description, status, entry['description'])
        self.cards.addWidget(card)

    def _remove(self, plugin_id, card):
        if self.manager is None:
            return
        entry = self._installed_entries[plugin_id]
        prompt = PluginRemovePrompt(entry['name'], self, icon_png=entry.get('icon_png', ''))
        try:
            if prompt.exec() != PluginRemovePrompt.Accepted:
                return
            try:
                self.manager.remove_plugin(plugin_id)
            except (OSError, ValueError) as error:
                prompt.show_error(error)
                return
        finally:
            prompt.deleteLater()
        del self.checks[plugin_id]
        self.card_details.pop(plugin_id, None)
        self.update_buttons.pop(plugin_id, None)
        self._installed_entries.pop(plugin_id, None)
        self._installed_cards.pop(plugin_id, None)
        self._installed_authors.pop(plugin_id, None)
        self._installed_progress.pop(plugin_id, None)
        self._detail_buttons.pop(plugin_id, None)
        self._details.pop(plugin_id, None)
        self.cards.removeWidget(card)
        card.deleteLater()
        self.store_page.show_offers(self.store_page.offers)
        self.store_page.offersChanged.emit(self.store_page.offers)
        self._files_changed = True
        self.changed.emit()
        self._filter_installed(reset_scroll=False)

    def _package_paths(self, event):
        if self.manager is None or not event.possibleActions() & Qt.CopyAction:
            return []
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        return [path for path in paths if path.lower().endswith(('.zip', '.exe'))]

    def dragEnterEvent(self, event):
        accepted = bool(self._package_paths(event))
        self.drop_feedback.setVisible(accepted)
        self._accept_package_drop(event, accepted)

    def dropEvent(self, event):
        paths = self._package_paths(event)
        self.drop_feedback.hide()
        self._accept_package_drop(event, bool(paths))
        for path in paths:
            self._install_archive(path)

    @staticmethod
    def _accept_package_drop(event, accepted):
        if accepted:
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self.drop_feedback.hide()
        event.accept()

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
        show_result(self.window(), "插件已安装")

    def needs_restart(self):
        return self._files_changed or {
            key: check.isChecked() for key, check in self.checks.items()
        } != self._initial_enabled

    def enabled_plugins(self):
        return None if all(check.isChecked() for check in self.checks.values()) else [
            name for name, check in self.checks.items() if check.isChecked()]
