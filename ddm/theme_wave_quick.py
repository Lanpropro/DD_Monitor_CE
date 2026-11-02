"""Render-thread circular reveal of an immutable UI snapshot."""
from pathlib import Path
import os

os.environ.setdefault('QSG_USE_SIMPLE_ANIMATION_DRIVER', '1')

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QPixmap, QSurfaceFormat
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickImageProvider, QQuickWindow

from . import motion
from .theme_transition import WaveOverlay


_QML = b'''import QtQuick
Item {
    id: root
    property url shaderSource
    property point origin
    property real radius
    property int milliseconds
    property var curve: []
    property url snapshotSource
    function hold() {
        reveal.stop();
        // UniformAnimator changes the GPU value without changing the GUI property.
        // Force a uniform update even when the GUI property is already zero.
        effect.progress = -1.0;
        effect.progress = 0.0;
    }
    function start() { reveal.restart(); }
    Image {
        id: bitmap
        source: root.snapshotSource
        anchors.fill: parent
        visible: false
        cache: false
        asynchronous: false
    }
    ShaderEffect {
        id: effect
        anchors.fill: parent
        property variant source: bitmap
        property real progress: 0.0
        property point viewportSize: Qt.point(width, height)
        property point waveOrigin: root.origin
        property real maxRadius: root.radius
        fragmentShader: root.shaderSource
        UniformAnimator {
            id: reveal
            target: effect
            uniform: "progress"
            from: 0
            to: 1
            duration: root.milliseconds
            easing.type: Easing.BezierSpline
            easing.bezierCurve: root.curve
        }
    }
}'''


class _SnapshotImage(QQuickImageProvider):
    def __init__(self, image):
        super().__init__(QQuickImageProvider.Image)
        self.image = image

    def requestImage(self, identifier, size, requested_size):
        return self.image


class QuickWaveOverlay(WaveOverlay):
    """Keep WaveOverlay's snapshot/interruption API; animate only on the GPU."""
    render_thread = True
    ready = Signal()

    def __init__(self, window, snapshot, origin):
        super().__init__(window, snapshot, origin)
        self._native_clip = False
        self.engine = QQmlEngine(self)
        self.images = _SnapshotImage(snapshot.toImage())
        self.engine.addImageProvider('theme', self.images)
        self.component = QQmlComponent(self.engine)
        self.component.setData(_QML, QUrl('ThemeWave.qml'))
        self.stage = self.component.create()
        if self.stage is None:
            raise RuntimeError(self.component.errorString())
        self.view = QQuickWindow()
        self.view.setTransientParent(window.windowHandle())
        surface = QSurfaceFormat()
        surface.setAlphaBufferSize(8)
        self.view.setFormat(surface)
        self.view.setFlags(Qt.Tool | Qt.FramelessWindowHint |
                           Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.view.setColor(Qt.transparent)
        self.stage.setProperty('shaderSource', QUrl.fromLocalFile(str(
            Path(__file__).parent / 'assets/shaders/theme_wave.frag.qsb')))
        self.stage.setProperty('milliseconds', motion.THEME_WAVE_MS)
        self.stage.setProperty('curve', [coordinate for point in motion.THEME_WAVE_EASING.toCubicSpline()
                                         for coordinate in (point.x(), point.y())])
        self.stage.setParentItem(self.view.contentItem())
        self.destroyed.connect(self.view.deleteLater)
        self._revision = 0
        self._ready_connections = []
        self.prepare(snapshot, origin)

    def _disconnect_ready(self):
        for connection in self._ready_connections:
            QObject.disconnect(connection)
        self._ready_connections.clear()

    def prepare(self, snapshot, origin):
        self._disconnect_ready()
        self._revision += 1
        revision = self._revision
        self.ready_to_reveal = False
        self._synced = False
        self.snapshot = snapshot
        window = self.parentWidget()
        top = round(snapshot.height()/snapshot.devicePixelRatio()-window.height())
        self.caption_height = top
        self.origin = window.mapFromGlobal(origin) + QPoint(0, top)
        self.stage.hold()
        self.images.image = snapshot.toImage()
        self.stage.setProperty('snapshotSource', QUrl(f'image://theme/snapshot-{revision}'))
        self.stage.setProperty('origin', self.origin)
        self.stage.setProperty('radius', max(((x-self.origin.x())**2 + (y-self.origin.y())**2)**.5
            for x in (0, window.width()) for y in (0, window.height()+top)))
        self.stage.setWidth(window.width())
        self.stage.setHeight(window.height()+top)
        self.view.setScreen(window.windowHandle().screen())
        self.view.setGeometry(QRect(window.mapToGlobal(QPoint(0, -top)),
                                   QSize(window.width(), window.height()+top)))
        self._ready_connections = [
            self.view.afterSynchronizing.connect(lambda: self._after_sync(revision), Qt.QueuedConnection),
            self.view.frameSwapped.connect(lambda: self._after_frame(revision), Qt.QueuedConnection)]

    def _after_sync(self, revision):
        if revision == self._revision:
            self._synced = True

    def _after_frame(self, revision):
        if revision == self._revision and self._synced and not self.ready_to_reveal:
            self.ready_to_reveal = True
            self._disconnect_ready()
            self.ready.emit()

    def show(self):
        self.view.show()

    def start_reveal(self):
        self.stage.start()

    def raise_(self):
        self.view.raise_()

    def reveal(self, progress):
        self.progress = progress  # GUI clock is only for completion/diagnostics.

    def grab(self):
        return QPixmap.fromImage(self.view.grabWindow())

    def hide(self):
        self._revision += 1
        self._disconnect_ready()
        self.stage.hold()
        self.view.hide()
