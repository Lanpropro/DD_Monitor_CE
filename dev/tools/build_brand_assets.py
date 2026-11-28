"""Render the checked-in SVG and icon artwork to the application brand assets."""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


REPO = Path(__file__).resolve().parents[2]
SVG_PATH = REPO / "assets" / "logo.svg"
PNG_PATH = REPO / "assets" / "logo.png"
ASSET_ICO_PATH = REPO / "assets" / "favicon.ico"
ROOT_ICO_PATH = REPO / "favicon.ico"
CLASSIC_ICO_PATH = REPO / "assets/app-icons/classic.ico"
BADGE_ICO_PATH = REPO / "assets/app-icons/badge.ico"
CHARACTER_SMALL_TRIM = 0.06
BADGE_SMALL_TRIM = 0.02
CHARACTER_SOURCE = REPO / "design/icon-concepts/app-icon-character.png"
BADGE_SOURCE = REPO / "design/icon-concepts/app-icon-badge.png"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return png_bytes(image)


def png_bytes(image: QImage) -> bytes:
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("failed to encode PNG")
    return bytes(payload)


def pack_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = []
    payloads = []
    for size, payload in images:
        encoded_size = 0 if size == 256 else size
        entries.append(struct.pack(
            "<BBBBHHII",
            encoded_size, encoded_size, 0, 0, 1, 32, len(payload), offset,
        ))
        payloads.append(payload)
        offset += len(payload)
    return header + b"".join(entries) + b"".join(payloads)


def render_icon(source: Path, *, small_trim: float) -> bytes:
    image = QImage(str(source))
    if image.isNull() or image.width() != image.height():
        raise RuntimeError(f"invalid square icon source: {source}")
    inset = round(image.width() * small_trim)
    side = image.width() - 2 * inset
    small_image = image.copy(inset, inset, side, side)
    frames = []
    for size in ICON_SIZES:
        frame = small_image if size <= 64 else image
        frames.append((size, png_bytes(frame.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))))
    return pack_ico(frames)


def build() -> tuple[bytes, bytes]:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise RuntimeError(f"invalid SVG: {SVG_PATH}")

    png = render_png(renderer, 1024)
    classic_ico = pack_ico([(size, render_png(renderer, size)) for size in ICON_SIZES])
    ico = render_icon(CHARACTER_SOURCE, small_trim=CHARACTER_SMALL_TRIM)
    badge_ico = render_icon(BADGE_SOURCE, small_trim=BADGE_SMALL_TRIM)
    PNG_PATH.write_bytes(png)
    CLASSIC_ICO_PATH.parent.mkdir(exist_ok=True)
    CLASSIC_ICO_PATH.write_bytes(classic_ico)
    BADGE_ICO_PATH.write_bytes(badge_ico)
    ASSET_ICO_PATH.write_bytes(ico)
    ROOT_ICO_PATH.write_bytes(ico)
    return png, ico


if __name__ == "__main__":
    rendered_png, rendered_ico = build()
    print(f"PNG: {PNG_PATH} ({len(rendered_png)} bytes)")
    print(f"ICO: {ROOT_ICO_PATH} ({len(rendered_ico)} bytes, {len(ICON_SIZES)} sizes)")
