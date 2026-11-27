"""Verify that the committed DD CE brand assets are valid and reproducible."""

from __future__ import annotations

import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dev.tools import build_brand_assets as brand


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
classic_ico = brand.pack_ico([
    (size, brand.render_png(renderer, size)) for size in brand.ICON_SIZES
])

from ddm import app_icon

default_ico = brand.render_icon(brand.CHARACTER_SOURCE)
badge_ico = brand.render_icon(brand.BADGE_SOURCE)
assert brand.PNG_PATH.read_bytes() == expected_png, "logo.png 必须由 logo.svg 生成"
for path, expected in ((brand.ASSET_ICO_PATH, default_ico), (brand.ROOT_ICO_PATH, default_ico),
                       (brand.BADGE_ICO_PATH, badge_ico), (brand.CLASSIC_ICO_PATH, classic_ico)):
    assert path.read_bytes() == expected, f"{path.name} 已过期"
    assert ico_sizes(expected) == list(brand.ICON_SIZES)

def pixels(style):
    icon = app_icon.load_icon(style)
    assert not icon.isNull()
    image = icon.pixmap(32, 32).toImage()
    return bytes(image.bits())

assert len({pixels(style) for style in ('d', 'b', 'f')}) == 3
for invalid in (None, 'invalid', ['b']):
    assert pixels(invalid) == pixels('d')
print("品牌资源自检通过：三款应用图标可复现，每款包含", len(brand.ICON_SIZES), "种尺寸")
