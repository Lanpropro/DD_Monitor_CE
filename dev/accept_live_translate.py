"""Open the production host with a separate translation acceptance profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare(candidate_path):
    candidate = json.loads(Path(candidate_path).read_text(encoding='utf-8'))
    package = Path(candidate['package'])
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    if digest != candidate['sha256']:
        raise ValueError('Acceptance package checksum does not match its candidate record')
    data = ROOT / 'work/live-translate-acceptance' / digest[:12]
    data.mkdir(parents=True, exist_ok=True)
    from ddm import config
    config.DATA_ROOT = str(data)
    config.CONFIG_PATH = str(data / 'utils/config.json')
    from ddm import plugins
    plugins.DEFAULT_PLUGINS_DIR = str(data / 'plugins_user')
    target = data / 'plugins_user/live_translate'
    if not target.exists():
        manager = plugins.PluginManager(plugins_dir=plugins.DEFAULT_PLUGINS_DIR, enabled=[])
        if manager.install_zip(str(package)) != 'live_translate':
            raise ValueError('Acceptance requires the live_translate source package')
    else:
        with zipfile.ZipFile(package) as archive:
            for name in archive.namelist():
                if not name.startswith('live_translate/'):
                    raise ValueError('Acceptance requires a single live_translate package')
                if archive.read(name) != (data / 'plugins_user' / name).read_bytes():
                    raise ValueError('Acceptance copy changed; existing files were preserved')
    state = config.load() or {
        'version': 1, 'rooms': [], 'wall': [],
        'plugins': {'live_translate': {'options': candidate.get('options', {})}},
        'plugins_enabled': ['live_translate'],
        'settings': {'auto_update': False, 'close_behavior': 'exit', 'preview_on_hover': False},
    }
    return data, state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path,
                        default=ROOT / 'work/live-translate-acceptance/candidate.json')
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    # Settings subprocesses resolve normal user data; acceptance stays in one process.
    os.environ.pop('DDM_SETTINGS_PROCESS', None)
    if args.smoke:
        os.environ.update(DDM_NO_SAVE='1', QT_QPA_PLATFORM='offscreen')
    platform._wmi_query = lambda *unused: (_ for _ in ()).throw(OSError('Acceptance'))
    data, state = prepare(args.candidate)
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication
    from ddm import config, theme
    from ddm.app import MainWindow, setup_file_log
    app = QApplication([])
    app.setApplicationName('实时翻译人工验收')
    app.setStyleSheet(theme.qss())
    setup_file_log()
    sidebar, wall = config.build_rooms(state)
    window = MainWindow(sidebar, wall, layout_id='1x1', state=state)
    window.setWindowTitle('DD监控室CE · 实时翻译验收（独立数据）')
    window._startup_update_timer.stop()
    window.resize(1200, 800)
    window.show()
    plugin = next(plugin for plugin in window.plugins.plugins if plugin.context.name == 'live_translate')
    plugin.open()
    if args.smoke:
        window._poll_timer.stop()
        window._stats_timer.stop()
        app.processEvents()
        loaded = {item.context.name for item in window.plugins.plugins}
        assert loaded == set(state['plugins_enabled']) and not window.plugins.skipped
        assert plugin.context.name == 'live_translate'
        assert plugin.panel.isVisible()
        assert plugin.session.worker is None and plugin.session.audio is None
        assert str(data) in config.CONFIG_PATH
        window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        app.shutdown()
        print('PASS: root host loaded the candidate with isolated data; no inference or download started')
        return 0
    app.setQuitOnLastWindowClosed(False)
    QTimer.singleShot(0, lambda: print('Acceptance data: ' + str(data), flush=True))
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
