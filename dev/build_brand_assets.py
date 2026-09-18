"""Render the checked-in SVG brand source to the app's PNG and ICO assets."""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


REPO = Path(__file__).resolve().parents[1]
SVG_PATH = REPO / "assets" / "logo.svg"
PNG_PATH = REPO / "assets" / "logo.png"
ASSET_ICO_PATH = REPO / "assets" / "favicon.ico"
ROOT_ICO_PATH = REPO / "favicon.ico"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()

    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError(f"failed to render {size}px PNG")
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


def build() -> tuple[bytes, bytes]:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise RuntimeError(f"invalid SVG: {SVG_PATH}")

    png = render_png(renderer, 1024)
    ico = pack_ico([(size, render_png(renderer, size)) for size in ICON_SIZES])
    PNG_PATH.write_bytes(png)
    ASSET_ICO_PATH.write_bytes(ico)
    ROOT_ICO_PATH.write_bytes(ico)
    return png, ico


if __name__ == "__main__":
    rendered_png, rendered_ico = build()
    print(f"PNG: {PNG_PATH} ({len(rendered_png)} bytes)")
    print(f"ICO: {ROOT_ICO_PATH} ({len(rendered_ico)} bytes, {len(ICON_SIZES)} sizes)")
