"""Background-only face detection and cached cover crop geometry."""
import json
import threading
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPixmap

_KEY = 'ddm_cover_faces_v1'
_LOCK = threading.Lock()
_DETECTORS = None


def _detect_faces(image):
    global _DETECTORS
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    try:
        with _LOCK:
            if _DETECTORS is None:
                assets = Path(__file__).resolve().parent / 'assets' / 'cover-focus'
                cv2.setNumThreads(1)
                real = cv2.FaceDetectorYN.create(
                    str(assets / 'face_detection_yunet_2023mar.onnx'), '', (320, 320),
                    score_threshold=0.85)
                anime = cv2.CascadeClassifier(str(assets / 'lbpcascade_animeface.xml'))
                if anime.empty():
                    return None
                _DETECTORS = real, anime
            small = image.scaled(640, 640, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            small = small.convertToFormat(QImage.Format_RGB888)
            pixels = np.frombuffer(small.constBits(), dtype=np.uint8).reshape(
                small.height(), small.bytesPerLine())[:, :small.width() * 3]
            bgr = cv2.cvtColor(pixels.reshape(small.height(), small.width(), 3), cv2.COLOR_RGB2BGR)
            real, anime = _DETECTORS
            real.setInputSize((small.width(), small.height()))
            _, found = real.detect(bgr)
            boxes = found[:, :4] if found is not None else []
            if not len(boxes):
                gray = cv2.equalizeHist(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
                boxes = anime.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                               minSize=(24, 24))
            return [[max(0., min(1., float(x) / small.width())),
                     max(0., min(1., float(y) / small.height())),
                     min(1., float(w) / small.width()), min(1., float(h) / small.height())]
                    for x, y, w, h in boxes]
    except (cv2.error, OSError):
        return None


def faces_for(pixmap):
    """Read metadata only; this function is also safe in paint events."""
    text = pixmap.toImage().text(_KEY)
    if not text:
        return None
    try:
        boxes = json.loads(text)
        if not isinstance(boxes, list):
            return None
        if not all(isinstance(box, list) and len(box) == 4
                   and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in box)
                   and box[2] > 0 and box[3] > 0 for box in boxes):
            return None
        return boxes
    except (ValueError, TypeError):
        return None


def prepare_cover(pixmap):
    """Called by cover workers; cache positive and negative detections in PNG text."""
    if faces_for(pixmap) is not None:
        return pixmap
    image = pixmap.toImage()
    boxes = _detect_faces(image)
    if boxes is None:
        return pixmap
    image.setText(_KEY, json.dumps(boxes, separators=(',', ':')))
    return QPixmap.fromImage(image)


def source_rect(pixmap, width, height, *, focus=True):
    """Keep cover scaling, moving the crop toward faces without extra zoom."""
    iw, ih = pixmap.width(), pixmap.height()
    scale = max(width / iw, height / ih)
    cw, ch = width / scale, height / scale
    centered = QRectF((iw - cw) / 2, (ih - ch) / 2, cw, ch)
    boxes = faces_for(pixmap) if focus else None
    if not boxes:
        return centered
    faces = [QRectF(x * iw, y * ih, w * iw, h * ih) for x, y, w, h in boxes]
    primary = max(faces, key=lambda box: box.width() * box.height())
    group = QRectF(primary)
    for box in faces:
        if box.width() * box.height() >= primary.width() * primary.height() * 0.35:
            group = group.united(box)
    selected = group if group.width() <= cw and group.height() * 1.35 <= ch else primary
    padded = selected.adjusted(-selected.width() * 0.15, -selected.height() * 0.35,
                               selected.width() * 0.15, selected.height() * 0.1)

    def origin(start, end, extent, crop, desired):
        if end - start <= crop:
            desired = min(max(desired, end - crop), start)
        return max(0, min(extent - crop, desired))

    horizontal = padded if padded.width() <= cw else selected
    vertical = padded if padded.height() <= ch else selected
    x = origin(horizontal.left(), horizontal.right(), iw, cw, selected.center().x() - cw * 0.7)
    y = origin(vertical.top(), vertical.bottom(), ih, ch,
               selected.top() + selected.height() * 0.4 - ch * 0.45)
    return QRectF(x, y, cw, ch)
