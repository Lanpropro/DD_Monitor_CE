"""send2 emoticon tabs, permission-aware picker and lazy images."""
import requests
import hashlib
import threading
from collections import OrderedDict
from concurrent.futures import Future
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QProxyStyle, QPushButton,
    QScrollArea, QSizePolicy, QStyle, QStyleOptionTab, QTabBar, QToolButton,
    QVBoxLayout, QWidget, QWidgetAction,
)

from pathlib import Path
from ddm import config, theme
from .gift_media import _fetch
from .emoticon_order import EmoticonOrder, emoticon_order
from .popup import AnchoredPopup, RefreshSpinner, picker_style
from .workers import start_worker as _start

_MAX_EMOTICON_COLUMNS = 4
_EMOTICON_CELL_SIZE = 84
_EMOTICON_ICON_SIZE = 64

def _style_button(button, *, diameter=None):
    button.setObjectName("TileCtrl")
    # 与主题注入的浅色局部样式放在同一层，并保留状态选择器的优先级。
    button.setStyleSheet("""
        QPushButton#TileCtrl:disabled {background: transparent; color: palette(tooltip-text);}
        QPushButton#TileCtrl:focus {border: none; outline: none;}
    """)
    if diameter is not None:
        button.setFixedSize(diameter, diameter)
        button.setStyleSheet(button.styleSheet() + f"""
            QPushButton#TileCtrl {{border-radius: {diameter // 2}px; padding: 0;}}
        """)
    button.setCursor(Qt.PointingHandCursor)
    button.setFocusPolicy(Qt.TabFocus)
    button.setAutoDefault(False)


