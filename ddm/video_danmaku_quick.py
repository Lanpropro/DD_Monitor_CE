"""Experimental shared Qt Quick texture layer for native video danmaku."""
import os
import threading

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, QUrl, Qt
from PySide6.QtGui import QImage, QRegion, QSurfaceFormat
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickImageProvider, QQuickWindow
from PySide6.QtWidgets import QApplication, QWidget


def _owned_by(widget, owner):
    while widget is not None:
        if widget is owner:
            return True
        widget = widget.parentWidget()
    return False


class _CommentImages(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        self.images = {}
        self._lock = threading.Lock()

    def requestImage(self, identifier, size, requested_size):
        with self._lock:
            image = self.images.get(identifier, QImage())
        if not image.isNull() and requested_size.isValid():
            image = image.scaled(requested_size, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)
        return image

    def set_image(self, identifier, image):
        with self._lock:
            self.images[identifier] = image

    def remove_image(self, identifier):
        with self._lock:
            self.images.pop(identifier, None)


_STAGE_QML = b'''import QtQuick
Item {
    id: stage
    property bool active: false
    Item {
        width: 1
        height: 1
        opacity: 0
        NumberAnimation on x {
            from: 0
            to: 1
            duration: 1000
            loops: Animation.Infinite
            running: stage.active
        }
    }
}'''


_GROUP_QML = b'''import QtQuick
import QtQuick.Effects
Item {
    id: root
    property bool rounded: true
    property alias content: contents
    property url maskImage
    property bool maskLoaded: bitmapMask.status === Image.Ready

    Item {
        id: contents
        anchors.fill: parent
        clip: true
        visible: false
    }
    MultiEffect {
        anchors.fill: parent
        visible: true
        source: contents
        maskEnabled: true
        maskSource: root.maskImage.toString().length > 0 ? bitmapMask : shapeMask
        Image {
            id: bitmapMask
            width: root.width
            height: root.height
            source: root.maskImage
            visible: false
            asynchronous: false
            cache: false
            smooth: false
        }
        Item {
            id: shapeMask
            width: root.width
            height: root.height
            layer.enabled: true
            visible: false
            Rectangle {
                anchors.fill: parent
                radius: root.rounded ? 9 : 0
                antialiasing: true
                color: "white"
            }
            Rectangle {
                visible: root.rounded
                x: 0
                y: Math.max(0, parent.height - 9)
                width: parent.width
                height: Math.min(9, parent.height)
                color: "white"
            }
        }
    }
}'''


_COMMENT_QML = b'''import QtQuick
Item {
    id: sprite
    property url imageSource
    property bool imageLoaded: picture.status === Image.Ready
    property bool motionPaused: !travel.running || travel.paused
    XAnimator {
        id: travel
        target: sprite
        easing.type: Easing.Linear
    }
    function setMotion(startX, endX, milliseconds, paused) {
        travel.stop();
        sprite.x = startX;
        travel.from = startX;
        travel.to = endX;
        travel.duration = Math.max(1, Math.round(milliseconds));
        if (!paused) travel.start();
    }
    function setMotionPaused(paused) {
        if (paused) {
            if (travel.running) travel.pause();
        } else if (travel.running) travel.resume();
        else travel.start();
    }
    Image {
        id: picture
        anchors.fill: parent
        source: sprite.imageSource
        asynchronous: false
        cache: false
        smooth: true
    }
}'''


class QuickDanmakuLayer(QObject):
    """One transparent, refresh-synchronized window shared by a playback wall."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self._surface_reset = QTimer(self)
        self._surface_reset.setSingleShot(True)
        self._surface_reset.timeout.connect(self._restore_surface)
        self._surface_dirty = False
        self.render_thread_animation = os.environ.get("DDM_QTQUICK_ANIMATOR", "1") != "0"
        self.images = _CommentImages()
        self.engine = QQmlEngine(parent)
        self.engine.addImageProvider("danmaku", self.images)
        self.stage_component = self._component(_STAGE_QML, "VideoDanmakuStage.qml")
        self.group_component = self._component(_GROUP_QML, "VideoDanmakuGroup.qml")
        self.comment_component = self._component(_COMMENT_QML, "VideoDanmaku.qml")

        # An owned top-level swap chain avoids opaque child-window composition
        # after Windows moves the playback wall between monitors.
        self.window = QQuickWindow()
        self.window.setTransientParent(parent.window().windowHandle())
        parent.destroyed.connect(self.window.deleteLater)
        self._empty_hide = QTimer(self)
        self._empty_hide.setSingleShot(True)
        self._empty_hide.timeout.connect(self.window.hide)
        surface_format = QSurfaceFormat()
        surface_format.setAlphaBufferSize(8)
        self.window.setFormat(surface_format)
        self.window.setFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                             Qt.WindowType.WindowTransparentForInput |
                             Qt.WindowType.WindowDoesNotAcceptFocus)
        self.window.setColor(Qt.GlobalColor.transparent)
        self.window.setGeometry(parent.mapToGlobal(QPoint()).x(), parent.mapToGlobal(QPoint()).y(),
                                parent.width(), parent.height())
        self.stage = self.stage_component.create()
        if self.stage is None:
            raise RuntimeError(self.stage_component.errorString())
        self.stage.setWidth(parent.width())
        self.stage.setHeight(parent.height())
        self.stage.setParentItem(self.window.contentItem())
        self.groups = {}
        self.items = {}
        self._group_sequence = 0
        self._item_sequence = 0
        self._mask_sequence = 0
        self.group_masks = {}
        self._active_groups = set()
        self._set_layered()
        self._occlusion_timer = QTimer(self)
        self._occlusion_timer.setSingleShot(True)
        self._occlusion_timer.timeout.connect(self.show)
        QApplication.instance().installEventFilter(self)
        parent.window().windowHandle().screenChanged.connect(self.reset_surface)

    def _component(self, source, name):
        component = QQmlComponent(self.engine)
        component.setData(source, QUrl(f"qrc:/{name}"))
        if component.isError():
            raise RuntimeError(component.errorString())
        return component

    def _set_layered(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        user32.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
        hwnd = int(self.window.winId())
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x00000002)

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is not self.parent and watched is not self.parent.window():
            if (isinstance(watched, QWidget) and watched.isWindow()
                    and _owned_by(watched, self.parent.window())
                    and kind in (QEvent.Show, QEvent.Hide, QEvent.Move, QEvent.Resize, QEvent.Close)):
                self._occlusion_timer.start(0)
            return False
        if kind in (QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange):
            self.reset_surface()
        elif kind == QEvent.WindowStateChange:
            changed = event.oldState() ^ watched.windowState()
            if changed & (Qt.WindowMaximized | Qt.WindowFullScreen | Qt.WindowMinimized):
                self.reset_surface()
        elif kind in (QEvent.Hide, QEvent.Close):
            self.window.hide()
        elif kind in (QEvent.Move, QEvent.Resize):
            self.resize()
            self._occlusion_timer.start(0)
        elif kind == QEvent.Show:
            self.show()
        return False

    def reset_surface(self, _screen=None):
        # Hide the old swap chain until screen/DPI/fullscreen changes settle.
        self._surface_dirty = True
        self.window.hide()
        self._surface_reset.start(100)

    def _restore_surface(self):
        if not self.parent.isVisible() or self.parent.window().isMinimized():
            return
        # Recreate only the overlay surface; retain QML items, motion and video HWNDs.
        self.window.hide()
        self.window.destroy()
        self.resize()
        self._set_layered()
        self._surface_dirty = False
        self.show()

    def show(self):
        self._empty_hide.stop()
        self.resize()
        has_items = any(self.groups[record["group"]].isVisible()
                        for record in self.items.values())
        if (not has_items or not self.parent.isVisible()
                or self.parent.window().isMinimized()):
            self.window.hide()
            return
        if self._surface_dirty:
            self._surface_reset.start(100)
            return
        if not self._update_occlusion():
            self.window.hide()
            return
        if not self.window.isVisible():
            self.window.show()
            self.window.raise_()

    def _update_occlusion(self):
        # Owned native windows can be raised above sibling dialogs and notices.
        # Clip their regions out so comments cannot paint over application UI.
        origin = self.parent.mapToGlobal(QPoint())
        region = QRegion(self.parent.rect())
        owner = self.parent.window()
        for widget in QApplication.topLevelWidgets():
            if widget is owner or not widget.isVisible() or not _owned_by(widget, owner):
                continue
            geometry = widget.frameGeometry()
            region -= QRegion(QRect(geometry.topLeft() - origin, geometry.size()))
        self.window.setMask(region)
        return not region.isEmpty()

    def resize(self):
        point = self.parent.mapToGlobal(QPoint())
        self.window.setGeometry(point.x(), point.y(), self.parent.width(), self.parent.height())
        self.stage.setWidth(self.parent.width())
        self.stage.setHeight(self.parent.height())
        if self._surface_reset.isActive():
            self._surface_reset.start(100)

    def raise_(self):
        if self.window.isVisible():
            self.window.raise_()

    def create_group(self, x, y, width, height, opacity=80, rounded=True):
        self._group_sequence += 1
        identifier = self._group_sequence
        group = self.group_component.create()
        if group is None:
            raise RuntimeError(self.group_component.errorString())
        group.setX(x)
        group.setY(y)
        group.setWidth(width)
        group.setHeight(height)
        group.setOpacity(max(0, min(100, int(opacity))) / 100)
        group.setProperty("rounded", bool(rounded))
        group.setParentItem(self.stage)
        self.groups[identifier] = group
        return identifier

    def set_group_geometry(self, identifier, x, y, width, height):
        group = self.groups.get(identifier)
        if group is not None:
            group.setX(x)
            group.setY(y)
            group.setWidth(width)
            group.setHeight(height)

    def set_group_visible(self, identifier, visible):
        group = self.groups.get(identifier)
        if group is not None:
            group.setVisible(bool(visible))
            self.show()

    def set_group_opacity(self, identifier, opacity):
        group = self.groups.get(identifier)
        if group is not None:
            group.setOpacity(max(0, min(100, int(opacity))) / 100)

    def set_group_rounded(self, identifier, rounded):
        group = self.groups.get(identifier)
        if group is not None:
            group.setProperty("rounded", bool(rounded))

    def set_group_mask(self, identifier, image):
        group = self.groups.get(identifier)
        if group is None:
            return
        old_key = self.group_masks.pop(identifier, None)
        if old_key is not None:
            self.images.remove_image(old_key)
        self._mask_sequence += 1
        key = f"mask-{identifier}-{self._mask_sequence}"
        self.images.set_image(key, image)
        group.setProperty("maskImage", QUrl(f"image://danmaku/{key}"))
        self.group_masks[identifier] = key

    def set_group_active(self, identifier, active):
        if identifier not in self.groups:
            return
        has_items = any(item["group"] == identifier for item in self.items.values())
        was_active = identifier in self._active_groups
        active = bool(active and has_items)
        if active:
            self._active_groups.add(identifier)
        else:
            self._active_groups.discard(identifier)
        if self.render_thread_animation and active != was_active:
            for record in self.items.values():
                if record["group"] == identifier:
                    record["item"].setMotionPaused(not active)
        self.stage.setProperty("active", bool(self._active_groups) and
                               not self.render_thread_animation)

    def add(self, group_id, image, x, y, width, height, speed=0):
        group = self.groups.get(group_id)
        if group is None:
            return 0
        content = group.property("content")
        self._item_sequence += 1
        identifier = self._item_sequence
        key = str(identifier)
        self.images.set_image(key, image)
        item = self.comment_component.create()
        if item is None:
            raise RuntimeError(self.comment_component.errorString())
        item.setWidth(width)
        item.setHeight(height)
        item.setX(x)
        item.setY(y)
        item.setProperty("imageSource", QUrl(f"image://danmaku/{key}"))
        item.setParentItem(content)
        self.items[identifier] = {"group": group_id, "item": item, "key": key,
                                  "speed": speed}
        self.set_group_active(group_id, True)
        self.move(identifier, x, y)
        self.show()
        return identifier

    def update(self, identifier, image, x, y, width, height, speed=0):
        record = self.items.get(identifier)
        if record is None:
            return
        self.images.remove_image(record["key"])
        self._item_sequence += 1
        key = str(self._item_sequence)
        self.images.set_image(key, image)
        item = record["item"]
        item.setWidth(width)
        item.setHeight(height)
        item.setX(x)
        item.setY(y)
        item.setProperty("imageSource", QUrl(f"image://danmaku/{key}"))
        record["key"] = key
        self.move(identifier, x, y, speed)

    def move(self, identifier, x, y, speed=None):
        record = self.items.get(identifier)
        if record is not None:
            item = record["item"]
            if speed is not None:
                record["speed"] = speed
            item.setY(y)
            if self.render_thread_animation and record["speed"] > 0:
                distance = max(0, x + item.width())
                item.setMotion(x, -item.width(), distance / record["speed"] * 1000,
                               record["group"] not in self._active_groups)
            else:
                item.setX(x)

    def remove(self, identifier):
        record = self.items.pop(identifier, None)
        if record is None:
            return
        record["item"].setVisible(False)
        record["item"].setParentItem(None)
        record["item"].deleteLater()
        self.images.remove_image(record["key"])
        self.set_group_active(record["group"], record["group"] in self._active_groups)
        if not self.items:
            # Let the render thread finish a Python frame callback before hiding.
            self._empty_hide.start(0)

    def clear_group(self, identifier):
        for item_id, record in tuple(self.items.items()):
            if record["group"] == identifier:
                self.remove(item_id)
        self.set_group_active(identifier, False)

    def remove_group(self, identifier):
        self.clear_group(identifier)
        group = self.groups.pop(identifier, None)
        if group is not None:
            mask_key = self.group_masks.pop(identifier, None)
            if mask_key is not None:
                self.images.remove_image(mask_key)
            group.setVisible(False)
            group.setParentItem(None)
            group.deleteLater()
