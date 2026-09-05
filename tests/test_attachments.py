import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qgis_ai_copilot.attachments import (
    Attachment,
    AttachmentError,
    MAX_ATTACHMENTS,
    MAX_TOTAL_ATTACHMENT_BYTES,
    _read_bounded,
    image_mime,
    parse_pdf_pages,
    prepare_file,
    validate_collection,
)

ONE_PIXEL_PNG_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
ONE_PIXEL_PNG = base64.b64decode(ONE_PIXEL_PNG_URL.split(",", 1)[1])


def fixture_attachment():
    return Attachment(
        name="screen.png",
        mime_type="image/png",
        source_kind="file",
        size=len(ONE_PIXEL_PNG),
        sha256="a" * 64,
        parts=[{"type": "image_url", "image_url": {"url": ONE_PIXEL_PNG_URL}}],
        preview_bytes=ONE_PIXEL_PNG,
    )


class AttachmentTests(unittest.TestCase):
    def test_manifest_excludes_binary_and_content_parts_are_independent(self):
        attachment = fixture_attachment()
        manifest = attachment.manifest()
        self.assertEqual(
            set(manifest), {"id", "name", "mime_type", "source_kind", "size", "sha256"}
        )
        parts = attachment.content_parts()
        parts[0]["image_url"]["url"] = "changed"
        self.assertEqual(attachment.parts[0]["image_url"]["url"], ONE_PIXEL_PNG_URL)

    def test_file_validates_input_before_image_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "screen.png"
            path.write_bytes(ONE_PIXEL_PNG)
            with (
                patch(
                    "qgis_ai_copilot.attachments._decode_image", return_value="decoded"
                ) as decode,
                patch(
                    "qgis_ai_copilot.attachments.prepare_image",
                    return_value=fixture_attachment(),
                ) as encode,
            ):
                item = prepare_file(path)
                decode.assert_called_once_with(ONE_PIXEL_PNG)
                self.assertEqual(
                    encode.call_args.args[:3], ("decoded", "screen.png", "file")
                )
                self.assertEqual(item.size, len(ONE_PIXEL_PNG))

    def test_unsupported_empty_corrupt_and_oversized_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.txt"
            path.write_text("private", encoding="utf-8")
            with self.assertRaises(AttachmentError):
                prepare_file(path)
            empty = Path(directory) / "empty.png"
            empty.touch()
            with self.assertRaises(AttachmentError):
                prepare_file(empty)
            with self.assertRaises(AttachmentError):
                image_mime(b"not an image")
            with patch("qgis_ai_copilot.attachments.MAX_ATTACHMENT_BYTES", 2):
                with self.assertRaises(AttachmentError):
                    _read_bounded(path)

    def test_collection_limits_encoded_bytes_and_file_count(self):
        item = fixture_attachment()
        with self.assertRaises(AttachmentError):
            validate_collection([item] * (MAX_ATTACHMENTS + 1))
        item.parts[0]["image_url"]["url"] = "x" * (MAX_TOTAL_ATTACHMENT_BYTES + 1)
        with self.assertRaises(AttachmentError):
            validate_collection([item])

    def test_pdf_selection_deduplicates_sorts_and_never_silently_truncates(self):
        self.assertEqual(parse_pdf_pages("all", 3), [1, 2, 3])
        self.assertEqual(parse_pdf_pages("3,1-2,2", 7), [1, 2, 3])
        for value, count in [
            ("all", 21),
            ("0", 3),
            ("4", 3),
            ("3-1", 4),
            ("1-300", 300),
            ("1,", 3),
        ]:
            with self.subTest(value=value), self.assertRaises(AttachmentError):
                parse_pdf_pages(value, count)


if __name__ == "__main__":
    unittest.main()
