"""Settings worker application and snapshot-driven isolated dialog."""
import json
from copy import deepcopy
import os
from pathlib import Path
import sys
import time
from PySide6.QtCore import QObject, QTimer, Signal


def run_worker():
    # The worker receives a settings snapshot; it must not read/write the
    # portable installation's account, configuration or installed plugins.
    from . import settings_process as host_api
    os.environ['DDM_NO_SAVE'] = '1'
    import tempfile
    import threading
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QIcon, QWindow
    from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QVBoxLayout, QWidget
    from . import config, theme
    from .dialogs import SettingsDialog
    from .shortcut_actions import SHORTCUT_ACTIONS

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    from .localization import install_chinese_translations
    install_chinese_translations(app)
    for icon_path in (Path(config.REPO) / 'assets/favicon.ico', Path(config.REPO) / 'favicon.ico'):
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
            break

    def send(message):
        print(host_api.PREFIX + json.dumps(message), flush=True)

    class RemoteDialog(SettingsDialog):
        def __init__(self, snapshot):
            from .native_diagnostics import set_dump_enabled
            set_dump_enabled(snapshot["settings"].get("native_crash_dump", False))
            self._host_save_error = False
            self.host_action_visible = False
            self.host_action_text = ''
            self.host_requested = False
            self.host_saved = False
            self.host_flush_done = False
            self.pending_close_result = None
            self.host_values = {}
            self.host_container = None
            self.host_surface_ready = False
            self.foreign = None
            self.plugin_checks = {}
            self.painted = False
            super().__init__(snapshot['settings'], snapshot['shortcuts'], preview=True)
            self._auto_save_enabled = True
            self.auto_save.requested.connect(lambda changes: send({'kind': 'auto-save', 'changes': changes}))
            self.occlusion_timer = QTimer(self)
            self.occlusion_timer.setSingleShot(True)
            self.occlusion_timer.timeout.connect(self.publish_occlusion)
            self.pageCreated.connect(lambda index, page: page.super_chat_placement.set_preview_context(
                snapshot.get('sc_preview_context', {})) if index == 2 else None)
            self.owner_window = None
            if snapshot.get('owner_hwnd') and app.platformName() == 'windows':
                # A separate process has no QWidget parent. Native ownership
                # keeps settings above the host when its video overlays raise.
                self.owner_window = QWindow.fromWinId(snapshot['owner_hwnd'])
                self.winId()
                self.windowHandle().setTransientParent(self.owner_window)
            # Compare against the values shown by the controls, not raw input.
            # settings() adds metadata such as an empty seen_update_versions map.
            self.initial_settings = deepcopy(self.settings())
            self.initial_shortcuts = {
                **{key: default for key, _label, default in SHORTCUT_ACTIONS},
                **self.shortcuts()}

        def event(self, event):
            result = super().event(event)
            if (event.type() in (QEvent.Show, QEvent.Hide, QEvent.Move, QEvent.Resize,
                                 QEvent.WindowStateChange)
                    and hasattr(self, 'occlusion_timer')):
                self.occlusion_timer.start(0)
            return result

        def _auto_save_status(self, state, error):
            self._host_save_error = False
            super()._auto_save_status(state, error)

        def _retry_auto_save(self):
            if self._host_save_error:
                send({'kind': 'host-retry'})
            else:
                self.auto_save.flush()

        def publish_occlusion(self):
            # The host cannot find this cross-process dialog in topLevelWidgets.
            rect = list(self.frameGeometry().getRect()) if self.isVisible() and not self.isMinimized() else []
            send({'kind': 'occlusion', 'rect': rect})

        def changes(self):
            return {'settings': {key: value for key, value in self.settings().items()
                                 if value != self.initial_settings.get(key)},
                    'shortcuts': {key: value for key, value in self.shortcuts().items()
                                  if value != self.initial_shortcuts.get(key)},
                    'plugin_controls': {name: check.isChecked() for name, check in self.plugin_checks.items()}}

        def set_plugin_controls(self, controls):
            if self.plugin_checks:
                return
            page = self.general_page
            grid = page.layout().itemAt(1).layout()
            anchor = page._checks['sidebar_platform_logos']
            row = grid.getItemPosition(grid.indexOf(anchor))[0] + 1
            for control in reversed(controls):
                for index in range(grid.count() - 1, -1, -1):
                    old_row, column, rows, columns = grid.getItemPosition(index)
                    if old_row >= row:
                        item = grid.takeAt(index)
                        grid.addItem(item, old_row + 1, column, rows, columns)
                check = QCheckBox(control['label'], page)
                check.setObjectName(control['name'])
                check.setChecked(control['checked'])
                grid.addWidget(check, row, 0, 1, 2)
                self.plugin_checks[control['name']] = check
            self.auto_save.adopt('plugin_controls', {name: check.isChecked() for name, check in self.plugin_checks.items()})
            if any(name.endswith('_show_platform_logo') for name in self.plugin_checks):
                grid.removeWidget(anchor)
                anchor.hide()
                anchor.setChecked(True)  # Per-plugin switches now decide which platforms are visible.

        def settings(self):
            return {**super().settings(), **self.host_values}

        def _on_page_changed(self, index):
            if index not in host_api.HOST_PAGES:
                super()._on_page_changed(index)
                if self.host_container is not None:
                    self.stack.finish_transition()  # Native child windows cannot use opacity effects.
                if self.host_requested:
                    send({'kind': 'host-hidden'})
                return
            self.host_requested = True
            self.stack.finish_transition()
            if self.host_container is None:
                placeholder = self.stack.widget(index)
                if placeholder.layout() is None:
                    layout = QVBoxLayout(placeholder)
                    label = QLabel('正在加载设置…')
                    label.setAlignment(Qt.AlignCenter)
                    layout.addWidget(label)
                self.stack.setCurrentIndex(index)
            else:
                self.stack.setCurrentWidget(self.host_container)
            self.confirm_button.setText(self.host_action_text)
            self.confirm_button.setVisible(self.host_action_visible)
            self.reset_button.setVisible(index == 1)
            self.reset_button.setText('恢复本页默认')
            send({'kind': 'host-page', 'index': index,
                  'parent_hwnd': int(self.winId()),
                  'settings': self.settings(), 'shortcuts': self.shortcuts()})

        def embed_host(self, hwnd):
            attached = False
            if self.host_container is None:
                self.foreign = QWindow.fromWinId(hwnd)
                if self.foreign is None:
                    raise RuntimeError('The platform cannot embed the host settings page')
                self.host_container = QWidget.createWindowContainer(self.foreign, self.stack)
                self.host_container.setFocusPolicy(Qt.StrongFocus)
                self.stack.addWidget(self.host_container)
                attached = True
            if self.nav.currentRow() in host_api.HOST_PAGES:
                self.stack.setCurrentWidget(self.host_container)
                self.stack.layout().activate()
            if attached:
                send({'kind': 'host-attached', 'size': [self.host_container.width(), self.host_container.height()]})

        def _reset_current(self):
            if self.nav.currentRow() in host_api.HOST_PAGES:
                send({'kind': 'host-reset'})
            else:
                super()._reset_current()

        def _save(self):
            if self.auto_save.defer(self._save):
                return
            self._save_clicked_at = host_api._save_trace('worker.click')
            if self.host_requested or self.plugin_checks:
                self.confirm_button.setEnabled(False)
                started = time.perf_counter_ns()
                changes = self.changes()
                host_api._save_trace('worker.changes.collected', started)
                send({'kind': 'host-save', 'changes': changes})
                host_api._save_trace('worker.host-save.sent', self._save_clicked_at)
            else:
                super()._save()

        def done(self, result):
            if not self.auto_save.request_close(result):
                return
            if self.host_requested and not self.host_saved and not self.host_flush_done:
                self.pending_close_result = int(result)
                send({'kind': 'host-flush'})
                return
            started = getattr(self, '_save_clicked_at', None)
            detached = time.perf_counter_ns()
            if self.foreign is not None:
                self.foreign.hide()
                self.foreign.setParent(None)
                self.foreign = None
            if started is not None:
                host_api._save_trace('worker.detach.finished', detached)
            super().done(result)
            if started is not None:
                host_api._save_trace('worker.done', started)

        def paintEvent(self, event):
            super().paintEvent(event)
            if not self.painted:
                self.painted = True
                send({'kind': 'painted', 'pid': os.getpid()})
                send({'kind': 'host-general', 'settings': self.settings(), 'shortcuts': self.shortcuts()})

    class Worker(QObject):
        request = Signal(dict)

        def __init__(self):
            super().__init__()
            self.dialog = None
            self.request.connect(self.handle)

        def handle(self, message):
            kind = message.get('kind')
            if kind == 'quit':
                if self.dialog is not None:
                    self.dialog.auto_save.active = False
                    self.dialog.host_flush_done = True
                    self.dialog.reject()
                app.quit()
            elif kind == 'host-ready' and self.dialog is not None:
                self.dialog.embed_host(message['hwnd'])
            elif kind == 'host-shown' and self.dialog is not None:
                self.dialog.host_surface_ready = True
            elif kind == 'host-flushed' and self.dialog is not None:
                self.dialog.host_flush_done = True
                self.dialog.done(self.dialog.pending_close_result)
            elif kind == 'auto-saved' and self.dialog is not None:
                self.dialog.auto_save.acknowledge(message.get('error', ''))
            elif kind == 'auto-status' and self.dialog is not None:
                self.dialog._host_save_error = message['state'] == 'error'
                SettingsDialog._auto_save_status(self.dialog, message['state'], message['error'])
            elif kind == 'host-state' and self.dialog is not None:
                self.dialog.host_values = message['values']
                self.dialog.set_material({**self.dialog._initial_settings, **message['values']})
                self.dialog.auto_save.adopt('settings', message['values'])
                self.dialog.host_action_visible = message.get('action_visible', False)
                self.dialog.host_action_text = message['save_text']
                self.dialog.confirm_button.setVisible(self.dialog.host_action_visible and self.dialog.nav.currentRow() in host_api.HOST_PAGES)
                self.dialog.confirm_button.setEnabled(message['save_enabled'])
                self.dialog.confirm_button.setText(message['save_text'])
                for key, active in message['marks'].items():
                    self.dialog._mark_update_page(key, active)
            elif kind == 'host-general-controls' and self.dialog is not None:
                self.dialog.set_plugin_controls(message['controls'])
            elif kind == 'host-theme' and self.dialog is not None:
                theme.apply(message['mode'])
            elif kind == 'host-save-blocked' and self.dialog is not None:
                host_api._save_trace('worker.save.blocked', getattr(self.dialog, '_save_clicked_at', None))
                self.dialog._save_clicked_at = None
                self.dialog.confirm_button.setEnabled(True)
                self.dialog.nav.setCurrentRow(message['index'])
            elif kind == 'host-saved' and self.dialog is not None:
                host_api._save_trace('worker.host-saved.received')
                self.dialog.host_saved = True
                self.dialog.reject()  # Unembed before acknowledging that the host may apply/restart.
            elif kind == 'host-request-save' and self.dialog is not None:
                self.dialog._save()
            elif kind == 'host-cancel' and self.dialog is not None:
                self.dialog.reject()
            elif kind == 'focus' and self.dialog is not None:
                host_api._activate_dialog(self.dialog)
            elif kind == 'open' and self.dialog is None:
                mode = theme.normalize_mode(message['settings'].get('appearance_mode'))
                theme.apply(mode)
                dialog = RemoteDialog(message)
                self.dialog = dialog
                dialog.finished.connect(self.finished)
                send({'kind': 'window', 'hwnd': int(dialog.winId())})
                host_api._activate_dialog(dialog)

        def finished(self, accepted):
            dialog, self.dialog = self.dialog, None
            started = getattr(dialog, '_save_clicked_at', None)
            if started is not None:
                host_api._save_trace('worker.finished', started)
            send({'kind': 'result', 'accepted': accepted == SettingsDialog.Accepted,
                  'changes': dialog.changes() if accepted == SettingsDialog.Accepted else {},
                  'host_saved': dialog.host_saved})
            if started is not None:
                host_api._save_trace('worker.result.sent', started)
            dialog.deleteLater()

    with tempfile.TemporaryDirectory(prefix='ddm_settings_') as temporary:
        config.REPO = temporary
        config.CONFIG_PATH = str(Path(temporary) / 'config.json')
        theme.apply('dark')
        warm = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        warm.ensurePolished()
        warm.deleteLater()
        worker = Worker()

        def read_requests():
            for line in sys.stdin:
                message = json.loads(line)
                worker.request.emit(message)
                if message.get('kind') == 'quit':
                    return
            worker.request.emit({'kind': 'quit'})

        threading.Thread(target=read_requests, name='settings-input', daemon=True).start()
        QTimer.singleShot(0, lambda: send({'kind': 'ready', 'pid': os.getpid()}))
        result = app.exec()
    app.shutdown()
    return result
