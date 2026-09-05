# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Pure protocol helpers for the Alpha Chat Completions adapter."""

from __future__ import annotations

import codecs
import json
import base64
import binascii
from dataclasses import asdict, dataclass
from copy import deepcopy
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from .constants import MAX_HISTORY_CHARACTERS, MAX_HISTORY_MESSAGES, THINKING_VALUES
from .attachments import MAX_TOTAL_ATTACHMENT_BYTES, MAX_ATTACHMENT_BYTES, MAX_PDF_PAGES, IMAGE_MIME_TYPES, AttachmentError, image_mime


class ProtocolError(ValueError):
    """Raised when a router payload does not match the Alpha contract."""


@dataclass(frozen=True)
class RouterProfile:
    name: str = "Router"
    base_url: str = ""
    authcfg: str = ""
    streaming: bool = True
    timeout_seconds: int = 90
    chat_idle_timeout_seconds: int = 600

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "RouterProfile":
        value = value or {}
        try:
            timeout = int(value.get("timeout_seconds", 90))
        except (TypeError, ValueError):
            timeout = 90
        try:
            chat_idle = int(value.get("chat_idle_timeout_seconds", 600))
        except (TypeError, ValueError):
            chat_idle = 600
        return cls(
            name=str(value.get("name") or "Router").strip() or "Router",
            base_url=str(value.get("base_url") or "").strip(),
            authcfg=str(value.get("authcfg") or "").strip(),
            streaming=bool(value.get("streaming", True)),
            timeout_seconds=max(10, min(timeout, 600)),
            chat_idle_timeout_seconds=max(30, min(chat_idle, 3600)),
        )


@dataclass(frozen=True)
class ModelRecord:
    id: str
    owned_by: str = ""
    explicit_thinking: tuple[str, ...] = ()
    supports_images: bool | None = None


