"""Chat document formatting, bounded history and emoticon resources; panel owns document and loaders."""
from html import escape
from itertools import islice

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QDrag, QFont, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPalette,
    QPen, QPixmap, QTextBlockFormat, QTextCursor, QTextDocument, QTextOption
)
from . import motion, theme
from .danmaku_content import content_html, content_runs
from .danmaku_format import (_brightness, _medal_chip, _escape)


class DanmakuDocument:
    EMOTICON_LINE_HEIGHT = 120
    EMOTICON_BLOCKS_PER_UPDATE = 16

    def __init__(self, host):
        self.host = host
        self._medal_style = None
        self._loaded_emoticons = set()
        self._emoticon_blocks = {}
        self._emoticon_refresh = QTimer(host)
        self._emoticon_refresh.setSingleShot(True)
        self._emoticon_refresh.setInterval(16)
        self._emoticon_refresh.timeout.connect(self._refresh_emoticon_blocks)

    def add_message(self, uname: str, text: str, color: str = "#00a1d6") -> None:
        """直接给文本的简写（预览、自检用）。"""
        host = self.host
        host.add_event({"kind": "danmaku", "uname": uname, "text": text, "color": color})

    def add_event(self, event: dict) -> None:
        self.add_events((event,))

    def event_entry(self, event: dict) -> dict:
        host = self.host
        return {
            "kind": event.get('kind') or 'danmaku',
            "uid": event.get('uid') or event.get('user_id') or event.get('author_id') or '',
            "platform": event.get('platform') or '',
            "room_id": event.get('room_id') or '',
            "uname": event.get("uname") or "",
            "text": event.get("text") or "",
            "color": event.get("color") or host.KIND_COLORS.get(
                event.get("kind") or "danmaku", theme.ACCENT),
            "medal": event.get("medal") or {},
            "emoticon": event.get("emoticon") or "",
            "dm_type": event.get("dm_type", 0),
            "emoticon_unique": event.get("emoticon_unique") or "",
            "emoticons": event.get("emoticons") or {},
            "self_sent": bool(event.get("self_sent")),
        }
    def add_events(self, events) -> None:
        host = self.host
        timeline = getattr(host, 'match_gui_timeline', None)
        prepared = timeline.begin() if timeline is not None else None
        entries, fragments = [], []
        for event in events:
            entry = host._event_entry(event)
            urls = frozenset(url for _, url in content_runs(entry) if url)
            entry['_emoticon_urls'] = urls
            for url in urls:
                host._ensure_emoticon(url)
            entries.append(entry)
            fragments.append(host._block_html(entry))
        if not entries:
            return
        if timeline is not None:
            timeline.end('chat.sidebar_prepare', prepared, len(entries))
        previous = len(host._blocks)
        removed = max(0, previous + len(entries) - host.max_blocks)
        scroll = timeline.begin() if timeline is not None else None
        scroll_state = host._scroll_state(min(removed, previous))
        if timeline is not None:
            timeline.end('chat.sidebar_scroll_state', scroll)
        if previous and removed >= previous:
            scroll_state = (scroll_state[0], 0, scroll_state[2])
        host._blocks.extend(entries)
        if removed:
            del host._blocks[:removed]
        markup = ''.join(fragments[-host.max_blocks:])
        insertion = timeline.begin() if timeline is not None else None
        if host._has_content:
            host.body.append(markup)
        else:
            host.body.setHtml(markup)
            for key, image in host._images.items():
                host._register_image(key, image)
            host._has_content = True
        if timeline is not None:
            timeline.end('chat.sidebar_insert', insertion, len(entries))
            scroll = timeline.begin()
        host._received += len(entries)
        host._refresh_count()
        host._restore_scroll_state(scroll_state)
        if timeline is not None:
            timeline.end('chat.sidebar_scroll_restore', scroll)

    def apply_style(self, font_family: str, font_size: int) -> None:
        """设置里的字体和字号（字号也能在底部滑块上实时拖）。"""
        host = self.host
        host._font_family = font_family or theme.danmaku_font_family()
        host._base_size = max(host.MIN_FONT_SIZE,
                              min(host.MAX_FONT_SIZE, int(font_size or host.BASE_FONT_SIZE)))
        font = theme.danmaku_font(host._font_family, host._base_size)
        host.body.setFont(font)          # 具体字号在 HTML 里，这里给个底
        host.font_slider.blockSignals(True)
        host.font_slider.setValue(host._base_size)
        host.font_slider.blockSignals(False)
        host.font_value.setText(str(host._base_size))
        if host._blocks:
            host._render_all()

    def font_size(self) -> int:
        host = self.host
        return host._base_size

    def set_max_blocks(self, count: int) -> None:
        """最多留多少条弹幕：超了就从最早的那条开始丢。"""
        host = self.host
        try:
            value = int(count)
        except (TypeError, ValueError):
            value = host.MAX_BLOCKS
        host.max_blocks = max(host.MIN_BLOCKS, value)
        scroll_state = host._scroll_state(max(0, len(host._blocks) - host.max_blocks))
        if len(host._blocks) > host.max_blocks:
            host._blocks = host._blocks[-host.max_blocks:]
        host.body.document().setMaximumBlockCount(host.max_blocks)
        host._restore_scroll_state(scroll_state)

    def on_font_slider(self, value: int) -> None:
        """面板上拖字号：立刻重排，并通知外面存进配置。"""
        host = self.host
        host._base_size = int(value)
        host.font_value.setText(str(host._base_size))
        if host._blocks:
            host._render_all()
        host.fontSizeChanged.emit(host._base_size)

    def block_html(self, entry: dict) -> str:
        host = self.host
        size = host._font_size()
        color = "#202630" if theme.is_light() else "#e6e9ee"
        name = (f'<span style="color:{entry["color"]}">{_escape(entry["uname"])}</span>')
        mark = (f'<span style="color:{theme.PINK};font-weight:700">▍</span> '
                if entry.get("self_sent") else "")
        body = host._body_html(entry)
        line_height = self.EMOTICON_LINE_HEIGHT if '<img ' in body else 150
        return (f'<div style="font-size:{size}px;line-height:{line_height}%;margin:0 0 4px 0">'
                f'{mark}{host._medal_html(entry["medal"])}{name}'
                f'<span style="color:{color}">：{body}</span></div>')

    def body_html(self, entry: dict) -> str:
        host = self.host
        height = host.EMOTICON_HEIGHT + 2 * (host._font_size() - host.BASE_FONT_SIZE)
        return content_html(content_runs(entry), host._images, height, fit_line=True)

    def medal_html(self, medal: dict) -> str:
        """粉丝牌使用同尺寸圆角底图，缺少颜色时使用默认色。"""
        host = self.host
        name = str(medal.get("name") or "")
        if not name:
            return ""
        level = str(medal.get("level") or "")
        color = str(medal.get("color") or "#c792ea")
        size = host._font_size()
        dpr = host.body.viewport().devicePixelRatioF()
        family = host._font_family
        style = size, family, dpr
        if style != self._medal_style:
            self._medal_style = style
            for key in tuple(host._images):
                if key.startswith('medal:'):
                    del host._images[key]
        key = f"medal:{name}|{level}|{color}"
        if key not in host._images:
            host._images[key] = _medal_chip(name, level, color, size, font_family=family, dpr=dpr)
        chip = host._images[key]
        host._register_image(key, chip)          # 不注册的话新到的弹幕会画成白块
        logical = chip.deviceIndependentSize()
        return (f'<img src="{escape(key, quote=True)}" width="{round(logical.width())}" '
                f'height="{round(logical.height())}" style="vertical-align:middle">&#160;')

    def refresh_medal_scale(self) -> None:
        if self._medal_style is not None and self.host._blocks:
            self.host._render_all()

    def register_image(self, key: str, image) -> None:
        """把图片挂到文本文档上，这样富文本里的 <img> 才画得出来。"""
        host = self.host
        host.body.document().addResource(QTextDocument.ImageResource, QUrl(key), image)

    def render_all(self) -> None:
        """主题、字体或全局样式变化时整体重排。"""
        host = self.host
        self.clear_emoticon_updates()
        scroll_state = host._scroll_state()
        html = "".join(host._block_html(entry) for entry in host._blocks)
        host.body.setHtml(html or "")
        for url, image in host._images.items():       # 图片按 url 注册成文档资源
            host._register_image(url, image)
        host._has_content = bool(host._blocks)
        host._restore_scroll_state(scroll_state)

    def ensure_emoticon(self, url: str, *, loader_type, thread_running) -> None:
        host = self.host
        AvatarLoader = loader_type
        _is_running = thread_running
        if url in host._images or url in host._loading_emoticons:
            return
        host._loading_emoticons.add(url)
        loader = AvatarLoader({url: url}, host, subdir="emoticons", diagnostic_source="panel-emoticon")
        loader.loaded.connect(host._on_emoticon_loaded)
        loader.finished.connect(lambda: host._loading_emoticons.discard(url))
        loader.finished.connect(loader.deleteLater)
        host._emoticon_loaders = [item for item in host._emoticon_loaders
                                  if _is_running(item)]
        host._emoticon_loaders.append(loader)
        loader.start()

    def on_emoticon_loaded(self, url: str, pixmap) -> None:
        host = self.host
        host._loading_emoticons.discard(url)
        image = pixmap.toImage()
        if image.isNull():
            return
        host._images[url] = image
        host._register_image(url, image)
        if host._blocks:
            self._loaded_emoticons.add(url)
            if not self._emoticon_refresh.isActive():
                self._emoticon_refresh.start()

    def clear_emoticon_updates(self) -> None:
        self._emoticon_refresh.stop()
        self._loaded_emoticons.clear()
        self._emoticon_blocks.clear()

    def _refresh_emoticon_blocks(self) -> None:
        host = self.host
        document = host.body.document()
        if self._loaded_emoticons:
            for index, entry in enumerate(host._blocks):
                if not self._loaded_emoticons.isdisjoint(entry.get('_emoticon_urls', ())):
                    self._emoticon_blocks[id(entry)] = (entry, document.findBlockByNumber(index))
            self._loaded_emoticons.clear()
        if not self._emoticon_blocks:
            return
        state = host._scroll_state()
        anchor = host.body.cursorForPosition(QPoint()).block()
        layout = document.documentLayout()
        previous_top = layout.blockBoundingRect(anchor).top() if not state[0] and anchor.isValid() else None
        transaction = QTextCursor(document)
        transaction.beginEditBlock()
        try:
            for key in tuple(islice(self._emoticon_blocks, self.EMOTICON_BLOCKS_PER_UPDATE)):
                entry, block = self._emoticon_blocks.pop(key)
                if not block.isValid():
                    continue
                index = block.blockNumber()
                if not 0 <= index < len(host._blocks) or host._blocks[index] is not entry:
                    continue
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                cursor.insertHtml(host._block_html(entry))
                style = cursor.blockFormat()
                style.setLineHeight(self.EMOTICON_LINE_HEIGHT, QTextBlockFormat.ProportionalHeight.value)
                cursor.setBlockFormat(style)
        finally:
            transaction.endEditBlock()
        if previous_top is not None and anchor.isValid():
            delta = round(layout.blockBoundingRect(anchor).top() - previous_top)
            state = (state[0], max(0, state[1] + delta), state[2])
        host._restore_scroll_state(state)
        if self._emoticon_blocks:
            self._emoticon_refresh.start()

    def clear(self) -> None:
        host = self.host
        host.set_placeholder("等待主画面的直播间…")

    def set_sample(self, messages: list[tuple[str, str, str]]) -> None:
        """预览用：塞几条示例弹幕，看看排版效果。"""
        host = self.host
        for uname, text, color in messages:
            host.add_message(uname, text, color)
