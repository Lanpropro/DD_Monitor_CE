"""Offline pixel and worker checks for native danmaku image preparation."""
import os
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from ddm import config, images
from ddm.danmaku_raster import RasterStyle, rasterize
from ddm.video_danmaku import VideoDanmaku

APP = QApplication.instance() or QApplication([])


class RasterTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        for module, name, value in (
            (config, "REPO", directory), (config, "CONFIG_PATH", str(Path(directory) / "config.json")),
            (images, "REPO", directory), (images, "_EMOTICON_IMAGES", OrderedDict()),
            (images, "_EMOTICON_PENDING", {}), (images, "_EMOTICON_BYTES", 0),
        ):
            self.stack.enter_context(patch.object(module, name, value))
        self.network = self.stack.enter_context(patch.object(
            images.requests, "get", side_effect=AssertionError("Unexpected network")))
        self.old = VideoDanmaku()
        self.addCleanup(self.old.close)
        self.old.resize(640, 360)
        self.old.settings = {"danmaku_font": "Microsoft YaHei", "video_danmaku_size": 28,
                             "video_danmaku_scale": False, "video_danmaku_outline_width": 2}
        self.style = RasterStyle(self.old._font().family(), 28, 2, 1280,
                                 self.old.devicePixelRatioF(), self.old.TEXT_SAMPLE_SCALE)

    def test_text_matches_existing_renderer_and_pixel_contract(self):
        for text in ("Hello gyp!", "中文弹幕测试", "Hello 中文 😀🌈", "x" * 300):
            for self_sent in (False, True):
                with self.subTest(text=text[:20], self_sent=self_sent):
                    prepared = rasterize(text, "#ff8030", [], self_sent, self.style)
                    reference = self.old._render_text(text, QColor("#ff8030"), self_sent).toImage()
                    self.assertEqual(prepared.image, reference)
                    self.assertEqual(prepared.image.format(), QImage.Format.Format_ARGB32_Premultiplied)
                    self.assertEqual(len(prepared.bgra), prepared.stride * prepared.pixel_height)
                    self.assertEqual(prepared.pixel_width * 4, prepared.stride)
                    self.assertEqual(prepared.logical_width * prepared.image.devicePixelRatio(),
                                     prepared.pixel_width)
                    alpha = prepared.bgra[3::4]
                    self.assertEqual(min(alpha), 0)
                    self.assertGreater(max(alpha), 0)
                    for offset in range(0, len(prepared.bgra), 4):
                        b, g, r, a = prepared.bgra[offset:offset + 4]
                        self.assertTrue(b <= a and g <= a and r <= a)
        self.network.assert_not_called()

    def test_rich_text_matches_existing_renderer_with_single_alpha_image_pass(self):
        emote = QImage(20, 20, QImage.Format.Format_ARGB32_Premultiplied)
        emote.fill(QColor(240, 50, 10, 96))
        url = "https://example.invalid/emote.png"
        self.old._images = {url: emote}
        for outline in (0, 2):
            self.old.settings["video_danmaku_outline_width"] = outline
            style = replace(self.style, outline_width=outline)
            for runs, text in (([("[emote]", url)], "[emote]"),
                               ([("中g ", ""), ("[emote]", url), (" 😀", "")], "中g [emote] 😀")):
                for self_sent in (False, True):
                    prepared = rasterize(text, "#40ff80", runs, self_sent, style, {url: emote})
                    reference = self.old._render_content(text, QColor("#40ff80"), runs, self_sent).toImage()
                    self.assertEqual(prepared.image, reference)
                    if len(runs) == 1 and not self_sent:
                        self.assertEqual(max(prepared.bgra[3::4]), 96,
                                         "Translucent images must be painted exactly once")
        self.assertEqual(emote.pixelColor(10, 10).alpha(), 96)

    def test_worker_raster_is_deterministic_and_owns_output(self):
        emote = QImage(20, 20, QImage.Format.Format_ARGB32_Premultiplied)
        emote.fill(QColor(20, 80, 120, 96))
        snapshots = {"https://example.invalid/thread.png": emote}
        runs = [("线程 中文 😀 ", ""), ("[emote]", next(iter(snapshots)))]
        expected = rasterize("线程 中文 😀 [emote]", "#fff", runs, True, self.style, snapshots)
        gui_thread = threading.get_ident()

        def prepare(_):
            self.assertNotEqual(threading.get_ident(), gui_thread)
            return rasterize("线程 中文 😀 [emote]", "#fff", runs, True, self.style, snapshots)

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(prepare, range(12)))
        for result in results:
            self.assertEqual(result.bgra, expected.bgra)
        original = results[1].bgra
        results[0].image.fill(QColor("red"))
        self.assertEqual(bytes(results[1].image.constBits()), original)
        self.assertEqual(results[0].bgra, expected.bgra)

    def test_decode_worker_cache_deduplicates_and_returns_detached_handles(self):
        source = QImage(16, 16, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(QColor(30, 90, 180, 128))
        source_path = Path(config.REPO) / "source.png"
        self.assertTrue(source.save(str(source_path)))
        response = Mock(status_code=200, content=source_path.read_bytes())

        def fetch(*args, **kwargs):
            time.sleep(.03)
            return response

        self.network.side_effect = fetch
        url = "https://example.invalid/cache.png"
        with patch.object(images, "QPixmap", side_effect=AssertionError("Worker QPixmap")):
            with ThreadPoolExecutor(max_workers=6) as pool:
                decoded = list(pool.map(lambda _: images.load_image(url, "emoticons"), range(6)))
        self.assertTrue(all(isinstance(image, QImage) for image in decoded))
        self.assertEqual(self.network.call_count, 1)
        self.assertEqual(images._EMOTICON_PENDING, {})
        self.assertEqual(images._EMOTICON_BYTES, source.sizeInBytes())
        first = decoded[0]
        assert first is not None
        original_color = first.pixelColor(8, 8)
        first.fill(QColor("red"))
        cached = images.load_image(url, "emoticons")
        assert cached is not None
        self.assertEqual(cached.pixelColor(8, 8), original_color)
        self.assertIsNotNone(images.load_pixmap(url, "emoticons"))
        self.assertEqual(self.network.call_count, 1)

    def test_style_validation_and_fractional_dpi(self):
        for change in ({"dpr": 0}, {"outline_width": -1}, {"logical_max_width": float("inf")},
                       {"pixel_size": 0}, {"sample_scale": float("nan")}):
            with self.assertRaises(ValueError):
                replace(self.style, **change)
        result = rasterize("g中文😀", "invalid-color", [], False, replace(self.style, dpr=1.25))
        self.assertEqual(result.image.devicePixelRatio(), 2.5)
        self.assertGreater(result.logical_height, 28)


if __name__ == "__main__":
    unittest.main()
