"""对话框：设置（常规 / 快捷键）、添加直播间、从关注导入。"""
import sys
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget
)

from .update_version import update_identity
from .motion import SettingsStack

# 快捷键动作：键名 -> (显示名, 默认按键)
# 按下的键用 QKeySequence 的字符串表示，组合键写成 "Alt+M" / "Ctrl+Shift+F"。
from .shortcut_actions import SHORTCUT_ACTIONS
from .settings_general import (CodecSettingsPanel, CodecSettingsDialog, GeneralSettingsPage, TraySettingsPage)
from .settings_notifications import (NotificationSwitch, NoticeBlurPreview, NotificationSettingsPage)
from .settings_shortcuts import ShortcutSettingsPage
from .settings_danmaku import DanmakuSettingsPage
from .settings_recording import RecordingSettingsPage
from .settings_plugins import (PluginRemovePrompt, PluginSettingsPage)
from .settings_appearance import AppearanceSettingsPage


class SettingsDialog(QDialog):
    updatesViewed = Signal(object)
    appearanceChanged = Signal(str)
    pageCreated = Signal(int, object)
    """设置总窗口：左边选类别，右边改内容，不再弹二级菜单。"""

    PAGES = [("general", "常规"), ("appearance", "外观"), ("danmaku", "弹幕"),
             ("recording", "录制"), ("notifications", "通知"), ("shortcuts", "快捷键"),
             ("tray", "托盘行为"), ("plugins", "插件"), ("updates", "软件更新")]
    PAGE_INDEX = {key: index for index, (key, _label) in enumerate(PAGES)}

    def __init__(self, settings: dict, shortcuts: dict, parent=None, plugin_manager=None, *, preview=False,
                 update_page_factory=None):
        super().__init__(parent)
        self._created_at = time.perf_counter()
        self._paint_logged = False
        from .config import DEFAULT_SETTINGS
        # Part artwork and per-tile video danmaku are saved by their own editors.
        self._initial_settings = {key: settings.get(key, default) for key, default in DEFAULT_SETTINGS.items()
                                  if not key.startswith('video_danmaku_')
                                  and key not in ('skin_parts', 'danmaku_retention_version')}
        self._initial_shortcuts = {key: shortcuts.get(key) or default for key, _label, default in SHORTCUT_ACTIONS}
        self._plugin_manager = plugin_manager
        self._preview_only = preview
        self._update_page_factory = update_page_factory
        self.setWindowTitle("设置")
        self.restart_requested = False
        self.seen_versions = dict(settings.get('seen_update_versions') or {})
        available = self.screen().availableGeometry()
        self.setMinimumSize(760, 520)
        self.resize(min(1200, available.width() - 48), min(800, available.height() - 72))

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        from .settings_navigation import SettingsNavigation, SettingsPointerNavigation
        from .online_ui import AppUpdatePage
        self.navigation = SettingsNavigation(self.PAGES, self)
        self.nav = self.navigation.nav
        root.addWidget(self.navigation)

        self.content = QWidget(self)
        right = QVBoxLayout(self.content)
        right.setContentsMargins(20, 18, 20, 16)
        right.setSpacing(14)
        self.stack = SettingsStack()
        self.stack.setObjectName("SettingsStack")
        self.general_page = GeneralSettingsPage(settings)
        # Build the expensive controls only when their page is first requested.
        # Keep the public page properties so callers and settings validation
        # still use the same controls and value normalization.
        self._page_factories = {
            1: lambda: AppearanceSettingsPage(settings, skin_controller=getattr(parent, 'skin_controller', None)),
            2: lambda: DanmakuSettingsPage(settings),
            3: lambda: RecordingSettingsPage(settings),
            4: lambda: NotificationSettingsPage(settings),
            5: lambda: ShortcutSettingsPage(shortcuts),
            6: lambda: TraySettingsPage(settings),
            7: lambda: PluginSettingsPage(plugin_manager),
            8: lambda: update_page_factory(settings) if update_page_factory else AppUpdatePage(settings),
        }
        self._loaded_pages = {}
        if preview:
            # The appearance thumbnail needs the real controls, without creating
            # update/download workers or reading an installation result.
            self._page_factories[7] = QWidget
            self._page_factories[8] = QWidget
        self.general_scroll = QScrollArea()
        self.general_scroll.setFrameShape(QFrame.NoFrame)
        self.general_scroll.setWidgetResizable(True)
        self.general_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.general_scroll.setWidget(self.general_page)
        self.stack.addWidget(self.general_scroll)
        for _index in range(len(self.PAGES) - 1):
            self.stack.addWidget(QWidget())
        right.addWidget(self.stack, 1)

        buttons = QHBoxLayout()
        self.reset_button = QPushButton("恢复默认")
        self.reset_button.setObjectName("IconButton")
        self.reset_button.clicked.connect(self._reset_current)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.clicked.connect(self.reject)
        self.confirm_button = QPushButton("保存")
        self.confirm_button.setObjectName("PrimaryButton")
        self.confirm_button.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm_button)
        right.addLayout(buttons)
        root.addWidget(self.content, 1)
        self.pointer_navigation = SettingsPointerNavigation(self, self.navigation, self.content)

        self.nav.currentRowChanged.connect(self._on_page_changed)
        self.nav.setCurrentRow(0)
        if preview:
            return
        self._update_save_button()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._paint_logged:
            self._paint_logged = True
            print(f"[设置耗时] 首次绘制 {(time.perf_counter() - self._created_at) * 1000:.1f}ms",
                  file=sys.stderr, flush=True)

    def _mark_update_page(self, key, active):
        for index in range(self.nav.count()):
            item = self.nav.item(index)
            if item.data(Qt.UserRole) == key:
                item.setData(Qt.UserRole + 1, active)

    def _page(self, index):
        if index not in self._loaded_pages:
            started = time.perf_counter()
            placeholder = self.stack.widget(index)
            page = self._page_factories[index]()
            self._loaded_pages[index] = page
            self.stack.removeWidget(placeholder)
            self.stack.insertWidget(index, page)
            placeholder.deleteLater()
            if index == 1:
                page.modeChanged.connect(self.appearanceChanged)
            elif index == 7 and not self._preview_only:
                from .online_ui import UpdateDot
                from PySide6.QtWidgets import QTabBar
                page.store_page.seen_versions = self.seen_versions
                self._plugin_update_dot = UpdateDot()
                page.tabs.tabBar().setTabButton(1, QTabBar.RightSide, self._plugin_update_dot)
                page.changed.connect(self._update_save_button)
                page.store_page.busyChanged.connect(self._update_save_button)
                page.store_page.offersChanged.connect(self._mark_plugin_updates)
                self._mark_plugin_updates(page.store_page.offers)
            elif index == 8 and not self._preview_only:
                page.saveRequested.connect(self._save)
                page.busyChanged.connect(self._update_save_button)
                page.releaseChecked.connect(self._mark_app_update)
                page.data_page.changed.connect(self._update_save_button)
                self._update_save_button()
            self.pageCreated.emit(index, page)
            print(f"[设置耗时] 创建 {self.PAGES[index][0]} 页 {(time.perf_counter() - started) * 1000:.1f}ms",
                  file=sys.stderr, flush=True)
        return self._loaded_pages[index]

    appearance_page = property(lambda self: self._page(1))
    danmaku_page = property(lambda self: self._page(2))
    recording_page = property(lambda self: self._page(3))
    notification_page = property(lambda self: self._page(4))
    shortcut_page = property(lambda self: self._page(5))
    plugin_page = property(lambda self: self._page(7))
    update_page = property(lambda self: self._page(8))

    def _remember_versions(self, versions):
        if any(self.seen_versions.get(key) != value for key, value in versions.items()):
            self.seen_versions.update(versions)
            self.updatesViewed.emit(dict(self.seen_versions))

    def _mark_app_update(self, offer):
        if offer and self.nav.currentRow() == 8:
            self._remember_versions({'app': update_identity(offer)})
        active = bool(offer and self.seen_versions.get('app') != update_identity(offer))
        self._mark_update_page('updates', active)

    def _mark_plugin_updates(self, offers):
        from .online_ui import plugin_update_offers
        updates = plugin_update_offers(self.plugin_page.store_page.manager, offers)
        if self.nav.currentRow() == 7:
            self._remember_versions({offer['id']: offer['version'] for offer in updates})
        active = any(self.seen_versions.get(offer['id']) != offer['version'] for offer in updates)
        self._mark_update_page('plugins', active)
        self._plugin_update_dot.setVisible(active)
        self.plugin_page.store_page.update_dots()

    def _update_save_button(self, *_args) -> None:
        plugin, update = self._loaded_pages.get(7), self._loaded_pages.get(8)
        data = getattr(update, 'data_page', None)
        restart = (plugin is not None and plugin.needs_restart()) or getattr(data, 'target', None) is not None
        self.confirm_button.setText("保存并重启" if restart else "保存")
        self.confirm_button.setEnabled(not (plugin is not None and plugin.store_page.jobs)
                                      and not (update is not None and update.jobs))

    def _save(self) -> None:
        appearance = self._loaded_pages.get(1)
        if appearance is not None and appearance.parts_editor is not None:
            if not appearance.parts_editor.save_changes():
                self.nav.setCurrentRow(1)
                appearance.scroll.ensureWidgetVisible(appearance.parts_editor.status)
                return
        plugin = self._loaded_pages.get(7)
        data = getattr(self._loaded_pages.get(8), 'data_page', None)
        if data is not None and not data.prepare():
            self.nav.setCurrentRow(8)
            self.update_page.scroll.ensureWidgetVisible(data.status)
            return
        self.restart_requested = (plugin is not None and plugin.needs_restart()) or getattr(data, 'target', None) is not None
        self.accept()

    def done(self, result):
        if self._preview_only:
            return super().done(result)
        self.stack.finish_transition()
        if 7 in self._loaded_pages:
            self._loaded_pages[7].store_page.stop()
        if 8 in self._loaded_pages:
            page = self._loaded_pages[8]
            if result != QDialog.Accepted:
                page.data_page.cancel_target()
            if self._update_page_factory is None:
                page.stop()
            elif page.parentWidget() is self.stack:
                page.saveRequested.disconnect()
                page.busyChanged.disconnect(self._update_save_button)
                page.releaseChecked.disconnect(self._mark_app_update)
                page.data_page.changed.disconnect(self._update_save_button)
                self.stack.removeWidget(page)
                page.hide()
                page.setParent(self.parentWidget())
        super().done(result)

    def _on_page_changed(self, index: int) -> None:
        if index >= 0:
            if index in self._page_factories:
                self._page(index)
            self.stack.show_page(index, animate=bool(QApplication.mouseButtons()))
            self.reset_button.setText("恢复本页默认")
            self.reset_button.setVisible(index not in (7, 8))
            if index == 7 and not self._preview_only:
                self._mark_plugin_updates(self.plugin_page.store_page.offers)
            elif index == 8 and not self._preview_only:
                self._mark_app_update(self.update_page.offer)

    def _reset_current(self) -> None:
        page = self.general_page if self.stack.currentIndex() == 0 else self.stack.currentWidget()
        if hasattr(page, "reset"):
            page.reset()

    def settings(self) -> dict:
        values = dict(self._initial_settings)
        values.update(self.general_page.values())
        for index in (1, 2, 3, 4, 6):
            if index in self._loaded_pages:
                values.update(self._loaded_pages[index].values())
        if 8 in self._loaded_pages:
            values.update(self._loaded_pages[8].values())
        values['seen_update_versions'] = dict(self.seen_versions)
        return values

    def shortcuts(self) -> dict:
        return self._loaded_pages[5].values() if 5 in self._loaded_pages else dict(self._initial_shortcuts)

    def enabled_plugins(self):
        if 7 in self._loaded_pages:
            return self._loaded_pages[7].enabled_plugins()
        enabled = self._plugin_manager.enabled if self._plugin_manager is not None else None
        return None if enabled is None else set(enabled)


from .room_dialogs import (_add_folder_option, _create_folder_for_dialog, AddRoomDialog, FollowImportDialog)
