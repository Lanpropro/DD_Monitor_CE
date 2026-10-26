"""双路合成媒体设置隔离对照；需本机 match_sync 源码、libmpv、FFmpeg 和音频设备。"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import types
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-root', type=Path, required=True)
    parser.add_argument('--mpv-dir', type=Path, required=True)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, nargs=2, required=True)
    parser.add_argument('--seconds', type=int, default=45)
    parser.add_argument('--warmup', type=int, default=65)
    parser.add_argument('--settings-action', choices=('cancel', 'save', 'busy'), default='cancel')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.environ.update(DDM_NO_SAVE='1', DDM_SETTINGS_PROCESS='1', PYTHONUTF8='1')
    os.environ['PATH'] = str(args.mpv_dir) + os.pathsep + os.environ['PATH']
    dll = os.add_dll_directory(str(args.mpv_dir))
    import plugins_user
    package = types.ModuleType('plugins_user._settings_benchmark')
    package.__path__ = [str(args.plugin_root / 'plugins/match_sync')]
    sys.modules[package.__name__] = package
    plugins_user._settings_benchmark = package
    from plugins_user._settings_benchmark import viewer as module
    from PySide6.QtCore import QEventLoop, QProcess, QTimer, Qt, qVersion
    os.environ['DDM_SETTINGS_TEST_QT'] = qVersion()
    from PySide6.QtWidgets import QApplication
    from ddm import app as host, config, plugins, recording, settings_process
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report = {'qt': qVersion(), 'plugin': str(args.plugin_root), 'output_volume': 0, 'phases': {}}
    phase = ['warmup']
    data = {}
    previous = {}
    canvases = {}
    clicks = []
    original_frame = module.Canvas.set_frame
    original_clock = module.AudioPump.clock
    original_fill = module.AudioPump._fill

    def record(key, value):
        data.setdefault(phase[0], {}).setdefault(key, []).append(value)

    def frame(canvas, item):
        before = canvas.presented
        result = original_frame(canvas, item)
        name = canvases.get(canvas)
        if name and canvas.presented != before:
            now = time.perf_counter()
            if name in previous:
                record(name + '_gap_ms', (now - previous[name]) * 1000)
            previous[name] = now
        return result

    def clock(pump):
        result = original_clock(pump)
        if pump.last_fill is not None:
            record('clock_age_ms', (time.perf_counter() - pump.last_fill) * 1000)
        return result

    def fill(pump):
        if pump.sink is not None and pump.written:
            record('audio_idle', int(pump.sink.state().name == 'IdleState'))
        return original_fill(pump)

    def forbidden(*_a, **_kw):
        raise AssertionError('External network forbidden')

    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        for name in ('connect', 'connect_ex'):
            stack.enter_context(patch.object(socket.socket, name, forbidden))
        stack.enter_context(patch.object(socket, 'getaddrinfo', forbidden))
        stack.enter_context(patch.object(config, 'REPO', temporary))
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')))
        stack.enter_context(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(Path(temporary) / 'plugins')))
        stack.enter_context(patch.object(recording, 'ffmpeg_path', return_value=str(args.ffmpeg)))
        for name in ('start_all', 'refresh_account', 'refresh_status', 'refresh_stats',
                     'load_cached_covers', 'load_cached_avatars', 'load_room_avatars'):
            stack.enter_context(patch.object(host.MainWindow, name))
        with patch.object(host.QTimer, 'singleShot'):
            window = host.MainWindow([], [], layout_id='1x1', state={'plugins_enabled': []})
        command = (sys.executable, [str(root / 'dev/selfcheck_settings_process.py'), '--worker-check', args.settings_action])
        stack.enter_context(patch.object(settings_process, 'worker_command', return_value=command))
        stack.enter_context(patch.object(module.Canvas, 'set_frame', frame))
        stack.enter_context(patch.object(module.AudioPump, 'clock', clock))
        stack.enter_context(patch.object(module.AudioPump, '_fill', fill))
        viewer = module.Viewer(plugins.PluginContext(window.plugins, 'settings-benchmark'), {})
        canvases[viewer.canvas] = 'main'
        loop = QEventLoop()
        duration = QTimer()
        duration.setSingleShot(True)
        duration.setTimerType(Qt.PreciseTimer)
        duration.timeout.connect(loop.quit)
        timer = QTimer()
        timer.setInterval(1500)

        def click():
            clicks.append(time.perf_counter())
            window.sidebar.settings_button.click()

        timer.timeout.connect(click)
        client = window._get_settings_process()
        opened = []
        def received(message):
            if message['kind'] == 'painted':
                opened.append(time.perf_counter())
                record('settings_first_paint_ms', (opened[-1] - clicks[-1]) * 1000)
        client.received.connect(received)
        try:
            client.warm()
            window.show()
            viewer.embed(window.wall.parentWidget())
            viewer.show()
            for key, source in zip(('1', '2'), args.fixtures):
                viewer.sources[key] = {'url': str(source)}
                viewer.add_room(key, {'alias': key})
                viewer.rows[key].volume.setValue(0)  # Keep synthetic background checks inaudible.
                viewer.rows[key].show_chat.setChecked(False)
            viewer.prefer_highest = False
            viewer.toggle_running()
            viewer.compare.setChecked(True)
            viewer.show_comparison('2')
            # Comparison canvas is created by show_comparison.
            canvases[viewer.comparison_panel.cards['2'][2]] = 'secondary'
            duration.start(args.warmup * 1000)
            loop.exec()
            assert client.ready and viewer.audio.device is not None
            assert all(row.decoder.history.received_frames > 100 for row in viewer.rows.values())
            for name in ('baseline', 'remote_settings'):
                phase[0] = name
                previous.clear()
                if name == 'remote_settings':
                    timer.start()
                start = time.perf_counter()
                duration.start(args.seconds * 1000)
                loop.exec()
                timer.stop()
                result = {}
                for key, values in data[name].items():
                    ordered = sorted(values)
                    result[key] = {'count': len(values), 'p95': ordered[int(.95 * len(values))], 'max': max(values)}
                result['elapsed_seconds'] = time.perf_counter() - start
                report['phases'][name] = result
                print(json.dumps({name: result}), flush=True)
            report.update(clicks=len(clicks), painted=len(opened))
            assert len(opened) >= args.seconds // 2
            remote = report['phases']['remote_settings']
            assert remote['main_gap_ms']['max'] < 100, remote
            assert remote['secondary_gap_ms']['max'] < 100, remote
            assert remote['clock_age_ms']['max'] < 100 and remote['audio_idle']['max'] == 0
        finally:
            timer.stop()
            decoders = [row.decoder for row in viewer.rows.values()]
            viewer.close()
            for decoder in decoders:
                decoder.stop()
                decoder.thread.join(4)
            window.close()
            deadline = time.perf_counter() + 3
            while client.process.state() != QProcess.NotRunning and time.perf_counter() < deadline:
                app.processEvents()
                time.sleep(.005)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    app.shutdown()
    dll.close()
    print('PASS: synthetic two-stream playback; live user acceptance remains pending')


if __name__ == '__main__':
    main()
