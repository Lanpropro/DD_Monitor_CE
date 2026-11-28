"""Accept image drags and fetch their direct browser image URLs."""
from html.parser import HTMLParser
import re

from PySide6.QtCore import QByteArray, QFileInfo, QObject, QUrl, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


_MAX_DOWNLOAD = 20 * 1024 * 1024
_IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.jfif', '.bmp', '.webp', '.tif', '.tiff', '.gif')
CALENDAR_IMAGE_FILTER = '图片 (' + ' '.join('*' + suffix for suffix in _IMAGE_SUFFIXES) + ')'
_BILI_THUMBNAIL = re.compile(
    r'(/bfs/(?:new_dyn|album)/[^/@]+\.(?:png|jpe?g|webp|gif))@[0-9][^/]*\.(?:avif|webp|png|jpe?g)',
    re.IGNORECASE,
)


def _bili_calendar_urls(url):
    if (url.scheme() not in ('https', 'http') or url.userInfo()
            or not re.fullmatch(r'i[0-9]+\.hdslb\.com', url.host())):
        return ()
    match = _BILI_THUMBNAIL.fullmatch(url.path())
    if not match:
        return ()
    original = QUrl(url)
    original.setPath(match[1])
    preview = QUrl(original)
    preview.setPath(match[1] + '@2560w.webp')
    return preview, original


class _ImageSource(HTMLParser):
    def __init__(self):
        super().__init__()
        self.source = ''

    def handle_starttag(self, tag, attrs):
        if tag == 'img' and not self.source:
            attrs = dict(attrs)
            self.source = attrs.get('src') or attrs.get('data-src') or ''


def dropped_calendar_image(mime):
    urls = mime.urls()
    for url in urls:
        if (url.isLocalFile() and url.toLocalFile().lower().endswith(_IMAGE_SUFFIXES)
                and QFileInfo(url.toLocalFile()).isFile()):
            return url
    html_image = None
    if mime.hasHtml():
        parser = _ImageSource()
        parser.feed(mime.html())
        if parser.source:
            url = QUrl(parser.source)
            if url.isRelative() and url.host():
                url.setScheme('https')
            elif url.isRelative() and urls:
                url = urls[0].resolved(url)
            if url.isValid() and url.scheme() in ('https', 'http', 'data'):
                html_image = url
    # Chromium can also provide a bitmap of the cropped thumbnail.
    for url in ([html_image] if html_image is not None else []) + urls:
        if _bili_calendar_urls(url):
            return url
    if mime.hasImage():
        image = mime.imageData()
        if isinstance(image, QPixmap):
            image = image.toImage()
        if isinstance(image, QImage) and not image.isNull():
            return image
    if html_image is not None:
        return html_image
    for url in urls:
        if url.isValid() and url.scheme() in ('https', 'http', 'data'):
            return url
    if mime.hasText():
        url = QUrl(mime.text().strip(), QUrl.StrictMode)
        if url.isValid() and url.scheme() in ('https', 'http') and (
                url.path().lower().endswith(_IMAGE_SUFFIXES) or _bili_calendar_urls(url)):
            return url
    return None


class CalendarImageLoader(QObject):
    loaded = Signal(QImage)
    failed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.reply = None

    def load(self, source):
        self.cancel()
        if isinstance(source, QImage):
            self.loaded.emit(source)
        elif source.isLocalFile():
            reader = QImageReader(source.toLocalFile())
            reader.setAutoTransform(True)
            self._deliver(reader.read())
        elif source.scheme() == 'data':
            payload = bytes(source.toEncoded())
            header, _, data = payload.partition(b',')
            if header.startswith(b'data:image/') and header.endswith(b';base64') and len(data) <= _MAX_DOWNLOAD:
                self._deliver(QImage.fromData(QByteArray.fromBase64(QByteArray.fromPercentEncoding(QByteArray(data)))))
            else:
                self.failed.emit('无法读取拖入的网页图片。')
        else:
            urls = _bili_calendar_urls(source)
            self._get(*(urls or (source,)))

    def _get(self, url, fallback=None):
        request = QNetworkRequest(url)
        request.setRawHeader(b'Accept', b'image/*')
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        request.setTransferTimeout(10000)
        reply = self.reply = self.network.get(request)
        reply.setReadBufferSize(_MAX_DOWNLOAD + 1)
        reply.readyRead.connect(lambda: self._limit(reply))
        reply.finished.connect(lambda: self._finished(reply, fallback))

    def _limit(self, reply):
        if reply.bytesAvailable() > _MAX_DOWNLOAD:
            reply.abort()

    def _finished(self, reply, fallback):
        if self.reply is reply:
            self.reply = None
            if reply.error() == QNetworkReply.NoError and reply.bytesAvailable() <= _MAX_DOWNLOAD:
                image = QImage.fromData(reply.readAll())
                if not image.isNull():
                    self.loaded.emit(image)
                elif fallback is not None:
                    self._get(fallback)
                elif bytes(reply.rawHeader(b'Content-Type')).lower().startswith(b'text/html'):
                    self.failed.emit('拖入的是网页链接。请按住动态中的图片拖入，或选择本地图片。')
                else:
                    self._deliver(image)
            elif fallback is not None:
                self._get(fallback)
            else:
                self.failed.emit('无法下载这张网页图片，可保存到本地后再拖入。')
        reply.deleteLater()

    def _deliver(self, image):
        if image.isNull():
            self.failed.emit('无法读取图片。请拖入图片本身，或选择本地图片。')
        else:
            self.loaded.emit(image)

    def cancel(self):
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
