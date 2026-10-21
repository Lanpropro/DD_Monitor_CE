"""Isolated original-resolution video A/B probe; never loads user state."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QUrl, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from ddm import config, skins
from ddm.recording import ffmpeg_path


def wait_for(predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate(), 'Video operation timed out'


def percentile(values, fraction):
    return sorted(values)[min(len(values) - 1, int((len(values) - 1) * fraction))]


class RasterProbe(skins.BackgroundLayer):
    def __init__(self, root, window=None):
        super().__init__(root, window or root)
        self.paint_ms = []

    def paintEvent(self, event):
        started = time.perf_counter()
        super().paintEvent(event)
        self.paint_ms.append((time.perf_counter() - started) * 1000)


QML = b'''
import QtQuick
import QtMultimedia
Rectangle {
    property alias videoSink: output.videoSink
    property real maskOpacity: 0.35
    color: "#202225"
    VideoOutput {
        id: output
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }
    Rectangle {
        anchors.fill: parent
        color: "#202225"
        opacity: parent.maskOpacity
    }
}
'''


def run_probe(args):
    app = QApplication([])
    assert os.environ.get('QT_QPA_PLATFORM') != 'offscreen', 'Use the Windows platform for GPU measurements'
    with tempfile.TemporaryDirectory(prefix='ddm-video-probe-') as directory, ExitStack() as stack:
        source = Path(directory) / 'original-4k.mp4'
        subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=size=3840x2160:rate=30', '-t', '2',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '20',
            '-pix_fmt', 'yuv420p', str(source)], check=True)
        if args.wall:
            from ddm.app import MainWindow
            from ddm.player import TilePlayer
            from selfcheck_tile_fullscreen import SilentPoller
            stack.enter_context(patch.object(config, 'REPO', directory))
            stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'state.json')))
            stack.enter_context(patch('ddm.app.StatusPoller', SilentPoller))
            stack.enter_context(patch('ddm.app.StatsPoller', SilentPoller))
            for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                           'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                           'load_cached_covers', 'load_cached_avatars'):
                stack.enter_context(patch.object(MainWindow, method))
            window = MainWindow([], [], layout_id='corner',
                state={'plugins_enabled': [], 'settings': {'auto_update': False}})
            root = window.centralWidget()
            managed = skins.import_asset(source)
            window.set_skin({'skin_background': managed, 'skin_mask': 35})
            window.skin_controller.layer.load('')
            source = Path(directory) / managed
            live_source = Path(directory) / 'synthetic-live.mp4'
            subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'color=c=blue:size=640x360:rate=30', '-t', '30',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                str(live_source)], check=True)
            live_players = []
            for tile in window.wall.tiles[:2]:
                live = TilePlayer(tile.video, window, silent=True)
                window.players[tile] = live
                live.play(str(live_source))
                tile.set_video_active(True)
                live_players.append((tile, live, int(tile.video.winId())))
        else:
            window = root = QWidget()
            live_players = []
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.setWindowTitle('DDM isolated background probe - ' + args.backend)
        window.resize(args.width, args.height)
        conversions = []
        original_run = skins._FrameImage.run

        def measured_run(job):
            started = time.perf_counter()
            original_run(job)
            conversions.append((time.perf_counter() - started) * 1000)

        with patch.object(skins._FrameImage, 'run', measured_run):
            if args.backend == 'raster':
                layer = RasterProbe(root, window)
                player = None
                view = None
            else:
                # Import only in the Quick child process: constructing QQuickWidget
                # changes the process-wide render loop and would contaminate A/B.
                from PySide6.QtQml import QQmlComponent
                from PySide6.QtQuickWidgets import QQuickWidget
                view = QQuickWidget(root)
                view.setResizeMode(QQuickWidget.SizeRootObjectToView)
                component = QQmlComponent(view.engine())
                component.setData(QML, QUrl('qrc:/SkinVideoProbe.qml'))
                assert not component.isError(), component.errorString()
                item = component.create()
                assert item is not None, component.errorString()
                view.setContent(QUrl('qrc:/SkinVideoProbe.qml'), component, item)
                view.setGeometry(root.rect())
                view.setAttribute(Qt.WA_TransparentForMouseEvents)
                player = QMediaPlayer(root)
                player.setAudioOutput(None)
                player.setLoops(QMediaPlayer.Infinite)
                sink = item.property('videoSink')
                player.setVideoSink(sink)
                player.setSource(QUrl.fromLocalFile(str(source)))
                layer = None
            # Raster widgets above the background approximate the application's
            # translucent panels, without loading accounts, plugins or live rooms.
            if not args.wall:
                panel = QLabel('Synthetic translucent sidebar', root)
                panel.setGeometry(0, 0, 240, args.height)
                panel.setStyleSheet('background: rgba(32,34,37,160); color: white;')
            window.show()
            app.processEvents()
            if view is not None:
                view.setGeometry(root.rect())
            if layer is not None:
                layer.load(str(source))
                player, sink = layer.player, layer.sink
                wait_for(lambda: layer.image is not None)
            else:
                view.lower()
                player.play()
            frames = []
            sink.videoFrameChanged.connect(lambda frame: frames.append(frame.startTime()) if frame.isValid() else None)
            try:
                wait_for(lambda: sink.videoFrame().isValid())
                for tile, live, hwnd in live_players:
                    wait_for(lambda: live._prop('time-pos', 0) > 0)
                assert sink.videoFrame().size().width() == 3840
                assert sink.videoFrame().size().height() == 2160
                assert Path(player.source().toLocalFile()) == source
                assert player.audioOutput() is None
                QTest.qWait(700)
                if view is not None:
                    assert view.status() == QQuickWidget.Ready, view.errors()
                    api = str(view.quickWindow().rendererInterface().graphicsApi())
                    assert 'Software' not in api and 'Unknown' not in api, api
                    snapshot = view.grabFramebuffer()
                    assert not snapshot.isNull()
                    item.setProperty('maskOpacity', 1.0)
                    QTest.qWait(80)
                    masked_image = view.grabFramebuffer()
                    masked = masked_image.pixelColor(masked_image.width() // 2, masked_image.height() // 2)
                    assert max(abs(masked.red() - 32), abs(masked.green() - 34), abs(masked.blue() - 37)) <= 2, masked
                    item.setProperty('maskOpacity', 0.35)
                else:
                    api = 'QImage/QPainter'
                # Exclude startup, shader compilation, assertions and readbacks.
                QTest.qWait(300)
                conversions.clear()
                frames.clear()
                if layer is not None:
                    layer.paint_ms.clear()
                gaps = []
                started = previous = time.perf_counter()
                cpu_started = time.process_time()
                while time.perf_counter() - started < args.seconds:
                    QTest.qWait(10)
                    now = time.perf_counter()
                    gaps.append((now - previous) * 1000)
                    previous = now
                elapsed = time.perf_counter() - started
                cpu = time.process_time() - cpu_started
                assert len(set(frames)) > 5, 'Video must animate and loop'
                if view is not None:
                    assert not conversions, 'Quick prototype must not use the Python toImage pipeline'
                else:
                    assert conversions and layer.paint_ms
                result = dict(backend=args.backend, graphics_api=api,
                    real_wall=args.wall, synthetic_live_streams=len(live_players),
                    source_size=[3840, 2160], viewport=[root.width(), root.height()],
                    device_pixel_ratio=root.devicePixelRatioF(), seconds=round(elapsed, 3),
                    cpu_core_percent=round(cpu / elapsed * 100, 2),
                    event_gap_p95_ms=round(percentile(gaps, .95), 3),
                    event_gap_max_ms=round(max(gaps), 3), frames=len(frames),
                    python_conversions=len(conversions),
                    conversion_p95_ms=round(percentile(conversions, .95), 3) if conversions else None,
                    paint_p95_ms=round(percentile(layer.paint_ms, .95), 3) if layer else None)
                player.pause()
                position = player.position()
                QTest.qWait(150)
                assert abs(player.position() - position) < 100, 'Pause must stop playback'
                player.play()
                wait_for(lambda: player.isPlaying())
                for tile, live, hwnd in live_players:
                    assert int(tile.video.winId()) == hwnd, 'Video HWND must remain unchanged'
                    assert live._prop('time-pos', 0) > elapsed and not live._prop('pause', False)
                print(json.dumps(result, sort_keys=True), flush=True)
            finally:
                if layer is not None:
                    layer.load('')
                    layer._frame_pool.waitForDone()
                else:
                    player.stop()
                    player.setSource(QUrl())
                    player.setVideoSink(None)
                window.close()
                window.deleteLater()
                app.processEvents()
    print('PASS: original 4K source, animation, mute, mask (Quick), pause/resume and cleanup')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('raster', 'quick'), required=True)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--wall', action='store_true', help='Use the real wall with two synthetic libmpv streams')
    options = parser.parse_args()
    assert 1 <= options.seconds <= 60
    assert 320 <= options.width <= 7680 and 180 <= options.height <= 4320
    run_probe(options)
