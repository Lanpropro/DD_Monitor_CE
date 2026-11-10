"""Sidebar thumbnail implementation; shared sidebar state stays with its owner."""
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QWidget
from .avatar_widgets import Avatar
from .corner_geometry import continuous_path
from .player import TilePlayer
from .widget_support import PORTRAIT_LIST_HEIGHT, _ignore_mouse, _repolish


class NavThumb(QFrame):
    """关注列表的封面卡片。

    展开时封面铺满条目，头像、主播名、标题和状态叠在上面；收起时只留头像。
    鼠标停够时间后直接在卡片里播放静音预览，移开就回到封面。
    """

    WIDTH, HEIGHT = 176, 116        # 展开后约 206x116，完整保持 16:9 预览比例
    LIST_HEIGHT = 48                # 简洁列表中，预览仍在这一行里播放
    COMPACT_SIZE = 32               # 收起成窄条时缩成正方
    RADIUS = 6
    AVATAR_SIZE = 28                # 展开卡片上的圆形主播头像
    PORTRAIT_AVATAR_SIZE = 48

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavThumb")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumSize(0, self.HEIGHT)
        self.setMaximumSize(16777215, self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._size = (self.WIDTH, self.HEIGHT)
        self._compact = False
        self._card_mode = True
        self._portrait_strip = False
        self._player: TilePlayer | None = None
        self._overlay_widgets: tuple[QWidget, QWidget, QWidget, QWidget] | None = None

        self.cover = QLabel(self)
        self.cover.setObjectName("NavThumbCover")
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setText("")
        self.cover.setGeometry(0, 0, self.WIDTH, self.HEIGHT)
        _ignore_mouse(self.cover)

        self.video = QFrame(self)
        self.video.setObjectName("NavThumbVideo")
        self.video.setAttribute(Qt.WA_StyledBackground, True)
        self.video.setGeometry(0, 0, self.WIDTH, self.HEIGHT)
        self.video.setVisible(False)

        self.hint = QLabel(self)
        self.hint.setObjectName("NavThumbHint")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setGeometry(0, 0, self.WIDTH, self.HEIGHT)
        self.hint.setVisible(False)
        _ignore_mouse(self.hint)

        # 头像挂在整行上，收起时仍能和底部账号头像保持同一条中线。
        self.face = Avatar("", 0, self.AVATAR_SIZE,
                           parent=parent if parent is not None else self)
        self.face.setObjectName("NavThumbFace")
        self._place_face()
        self.face.setVisible(False)
        self._cover_dirty = False
        self._cover_hold = False         # 布局切换期间挂起封面重裁，见 set_cover_hold()
        self._cover_source: QPixmap | None = None
        self._banner_source: QPixmap | None = None
        self._compact_background = True
        self._face_source: QPixmap | None = None

    # ---- 外观 ----
    def set_overlay_widgets(self, name: QWidget, title: QWidget, badge: QWidget,
                            platform: QWidget) -> None:
        self._overlay_widgets = (name, title, badge, platform)
        for widget in self._overlay_widgets:
            widget.setParent(self.face.parentWidget() if widget is platform else self)
            widget.raise_()
        self.face.raise_()
        platform.raise_()
        self._layout_overlay()

    def _layout_overlay(self) -> None:
        if self._overlay_widgets is None:
            return
        name, title, badge, platform = self._overlay_widgets
        card = self.parentWidget()
        if hasattr(card, '_layout_selection_marker'):
            card._layout_selection_marker()
        compact = self._compact_thumb()
        platform.setVisible(not self.video.isVisible() and
                            platform.property("showPlatform") is not False)
        icon_size = QSize(14, 14) if compact else QSize(24, 22)
        if platform.size() != icon_size:
            platform.setFixedSize(icon_size)
            platform.setPixmap(platform.icon.pixmap(12 if compact else 20, 12 if compact else 20))
        if compact:
            platform.move(self.face.pos() + QPoint(0, max(0, self.face.height() - platform.height())))
            platform.setVisible(platform.property("showPlatform") is not False)
            platform.raise_()
            return
        width, height = self._size
        platform_pos = QPoint(8 if self._card_mode and not self._portrait_strip else
                              max(4, width - platform.width() - 8),
                              height - 24 if self._card_mode and not self._portrait_strip else 4)
        if getattr(card, 'select_mode', False) and (not self._card_mode or self._portrait_strip):
            platform_pos.setX(max(4, platform_pos.x() - 28))
        platform.move(self.mapTo(platform.parentWidget(), platform_pos))
        if self._portrait_strip:
            name.setGeometry(4, 67, max(0, width - 8), 20)
            name.setAlignment(Qt.AlignCenter)
            title.setGeometry(4, 89, max(0, width - 8), 18)
            title.setAlignment(Qt.AlignCenter)
            badge.hide()
            name.raise_()
            title.raise_()
            platform.raise_()
            return
        name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        text_left = 48 if self._card_mode else 44
        right = 8
        name_right = right + (28 if getattr(card, 'select_mode', False) else 0)
        name_y = 7 if self._card_mode else 3
        second_y = 29 if self._card_mode else 25
        badge_y = (height - 24) if self._card_mode else (second_y + 1)
        name.setGeometry(text_left, name_y,
                         max(0, width - text_left - name_right -
                             (platform.width() + 6 if not self._card_mode and
                              platform.property("showPlatform") is not False else 0)), 20)
        badge.adjustSize()
        badge_width = badge.width()
        badge.move(max(text_left, width - badge_width - right), badge_y)
        title_width = (width - text_left - right if self._card_mode
                       else max(0, badge.x() - text_left - 6))
        title.setGeometry(text_left, second_y, max(0, title_width), 18)
        for widget in self._overlay_widgets:
            widget.raise_()

    def set_cover(self, pixmap) -> None:
        if pixmap is None or pixmap.isNull():
            return
        self.cover.setText("")
        self._cover_source = pixmap
        self._render_cover()

    def set_banner(self, pixmap) -> None:
        self._banner_source = None if pixmap is None or pixmap.isNull() else pixmap
        if not self._card_mode:
            self._render_cover()

    def set_compact_background(self, enabled: bool) -> None:
        self._compact_background = bool(enabled)
        self._render_cover()

    def set_face(self, pixmap) -> None:
        if pixmap is None or pixmap.isNull():
            return
        self._face_source = pixmap
        self._render_face()

    def face_pixmap(self) -> QPixmap | None:
        """已经下载好的主播头像（顶部横栏的头像排要用同一张）。"""
        return self._face_source

    def _avatar_size(self) -> int:
        return (self.COMPACT_SIZE if self._compact_thumb() else
                self.PORTRAIT_AVATAR_SIZE if self._portrait_strip else self.AVATAR_SIZE)

    def _face_letter(self) -> str:
        """还没拿到头像时顶上去的那个字：主播名首字，取不到就是问号。"""
        room = getattr(self.parentWidget(), "room", None) or {}
        name = str(room.get("uname") or "").strip()
        return name[0] if name else "?"

    def _render_face(self) -> None:
        """头像的尺寸、位置、可见性**全在这里算**。

        以前这三件事散在三处：这里末尾写「视频没在播就露脸」、`resizeEvent` 之后的
        `_sync_geometry` 里写「有 pixmap 才露脸」、初始化时写死 `False` ——
        谁最后跑谁说了算，同一条目会随着布局/尺寸变化在「露脸」和「不露」之间跳。
        收起的关注栏**只有头像这一样东西**（封面本来就不显示），一旦走了后一条，
        整个条目就空掉，头像还没下到的那段时间尤其明显。

        另外：拿不到头像时不再直接 return，而是用主播名首字顶着 —— 否则连尺寸和
        位置都不更新，收起后条目的留白也全是错的。
        """
        size = self._avatar_size()
        pixmap = self._face_source
        if pixmap is not None and not pixmap.isNull():
            # 尺寸和图片一次更新，圆形裁切与圆环只绘制一遍。
            self.face.set_pixmap_image(pixmap, size=size, ring=True)
        else:
            # 还没下到头像：用名字首字顶着，别让条目空着
            self.face.set_size(size)
            self.face.setText(self._face_letter())
            self.face.set_color(None)
        self._place_face()
        # 紧凑条目只有头像可认，所以一定要露；卡片模式封面才是主体，头像还没下到
        # 就先别占那一块。视频预览占着整块时两者都让位。
        self.face.setVisible(not self.video.isVisible() and
                             (self._compact_thumb() or pixmap is not None))

    def _face_local_rect(self) -> QRect:
        """展开时头像叠在封面左侧；收起时在 32px 方框中居中。"""
        width, height = self._size
        avatar_size = (self.COMPACT_SIZE if self._compact_thumb() else
                       self.PORTRAIT_AVATAR_SIZE if self._portrait_strip else self.AVATAR_SIZE)
        if self._compact_thumb():
            return QRect((width - avatar_size) // 2,
                         (height - avatar_size) // 2,
                         avatar_size, avatar_size)
        if self._portrait_strip:
            return QRect((width - avatar_size) // 2, 8, avatar_size, avatar_size)
        return QRect(10 if self._card_mode else 4,
                     10,
                     avatar_size, avatar_size)

    def _place_face(self) -> None:
        """把头像摆到它该在的位置（挂在自己身上就按相对坐标，挂在行上就加上偏移）。"""
        rect = self._face_local_rect()
        if self.face.parentWidget() is self:
            self.face.move(rect.topLeft())
        else:
            self.face.move(self.pos() + rect.topLeft())

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._place_face()               # 缩略图被布局挪动时，头像要跟着走
        if self._overlay_widgets is not None:
            platform = self._overlay_widgets[3]
            platform.move(platform.pos() + event.pos() - event.oldPos())

    def refresh_cover(self) -> None:
        """按收起/展开后的最终尺寸重裁封面。"""
        self._render_cover()

    def set_cover_hold(self, hold: bool) -> None:
        """切换布局时暂缓封面重裁，最终尺寸确定后只补可见条目。"""
        hold = bool(hold)
        if hold == self._cover_hold:
            return
        self._cover_hold = hold
        self._cover_dirty = True
        try:
            self.cover.setScaledContents(hold)
        except RuntimeError:                    # 控件已经被回收
            return
        # 解除挂起时**不在这里**重绘：由调用方决定哪些条目值得立刻补
        # （见 Sidebar._finish_collapse）—— 36 条一起补会把收尾那一下又拖垮。
        # 没补到的条目滚进视野时由 paintEvent 补裁，不依赖滚动时出现 resizeEvent。

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        size = (self.width(), self.height())
        if size != self._size:
            was_compact = self._compact_thumb()
            self._size = size
            self.cover.setGeometry(self.rect())
            self.video.setGeometry(self.rect())
            self.hint.setGeometry(self.rect())
            self._render_cover()
            if was_compact != self._compact_thumb():
                self._render_face()
        self._place_face()
        self._layout_overlay()

    def paintEvent(self, event) -> None:
        if self._cover_dirty and not self._cover_hold:
            self._render_cover()
        super().paintEvent(event)

    def _render_cover(self) -> None:
        """把封面裁成圆角，并加深色渐变供叠加文字阅读。"""
        if self._cover_hold:
            return                       # 布局切换期间不重裁，见 set_cover_hold()
        if self._compact_thumb():
            return                       # 收起后封面隐藏，展开时再裁切即可
        source = getattr(self, "_cover_source", None)
        if not self._card_mode and self._banner_source is not None:
            source = self._banner_source
        if not self._card_mode and not self._compact_background:
            source = None
        has_background = source is not None and not source.isNull()
        if self._overlay_widgets is not None:
            for label in self._overlay_widgets[:2]:
                if label.property('roomBackdrop') != has_background:
                    label.setProperty('roomBackdrop', has_background)
                    _repolish(label)
        self.cover.setVisible(has_background and not self._compact)
        if source is None or source.isNull():
            return
        if self.visibleRegion().isEmpty():
            self._cover_dirty = True
            return
        self._cover_dirty = False
        width, height = self._size
        from .cover_focus import source_rect
        crop = source_rect(source, width, height,
                           focus=self._card_mode or self._banner_source is None)
        canvas = QPixmap(width, height)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        path = QPainterPath()
        path.addPath(continuous_path(QRectF(0, 0, width, height), self.RADIUS))
        painter.setClipPath(path)
        painter.drawPixmap(QRectF(0, 0, width, height), source, crop)
        if not self._compact_thumb():
            shade = QLinearGradient(0, 0, width, 0)
            shade.setColorAt(0.0, QColor(7, 9, 13, 205))
            shade.setColorAt(0.62, QColor(7, 9, 13, 130))
            shade.setColorAt(1.0, QColor(7, 9, 13, 92))
            painter.fillRect(QRectF(0, 0, width, height), shade)
            header = QLinearGradient(0, 0, 0, height * 0.68)
            header.setColorAt(0.0, QColor(7, 9, 13, 190))
            header.setColorAt(1.0, QColor(7, 9, 13, 0))
            painter.fillRect(QRectF(0, 0, width, height), header)
        painter.end()
        self.cover.setPixmap(canvas)

    def set_hint(self, text: str) -> None:
        """封面上的小提示（连接中…/取流失败），播放起来就藏掉。"""
        self.hint.setText(text or "")
        if text and not self.video.isVisible() and not self._compact_thumb():
            self.hint.setGeometry(self._preview_rect())
        else:
            self.hint.setGeometry(self.rect())
        self.hint.setVisible(bool(text) and not self.video.isVisible())

    def _compact_thumb(self) -> bool:
        return self._compact

    def _preview_rect(self) -> QRect:
        """预览画面占据的矩形。

        卡片模式（封面铺满条目）和竖屏条都用整块。紧凑的长条卡片**不放预览**
        （只有 48px 高，画面会被压扁；预览改在卡片旁边弹浮层），所以这里也不用再
        算「右侧 1/3」那块小窗了。
        """
        return self.rect()

    def sync_preview_position(self) -> None:
        # Silent previews keep their ancestors alien. Scrolling an alien parent
        # does not move this native surface; map from the thumbnail, not the
        # surface's stale QWindow position. Keep the existing HWND and mpv core.
        window = self.video.windowHandle()
        if self.video.isVisible() and window is not None:
            ancestor = self.video.nativeParentWidget()
            window.setPosition(self.mapTo(ancestor, self.video.pos()))

    def _set_overlay_visible(self, visible: bool) -> None:
        if self._overlay_widgets is None:
            return
        for widget in self._overlay_widgets:
            widget.setVisible(bool(visible) and (not self._compact or widget is self._overlay_widgets[3])
                              and (not self._portrait_strip or widget is not self._overlay_widgets[2])
                              and (widget is not self._overlay_widgets[3] or
                                   widget.property("showPlatform") is not False))

    def set_portrait_strip(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._portrait_strip:
            return
        if self._player is not None:
            self.stop()
        self._portrait_strip = enabled
        if not self._compact:
            height = (PORTRAIT_LIST_HEIGHT - 12 if enabled else
                      self.HEIGHT if self._card_mode else self.LIST_HEIGHT)
            self.setFixedHeight(height)
        self._render_face()
        self._place_face()
        self._layout_overlay()
        self._set_overlay_visible(True)

    def set_card_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._card_mode:
            return
        if self._player is not None:
            self.stop()
        self._card_mode = enabled
        if not self._compact:
            height = (PORTRAIT_LIST_HEIGHT - 12 if self._portrait_strip else
                      self.HEIGHT if enabled else self.LIST_HEIGHT)
            self.setMinimumSize(0, height)
            self.setMaximumSize(16777215, height)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cover.setVisible(not self._compact)
        self._render_face()
        self._render_cover()
        self._place_face()
        self._layout_overlay()

    def set_thumb_size(self, compact: bool) -> None:
        width = self.COMPACT_SIZE if compact else self.WIDTH
        expanded_height = (PORTRAIT_LIST_HEIGHT - 12 if self._portrait_strip else
                           self.HEIGHT if self._card_mode else self.LIST_HEIGHT)
        height = self.COMPACT_SIZE if compact else expanded_height
        if compact == self._compact_thumb():
            return
        if compact and self._player is not None:
            self.stop()
        self._compact = compact
        if compact:
            self.setFixedSize(width, height)
        else:
            self.setMinimumSize(0, height)
            self.setMaximumSize(16777215, height)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._size = (self.width(), self.height())
        self.cover.setGeometry(self.rect())
        preview_rect = self._preview_rect() if self.video.isVisible() else self.rect()
        self.video.setGeometry(preview_rect)
        self.hint.setGeometry(preview_rect if self.hint.isVisible() else self.rect())
        self.cover.setVisible(not compact)
        self._render_face()          # 可见性也归它管（见 _render_face）
        self._render_cover()
        self._layout_overlay()

    # ---- 预览播放 ----
    def _ensure_player(self) -> TilePlayer:
        """复用卡片的静音播放器，禁用音轨。"""
        if self._player is None:
            self._player = TilePlayer(self.video, self, silent=True)
            self._player.freeze_watch = False        # 缩略图不用卡死检测
            self._player.stateChanged.connect(self._on_player_state)
        return self._player

    def prepare_preview(self) -> None:
        """在取流期间准备播放器，封面继续显示。"""
        if self._card_mode and not self._compact_thumb():
            self._ensure_player().bind()

    def play(self, url: str, profile: str = "web", options=None, *, headers=None) -> None:
        """在这个缩略图里放预览（静音、低画质）。

        ``options`` 由预览那边给（见 ddm/preview.py 的 PREVIEW_MEDIA_OPTIONS）。
        """
        if self._compact_thumb():
            return                         # 收起的关注栏固定显示主播头像
        if not self._card_mode:
            # 紧凑（长条）卡片里**不塞预览**：这行只有 LIST_HEIGHT(48) 高，塞进去
            # 只会得到一块压扁的小画面 —— 用户要求把卡片里那个小预览窗删掉。
            # 紧凑布局的预览改成在卡片旁边弹浮层，见 ddm/preview.py 的 _needs_popup()。
            return
        player = self._ensure_player()
        self.video.setGeometry(self._preview_rect())
        self.hint.setGeometry(self._preview_rect())
        self.video.setVisible(True)
        self.video.raise_()
        # 大卡片预览时让画面完全干净；简洁列表的预览只占右侧三分之一，左侧信息保留。
        self._set_overlay_visible(not self._card_mode and not self._portrait_strip)
        self.face.setVisible(not self._card_mode and not self._portrait_strip)
        self.hint.setVisible(False)
        player.set_muted(True)                       # 预览永远静音
        player.set_volume(0)
        player.play(url, profile, headers=headers, options=options)

    def stop(self) -> None:
        """收掉预览，回到封面（播放器留着复用，下回悬停直接 play）。"""
        if self._player is None and self.video.isHidden() and self.hint.isHidden():
            return
        if self._player is not None:
            self._player.stop()
        self.video.setVisible(False)
        self.hint.setVisible(False)
        self.video.setGeometry(self.rect())
        self.hint.setGeometry(self.rect())
        self.cover.setVisible(not self._compact_thumb() and
                              (self._card_mode or self._compact_background))
        self.face.setVisible(bool(self.face.pixmap()))
        self._set_overlay_visible(True)

    def release_player(self) -> None:
        """真正放掉预览播放器：只在关窗时用，平时留着复用。"""
        if self._player is None:
            return
        self._player.release()
        self._player = None

    def _on_player_state(self, state: str) -> None:
        if state == "playing":
            self.hint.setVisible(False)
        elif state == "buffering":
            self.set_hint("缓冲中…")
        elif state == "error":
            self.video.setVisible(False)
            self._set_overlay_visible(True)
            self.face.setVisible(bool(self.face.pixmap()))
            self.set_hint("播放失败")