def normalized_base_url(base_url: str) -> str:
    candidate = base_url.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProtocolError("Base URL must be an http(s) URL with a host.")
    if parsed.username is not None or parsed.password is not None:
        raise ProtocolError("Base URL credentials must use QGIS Authentication Manager.")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ProtocolError("Remote router Base URLs must use HTTPS.")
    if parsed.query or parsed.fragment:
        raise ProtocolError("Base URL must not contain a query or fragment.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def normalized_external_link(url: str) -> tuple[str, str]:
    """Validate a model-supplied link before offering to open it."""

    candidate = url.strip()
    if not candidate or any(ord(character) < 32 for character in candidate):
        raise ProtocolError("The link is empty or malformed.")
    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ProtocolError("Only http and https links can be opened.")
    if scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ProtocolError("Remote links must use HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ProtocolError("Links containing credentials are blocked.")
    try:
        parsed.port
    except ValueError as exc:
        raise ProtocolError("The link contains an invalid port.") from exc
    normalized = urlunsplit(
        (scheme, parsed.netloc, parsed.path or "/", parsed.query, parsed.fragment)
    )
    return normalized, parsed.hostname


def endpoint_url(base_url: str, endpoint: str) -> str:
    base = normalized_base_url(base_url)
    path = "/" + endpoint.lstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return base + path


def _normalize_explicit_thinking(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    lookup = {value.lower(): value for value in THINKING_VALUES if value != "Auto"}
    normalized: list[str] = []
    for value in values:
        match = lookup.get(str(value).replace("_", "").replace("-", "").lower())
        if match and match not in normalized:
            normalized.append(match)
    return tuple(normalized)


def parse_model_catalog(payload: bytes | str | dict[str, Any]) -> list[ModelRecord]:
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("Model catalog is not valid UTF-8.") from exc
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProtocolError("Model catalog is not valid JSON.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ProtocolError("Model catalog must contain a data list.")

    records: list[ModelRecord] = []
    seen: set[str] = set()
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        explicit = ()
        for key in (
            "supported_reasoning_efforts",
            "reasoning_efforts",
            "supported_thinking_levels",
        ):
            if key in item:
                explicit = _normalize_explicit_thinking(item[key])
                break
        records.append(
            ModelRecord(
                id=model_id,
                owned_by=str(item.get("owned_by") or ""),
                explicit_thinking=explicit,
                supports_images=_image_capability(item),
            )
        )
    if not records:
        raise ProtocolError("Model catalog is empty.")
    return records


def _image_capability(item: dict[str, Any]) -> bool | None:
    modalities = item.get("input_modalities")
    if modalities is None and isinstance(item.get("architecture"), dict):
        modalities = item["architecture"].get("input_modalities")
    if isinstance(modalities, list) and modalities and all(isinstance(value, str) for value in modalities):
        return "image" in modalities
    return None


def thinking_api_value(value: str) -> str:
    if value not in THINKING_VALUES or value == "Auto":
        raise ProtocolError(f"Unsupported explicit Thinking value: {value}")
    return value.lower()


def _canonical_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or not content:
        raise ProtocolError("Conversation message content must be text or content parts.")
    canonical: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            raise ProtocolError("Conversation content parts must be objects.")
        kind = str(part.get("type") or "")
        if kind == "text":
            text = part.get("text")
            if not isinstance(text, str) or not text:
                raise ProtocolError("Text content parts must contain text.")
            canonical.append({"type": "text", "text": text})
            continue
        if kind == "image_url":
            image_url = part.get("image_url")
            if not isinstance(image_url, dict):
                raise ProtocolError("Image content parts must contain an image_url object.")
            url = image_url.get("url")
            if not isinstance(url, str) or not url.startswith("data:image/"):
                raise ProtocolError("Image attachments must use an inline image data URL.")
            if len(url) > MAX_TOTAL_ATTACHMENT_BYTES:
                raise ProtocolError("Image payload exceeds 24 MB.")
            prefix, separator, encoded = url.partition(",")
            mime = prefix[5:].removesuffix(";base64")
            if not separator or mime not in IMAGE_MIME_TYPES or not prefix.endswith(";base64"):
                raise ProtocolError("Image data URL has an unsupported MIME type or encoding.")
            try:
                decoded = base64.b64decode(encoded, validate=True)
                if len(decoded) > MAX_ATTACHMENT_BYTES:
                    raise AttachmentError("Each image must be 12 MB or smaller.")
                if image_mime(decoded) != mime:
                    raise AttachmentError("Image type does not match its content.")
            except (ValueError, binascii.Error, AttachmentError) as exc:
                raise ProtocolError("Image data URL is invalid or has the wrong image type.") from exc
            canonical.append(
                {
                    "type": "image_url",
                    "image_url": {"url": url},
                }
            )
            continue
        raise ProtocolError(f"Unsupported conversation content part: {kind or 'unknown'}.")
    return canonical


def build_chat_payload(
    model: str,
    messages: Iterable[dict[str, Any]],
    thinking: str = "Auto",
    stream: bool = True,
) -> dict[str, Any]:
    model = model.strip()
    if not model:
        raise ProtocolError("A model must be selected.")
    canonical: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ProtocolError("Conversation messages must be objects.")
        role = str(message.get("role") or "")
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            raise ProtocolError("Conversation message role or content is invalid.")
        if isinstance(content, list) and role != "user":
            raise ProtocolError("Visual attachments belong to user messages only.")
        canonical.append({"role": role, "content": deepcopy(_canonical_content(content))})
    if not canonical:
        raise ProtocolError("Conversation is empty.")
    total_bytes = sum(_visual_size(message.get("content"))[0] for message in canonical)
    total_images = sum(_visual_size(message.get("content"))[1] for message in canonical)
    if total_bytes > MAX_TOTAL_ATTACHMENT_BYTES or total_images > MAX_PDF_PAGES:
        raise ProtocolError("This request exceeds 24 MB or 20 image/PDF pages. Remove attachments or start a new chat.")

    payload: dict[str, Any] = {
        "model": model,
        "messages": canonical,
        "stream": bool(stream),
    }
    if thinking != "Auto":
        payload["reasoning_effort"] = thinking_api_value(thinking)
    return payload


def bounded_chat_history(
    messages: Iterable[dict[str, Any]],
    max_messages: int = MAX_HISTORY_MESSAGES,
    max_characters: int = MAX_HISTORY_CHARACTERS,
) -> list[dict[str, Any]]:
    """Return the newest contiguous history window within fixed request bounds."""

    canonical = list(messages)
    selected: list[dict[str, Any]] = []
    characters = 0
    visual_bytes = 0
    images = 0
    for message in reversed(canonical):
        content = message.get("content", "")
        content_length = len(_content_text(content))
        byte_count, image_count = _visual_size(content)
        over_limit = characters + content_length > max_characters or visual_bytes + byte_count > MAX_TOTAL_ATTACHMENT_BYTES or images + image_count > MAX_PDF_PAGES
        if not selected and over_limit:
            raise ProtocolError("The current message exceeds the text or attachment limit.")
        if len(selected) >= max_messages or over_limit:
            break
        selected.append(message)
        characters += content_length
        visual_bytes += byte_count
        images += image_count
    selected.reverse()
    return selected


def _visual_size(content: Any) -> tuple[int, int]:
    if not isinstance(content, list):
        return 0, 0
    urls = [part.get("image_url", {}).get("url", "") for part in content if isinstance(part, dict) and part.get("type") == "image_url" and isinstance(part.get("image_url"), dict)]
    return sum(len(url) for url in urls if isinstance(url, str)), len(urls)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""


def parse_chat_response(payload: bytes | str | dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("Chat response is not valid UTF-8.") from exc
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProtocolError("Chat response is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("Chat response must be a JSON object.")
    if isinstance(payload.get("error"), dict):
        raise ProtocolError(str(payload["error"].get("message") or "Router returned an error."))
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProtocolError("Chat response does not contain a choice.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ProtocolError("Chat response does not contain a message.")
    content = _content_text(message.get("content"))
    if not content:
        raise ProtocolError("Chat response message is empty.")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return content, usage


class SseDecoder:
    """Incrementally splits UTF-8 server-sent events into data payloads."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._buffer = ""
        self._data_lines: list[str] = []

    def feed(self, chunk: bytes) -> list[str]:
        self._buffer += self._decoder.decode(chunk)
        output: list[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if not line:
                if self._data_lines:
                    output.append("\n".join(self._data_lines))
                    self._data_lines.clear()
                continue
            if line.startswith(":"):
                continue
            if line == "data":
                self._data_lines.append("")
            elif line.startswith("data:"):
                value = line[5:]
                if value.startswith(" "):
                    value = value[1:]
                self._data_lines.append(value)
        return output

    @property
    def has_incomplete_event(self) -> bool:
        return bool(self._buffer or self._data_lines)


def parse_sse_chat_data(data: str) -> tuple[str, Any]:
    if data.strip() == "[DONE]":
        return "done", None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Streaming response contains invalid JSON.") from exc
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        raise ProtocolError(str(payload["error"].get("message") or "Router stream failed."))
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return "noop", None
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        return "noop", None
    content = _content_text(delta.get("content"))
    return ("delta", content) if content else ("noop", None)


def router_error_message(payload: bytes | str) -> str:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    text = payload.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            error = value.get("error")
            if isinstance(error, dict) and error.get("message"):
                text = str(error["message"])
            elif value.get("message"):
                text = str(value["message"])
    except (json.JSONDecodeError, TypeError):
        pass
    return " ".join(text.split())[:500] or "The router returned an empty error response."


def classify_router_error(status: int, message: str, network_error: bool = False) -> str:
    lower = message.lower()
    if network_error and any(word in lower for word in ("ssl", "tls", "certificate")):
        return "tls"
    if network_error:
        return "network"
    if status in {401, 403}:
        return "authentication"
    if status == 404:
        return "protocol"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "server"
    if status == 400 and ("reasoning_effort" in lower or "reasoning effort" in lower):
        return "thinking_unsupported"
    if 400 <= status < 500:
        return "request"
    return "protocol"
