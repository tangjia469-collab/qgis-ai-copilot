# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Bounded, memory-only visual attachments and local PDF page rendering."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

MAX_ATTACHMENTS = 6
MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 24 * 1024 * 1024
MAX_CACHED_ATTACHMENT_BYTES = 48 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 32_000_000
IMAGE_MIME_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}
PDF_MIME_TYPE = "application/pdf"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
FILE_FILTER = "Images and PDFs (*.png *.jpg *.jpeg *.webp *.gif *.pdf)"


class AttachmentError(ValueError):
    """A selected attachment could not be prepared within the supported limits."""


def _display_name(name: str) -> str:
    return (
        "".join(
            ch for ch in name.replace("\\", "/").split("/")[-1] if ch.isprintable()
        )[:200]
        or "attachment"
    )


def image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise AttachmentError("The selected file is not a supported image.")


def _read_bounded(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_ATTACHMENT_BYTES + 1)
    except OSError as exc:
        raise AttachmentError(f"Could not read {_display_name(path.name)}.") from exc
    if not data:
        raise AttachmentError("The selected file is empty.")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError("Each file must be 12 MB or smaller.")
    return data


def _pdf_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    # Finder-launched QGIS does not necessarily inherit Homebrew's PATH.
    for directory in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise AttachmentError(
        "PDF rendering requires Poppler (pdfinfo and pdftoppm). Images are still supported."
    )


def parse_pdf_pages(selection: str, page_count: int) -> list[int]:
    value = selection.strip().lower()
    if value in {"", "all"}:
        if page_count > MAX_PDF_PAGES:
            raise AttachmentError(
                f"This PDF has {page_count} pages. Attach again and select up to {MAX_PDF_PAGES} pages."
            )
        return list(range(1, page_count + 1))
    selected: set[int] = set()
    for group in value.split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", group)
        if not match:
            raise AttachmentError("Invalid PDF pages. Use all, 1-5, or 1-3,8.")
        first = int(match[1])
        last = int(match[2] or first)
        if not 1 <= first <= last <= page_count:
            raise AttachmentError(
                f"PDF page numbers must be between 1 and {page_count}."
            )
        if last - first + 1 > MAX_PDF_PAGES:
            raise AttachmentError(
                f"Select up to {MAX_PDF_PAGES} PDF pages per message."
            )
        selected.update(range(first, last + 1))
    if len(selected) > MAX_PDF_PAGES:
        raise AttachmentError(f"Select up to {MAX_PDF_PAGES} PDF pages per message.")
    return sorted(selected)


@dataclass
class Attachment:
    name: str
    mime_type: str
    source_kind: str
    size: int
    sha256: str
    parts: list[dict[str, Any]] = field(default_factory=list)
    preview_bytes: bytes = b""
    page_count: int | None = None
    pages: list[int] = field(default_factory=list)
    attachment_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def payload_size(self) -> int:
        return sum(
            len(part.get("text", "").encode("utf-8"))
            + len(part.get("image_url", {}).get("url", ""))
            for part in self.parts
        )

    @property
    def image_count(self) -> int:
        return sum(part.get("type") == "image_url" for part in self.parts)

    @property
    def retained_size(self) -> int:
        return self.payload_size + len(self.preview_bytes)

    def manifest(self) -> dict[str, Any]:
        value = {
            "id": self.attachment_id,
            "name": self.name,
            "mime_type": self.mime_type,
            "source_kind": self.source_kind,
            "size": self.size,
            "sha256": self.sha256,
        }
        if self.page_count is not None:
            value.update(page_count=self.page_count, pages=list(self.pages))
        return value

    def display_line(self) -> str:
        pages = (
            f"; pages {', '.join(map(str, self.pages))} of {self.page_count}"
            if self.pages
            else ""
        )
        return f"{self.name} ({self.size / 1024:.0f} KB{pages})"

    def content_parts(self) -> list[dict[str, Any]]:
        return deepcopy(self.parts)


def _image_part(data: bytes, mime_type: str) -> dict[str, Any]:
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime_type};base64," + base64.b64encode(data).decode("ascii")
        },
    }


