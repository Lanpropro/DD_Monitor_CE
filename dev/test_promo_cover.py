"""Validate the saved cover's dimensions and complete PNG data."""
import struct
import unittest
import zlib
from pathlib import Path

COVER = Path(__file__).resolve().parents[1] / "videos/dd-monitor-ce-plugins-promo/covers/dd-monitor-ce-cover-v1.png"


class CoverTests(unittest.TestCase):
    def test_landscape_cover_is_high_resolution_and_nearly_sixteen_nine(self):
        data = COVER.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        self.assertGreaterEqual(width, 1600)
        self.assertAlmostEqual(width / height, 16 / 9, delta=.001)

    def test_png_chunks_and_pixels_are_complete(self):
        data = COVER.read_bytes()
        offset, pixels, ended = 8, bytearray(), False
        while offset < len(data):
            length = struct.unpack(">I", data[offset:offset+4])[0]
            kind = data[offset+4:offset+8]
            payload = data[offset+8:offset+8+length]
            crc = struct.unpack(">I", data[offset+8+length:offset+12+length])[0]
            self.assertEqual(zlib.crc32(kind + payload), crc)
            if kind == b"IHDR":
                width, height, *format_fields = struct.unpack(">IIBBBBB", payload)
                self.assertEqual(format_fields, [8, 2, 0, 0, 0])
            elif kind == b"IDAT":
                pixels.extend(payload)
            elif kind == b"IEND":
                ended = True
            offset += length + 12
        self.assertTrue(ended)
        self.assertEqual(offset, len(data))
        self.assertEqual(len(zlib.decompress(pixels)), height * (width * 3 + 1))


if __name__ == "__main__":
    unittest.main()
