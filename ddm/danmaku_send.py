"""B 站逐房间弹幕输入与表情选择；网络请求在后台执行。"""
import requests
import hashlib
import json
from pathlib import Path
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QProxyStyle, QPushButton,
    QScrollArea, QSizePolicy, QStyle, QStyleOptionTab, QTabBar, QToolButton,
    QVBoxLayout, QWidget, QWidgetAction,
)

from . import bili, config, images, motion, theme


def _catalog_path(room_id, identity):
    key = hashlib.sha256(json.dumps([room_id, identity]).encode('utf-8')).hexdigest()
    return Path(config.REPO) / 'cache' / 'emoticon_catalogs' / (key + '.json')


def _load_catalog(room_id, identity):
    try:
        packages = json.loads(_catalog_path(room_id, identity).read_text(encoding='utf-8'))
        if isinstance(packages, list) and all(isinstance(p, dict)
                and p.get('pkg_type') in (1, 2, 3, 5)
                and isinstance(p.get('emoticons'), list)
                and all(isinstance(e, dict) for e in p['emoticons']) for p in packages):
            return packages
    except (OSError, ValueError):
        pass
    return None


def _save_catalog(room_id, identity, packages):
    path = _catalog_path(room_id, identity)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        supported = [p for p in packages if p.get('pkg_type') in (1, 2, 3, 5)]
        temporary.write_text(json.dumps(supported, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)
    except OSError:
        pass


class EmoticonOrder(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.orders = {}

    def load(self, orders):
        self.orders = {key: list(dict.fromkeys(value)) for key, value in orders.items()
                       if isinstance(key, str) and isinstance(value, list)
                       and all(isinstance(item, str) for item in value)} if isinstance(orders, dict) else {}

    @staticmethod
    def key(emote):
        return str(emote.get('emoticon_unique') or emote.get('emoji') or '')

    @staticmethod
    def package_key(package):
        return f"{package['pkg_type']}:{package.get('pkg_id') or package.get('pkg_name') or ''}"

    def arrange_packages(self, packages):
        ranks = {key: index for index, key in enumerate(self.orders.get('_tabs', []))}
        return sorted(packages, key=lambda package: ranks.get(self.package_key(package), len(ranks)))

    def save_packages(self, packages):
        keys = [self.package_key(package) for package in packages]
        # Preserve categories absent from the current room in their saved slots.
        pending = iter(keys)
        previous = self.orders.get('_tabs', [])
        self.orders['_tabs'] = [next(pending) if key in keys else key for key in previous]
        self.orders['_tabs'].extend(pending)
        self.changed.emit()

    def arrange(self, category, emotes):
        ranks = {key: index for index, key in enumerate(self.orders.get(category, []))}
        return sorted(emotes, key=lambda emote: ranks.get(self.key(emote), len(ranks)))

    def save(self, category, emotes):
        self.orders[category] = [self.key(emote) for emote in emotes]
        self.changed.emit()


emoticon_order = EmoticonOrder()


# 关闭格子/浮窗不销毁仍在执行网络请求的线程；Qt 自动断开已销毁接收者。
_active_requests: set[QThread] = set()


def _start(worker, priority=QThread.InheritPriority):
    _active_requests.add(worker)
    worker.finished.connect(lambda: _active_requests.discard(worker))
    worker.finished.connect(worker.deleteLater)
    worker.start(priority)


def wait_for_requests():
    """主窗口已隐藏后等待有超时的请求，避免退出时析构仍运行的 QThread。"""
    for worker in list(_active_requests):
        worker.wait()


def _style_button(button):
    button.setObjectName("TileCtrl")
    # 与主题注入的浅色局部样式放在同一层，并保留状态选择器的优先级。
    button.setStyleSheet("""
        QPushButton#TileCtrl:disabled {background: transparent; color: palette(tooltip-text);}
        QPushButton#TileCtrl:focus {border: 1px solid palette(highlight);}
    """)
    button.setCursor(Qt.PointingHandCursor)
    button.setAutoDefault(False)


class EmoticonButton(QPushButton):
    """与播放器控制同样使用矢量绘制，避免字体笑脸过小或被替换为彩色 emoji。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event):
        color = theme.TEXT2 if self.isEnabled() else theme.TEXT4
        if self.isEnabled() and self.property("menuOpen"):
            color = theme.ACCENT
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(self.width() / 2, self.height() / 2)
        pen = QPen(theme.qcolor(color), 1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(-8, -8, 16, 16))
        smile = QPainterPath(QPointF(-3.6, 1.8))
        smile.quadTo(0, 6, 3.6, 1.8)
        painter.drawPath(smile)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(color))
        for x in (-3, 3):
            painter.drawEllipse(QPointF(x, -2.3), .9, .9)


class _Request(QThread):
    completed = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, context, task, *, timeout_message="请求超时，请稍后重试"):
        super().__init__()
        self.context, self.task = context, task
        self.timeout_message = timeout_message

    def run(self):
        try:
            result = self.task()
        except requests.Timeout:
            self.failed.emit(self.context, self.timeout_message)
        except requests.RequestException:
            self.failed.emit(self.context, "网络请求失败，请检查网络后重试")
        except Exception as error:  # noqa: BLE001
            self.failed.emit(self.context, str(error) or "请求失败，请重试")
        else:
            self.completed.emit(self.context, result)


class DanmakuEdit(QLineEdit):
    """输入时接管单键快捷键，中文选词回车不触发发送。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._composing = False

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and not (
                event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            event.accept()
            return True
        return super().event(event)

    def inputMethodEvent(self, event):
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self._composing:
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.clearFocus()
            event.accept()
            return
        super().keyPressEvent(event)


class _EmoticonImageLoader(QThread):
    """当前表情包串行读图；避免头像加载器的八路并发与音频回调争用。"""
    loaded = Signal(int, str, QPixmap)

    def __init__(self, generation, urls):
        super().__init__()
        self.generation, self.urls = generation, urls

    def run(self):
        for url in self.urls:
            if self.isInterruptionRequested():
                break
            pixmap = images.load_pixmap(url, "emoticons")
            if self.isInterruptionRequested():
                break
            if pixmap is not None and not pixmap.isNull():
                # 图标按 32 逻辑像素显示，保留 2x 分辨率，避免缓存整张原图。
                pixmap = pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.loaded.emit(self.generation, url, pixmap)
            self.msleep(4)


class _CenteredTabStyle(QProxyStyle):
    def drawControl(self, element, option, painter, widget=None):
        if element == QStyle.CE_TabBarTab and isinstance(option, QStyleOptionTab):
            selected = bool(option.state & QStyle.State_Selected)
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(theme.qcolor(theme.ACCENT if selected else theme.BORDER), 1))
            painter.setBrush(theme.qcolor(theme.ACCENT_SOFT) if selected else Qt.NoBrush)
            painter.drawRoundedRect(QRectF(option.rect).adjusted(2.5, 2.5, -2.5, -2.5),
                                    theme.RADIUS_SM, theme.RADIUS_SM)
            if not option.icon.isNull():
                rect = QRect(QPoint(), option.iconSize)
                rect.moveCenter(option.rect.center())
                mode = QIcon.Normal if option.state & QStyle.State_Enabled else QIcon.Disabled
                option.icon.paint(painter, rect, Qt.AlignCenter, mode,
                                  QIcon.On if selected else QIcon.Off)
            else:
                painter.setPen(theme.qcolor(theme.ACCENT if selected else theme.TEXT2))
                text = option.fontMetrics.elidedText(option.text, Qt.ElideRight, option.rect.width() - 8)
                painter.drawText(option.rect.adjusted(4, 0, -4, 0), Qt.AlignCenter, text)
            painter.restore()
            return
        super().drawControl(element, option, painter, widget)


class EmoticonTabs(QTabBar):
    """包名和封面共用固定方形位置，异步换图时不重排分类。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Keep Qt's native drag painting (including its moving-tab snapshot).
        # Style both the stationary tab and its drag snapshot identically.
        self._centered_style = _CenteredTabStyle()
        self._centered_style.setParent(self)
        self.setStyle(self._centered_style)

    def tabSizeHint(self, index):
        return QSize(40, 40)

    def minimumTabSizeHint(self, index):
        return self.tabSizeHint(index)


class EmoticonPopup(QMenu):
    selected = Signal(int, dict)
    retryRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EmoticonPopup")
        self.setStyleSheet(f"""
            #EmoticonButton {{border: 1px solid transparent; border-radius: {theme.RADIUS_MD}px;
                color: {theme.TEXT1}; font-size: {theme.FONT_CAPTION}px; padding: 1px;}}
            #EmoticonButton:hover {{background: {theme.CONTENT_HOVER};}}
            #EmoticonButton:disabled {{color: {theme.TEXT3};}}
            #EmoticonTabs {{background: transparent; font-size: {theme.FONT_CAPTION}px;}}
            #EmoticonStatus {{color: {theme.TEXT3}; font-size: {theme.FONT_CAPTION}px;}}
        """)
        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        self.status = QLabel("正在加载表情…")
        self.status.setObjectName("EmoticonStatus")
        self.status.setWordWrap(True)
        header.addWidget(self.status, 1)
        self.retry_button = QPushButton("重试")
        _style_button(self.retry_button)
        self.retry_button.setFixedSize(48, theme.TILE_CONTROL_HEIGHT)
        self.retry_button.setToolTip("重新获取当前直播间的表情列表")
        self.retry_button.clicked.connect(self.retryRequested)
        self.retry_button.hide()
        header.addWidget(self.retry_button)
        layout.addLayout(header)
        self.tabs = EmoticonTabs()
        self.tabs.setObjectName("EmoticonTabs")
        self.tabs.setAccessibleName("表情包分类")
        self.tabs.setExpanding(False)
        self.tabs.setMovable(True)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.setIconSize(QSize(24, 24))
        self.tabs.currentChanged.connect(self._select_package)
        self.tabs.tabMoved.connect(self._tab_moved)
        self.tabs.hide()
        layout.addWidget(self.tabs)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(self.scroll, 1)
        self._packages = []
        self._covers = {}
        self._pixmaps = {}
        self._generation = 0
        self._image_loader = None
        self._pending_urls = {}
        self._drag_button = None
        self._syncing_tabs = False
        self._build_timer = QTimer(self)
        self._build_timer.setInterval(8)
        self._build_timer.timeout.connect(self._build_batch)
        self._clear_body()
        action = QWidgetAction(self)
        action.setDefaultWidget(holder)
        self.addAction(action)
        self._holder = holder
        self._holder.setFixedSize(340, 300)

    def _clear_body(self):
        self._drag_button = None
        self._drag_origin = None
        self._buttons = []
        self._animations = {}
        self._pause_loading()
        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(4)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.scroll.setWidget(body)
        self._images = {}
        self._emotes = []
        self._next_emote = 0
        self._category = None

    def _pause_loading(self):
        self._build_timer.stop()
        self._generation += 1
        self._pending_urls.clear()
        self._requested_urls = set()
        if self._image_loader is not None:
            self._image_loader.requestInterruption()

    def _clear_packages(self):
        self._clear_body()
        self._packages = []
        self._covers.clear()
        self._pixmaps.clear()
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        self.tabs.blockSignals(False)
        self.tabs.hide()

    def set_loading(self):
        self._clear_packages()
        self.status.setText("正在加载表情…")
        self.status.show()
        self.retry_button.setText("刷新")
        self.retry_button.setEnabled(False)
        self.retry_button.show()

    def set_error(self, message):
        self.status.setText(message)
        self.status.show()
        self.retry_button.setText("重试")
        self.retry_button.setEnabled(True)
        self.retry_button.show()

    def set_packages(self, packages):
        self._clear_packages()
        self.retry_button.setText("刷新")
        self.retry_button.setEnabled(True)
        self.retry_button.show()
        self._packages = emoticon_order.arrange_packages(
            [p for p in packages if p.get("pkg_type") in (1, 2, 3, 5)])
        self.tabs.blockSignals(True)
        for package in self._packages:
            name = str(package.get("pkg_name") or "表情")
            if package["pkg_type"] == 3 and name.lower() == "emoji":
                name = "表情"
            index = self.tabs.addTab(name)
            self.tabs.setTabData(index, emoticon_order.package_key(package))
            self.tabs.setTabToolTip(index, name)
            self.tabs.setAccessibleTabName(index, name)
            cover = package.get("current_cover")
            if package["pkg_type"] != 3 and isinstance(cover, str) and cover.startswith(("https://", "http://")):
                self._covers.setdefault(cover, []).append(index)
                pixmap = images.load_cached_emoticon(cover)
                if pixmap is not None:
                    self._pixmaps[cover] = pixmap
                    self.tabs.setTabIcon(index, QIcon(pixmap))
                    self.tabs.setTabText(index, "")
        self.tabs.blockSignals(False)
        self.tabs.setVisible(bool(self._packages))
        self._select_package(self.tabs.currentIndex())

    def _tab_moved(self, source, target):
        self._packages.insert(target, self._packages.pop(source))
        self._covers.clear()
        for index, package in enumerate(self._packages):
            cover = package.get('current_cover')
            if package['pkg_type'] != 3 and isinstance(cover, str) and cover.startswith(('https://', 'http://')):
                self._covers.setdefault(cover, []).append(index)
        if not self._syncing_tabs:
            emoticon_order.save_packages(self._packages)

    def _select_package(self, index, force=False):
        key = self.tabs.tabData(index) if index >= 0 else None
        if not force and key is not None and key == self._category:
            return
        self._clear_body()
        package = next((p for p in self._packages if emoticon_order.package_key(p) == key), None)
        if package is not None:
            self._kind = package["pkg_type"]
            self._category = key
            self._emotes = emoticon_order.arrange(self._category,
                [e for e in package.get("emoticons") or [] if isinstance(e, dict)])
            # Reserve the complete category height before lazy batches arrive.
            # Otherwise QScrollArea initially squeezes rows, then expands them
            # on reopen, making every subsequent row appear to drift downward.
            rows = (len(self._emotes) + 4) // 5
            self.scroll.widget().setMinimumHeight(max(0, rows * 60 - 4))
        self.status.setText("表情" if self._emotes else "暂无可用表情")
        self.status.show()
        self._resume_loading()

    def _build_batch(self):
        # 每批两行，长包不会一次占用 GUI 线程；未选中的包不创建按钮。
        end = min(self._next_emote + 10, len(self._emotes))
        for index in range(self._next_emote, end):
            emote = self._emotes[index]
            text = str(emote.get("emoji") or "表情")
            button = QToolButton()
            button.setText(text)
            button.setAccessibleName(text)
            button.setObjectName("EmoticonButton")
            button.setFixedSize(56, 56)
            button.setIconSize(QSize(32, 32))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setCursor(Qt.PointingHandCursor)
            button.installEventFilter(self)
            available = emote.get("perm") == 1 and bool(emote.get(
                "emoji" if self._kind == 3 else "emoticon_unique"))
            button.setEnabled(available)
            button.setToolTip(text if available else
                              f"{text}：{emote.get('unlock_show_text') or '当前账号尚未解锁'}")
            button.clicked.connect(lambda _checked=False, k=self._kind, e=dict(emote): self._choose(k, e))
            self.grid.addWidget(button, index // 5, index % 5)
            self.grid.setRowMinimumHeight(index // 5, 56)
            self._buttons.append(button)
            url = emote.get("url")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                self._images.setdefault(url, []).append(button)
                if url in self._pixmaps:
                    button.setIcon(QIcon(self._pixmaps[url]))
                elif url not in self._requested_urls:
                    self._requested_urls.add(url)
                    self._pending_urls[url] = None
        self._next_emote = end
        if end == len(self._emotes):
            self._build_timer.stop()
        self._start_images()

    def _arrange_buttons(self, animate=True):
        positions = {button: button.pos() for button in self._buttons}
        for button in self._buttons:
            animation = self._animations.pop(button, None)
            if animation is not None:
                animation.stop()
                animation.deleteLater()
            self.grid.removeWidget(button)
        for index, button in enumerate(self._buttons):
            self.grid.addWidget(button, index // 5, index % 5)
        self.grid.activate()
        for button in self._buttons:
            target = button.pos()
            if button is self._drag_button:
                button.move(positions[button])
            elif animate and motion.enabled() and target != positions[button]:
                animation = QPropertyAnimation(button, b'pos', button)
                animation.setDuration(150)
                animation.setEasingCurve(QEasingCurve.OutCubic)
                animation.setStartValue(positions[button])
                animation.setEndValue(target)
                self._animations[button] = animation
                animation.start()

    def eventFilter(self, button, event):
        if button not in self._buttons:
            return super().eventFilter(button, event)
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_offset = event.position().toPoint()
        elif event.type() == QEvent.MouseMove and event.buttons() & Qt.LeftButton and self._drag_origin is not None:
            point = event.globalPosition().toPoint()
            if self._drag_button is None:
                if (point - self._drag_origin).manhattanLength() < QApplication.startDragDistance():
                    return False
                self._drag_button = button
                button.setDown(False)
                button.raise_()
            body = self.scroll.widget()
            local = body.mapFromGlobal(point)
            button.move(local - self._drag_offset)
            viewport = self.scroll.viewport()
            y = viewport.mapFromGlobal(point).y()
            bar = self.scroll.verticalScrollBar()
            if y < 24 or y > viewport.height() - 24:
                bar.setValue(bar.value() + (-18 if y < 24 else 18))
            targets = [(self.grid.cellRect(i // 5, i % 5).center() - local).manhattanLength()
                       for i in range(len(self._buttons))]
            target = min(range(len(targets)), key=targets.__getitem__)
            source = self._buttons.index(button)
            if source != target:
                self._buttons.insert(target, self._buttons.pop(source))
                self._emotes.insert(target, self._emotes.pop(source))
                self._arrange_buttons()
            return True
        elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self._drag_origin = None
            if self._drag_button is not None:
                self._drag_button = None
                button.setDown(False)
                self._arrange_buttons()
                emoticon_order.save(self._category, self._emotes)
                return True
        return super().eventFilter(button, event)

    def _start_images(self):
        if not self.isVisible() or self._image_loader is not None or not self._pending_urls:
            return
        urls = [url for url in self._pending_urls if url in self._images]
        if not urls:
            if self._next_emote < len(self._emotes):
                return  # 等下一批当前包按钮提供 URL，不让导航封面抢在前面。
            urls = list(self._pending_urls)[:1]
        for url in urls:
            del self._pending_urls[url]
        loader = _EmoticonImageLoader(self._generation, urls)
        self._image_loader = loader
        loader.loaded.connect(self._image_loaded)
        loader.finished.connect(self._images_finished)
        _start(loader, QThread.LowPriority)

    def _images_finished(self):
        self._image_loader = None
        self._start_images()

    def _image_loaded(self, generation, url, pixmap):
        if generation != self._generation:
            return
        self._pixmaps[url] = pixmap
        for index in self._covers.get(url, []):
            self.tabs.setTabIcon(index, QIcon(pixmap))
            # 加载成功才移除文字，缺图或失败仍有可读的包名作为回退。
            self.tabs.setTabText(index, "")
        for button in self._images.get(url, []):
            button.setIcon(QIcon(pixmap))

    def hideEvent(self, event):
        if self._drag_button is not None:
            self._drag_button = None
            self._arrange_buttons(False)
            emoticon_order.save(self._category, self._emotes)
        self._drag_origin = None
        self._pause_loading()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._resume_loading()

    def _resume_loading(self):
        if not self.isVisible():
            return
        # 分类封面只加载少量导航图片，包内表情仍仅按当前 Tab 构建。
        for url in (*self._covers, *self._images):
            if url not in self._pixmaps and url not in self._requested_urls:
                self._requested_urls.add(url)
                self._pending_urls[url] = None
        if self._next_emote < len(self._emotes):
            self._build_timer.start()
        self._start_images()

    def _choose(self, kind, emote):
        self.hide()
        self.selected.emit(kind, emote)

    def open_at(self, button):
        if self._packages:
            # Keep cached cells and the scroll position on ordinary reopen.
            # Only reconcile changes made in another room's popup.
            self._syncing_tabs = True
            try:
                for target, package in enumerate(emoticon_order.arrange_packages(self._packages)):
                    source = self._packages.index(package)
                    if source != target:
                        self.tabs.moveTab(source, target)
            finally:
                self._syncing_tabs = False
            if emoticon_order.arrange(self._category, self._emotes) != self._emotes:
                self._select_package(self.tabs.currentIndex(), force=True)
        screen = button.screen().availableGeometry()
        self._holder.setFixedSize(min(340, screen.width() - 16), min(300, screen.height() - 16))
        self.adjustSize()
        anchor = button.mapToGlobal(QPoint(button.width(), 0))
        x = max(screen.left(), min(anchor.x() - self.width(), screen.right() - self.width() + 1))
        y = anchor.y() - self.height() - 6
        if y < screen.top():
            y = button.mapToGlobal(button.rect().bottomLeft()).y() + 6
        self.popup(QPoint(x, max(screen.top(), min(y, screen.bottom() - self.height() + 1))))


class DanmakuComposer(QWidget):
    deviceCookieReady = Signal()
    noticeRequested = Signal(str, bool)
    HEIGHT = theme.TILE_CONTROL_HEIGHT

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DanmakuComposer")
        self.setCursor(Qt.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._room_id = ""
        self._closing = False
        self._generation = self._revision = 0
        self._auth = self._auth_identity(bili._cookies())
        self._pending = self._catalog_pending = None
        self._catalog_key = None
        self._packages = None
        self.popup = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.edit = DanmakuEdit()
        self.edit.setObjectName("DanmakuInput")
        self.edit.setAccessibleName("发送到当前直播间的弹幕")
        self.edit.setPlaceholderText("输入弹幕，Enter 发送")
        self.edit.setMinimumWidth(0)
        self.edit.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.edit.setFixedHeight(self.HEIGHT)
        self.edit.textChanged.connect(self._text_changed)
        self.edit.returnPressed.connect(self.send_text)
        row.addWidget(self.edit, 1)
        self.emote_button = EmoticonButton()
        self.emote_button.setAccessibleName("选择直播间表情")
        self.emote_button.setToolTip("选择表情；大表情点击后直接发送")
        self.emote_button.setFixedSize(self.HEIGHT, self.HEIGHT)
        self.emote_button.clicked.connect(self.open_emoticons)
        row.addWidget(self.emote_button)
        self.send_button = QPushButton("发送")
        self.send_button.setFixedSize(52, self.HEIGHT)
        self.send_button.clicked.connect(self.send_text)
        row.addWidget(self.send_button)
        for button in (self.emote_button, self.send_button):
            _style_button(button)
        self.send_button.setObjectName("DanmakuSendButton")
        self.send_button.setStyleSheet("")
        self.feedback = QLabel("", self)
        self.feedback.setObjectName("DanmakuSendFeedback")
        self.feedback.setAttribute(Qt.WA_ShowWithoutActivating)
        self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setWordWrap(True)
        self.feedback.setMaximumWidth(380)
        self.feedback.setAccessibleName("弹幕发送状态")
        self.feedback.hide()
        self._update_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 小格保留输入和表情入口，回车仍可发送，不为单独按钮挤掉输入空间。
        self.send_button.setVisible(self.width() >= 144)

    def hideEvent(self, event):
        self.feedback.hide()
        if self.popup:
            self.popup.hide()
        super().hideEvent(event)

    @property
    def busy(self):
        return self._pending is not None

    def shutdown(self):
        self._closing = True
        self._generation += 1
        self._pending = self._catalog_pending = None
        self._packages = self._catalog_key = None
        self.feedback.hide()
        if self.popup:
            self.popup.hide()
        self.setEnabled(False)

    @property
    def supported(self):
        return self._room_id.isascii() and self._room_id.isdigit() and bool(self._room_id.strip("0"))

    @staticmethod
    def _auth_identity(cookies):
        return cookies.get("SESSDATA", ""), cookies.get("bili_jct", "")

    def sync_credentials(self):
        cookies = bili._cookies()
        identity = self._auth_identity(cookies)
        if identity != self._auth:
            self._auth = identity
            self._generation += 1
            self._pending = self._catalog_pending = None
            self._packages = self._catalog_key = None
            self._feedback("")
            if self.popup:
                self.popup.set_loading()
                self.popup.hide()
            self._update_buttons()
        return cookies

    def set_room(self, room_id):
        room_id = str(room_id or "")
        if room_id != self._room_id:
            self._generation += 1
            self._room_id = room_id
            self._pending = self._catalog_pending = None
            self._packages = self._catalog_key = None
            self.edit.clear()
            self._feedback("")
            if self.popup:
                self.popup.hide()
        self.setVisible(self.supported)
        self._update_buttons()

    def _text_changed(self):
        self._revision += 1
        self.feedback.hide()
        self._update_buttons()

    def _update_buttons(self):
        has_text = bool(self.edit.text().strip())
        self.send_button.setEnabled(has_text and not self.busy)
        if self.send_button.property("hasText") != has_text:
            self.send_button.setProperty("hasText", has_text)
            self.send_button.style().unpolish(self.send_button)
            self.send_button.style().polish(self.send_button)
        self.send_button.setText("…" if self.busy else "发送")

    def _context(self):
        self.sync_credentials()
        # buvid3 的按需初始化不代表账号变化，不能使首次表情请求失效。
        return self._generation, self._room_id, self._auth

    def send_text(self):
        if self.edit.text().strip():
            self._send(self.edit.text(), 0)

    def _send(self, message, dm_type):
        cookies = self.sync_credentials()
        if self._closing or self.busy or not self.supported:
            return
        if not cookies.get("SESSDATA") or not cookies.get("bili_jct"):
            self._feedback("请先登录 B 站" if not cookies.get("SESSDATA") else
                           "B 站登录凭证不完整，请重新登录", login_required=True)
            return
        context = (*self._context(), self._revision, dm_type)
        self._pending = context
        self._feedback("正在发送…")
        self._update_buttons()
        room_id = self._room_id
        worker = _Request(context, lambda: bili.send_danmaku(room_id, message, dm_type=dm_type, cookies=cookies),
                          timeout_message="发送请求超时，结果可能未确认，请确认后再试")
        worker.completed.connect(self._sent)
        worker.failed.connect(self._send_failed)
        _start(worker)

    @staticmethod
    def _needs_login(text):
        return any(word in text.lower() for word in (
            "未登录", "登录失效", "请先登录", "csrf", "bili_jct", "-101"))

    def _feedback(self, text, *, login_required=False):
        self.feedback.setText(text)
        self.feedback.setToolTip(text)
        self.feedback.setAccessibleDescription(text)
        self.edit.setAccessibleDescription(text)
        self.feedback.hide()
        if text and not self.busy:
            login_required = login_required or self._needs_login(text)
            self.noticeRequested.emit(text, login_required)

    def _finish_send(self, context):
        if context != self._pending:
            return False
        self._pending = None
        self._update_buttons()
        if context[:3] != self._context():
            self._feedback("")
            return False
        return True

    def _sent(self, context, _result):
        self.deviceCookieReady.emit()
        if self._finish_send(context):
            if context[4] == 0 and context[3] == self._revision:
                self.edit.clear()
            self._feedback("")

    def _send_failed(self, context, error):
        self.deviceCookieReady.emit()
        if self._finish_send(context):
            self._feedback(error)

    def choose_emoticon(self, pkg_type, emote):
        if self._closing:
            return
        self.sync_credentials()
        if emote.get("perm") != 1:
            return
        if pkg_type == 3:
            self.edit.insert(str(emote.get("emoji") or ""))
        elif pkg_type in (1, 2, 5) and emote.get("emoticon_unique"):
            self._send(str(emote["emoticon_unique"]), 1)
        self.edit.setFocus(Qt.OtherFocusReason)

    def open_emoticons(self, _checked=False):
        cookies = self.sync_credentials()
        self.feedback.hide()
        if self._closing or not self.supported:
            return
        if not cookies.get("SESSDATA"):
            self._feedback("请先登录 B 站后选择表情", login_required=True)
            return
        if self.popup is None:
            self.popup = EmoticonPopup(self)
            self.popup.selected.connect(self._choose_cached_emoticon)
            self.popup.retryRequested.connect(self._reload_emoticons)
            self.popup.aboutToShow.connect(lambda: self._set_emoticon_open(True))
            self.popup.aboutToHide.connect(lambda: self._set_emoticon_open(False))
        self.popup.open_at(self.emote_button)
        context = self._context()
        if self._catalog_key == context and self._packages is not None:
            return
        if self._catalog_pending == context:
            return
        cached = _load_catalog(self._room_id, self._auth)
        if cached is not None:
            self._catalog_key, self._packages = context, cached
            self.popup.set_packages(cached)
            return
        self.popup.set_loading()
        self._catalog_pending = context
        room_id = self._room_id
        worker = _Request(context, lambda: bili.get_emoticons(room_id, cookies=cookies))
        worker.completed.connect(self._emoticons_loaded)
        worker.failed.connect(self._emoticons_failed)
        _start(worker)

    def _set_emoticon_open(self, opened):
        self.emote_button.setProperty('menuOpen', opened)
        self.emote_button.update()

    def _choose_cached_emoticon(self, kind, emote):
        # 菜单打开后可能退出/切换账号，旧的权限结果不能沿用。
        if self._catalog_key == self._context():
            self.choose_emoticon(kind, emote)

    def _reload_emoticons(self):
        try:
            _catalog_path(self._room_id, self._auth).unlink(missing_ok=True)
        except OSError:
            pass
        self._catalog_key = None
        self.open_emoticons()

    def _emoticons_loaded(self, context, packages):
        self.deviceCookieReady.emit()
        if context != self._context():
            return
        self._catalog_pending = None
        self._catalog_key, self._packages = context, packages
        _save_catalog(self._room_id, self._auth, packages)
        self.popup.set_packages(packages)

    def _emoticons_failed(self, context, error):
        self.deviceCookieReady.emit()
        if context != self._context():
            return
        self._catalog_pending = None
        if self._needs_login(error):
            self.popup.hide()
            self._feedback(error, login_required=True)
        else:
            self.popup.set_error(error)
