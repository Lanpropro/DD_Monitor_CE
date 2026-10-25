"""Host-dependent settings content embedded in the existing worker window."""
from types import SimpleNamespace

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QCheckBox

from .dialogs import SettingsDialog
from .config import DEFAULT_SETTINGS


class SettingsHost(QObject):
    def __init__(self, window, client, message):
        super().__init__(window)
        self.window, self.client = window, client
        self.before = (None if window.plugins.enabled is None else set(window.plugins.enabled),
                       dict(window.plugins._platform_owner), set(window.plugins._removed))
        self.dialog = window._create_settings_dialog(
            {**window.settings, **{key: value for key, value in message['settings'].items()
                                   if key in DEFAULT_SETTINGS}}, message['shortcuts'])
        self.stack = self.dialog.stack
        self.embedded = False
        # Existing plugins contribute controls on SettingsDialog's Show event.
        # Dispatch that event without showing or activating a second window.
        QApplication.sendEvent(self.dialog, QEvent(QEvent.Show))
        page = self.dialog.general_page
        core = set(page._checks.values())
        grid = page.layout().itemAt(1).layout()
        checks = [check for check in page.findChildren(QCheckBox)
                  if check not in core and check.objectName() and grid.indexOf(check) >= 0]
        checks.sort(key=lambda check: grid.getItemPosition(grid.indexOf(check))[:2])
        self.plugin_checks = {check.objectName(): check for check in checks}
        escape = QShortcut(QKeySequence(Qt.Key_Escape), self.stack)
        escape.setContext(Qt.WidgetWithChildrenShortcut)
        escape.activated.connect(lambda: client._send({'kind': 'host-cancel'}))
        self.dialog.appearanceChanged.connect(
            lambda mode: client._send({'kind': 'host-theme', 'mode': mode}))
        self.last_state = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.sync)
        self.timer.start()

    def handle(self, message):
        kind = message['kind']
        if kind == 'host-general':
            master = self.dialog.general_page._checks['sidebar_platform_logos'].isChecked()
            self.client._send({'kind': 'host-general-controls', 'controls': [
                {'name': name, 'label': check.text(), 'checked': check.isChecked() and
                 (master if name.endswith('_show_platform_logo') else True)}
                for name, check in self.plugin_checks.items()]})
        elif kind == 'host-page':
            if not self.embedded:
                self.stack.setProperty('embeddedSettings', True)
                self.stack.setParent(None, Qt.FramelessWindowHint)
                self.stack.setAttribute(Qt.WA_ShowWithoutActivating)
                self.stack.style().polish(self.stack)
                self.embedded = True
            self.dialog.nav.setCurrentRow(message['index'])
            self.stack.finish_transition()
            self.client._send({'kind': 'host-ready', 'hwnd': int(self.stack.winId())})
            self.sync()
        elif kind == 'host-reset':
            self.dialog._reset_current()
            self.sync()
        elif kind == 'host-attached':
            self.stack.show()
        elif kind == 'host-hidden':
            self.dialog.nav.setCurrentRow(-1)
        elif kind == 'host-save':
            self.save(message['changes'])

    def values(self):
        values = {'seen_update_versions': dict(self.dialog.seen_versions)}
        for index in (1, 7):
            page = self.dialog._loaded_pages.get(index)
            if page is not None:
                values.update(page.values())
        return values

    def sync(self):
        state = {'kind': 'host-state', 'values': self.values(),
                 'save_enabled': self.dialog.confirm_button.isEnabled(),
                 'save_text': self.dialog.confirm_button.text(),
                 'marks': {key: bool(self.dialog.nav.item(index).data(Qt.UserRole + 1))
                           for index, (key, _label) in enumerate(self.dialog.PAGES)}}
        if state != self.last_state:
            self.last_state = state
            self.client._send(state)

    def save(self, changes):
        for name, checked in changes.get('plugin_controls', {}).items():
            self.plugin_checks[name].setChecked(checked)
        self.dialog._update_save_button()
        if not self.dialog.confirm_button.isEnabled():
            self.sync()
            return
        self.dialog.setResult(SettingsDialog.Rejected)
        self.dialog._save()
        if self.dialog.result() != SettingsDialog.Accepted:
            self.client._send({'kind': 'host-save-blocked', 'index': 1})
            return
        values = {**changes.get('settings', {}), **self.values()}
        adapter = SimpleNamespace(
            settings=lambda: values,
            shortcuts=lambda: {**self.window.shortcuts, **changes.get('shortcuts', {})},
            enabled_plugins=self.dialog.enabled_plugins,
            _loaded_pages=self.dialog._loaded_pages,
            update_page=self.dialog._loaded_pages.get(7),
            restart_requested=self.dialog.restart_requested)
        self.window._apply_settings_dialog(adapter, self.before)
        if not self.client.closing:
            self.client._send({'kind': 'host-saved'})

    def close(self):
        self.timer.stop()
        self.stack.hide()
        self.stack.setParent(self.dialog)
        self.dialog.reject()
        self.dialog.deleteLater()
        self.deleteLater()
