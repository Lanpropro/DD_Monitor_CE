"""video danmaku raster; VideoDanmaku retains comment state, timers and Qt ownership."""
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from .danmaku_raster import CommentRaster, CommentRasterJob
from .images import AvatarLoader


class VideoDanmakuRaster:
    def __init__(self, host):
        self.host = host

    def ensure_emoticon(self, url: str) -> None:
        host = self.host
        if url in host._images or url in host._emoticon_loaders or len(host._emoticon_loaders) >= 16:
            return
        # The app owns downloads so removing a tile cannot destroy a running thread.
        app = QApplication.instance()
        loader = AvatarLoader({url: url}, app, subdir="emoticons")
        host._emoticon_loaders[url] = loader
        loader.loaded.connect(host._on_emoticon_loaded)
        loader.finished.connect(lambda: host._emoticon_loaders.pop(url, None))
        loader.finished.connect(loader.deleteLater)
        app.aboutToQuit.connect(loader.wait)
        loader.start()

    def on_emoticon_loaded(self, url: str, pixmap) -> None:
        host = self.host
        if pixmap.isNull():
            return
        if len(host._images) >= 128 and url not in host._images:
            host._images.pop(next(iter(host._images)))
        host._images[url] = pixmap.toImage()
        if any(url == image_url for comment in host.comments for _, image_url in comment.runs):
            host._queue_comment_raster()

    def comment_renderer(self):
        host = self.host
        return CommentRaster(host._font(), host.outline_width(),
            host.devicePixelRatioF() * host.TEXT_SAMPLE_SCALE,
            max(128, host.width() * 2), host._images)

    def render_content(self, text, color, runs, self_sent=False) -> QPixmap:
        host = self.host
        if not any(url in host._images for _, url in runs if url):
            return host._render_text(text, color, self_sent)
        return QPixmap.fromImage(host._comment_renderer()._render_content(text, color, runs, self_sent))

    def render_text(self, text, color, self_sent=False) -> QPixmap:
        host = self.host
        return QPixmap.fromImage(host._comment_renderer()._render_text(text, color, self_sent))

    def queue_comment_raster(self):
        host = self.host
        if host._comment_raster_job is not None:
            return  # The active batch will request the latest geometry when it returns.
        renderer = host._comment_renderer()
        cached, rows = [], []
        for comment in host.comments:
            key = renderer.key(comment.text, comment.color, comment.runs, comment.self_sent)
            if key == comment.raster_key:
                continue
            if key in comment.rasters:
                cached.append((id(comment), key, comment.rasters[key]))
            else:
                rows.append((id(comment), key, comment.text, QColor(comment.color),
                             tuple(comment.runs), comment.self_sent))
        for identifier, (text, color, runs, self_sent, _event) in host._pending_comments.items():
            rows.append((identifier, None, text, QColor(color), tuple(runs), self_sent))
        host._apply_comment_rasters(cached)
        if rows:
            job = host._comment_raster_job = CommentRasterJob(renderer, rows)
            job.signals.finished.connect(host._finish_comment_raster, Qt.QueuedConnection)
            QThreadPool.globalInstance().start(job)

    def finish_comment_raster(self, images):
        host = self.host
        job = host._comment_raster_job
        host._comment_raster_job = None
        if images is None:
            for identifier, *_ in job.rows:
                host._pending_comments.pop(identifier, None)
            return
        host._apply_comment_rasters(images)
        host._queue_comment_raster()

    def apply_comment_rasters(self, images):
        host = self.host
        if not images:
            return
        renderer = host._comment_renderer()
        images = {identifier: (key, image) for identifier, key, image in images}
        if host._quick_animated() and host.timer.isActive():
            host._tick()
        for comment in host.comments:
            result = images.get(id(comment))
            if result is None or result[0] == comment.raster_key:
                continue
            key, image = result
            if key != renderer.key(comment.text, comment.color, comment.runs, comment.self_sent):
                continue  # Ignore an old size, changed settings or newly loaded emoticons.
            distance = host.width() + comment.image.width() / comment.image.devicePixelRatioF()
            progress = (host.width() - comment.x) / max(1, distance)
            comment.image = QPixmap.fromImage(image)
            comment.raster_key = key
            if len(comment.rasters) == 2 and key not in comment.rasters:
                comment.rasters.pop(next(iter(comment.rasters)))
            comment.rasters[key] = image
            width = comment.image.width() / comment.image.devicePixelRatioF()
            comment.x = host.width() - progress * (host.width() + width)
            comment.speed = (host.width() + width) / 8 * int(host.settings.get('video_danmaku_speed') or 100) / 100
            if host._quick_layer is not None and host._quick_group is not None:
                host._quick_layer.update(comment.render_id, image, comment.x,
                    comment.lane * host.lane_height(), width,
                    comment.image.height() / comment.image.devicePixelRatioF(), comment.speed)
        host._prune_lanes()
        # Results are admitted in arrival order, only with the current font/images.
        # Cleared tokens are absent, so late jobs cannot revive old room messages.
        for identifier, pending in list(host._pending_comments.items()):
            result = images.get(identifier)
            if result is None:
                break
            text, color, runs, self_sent, event = pending
            key, image = result
            if key != renderer.key(text, color, runs, self_sent):
                break
            host._pending_comments.pop(identifier)
            host._admit_comment(image, key, text, color, runs, self_sent, event)
        if host._quick_layer is None:
            host.update()

    def resize_comments(self, *, redraw=True) -> None:
        host = self.host
        if redraw:
            host._comment_resize_timer.stop()
        if host._quick_animated() and host.timer.isActive():
            host._tick()
        for comment in host.comments:
            old_distance = host._comment_width + comment.image.width() / comment.image.devicePixelRatioF()
            progress = (host._comment_width - comment.x) / max(1, old_distance)
            if redraw:
                comment.image = host._render_content(comment.text, comment.color, comment.runs,
                                                     comment.self_sent)
                comment.raster_key = host._comment_renderer().key(
                    comment.text, comment.color, comment.runs, comment.self_sent)
                comment.rasters = {comment.raster_key: comment.image.toImage()}
            distance = host.width() + comment.image.width() / comment.image.devicePixelRatioF()
            comment.x = host.width() - progress * distance
            comment.speed = distance / 8 * int(host.settings.get("video_danmaku_speed") or 100) / 100
        host._comment_width = host.width()
        host._prune_lanes()
        if host._quick_layer is not None and host._quick_group is not None:
            for comment in host.comments:
                if redraw:
                    host._quick_layer.update(
                        comment.render_id, comment.image.toImage(), comment.x,
                        comment.lane * host.lane_height(),
                        comment.image.width() / comment.image.devicePixelRatioF(),
                        comment.image.height() / comment.image.devicePixelRatioF(), comment.speed)
                else:
                    host._quick_layer.move(comment.render_id, comment.x,
                        comment.lane * host.lane_height(), comment.speed)
        else:
            host.update()