class EmoticonButton(QPushButton):
    """与播放器控制同样使用矢量绘制，避免字体笑脸过小或被替换为彩色 emoji。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        _style_button(self, diameter=24)

    def paintEvent(self, event):
        super().paintEvent(event)
        color = theme.TEXT2 if self.isEnabled() else theme.TEXT4
        if self.isEnabled() and (self.underMouse() or self.property("hovered") is True):
            color = theme.ACCENT if theme.is_light() else theme.BG
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(.875, .875)
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


# Keep decoded images across popups. QImage is safe in worker threads; QPixmap
# conversion stays on the GUI thread. Include the root to isolate test caches.
_EMOTICON_IMAGES = OrderedDict()
_EMOTICON_PENDING = {}
_EMOTICON_LOCK = threading.Lock()
_EMOTICON_BYTES = 0
_EMOTICON_CACHE_LIMIT = 16 * 1024 * 1024


def _read_image(url, subdir, root):
    digest = hashlib.md5(url.encode('utf-8')).hexdigest() + '.png'
    for directory in dict.fromkeys((subdir, 'emoticons')):
        legacy = root / 'cache' / directory / digest
        if legacy.is_file():
            image = QImage(str(legacy))
            if not image.isNull():
                return image
    return QImage(_fetch(url, root / 'cache' / subdir))


def _load_image(url, subdir):
    global _EMOTICON_BYTES
    root = Path(config.data_root())
    key = (str(root), subdir, url)
    with _EMOTICON_LOCK:
        cached = _EMOTICON_IMAGES.get(key)
        if cached is not None:
            _EMOTICON_IMAGES.move_to_end(key)
            return QImage(cached)
        pending = _EMOTICON_PENDING.get(key)
        owner = pending is None
        if owner:
            pending = _EMOTICON_PENDING[key] = Future()
    if not owner:
        return QImage(pending.result())
    decoded = QImage()
    error = None
    try:
        decoded = _read_image(url, subdir, root)
        if not decoded.isNull():
            size = decoded.sizeInBytes()
            if size <= _EMOTICON_CACHE_LIMIT:
                with _EMOTICON_LOCK:
                    _EMOTICON_IMAGES[key] = QImage(decoded)
                    _EMOTICON_BYTES += size
                    while _EMOTICON_BYTES > _EMOTICON_CACHE_LIMIT or len(_EMOTICON_IMAGES) > 256:
                        _, evicted = _EMOTICON_IMAGES.popitem(last=False)
                        _EMOTICON_BYTES -= evicted.sizeInBytes()
        return QImage(decoded)
    except BaseException as exception:
        error = exception
        raise
    finally:
        with _EMOTICON_LOCK:
            _EMOTICON_PENDING.pop(key, None)
            if error is None:
                pending.set_result(decoded)
            else:
                pending.set_exception(error)


class _EmoticonImageLoader(QThread):
    """Bounded QThreads decode QImage; QPixmap stays on the GUI thread."""
    loaded = Signal(int, str, QImage)

    def __init__(self, generation, urls):
        super().__init__()
        self.generation, self.urls = generation, urls

    def run(self):
        for url in self.urls:
            if self.isInterruptionRequested():
                break
            try:
                pixmap = _load_image(url, "bili_live/emoticons")
            except Exception:
                continue
            if self.isInterruptionRequested():
                break
            if pixmap is not None and not pixmap.isNull():
                # 图标保留 2x 分辨率，避免给弹窗缓存整张原图。
                icon_pixels = 2 * _EMOTICON_ICON_SIZE
                pixmap = pixmap.scaled(icon_pixels, icon_pixels, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.loaded.emit(self.generation, url, pixmap)


def _emoji_category_icon():
    pixmap = QPixmap(48, 48)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(12, 12)
    pen = QPen(theme.qcolor(theme.TEXT2), 1.7)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QRectF(-8, -8, 16, 16))
    smile = QPainterPath(QPointF(-3.6, 1.8))
    smile.quadTo(0, 6, 3.6, 1.8)
    painter.drawPath(smile)
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.qcolor(theme.TEXT2))
    for x in (-3, 3):
        painter.drawEllipse(QPointF(x, -2.3), .9, .9)
    painter.end()
    return QIcon(pixmap)



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


class EmoticonPopup(AnchoredPopup):
    selected = Signal(int, dict)
    retryRequested = Signal()
    _holder_size = QSize(388, 368)

    def __init__(self, parent=None, *, order=None):
        super().__init__(parent)
        self.order = order if order is not None else emoticon_order
        self._syncing_tabs = False
        self._columns = _MAX_EMOTICON_COLUMNS
        self.setObjectName("EmoticonPopup")
        self.setStyleSheet(picker_style() + f"""
            #EmoticonButton {{border: 1px solid transparent; border-radius: {theme.RADIUS_SM}px;
                color: {theme.TEXT1}; font-size: 11px; padding: 1px;}}
            #EmoticonButton:hover, #EmoticonButton:focus {{background: {theme.CONTENT_HOVER};
                border-color: {theme.ACCENT};}}
            #EmoticonButton:disabled {{color: {theme.TEXT3};}}
            #EmoticonTabs {{background: transparent; font-size: {theme.FONT_CAPTION}px;}}
        """)
        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        policy=self.status.sizePolicy();policy.setRetainSizeWhenHidden(True);self.status.setSizePolicy(policy)
        header.addWidget(self.status, 1)
        self.status.hide()
        self.refresh_spinner=RefreshSpinner()
        header.addWidget(self.refresh_spinner,0,Qt.AlignVCenter)
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
        self.tabs.setMovable(True)
        self.tabs.tabMoved.connect(self._tab_moved)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.setIconSize(QSize(24, 24))
        self.tabs.currentChanged.connect(self._select_package)
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
        self._image_workers = set()
        self._pending_urls = {}
        self._build_timer = QTimer(self)
        self._build_timer.setInterval(8)
        self._build_timer.timeout.connect(self._build_batch)
        self._clear_body()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6,6,6,6)
        outer.addWidget(holder)
        self._holder = holder
        self._holder.setFixedSize(self._holder_size)
        self.order.changed.connect(self._order_changed)

    def _clear_body(self):
        self._drag_button = None
        self._drag_origin = None
        self._buttons = []
        self._category = None
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

    def _pause_loading(self):
        self._build_timer.stop()
        self._generation += 1
        self._pending_urls.clear()
        self._requested_urls = set()
        for loader in self._image_workers:
            loader.requestInterruption()

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

    def set_loading(self,*,clear=False):
        if clear:self._clear_packages()
        self.status.clear()
        self.status.hide()
        self.refresh_spinner.set_busy(True)
        self.retry_button.setText("刷新")
        self.retry_button.setEnabled(False)
        self.retry_button.show()

    def set_error(self, message):
        self.refresh_spinner.set_busy(False)
        self.status.setText(message)
        self.status.show()
        self.retry_button.setText("重试")
        self.retry_button.setEnabled(True)
        self.retry_button.show()

    def set_packages(self, packages):
        packages = self.order.arrange_packages(
            [p for p in packages if isinstance(p, dict) and p.get("pkg_type") in (1, 2, 3, 5)])
        self.refresh_spinner.set_busy(False)
        self.retry_button.setText("刷新")
        self.retry_button.setEnabled(True)
        self.retry_button.show()
        if packages and packages==self._packages:
            self.status.setText("表情" if self._emotes else "暂无可用表情")
            self.status.show()
            return
        selected = self._category
        pixmaps = dict(self._pixmaps)
        self._clear_packages()
        valid_urls = {url for package in packages
                      for url in [package.get('current_cover'),
                                  *(emote.get('url') for emote in package.get('emoticons') or []
                                    if isinstance(emote, dict))]
                      if isinstance(url, str)}
        self._pixmaps = {url: image for url, image in pixmaps.items() if url in valid_urls}
        self._packages = packages
        self.tabs.blockSignals(True)
        for package in self._packages:
            name = str(package.get("pkg_name") or "表情")
            if package["pkg_type"] == 3 and name.lower() == "emoji":
                name = "表情"
            index = self.tabs.addTab(name)
            if package['pkg_type'] == 3:
                self.tabs.setTabIcon(index, _emoji_category_icon())
                self.tabs.setTabText(index, '')
            self.tabs.setTabData(index, self.order.package_key(package))
            self.tabs.setTabToolTip(index, name)
            self.tabs.setAccessibleTabName(index, name)
            cover = package.get("current_cover")
            if package["pkg_type"] != 3 and isinstance(cover, str) and cover.startswith(("https://", "http://")):
                self._covers.setdefault(cover, []).append(index)
                if cover in self._pixmaps:
                    self.tabs.setTabIcon(index, QIcon(self._pixmaps[cover]))
                    self.tabs.setTabText(index, '')
        for index in range(self.tabs.count()):
            if self.tabs.tabData(index) == selected:
                self.tabs.setCurrentIndex(index)
                break
        self.tabs.blockSignals(False)
        self.tabs.setVisible(bool(self._packages))
        self._select_package(self.tabs.currentIndex())

    def refresh_theme(self):
        for index, package in enumerate(self._packages):
            if package['pkg_type'] == 3:
                self.tabs.setTabIcon(index, _emoji_category_icon())

    def _tab_moved(self, source, target):
        self._packages.insert(target, self._packages.pop(source))
        self._covers.clear()
        for index, package in enumerate(self._packages):
            cover = package.get('current_cover')
            if package['pkg_type'] != 3 and isinstance(cover, str) and cover.startswith(('https://', 'http://')):
                self._covers.setdefault(cover, []).append(index)
        if not self._syncing_tabs:
            self.order.save_packages(self._packages)

    def _order_changed(self):
        if self._syncing_tabs or not self._packages:
            return
        self._syncing_tabs = True
        try:
            for target, package in enumerate(self.order.arrange_packages(self._packages)):
                source = self._packages.index(package)
                if source != target:
                    self.tabs.moveTab(source, target)
        finally:
            self._syncing_tabs = False
        arranged = self.order.arrange(self._category, self._emotes)
        if arranged != self._emotes:
            # Complete categories can move existing cells without losing icons,
            # focus or scroll. A partially built category remains lazy.
            built = {id(emote): button for emote, button in zip(self._emotes, self._buttons)}
            if all(id(emote) in built for emote in arranged[:self._next_emote]):
                self._emotes = arranged
                self._buttons = [built[id(emote)] for emote in arranged[:self._next_emote]]
                self._arrange_buttons()
            else:
                scroll = self.scroll.verticalScrollBar().value()
                self._select_package(self.tabs.currentIndex(), force=True)
                self.scroll.verticalScrollBar().setValue(scroll)

    def _select_package(self, index, force=False):
        key = self.tabs.tabData(index) if index >= 0 else None
        if not force and key is not None and key == self._category:
            return
        self._clear_body()
        package = next((p for p in self._packages if self.order.package_key(p) == key), None)
        if package is not None:
            self._kind = package["pkg_type"]
            self._category = key
            self._emotes = self.order.arrange(key,
                [e for e in package.get("emoticons") or [] if isinstance(e, dict)])
            self._set_grid_height()
        self.status.setText("表情" if self._emotes else "暂无可用表情")
        self.status.show()
        self._resume_loading()

    def _set_grid_height(self):
        rows = (len(self._emotes) + self._columns - 1) // self._columns
        height = rows * _EMOTICON_CELL_SIZE + max(0, rows - 1) * self.grid.spacing()
        self.scroll.widget().setMinimumHeight(height)

    def _build_batch(self):
        # 每批两行，长包不会一次占用 GUI 线程；未选中的包不创建按钮。
        end = min(self._next_emote + 2 * self._columns, len(self._emotes))
        for index in range(self._next_emote, end):
            emote = self._emotes[index]
            text = str(emote.get("emoji") or "表情")
            button = QToolButton()
            button.setText(text)
            button.setAccessibleName(text)
            button.setObjectName("EmoticonButton")
            button.setFixedSize(_EMOTICON_CELL_SIZE, _EMOTICON_CELL_SIZE)
            button.setIconSize(QSize(_EMOTICON_ICON_SIZE, _EMOTICON_ICON_SIZE))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setCursor(Qt.PointingHandCursor)
            button.installEventFilter(self)
            available = emote.get("perm") == 1 and bool(emote.get(
                "emoji" if self._kind == 3 else "emoticon_unique"))
            button.setEnabled(available)
            button.setToolTip(text if available else
                              f"{text}：{emote.get('unlock_show_text') or '当前账号尚未解锁'}")
            button.clicked.connect(lambda _checked=False, k=self._kind, e=dict(emote): self._choose(k, e))
            self.grid.addWidget(button, *divmod(index, self._columns))
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

    def _arrange_buttons(self):
        positions = {button: button.pos() for button in self._buttons}
        for button in self._buttons:
            self.grid.removeWidget(button)
        for index, button in enumerate(self._buttons):
            self.grid.addWidget(button, *divmod(index, self._columns))
        self.grid.activate()
        if self._drag_button is not None:
            self._drag_button.move(positions[self._drag_button])

    def eventFilter(self, button, event):
        if button not in getattr(self, '_buttons', ()):
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
                self._build_timer.stop()
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
            targets = [(self.grid.cellRect(*divmod(i, self._columns)).center() - local).manhattanLength()
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
                self.order.save(self._category, self._emotes)
                self._resume_loading()
                return True
        return super().eventFilter(button, event)

    def _start_images(self):
        if not self.isVisible() or not self._pending_urls:
            return
        urls = [url for url in self._pending_urls if url in self._images]
        if not urls:
            if self._next_emote < len(self._emotes):
                return  # 等下一批当前包按钮提供 URL，不让导航封面抢在前面。
            urls = list(self._pending_urls)
        for url in urls[:max(0,4-len(self._image_workers))]:
            del self._pending_urls[url]
            loader = _EmoticonImageLoader(self._generation, [url])
            self._image_workers.add(loader)
            loader.loaded.connect(self._image_loaded)
            loader.finished.connect(self._images_finished)
            _start(loader, QThread.LowPriority)

    def _images_finished(self):
        self._image_workers.discard(self.sender())
        self._start_images()

    def _image_loaded(self, generation, url, pixmap):
        if generation != self._generation:
            return
        pixmap = QPixmap.fromImage(pixmap)
        self._pixmaps[url] = pixmap
        for index in self._covers.get(url, []):
            self.tabs.setTabIcon(index, QIcon(pixmap))
            # 加载成功才移除文字，缺图或失败仍有可读的包名作为回退。
            self.tabs.setTabText(index, "")
        for button in self._images.get(url, []):
            button.setIcon(QIcon(pixmap))

    def hideEvent(self, event):
        if self._drag_button is not None:
            self._drag_button.setDown(False)
            self._drag_button = None
            self._arrange_buttons()
            self.order.save(self._category, self._emotes)
        self._drag_origin = None
        self._pause_loading()
        super().hideEvent(event)

    def showEvent(self, event):
        self._order_changed()
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
        screen = button.screen().availableGeometry()
        self._holder.setFixedSize(self._holder_size.boundedTo(screen.size() - QSize(16, 16)))
        margins = self._holder.layout().contentsMargins()
        scrollbar = self.scroll.verticalScrollBar().sizeHint().width()
        width = self._holder.width() - margins.left() - margins.right() - scrollbar
        spacing = self.grid.spacing()
        columns = max(1, min(_MAX_EMOTICON_COLUMNS, (width + spacing) // (_EMOTICON_CELL_SIZE + spacing)))
        if columns != self._columns:
            self._columns = columns
            self._set_grid_height()
            self._arrange_buttons()
        self.adjustSize()
        super().open_at(button)
