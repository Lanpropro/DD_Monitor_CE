"""Static contract checks for the DD 监控室 CE Live Stage prototype.

Run directly:
    python website-prototype/test_prototype.py -v

The companion `capture.mjs` performs the runtime checks (overflow, image
loading, console errors) with a local Chrome/Edge install.
"""

from __future__ import annotations

import re
import struct
import unittest
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = (HERE / "index.html").read_text(encoding="utf-8")
CSS = (HERE / "styles.css").read_text(encoding="utf-8")
JS = (HERE / "app.js").read_text(encoding="utf-8")


class DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        data = dict(attrs)
        self.tags.append((tag, data))
        if data.get("id"):
            self.ids.append(data["id"])


def parse_document() -> DocumentParser:
    parser = DocumentParser()
    parser.feed(HTML)
    return parser


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError(f"{path.name} is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


class PrototypeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = parse_document()
        cls.ids = set(cls.doc.ids)

    def test_document_language_and_metadata(self) -> None:
        self.assertIn('lang="zh-CN"', HTML)
        self.assertIn("<title>", HTML)
        self.assertIn('name="description"', HTML)
        self.assertIn('property="og:title"', HTML)
        self.assertIn('property="og:image"', HTML)
        self.assertIn('name="theme-color"', HTML)

    def test_single_h1_and_five_sections(self) -> None:
        h1 = [tag for tag, _ in self.doc.tags if tag == "h1"]
        h2 = [tag for tag, _ in self.doc.tags if tag == "h2"]
        self.assertEqual(len(h1), 1, "the page must have exactly one h1")
        self.assertGreaterEqual(len(h2), 5, "expected one h2 per major section")
        for required in ("main", "layout", "control", "record", "plugins", "download"):
            self.assertIn(required, self.ids, f"missing anchor target #{required}")

    def test_ids_are_unique(self) -> None:
        self.assertEqual(len(self.doc.ids), len(set(self.doc.ids)), "duplicate ids")

    def test_local_assets_exist(self) -> None:
        for tag, attrs in self.doc.tags:
            src = attrs.get("src")
            if tag == "img" and src:
                self.assertFalse(src.startswith(("http://", "https://")), f"remote image: {src}")
                self.assertIsNotNone(attrs.get("alt"), f"missing alt: {src}")
                if not src.startswith("data:"):
                    path = HERE / src
                    self.assertTrue(path.is_file(), f"missing image: {src}")
                    self.assertGreater(path.stat().st_size, 1_000, f"suspiciously small: {src}")
            if tag == "script" and src:
                self.assertFalse(src.startswith(("http://", "https://")), f"remote script: {src}")
                self.assertTrue((HERE / src).is_file(), f"missing script: {src}")

        self.assertTrue((HERE / "assets/logo.svg").is_file(), "missing product logo")

    def test_no_remote_or_imported_css(self) -> None:
        self.assertTrue("@import" not in CSS, "CSS must not import remote styles")
        self.assertIsNone(
            re.search(r"url\(\s*[\"']?https?://", CSS),
            "CSS must not load remote assets",
        )

    def test_internal_anchors_resolve(self) -> None:
        for tag, attrs in self.doc.tags:
            if tag != "a":
                continue
            href = attrs.get("href") or ""
            if href.startswith("#"):
                self.assertIn(href[1:], self.ids, f"broken anchor: {href}")
            elif href:
                self.assertTrue(
                    href.startswith("https://github.com/Lanpropro/"),
                    f"unexpected external link: {href}",
                )

    def test_layout_and_plugin_controls_are_accessible(self) -> None:
        tabs = [attrs for tag, attrs in self.doc.tags if tag == "button" and attrs.get("data-mode")]
        self.assertEqual(len(tabs), 4)
        for attrs in tabs:
            self.assertIn("aria-pressed", attrs)
        self.assertEqual(sum(1 for attrs in tabs if attrs.get("aria-pressed") == "true"), 1)

        switches = [attrs for tag, attrs in self.doc.tags if attrs.get("class") and "switch" in attrs["class"]]
        self.assertEqual(len(switches), 2)
        for attrs in switches:
            self.assertIn("aria-pressed", attrs)

    def test_css_has_reduced_motion_and_capture_mode(self) -> None:
        for needle in (
            "@media (prefers-reduced-motion: reduce)",
            ".capture .hero-copy > *",
            ".capture .stage-card--screen",
            "animation-duration: 0.001ms !important",
            "overflow-x: hidden",
        ):
            self.assertTrue(needle in CSS, f"missing CSS contract: {needle}")

    def test_js_handles_capture_modes_and_reduced_motion(self) -> None:
        for needle in (
            'params.has("capture")',
            "prefers-reduced-motion: reduce",
            '"is-portrait"',
            "data-mode",
            "data-mode-row",
        ):
            self.assertTrue(needle in JS, f"missing JS contract: {needle}")
        for forbidden in ("fetch(", "import ", "http://", "https://"):
            self.assertTrue(forbidden not in JS, f"unexpected JS dependency: {forbidden}")

    def test_copy_covers_product_and_plugin_facts(self) -> None:
        required = [
            "把喜欢的直播",
            "摆成",
            "16 路",
            "Windows 10 / 11",
            "LGPL-2.1",
            "一块屏",
            "每一格",
            "多一块积木",
            "domestic_live",
            "global_live",
            "虎牙",
            "斗鱼",
            "抖音",
            "Twitch",
            "YouTube",
            "安全提示",
            "官方插件商店",
            "本地 ZIP",
        ]
        for text in required:
            self.assertTrue(text in HTML, f"missing product fact: {text}")
        for placeholder in ("lorem ipsum", "TODO", "占位文案"):
            self.assertTrue(placeholder.lower() not in HTML.lower(), f"placeholder copy: {placeholder}")

    def test_screenshots_exist_and_have_expected_dimensions(self) -> None:
        desktop = HERE / "shots/desktop.png"
        mobile = HERE / "shots/mobile.png"
        hero = HERE / "shots/hero.png"
        for file in (desktop, mobile, hero):
            self.assertTrue(file.is_file(), f"missing screenshot: {file.name}")
            self.assertGreater(file.stat().st_size, 100_000, f"small screenshot: {file.name}")

        self.assertEqual(png_size(hero), (1440, 900))
        width, height = png_size(desktop)
        self.assertEqual(width, 1440)
        self.assertGreater(height, 4_500)
        self.assertLess(height, 6_500)

        width, height = png_size(mobile)
        self.assertEqual(width, 390)
        self.assertGreater(height, 6_500)
        self.assertLess(height, 8_500)

    def test_capture_script_has_runtime_audits(self) -> None:
        script = (HERE / "capture.mjs").read_text(encoding="utf-8")
        for width in ("320", "375", "414", "768", "1024", "1440"):
            self.assertIn(width, script)
        self.assertIn("Horizontal overflow", script)
        self.assertIn("brokenImages", script)
        self.assertIn("Browser errors", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
