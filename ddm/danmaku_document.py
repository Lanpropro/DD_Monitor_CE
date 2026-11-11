"""Chat document formatting, bounded history and emoticon resources; panel owns document and loaders."""
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QDrag, QFont, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPalette,
    QPen, QPixmap, QTextDocument, QTextOption
)
from . import motion, theme
from .danmaku_content import content_html, content_runs
from .danmaku_format import (_brightness, _medal_chip, _escape)


class DanmakuDocument:
    def __init__(self, host):
        self.host = host

    def add_message(self, uname: str, text: str, color: str = "#00a1d6") -> None:
        """直接给文本的简写（预览、自检用）。"""
        host = self.host
        host.add_event({"kind": "danmaku", "uname": uname, "text": text, "color": color})

    def add_event(self, event: dict) -> None:
        """一条消息：带粉丝牌、表情（表情图下好之后会补上）。"""
        host = self.host
        entry = {
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
        host._received += 1
        host._refresh_count()
        for _, url in content_runs(entry):
            if url:
                host._ensure_emoticon(url)
        host._blocks.append(entry)
        removed = max(0, len(host._blocks) - host.max_blocks)
        scroll_state = host._scroll_state(removed)
        if removed:
            host._blocks = host._blocks[-host.max_blocks:]
        block = host._block_html(entry)
        if host._has_content:
            host.body.append(block)
        else:
            host.body.setHtml(block)              # 第一条：先把占位文字换掉
            host._has_content = True
        host._restore_scroll_state(scroll_state)

    def apply_style(self, font_family: str, font_size: int) -> None:
        """设置里的字体和字号（字号也能在底部滑块上实时拖）。"""
        host = self.host
        host._font_family = font_family or theme.danmaku_font_family()
        host._base_size = max(host.MIN_FONT_SIZE,
                              min(host.MAX_FONT_SIZE, int(font_size or host.BASE_FONT_SIZE)))
        font = QFont(host._font_family)
        font.setPixelSize(host._base_size)
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
        return (f'<div style="font-size:{size}px;line-height:150%;margin:0 0 4px 0">'
                f'{mark}{host._medal_html(entry["medal"])}{name}'
                f'<span style="color:{color}">：{host._body_html(entry)}</span></div>')

    def body_html(self, entry: dict) -> str:
        host = self.host
        height = max(host.EMOTICON_HEIGHT // 2, round(host._font_size() * 1.7))
        return content_html(content_runs(entry), host._images, height)

    def medal_html(self, medal: dict) -> str:
        """粉丝牌：有颜色就画成圆角小色块（图片），没有就退化成[名字等级]。"""
        host = self.host
        name = str(medal.get("name") or "")
        if not name:
            return ""
        level = str(medal.get("level") or "")
        color = str(medal.get("color") or "")
        if not color:
            return f'<span style="color:#c792ea">[{_escape(name)}{_escape(level)}]</span>&#160;'
        size = host._font_size()
        key = f"medal:{name}|{level}|{color}|{size}"
        if key not in host._images:
            host._images[key] = _medal_chip(name, level, color, size)
        chip = host._images[key]
        host._register_image(key, chip)          # 不注册的话新到的弹幕会画成白块
        return (f'<img src="{key}" width="{chip.width()}" height="{chip.height()}">&#160;')

    def register_image(self, key: str, image) -> None:
        """把图片挂到文本文档上，这样富文本里的 <img> 才画得出来。"""
        host = self.host
        host.body.document().addResource(QTextDocument.ImageResource, QUrl(key), image)

    def render_all(self) -> None:
        """整体重排（表情图下好、或者字体变化时用）。"""
        host = self.host
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
        loader = AvatarLoader({url: url}, host, subdir="emoticons")
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
        host._render_all()          # 之前显示成文字的那些，现在换成图

    def clear(self) -> None:
        host = self.host
        host.set_placeholder("等待主画面的直播间…")

    def set_sample(self, messages: list[tuple[str, str, str]]) -> None:
        """预览用：塞几条示例弹幕，看看排版效果。"""
        host = self.host
        for uname, text, color in messages:
            host.add_message(uname, text, color)