def _encode_image(image: Any, mime_type: str, quality: int = 90) -> bytes:
    from qgis.PyQt.QtCore import QBuffer, QIODevice

    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    # Qt's PNG "quality" is inverse compression effort, not visual quality.
    # 90 disables compression in the bundled Qt build; -1 uses normal lossless
    # compression. JPEG uses the conventional visual-quality scale.
    encoded = image.save(
        buffer,
        "JPEG" if mime_type == "image/jpeg" else "PNG",
        quality if mime_type == "image/jpeg" else -1,
    )
    data = bytes(buffer.data())
    buffer.close()
    if not encoded or not data:
        raise AttachmentError("The image could not be encoded.")
    return data


def _fit_image(image: Any, mime_type: str) -> tuple[bytes, str]:
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QImage, QPainter

    mime_type = "image/jpeg" if mime_type == "image/jpeg" else "image/png"
    data = _encode_image(image, mime_type)
    if len(data) <= MAX_ATTACHMENT_BYTES:
        return data, mime_type

    # Keep full pixel dimensions first so labels and form fields remain legible.
    # JPEG has no alpha: composite on white, never drop alpha into black pixels.
    opaque = QImage(image.size(), QImage.Format_RGB32)
    opaque.fill(Qt.white)
    painter = QPainter(opaque)
    painter.drawImage(0, 0, image)
    painter.end()
    for quality in (90, 80):
        data = _encode_image(opaque, "image/jpeg", quality)
        if len(data) <= MAX_ATTACHMENT_BYTES:
            return data, "image/jpeg"

    # Two bounded downscales are a last resort; never crop or modify the source.
    for scale in (0.75, 0.5):
        resized = opaque.scaled(
            max(1, round(opaque.width() * scale)),
            max(1, round(opaque.height() * scale)),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        data = _encode_image(resized, "image/jpeg", 80)
        if len(data) <= MAX_ATTACHMENT_BYTES:
            return data, "image/jpeg"
    raise AttachmentError(
        "The image remains too large after automatic compression. Try a smaller capture area."
    )


def prepare_image(
    image: Any,
    name: str = "clipboard.png",
    source_kind: str = "clipboard",
    mime_type: str = "image/png",
) -> Attachment:
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QImage, QPainter

    value = image.toImage() if hasattr(image, "toImage") else image
    if not isinstance(value, QImage) or value.isNull():
        raise AttachmentError("No usable image was found.")
    if value.devicePixelRatio() != 1.0:
        # QPainter otherwise interprets the source in logical pixels and can
        # leave the physical-pixel tail transparent on Retina captures.
        value = value.copy()
        value.setDevicePixelRatio(1.0)
    if value.width() * value.height() > MAX_IMAGE_PIXELS:
        raise AttachmentError(
            "The image exceeds 32 megapixels. Crop or resize it before attaching."
        )
    if max(value.width(), value.height()) > MAX_IMAGE_DIMENSION:
        value = value.scaled(
            MAX_IMAGE_DIMENSION,
            MAX_IMAGE_DIMENSION,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
    # Painting pixels into a new image avoids copying EXIF, text metadata or paths.
    clean = QImage(value.size(), QImage.Format_ARGB32)
    clean.fill(Qt.transparent)
    painter = QPainter(clean)
    painter.drawImage(0, 0, value)
    painter.end()
    data, mime_type = _fit_image(clean, mime_type)
    return Attachment(
        name=_display_name(name),
        mime_type=mime_type,
        source_kind=source_kind,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        parts=[_image_part(data, mime_type)],
        preview_bytes=data,
    )


def _decode_image(data: bytes):
    from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, QSize
    from qgis.PyQt.QtGui import QImageReader

    image_mime(data)
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > MAX_IMAGE_PIXELS:
        raise AttachmentError("The image is corrupt or exceeds 32 megapixels.")
    if reader.imageCount() > 1:
        raise AttachmentError(
            "Animated images are not supported. Attach a still frame."
        )
    ratio = min(1, MAX_IMAGE_DIMENSION / max(size.width(), size.height()))
    reader.setScaledSize(
        QSize(max(1, round(size.width() * ratio)), max(1, round(size.height() * ratio)))
    )
    image = reader.read()
    if image.isNull():
        raise AttachmentError("The image could not be decoded.")
    return image


def _pdf_attachment(
    data: bytes, name: str, source_kind: str, selection: str, cancelled
) -> Attachment:
    if not data.startswith(b"%PDF-"):
        raise AttachmentError("The selected file is not a PDF.")
    info_tool, render_tool = _pdf_tool("pdfinfo"), _pdf_tool("pdftoppm")
    parts: list[dict[str, Any]] = []
    preview = b""
    encoded_size = 0
    # Render a private immutable copy, removing it and all rasters on exit.
    with tempfile.TemporaryDirectory(prefix="qgis-ai-copilot-pdf-") as directory:
        input_path = Path(directory) / "input.pdf"
        input_path.write_bytes(data)
        os.chmod(input_path, 0o600)
        try:
            info = subprocess.run(
                [info_tool, str(input_path)],
                capture_output=True,
                timeout=10,
                check=True,
                env={**os.environ, "LC_ALL": "C"},
            )
            match = re.search(rb"(?m)^Pages:\s+(\d+)\s*$", info.stdout)
            if not match:
                raise AttachmentError("PDF page count could not be read.")
            count = int(match[1])
            if count < 1 or re.search(rb"(?m)^Encrypted:\s+yes", info.stdout):
                raise AttachmentError("Attach an unlocked PDF with at least one page.")
            pages = parse_pdf_pages(selection, count)
            prefix = str(Path(directory) / "page")
            for number in pages:
                if cancelled():
                    raise AttachmentError("Attachment preparation cancelled.")
                subprocess.run(
                    [
                        render_tool,
                        "-png",
                        "-scale-to",
                        "2048",
                        "-f",
                        str(number),
                        "-l",
                        str(number),
                        "-singlefile",
                        str(input_path),
                        prefix,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    check=True,
                )
                raster = _read_bounded(Path(prefix + ".png"))
                image_mime(raster)
                part = _image_part(raster, "image/png")
                encoded_size += len(part["image_url"]["url"])
                if encoded_size > MAX_TOTAL_ATTACHMENT_BYTES:
                    raise AttachmentError(
                        "PDF pages exceed 24 MB after rendering. Select fewer pages."
                    )
                parts.extend(
                    [
                        {
                            "type": "text",
                            "text": f"PDF {_display_name(name)}, page {number} of {count}:",
                        },
                        part,
                    ]
                )
                if not preview:
                    preview = raster
        except (OSError, subprocess.SubprocessError) as exc:
            raise AttachmentError(
                "PDF rendering failed or timed out. Check that the PDF is valid and unlocked, or select fewer pages."
            ) from exc
    return Attachment(
        name=_display_name(name),
        mime_type=PDF_MIME_TYPE,
        source_kind=source_kind,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        parts=parts,
        preview_bytes=preview,
        page_count=count,
        pages=pages,
    )


def prepare_file(
    path: str | os.PathLike[str],
    source_kind: str = "file",
    pdf_pages: str = "all",
    cancelled=lambda: False,
) -> Attachment:
    candidate = Path(path)
    if not candidate.is_file():
        raise AttachmentError("The selected attachment is not a file.")
    if candidate.suffix.lower() not in IMAGE_SUFFIXES | {".pdf"}:
        raise AttachmentError("Choose a PNG, JPEG, WebP, GIF, or PDF file.")
    data = _read_bounded(candidate)
    if candidate.suffix.lower() == ".pdf":
        return _pdf_attachment(data, candidate.name, source_kind, pdf_pages, cancelled)
    image = _decode_image(data)
    attachment = prepare_image(
        image,
        candidate.name,
        source_kind,
        "image/jpeg" if image_mime(data) == "image/jpeg" else "image/png",
    )
    attachment.size = len(data)
    return attachment


def validate_collection(attachments: Iterable[Attachment]) -> None:
    values = list(attachments)
    if len(values) > MAX_ATTACHMENTS:
        raise AttachmentError(f"Attach up to {MAX_ATTACHMENTS} files per message.")
    if sum(item.payload_size for item in values) > MAX_TOTAL_ATTACHMENT_BYTES:
        raise AttachmentError(
            "Prepared attachments exceed 24 MB. Remove a file or select fewer PDF pages."
        )
    if sum(item.image_count for item in values) > MAX_PDF_PAGES:
        raise AttachmentError(
            f"Attach up to {MAX_PDF_PAGES} images or PDF pages per message."
        )
