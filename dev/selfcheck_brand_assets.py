"""Verify that the committed DD CE brand assets are valid and reproducible."""

from __future__ import annotations

import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "dev"))

import build_brand_assets as brand


def ico_sizes(payload: bytes) -> list[int]:
    reserved, kind, count = struct.unpack_from("<HHH", payload)
    assert (reserved, kind) == (0, 1), "favicon.ico 必须是 Windows 图标容器"
    sizes = []
    for index in range(count):
        width, height, _, _, planes, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", payload, 6 + index * 16,
        )
        width = width or 256
        height = height or 256
        assert width == height
        assert planes == 1 and bits == 32
        png = payload[offset:offset + length]
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        png_width, png_height = struct.unpack_from(">II", png, 16)
        assert (png_width, png_height) == (width, height)
        sizes.append(width)
    return sizes


root = ET.parse(brand.SVG_PATH).getroot()
assert root.tag.endswith("svg")
svg_text = brand.SVG_PATH.read_text(encoding="utf-8")
assert "DD remains the inherited primary mark" in svg_text
assert "CE is a deliberate second-level mark" in svg_text

app = brand.QGuiApplication.instance() or brand.QGuiApplication(sys.argv[:1])
renderer = brand.QSvgRenderer(str(brand.SVG_PATH))
assert renderer.isValid(), "logo.svg 必须能被 Qt 正常渲染"
expected_png = brand.render_png(renderer, 1024)
expected_ico = brand.pack_ico([
    (size, brand.render_png(renderer, size)) for size in brand.ICON_SIZES
])

assert brand.PNG_PATH.read_bytes() == expected_png, "logo.png 必须由 logo.svg 生成"
assert brand.ASSET_ICO_PATH.read_bytes() == expected_ico, "assets/favicon.ico 已过期"
assert brand.ROOT_ICO_PATH.read_bytes() == expected_ico, "根目录 favicon.ico 已过期"
assert ico_sizes(expected_ico) == list(brand.ICON_SIZES)

print("品牌资源自检通过：SVG / PNG / ICO 一致，ICO 含", len(brand.ICON_SIZES), "种尺寸")
