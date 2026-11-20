"""Decode local gallery thumbnails without accessing widgets on worker threads."""
from threading import Event

from PySide6.QtCore import QRunnable, Qt
from PySide6.QtGui import QImageReader


def read_thumbnail(path):
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(size.scaled(288, 180, Qt.KeepAspectRatio))
    return reader.read()


class ThumbnailBatch(QRunnable):
    def __init__(self, files, generation, ready):
        super().__init__()
        self.files, self.generation, self.ready = files, generation, ready
        self.cancelled = Event()

    def run(self):
        for path, relative in self.files:
            if self.cancelled.is_set():
                return
            image = read_thumbnail(path)
            if self.cancelled.is_set():
                return
            if not image.isNull():
                try:
                    self.ready.emit(self.generation, relative, image)
                except RuntimeError:
                    return  # The settings gallery has already been destroyed.
