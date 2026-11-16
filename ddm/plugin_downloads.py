"""Host-owned plugin downloads survive settings/notification presentation changes."""
from pathlib import Path
import tempfile
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from . import online, plugin_updates
from .update_errors import error_message
from .online_tasks import (_retired_online_tasks, _release_online_task,
                           _wait_online_tasks_on_exit)


class PluginDownloads(QObject):
    changed = Signal(str)
    installed = Signal(object)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.jobs = []
        self.states = {}
        self.offers = {}
        self.stopping = False

    def start(self, offer):
        plugin_id = offer['id']
        if (self.stopping or not self.manager or not offer.get('available')
                or any(task.key == plugin_id for task in self.jobs)
                or plugin_id in plugin_updates.pending_versions(self.manager)):
            return
        from .online_ui import OnlineTask
        offer = dict(offer)
        self.offers[plugin_id] = offer
        self.states[plugin_id] = dict(received=0, total=offer.get('size', 0),
                                      speed=0, percent=0, phase='downloading')

        def install(cancelled, progress):
            with tempfile.TemporaryDirectory(prefix='ddm-plugin-download-') as temporary, online.session() as client:
                archive = online.download(offer, Path(temporary) / 'plugin.zip', client, cancelled, progress)
                if cancelled():
                    raise InterruptedError('安装已取消')
                new = plugin_id not in {entry['id'] for entry in self.manager.catalog()}
                return plugin_updates.install(self.manager, archive, offer), new

        task = OnlineTask(install, None, self)
        task.key, task.percent = plugin_id, 0
        self.jobs.append(task)
        task.transferProgress.connect(self._progress)
        task.succeeded.connect(self._installed)
        task.failed.connect(self._failed)
        task.finished.connect(self._finished)
        self.changed.emit(plugin_id)
        task.start()

    def _progress(self, state):
        if self.stopping:
            return
        task = self.sender()
        task.percent = state['percent']
        self.states[task.key] = state
        self.changed.emit(task.key)

    def _installed(self, payload):
        if self.stopping:
            return
        task, result = payload
        plugin_id, new = result
        try:
            if new and self.manager.enabled is not None:
                self.manager.enabled.add(plugin_id)
                self.manager.save_plugin_settings()
        except (OSError, ValueError) as error:
            self._failed((task, error_message(error)))
            return
        self.states[plugin_id] = dict(self.states[plugin_id], phase='ready', percent=100)
        self.installed.emit(result)
        self.changed.emit(plugin_id)

    def _failed(self, payload):
        if self.stopping:
            return
        task, error = payload
        self.states[task.key] = dict(self.states[task.key], phase='failed', error=error)
        self.changed.emit(task.key)

    def _finished(self):
        if self.stopping:
            return
        task = self.sender()
        self.jobs.remove(task)
        self.changed.emit(task.key)
        task.deleteLater()

    def stop(self):
        self.stopping = True
        app = QApplication.instance()
        if not getattr(app, '_online_task_cleanup_connected', False):
            app.aboutToQuit.connect(_wait_online_tasks_on_exit)
            app._online_task_cleanup_connected = True
        jobs, self.jobs = self.jobs, []
        for task in jobs:
            task.requestInterruption()
            task.transferProgress.disconnect(self._progress)
            task.succeeded.disconnect(self._installed)
            task.failed.disconnect(self._failed)
            task.finished.disconnect(self._finished)
            task.setParent(None)
            _retired_online_tasks.add(task)
            task.finished.connect(lambda t=task: _release_online_task(t))
            if not task.isRunning():
                _release_online_task(task)
