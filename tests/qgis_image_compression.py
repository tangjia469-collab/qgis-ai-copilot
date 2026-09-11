"""Regression tests for clipboard images becoming oversized during encoding."""

import base64
import hashlib
import random
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QBuffer, QIODevice
from qgis.PyQt.QtGui import QColor, QImage, QPainter

from qgis_ai_copilot.attachments import prepare_image
from qgis_ai_copilot.protocol import build_chat_payload


class ScreenshotCompressionTests(unittest.TestCase):
    def test_retina_capture_keeps_all_physical_pixels_without_transparent_padding(self):
        image = QImage(800, 600, QImage.Format_ARGB32)
        image.fill(QColor("#5a8bc0"))
        image.setDevicePixelRatio(2.0)
        item = prepare_image(image, "retina-map.png", "map-canvas")
        result = QImage.fromData(item.preview_bytes)
        self.assertEqual(result.size(), image.size())
        self.assertEqual(result.pixelColor(799, 599), QColor("#5a8bc0"))
        self.assertEqual(image.devicePixelRatio(), 2.0)

    def test_flat_4k_screenshot_stays_lossless_and_compact(self):
        image = QImage(4096, 2304, QImage.Format_ARGB32)
        image.fill(QColor("#e8e8e8"))
        image.setText("private_source", "/Users/private/screenshot.png")
        painter = QPainter(image)
        painter.fillRect(120, 100, 300, 90, QColor("red"))
        painter.end()
        try:
            item = prepare_image(image)
        except ValueError as exc:
            self.fail(
                f"A normal 4K screenshot should be compressed automatically: {exc}"
            )
        self.assertLess(len(item.preview_bytes), 200_000)
        self.assertEqual(item.mime_type, "image/png")
        result = QImage.fromData(item.preview_bytes)
        self.assertEqual(result.size(), image.size())
        self.assertEqual(result.pixelColor(121, 101), QColor("red"))
        self.assertEqual(result.pixelColor(0, 0), QColor("#e8e8e8"))
        self.assertEqual(result.textKeys(), [])

    def test_dense_screenshot_falls_back_to_readable_jpeg_under_upload_limit(self):
        # Seeded high-entropy pixels exceed 12 MiB even with real PNG compression.
        pixels = random.Random(731).randbytes(4096 * 2048 * 3)
        image = QImage(pixels, 4096, 2048, 4096 * 3, QImage.Format_RGB888).copy()
        painter = QPainter(image)
        painter.fillRect(20, 20, 120, 80, QColor("white"))
        painter.fillRect(160, 20, 120, 80, QColor("black"))
        painter.end()
        try:
            item = prepare_image(image, "dense-screen.png")
        except ValueError as exc:
            self.fail(
                f"Dense screenshots should be optimized rather than rejected: {exc}"
            )
        self.assertEqual(item.mime_type, "image/jpeg")
        self.assertLessEqual(len(item.preview_bytes), 12 * 1024 * 1024)
        result = QImage.fromData(item.preview_bytes)
        self.assertEqual(
            result.size(), image.size(), "Do not shrink legible text if JPEG alone fits"
        )
        self.assertGreater(result.pixelColor(50, 50).red(), 240)
        self.assertLess(result.pixelColor(190, 50).red(), 15)
        self.assertEqual(item.size, len(item.preview_bytes))
        self.assertEqual(item.sha256, hashlib.sha256(item.preview_bytes).hexdigest())
        uri = item.parts[0]["image_url"]["url"]
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
        self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), item.preview_bytes)
        payload = build_chat_payload(
            "test-model", [{"role": "user", "content": item.content_parts()}]
        )
        self.assertEqual(payload["messages"][0]["content"][0]["image_url"]["url"], uri)

    def test_transparency_is_preserved_when_lossless_image_fits(self):
        image = QImage(120, 80, QImage.Format_ARGB32)
        image.fill(QColor(30, 60, 90, 100))
        item = prepare_image(image)
        self.assertEqual(item.mime_type, "image/png")
        result = QImage.fromData(item.preview_bytes)
        self.assertEqual(result.pixelColor(20, 20), QColor(30, 60, 90, 100))

    def test_fallback_flattens_transparency_on_white_and_resizes_if_required(self):
        pixels = random.Random(482).randbytes(1024 * 1024 * 3)
        image = QImage(
            pixels, 1024, 1024, 1024 * 3, QImage.Format_RGB888
        ).convertToFormat(QImage.Format_ARGB32)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(0, 0, 256, 256, QColor(0, 0, 0, 0))
        painter.end()
        with patch("qgis_ai_copilot.attachments.MAX_ATTACHMENT_BYTES", 200_000):
            try:
                item = prepare_image(image)
            except ValueError as exc:
                self.fail(
                    f"Fallback must optimize pixels and preserve transparent-area legibility: {exc}"
                )
        result = QImage.fromData(item.preview_bytes)
        self.assertEqual(item.mime_type, "image/jpeg")
        self.assertLessEqual(len(item.preview_bytes), 200_000)
        self.assertLess(result.width(), 1024)
        self.assertGreaterEqual(result.width(), 512)
        self.assertEqual(result.width(), result.height())
        self.assertGreater(result.pixelColor(20, 20).red(), 245)
        self.assertEqual(
            image.pixelColor(20, 20).alpha(), 0, "Leave the original image untouched"
        )

    def test_extreme_byte_limit_exits_after_bounded_compression_attempts(self):
        image = QImage(32, 32, QImage.Format_RGB32)
        image.fill(QColor("white"))
        with patch("qgis_ai_copilot.attachments.MAX_ATTACHMENT_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "automatic compression"):
                prepare_image(image)

    def test_oversized_original_pixels_are_scaled_without_mutation(self):
        image = QImage(5120, 2880, QImage.Format_RGB32)
        image.fill(QColor("white"))
        try:
            item = prepare_image(image)
        except ValueError as exc:
            self.fail(
                f"Retina screenshots should be scaled and encoded automatically: {exc}"
            )
        self.assertEqual((image.width(), image.height()), (5120, 2880))
        result = QImage.fromData(item.preview_bytes)
        self.assertEqual((result.width(), result.height()), (4096, 2304))
        self.assertLess(len(item.preview_bytes), 200_000)

    def test_encoding_fix_does_not_change_pixels_compared_to_lossless_reference(self):
        image = QImage(400, 240, QImage.Format_ARGB32)
        image.fill(QColor("#123456"))
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG", -1)
        reference = QImage.fromData(bytes(buffer.data()))
        item = prepare_image(image)
        self.assertLess(len(item.preview_bytes), 5000)
        self.assertEqual(QImage.fromData(item.preview_bytes), reference)


if __name__ == "__main__":
    unittest.main()
