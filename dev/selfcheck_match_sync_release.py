"""Reproduce old disk plugin failure and verify replacement in the actual frozen EXE.

Only packaged runtime files are copied. No real configuration, account, stream,
or other installed plugins enter the sandbox. The original release is read-only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DDM_NO_SAVE', '1')
from dev.selfcheck_match_sync_media import generate

PROBE = '''
import json, os, time, traceback
from array import array
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from ddm.plugins import Plugin

class Probe(Plugin):
    def on_load(self, context):
        Path(os.environ['MATCH_RELEASE_RESULT']).with_suffix('.phase').write_text('probe on_load', encoding='utf-8')
        self.context = context
        self.worker = None
        self.viewer = None
        self.checks = {}
        self.deadline = time.monotonic() + 20
        context.window.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.timer = QTimer(context.window)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        QTimer.singleShot(0, self.start)

    def start(self):
        Path(os.environ['MATCH_RELEASE_RESULT']).with_suffix('.phase').write_text('probe start', encoding='utf-8')
        try:
            catalog = next(item for item in self.context.manager.catalog() if item['id'] == 'match_sync')
            self.checks['catalog'] = catalog
            if catalog['status'] != '已加载':
                self.finish()
                return
            from ddm import audio_output
            from ddm_plugin_match_sync import engine, media, viewer as module
            self.checks['frozen'] = bool(getattr(__import__('sys'), 'frozen', False))
            self.checks['host_has_old_function'] = hasattr(audio_output, 'route_pcm_s16_stereo')
            assert module.route_pcm_s16_stereo is engine.route_pcm_s16_stereo
            pcm = array('h', [1000, -500, 400, 200]).tobytes()
            for implementation in (engine.audioop, None):
                previous, engine.audioop = engine.audioop, implementation
                try:
                    assert list(array('h', engine.route_pcm_s16_stereo(pcm, 3))) == [250, 0, 300, 0]
                    assert list(array('h', engine.route_pcm_s16_stereo(pcm, 4))) == [0, 250, 0, 300]
                finally:
                    engine.audioop = previous
            self.checks['routing'] = True
            assert media.av is not None and media.np is not None
            module.AudioPump.start = lambda _self: None
            plugin = next(item for item in self.context.manager.plugins if item.context.name == 'match_sync')
            assert plugin.button is not None
            plugin.button.setChecked(True)
            self.viewer = plugin.viewer
            self.checks['viewer'] = bool(self.viewer.embedded)
            self.worker = module.Decoder('1', {'url': os.environ['MATCH_RELEASE_MEDIA']})
            self.worker.start()
            self.timer.start()
        except Exception:
            self.finish(traceback.format_exc())

    def poll(self):
        try:
            if time.monotonic() > self.deadline:
                raise AssertionError('Local video/PCM decoding timed out')
            bounds = self.worker.history.bounds()
            if bounds and bounds[1] - bounds[0] > 1 and self.worker.history.audio.end > 48000:
                self.viewer.canvas.show_at(self.worker, bounds[1] - .3)
                if self.viewer.canvas.frame_key is not None:
                    self.checks['local_video_pcm'] = True
                    self.finish()
        except Exception:
            self.finish(traceback.format_exc())

    def finish(self, error=None):
        self.timer.stop()
        if error:
            self.checks['error'] = error
        if self.worker is not None:
            self.worker.stop()
        if self.viewer is not None:
            self.viewer.close()
        Path(os.environ['MATCH_RELEASE_RESULT']).write_text(json.dumps(self.checks, ensure_ascii=False), encoding='utf-8')
        QTimer.singleShot(0, lambda: QApplication.instance().exit(0))

plugin = Probe()
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True, type=Path)
    parser.add_argument('--plugin-zip', required=True, type=Path)
    parser.add_argument('--legacy-zip', type=Path, help='Optional old plugin ZIP for a repeatable failure comparison')
    parser.add_argument('--output', type=Path, default=ROOT / 'results/match-sync-release-compat.json')
    args = parser.parse_args()
    release, archive = args.release.resolve(), args.plugin_zip.resolve()
    executable = release / 'DD监控室CE.exe'
    assert executable.is_file() and (release / 'ffmpeg.exe').is_file()
    files = ('plugin.json', 'plugin.py', 'engine.py', 'media.py', 'video.py', 'viewer.py', 'README.md')
    with zipfile.ZipFile(archive) as package:
        assert set(package.namelist()) == {'match_sync/' + name for name in files}
        replacement = {name: package.read('match_sync/' + name) for name in files}
    report = {'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
              'plugin_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'runs': {}}
    with tempfile.TemporaryDirectory(prefix='ddm_match_release_') as temporary:
        sandbox = Path(temporary)
        app_dir = sandbox / 'app'
        app_dir.mkdir()
        shutil.copytree(release / '_internal', app_dir / '_internal')
        for name in (executable.name, 'ffmpeg.exe'):
            shutil.copy2(release / name, app_dir / name)
        fixture = sandbox / 'fixture.mkv'
        generate(str(app_dir / 'ffmpeg.exe'), fixture)
        plugins = app_dir / 'plugins_user'
        target = plugins / 'match_sync'
        target.mkdir(parents=True)
        probe = plugins / 'zz_match_release_probe'
        probe.mkdir()
        (probe / 'plugin.py').write_text(PROBE, encoding='utf-8')
        (probe / 'plugin.json').write_text(json.dumps({'id': probe.name, 'name': 'Isolated release probe',
                                                     'description': 'Synthetic local compatibility check',
                                                     'version': '1.0'}), encoding='utf-8')
        config = app_dir / 'utils/config.json'
        config.parent.mkdir()
        config.write_text(json.dumps({'version': 2, 'rooms': [], 'wall': [], 'user_notice_accepted': True,
                                      'plugins_enabled': ['match_sync', probe.name],
                                      'settings': {'auto_update': False, 'recording_enabled': False}}), encoding='utf-8')
        versions = [('replacement', replacement)]
        legacy = release / 'plugins_user/match_sync'
        if args.legacy_zip:
            with zipfile.ZipFile(args.legacy_zip) as package:
                versions.insert(0, ('legacy', {name: package.read('match_sync/' + name) for name in files}))
        elif (legacy / 'viewer.py').is_file() and b'from ddm.audio_output import route_pcm_s16_stereo' in (legacy / 'viewer.py').read_bytes():
            versions.insert(0, ('legacy', {name: (legacy / name).read_bytes() for name in files}))
        for name, content in versions:
            for filename, data in content.items():
                (target / filename).write_bytes(data)
            cache = target / '__pycache__'
            assert cache.resolve().is_relative_to(sandbox.resolve())
            shutil.rmtree(cache, ignore_errors=True)
            result = sandbox / (name + '.json')
            environment = dict(os.environ, DDM_NO_SAVE='1', QT_QPA_PLATFORM='offscreen',
                               MATCH_RELEASE_MEDIA=str(fixture), MATCH_RELEASE_RESULT=str(result))
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.Popen([str(app_dir / executable.name)], cwd=app_dir, env=environment,
                                       startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                process.wait(timeout=35)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                logs = '\n'.join(path.read_text(encoding='utf-8', errors='replace')[-6000:]
                                 for path in (app_dir / 'logs').glob('*.log'))
                phase = result.with_suffix('.phase')
                raise AssertionError(f'Frozen {name} test timed out; phase={phase.read_text() if phase.exists() else "none"}\n{logs}')
            assert result.is_file(), f'Frozen EXE produced no {name} result (exit {process.returncode})'
            checks = json.loads(result.read_text(encoding='utf-8'))
            report['runs'][name] = checks
            if name == 'legacy':
                assert 'route_pcm_s16_stereo' in checks['catalog']['reason']
                assert checks['catalog']['status'] == '加载失败'
            else:
                assert process.returncode == 0 and 'error' not in checks, checks
                assert checks['catalog']['status'] == '已加载'
                assert all(checks.get(key) for key in ('frozen', 'routing', 'viewer', 'local_video_pcm')), checks
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: actual frozen EXE compatibility, disk plugin load, local routing, viewer and local video/PCM')
    print(f'Report: {args.output}')


if __name__ == '__main__':
    main()
