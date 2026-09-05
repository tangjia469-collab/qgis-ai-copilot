# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Asynchronous QGIS network client for the Alpha router contract."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from qgis.PyQt.QtCore import QByteArray, QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsApplication, QgsNetworkAccessManager

from .constants import USER_AGENT
from .protocol import (
    ProtocolError,
    RouterProfile,
    SseDecoder,
    classify_router_error,
    endpoint_url,
    parse_chat_response,
    parse_model_catalog,
    parse_sse_chat_data,
    router_error_message,
)


def _request_enum(legacy_name: str, scoped_name: str):
    if hasattr(QNetworkRequest, legacy_name):
        return getattr(QNetworkRequest, legacy_name)
    return getattr(QNetworkRequest.Attribute, scoped_name)


HTTP_STATUS_ATTRIBUTE = _request_enum("HttpStatusCodeAttribute", "HttpStatusCodeAttribute")
CONTENT_TYPE_HEADER = (
    QNetworkRequest.ContentTypeHeader
    if hasattr(QNetworkRequest, "ContentTypeHeader")
    else QNetworkRequest.KnownHeaders.ContentTypeHeader
)


class RouterClient(QObject):
    catalogStarted = pyqtSignal()
    catalogLoaded = pyqtSignal(object, str)
    catalogFailed = pyqtSignal(str, str, int)

    chatStarted = pyqtSignal()
    chatDelta = pyqtSignal(str)
    chatCompleted = pyqtSignal(str, bool, object)
    chatStopped = pyqtSignal(str)
    chatFailed = pyqtSignal(str, str, int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = QgsNetworkAccessManager.instance()
        self._catalog_reply: QNetworkReply | None = None
        self._catalog_timer = QTimer(self)
        self._catalog_timer.setSingleShot(True)
        self._catalog_timer.timeout.connect(self._catalog_timeout)

        self._chat_reply: QNetworkReply | None = None
        self._chat_timer = QTimer(self)
        self._chat_timer.setSingleShot(True)
        self._chat_timer.timeout.connect(self._chat_timeout)
        self._chat_streaming = True
        self._chat_raw = bytearray()
        self._chat_decoder = SseDecoder()
        self._chat_partial = ""
        self._chat_done = False
        self._chat_cancel_requested = False
        self._chat_forced_error: tuple[str, str] | None = None

    @staticmethod
    def _status(reply: QNetworkReply) -> int:
        value = reply.attribute(HTTP_STATUS_ATTRIBUTE)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _content_type(reply: QNetworkReply) -> str:
        value = reply.header(CONTENT_TYPE_HEADER)
        return str(value or "").lower()

    def _request(self, url: str, profile: RouterProfile, accept: bytes) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(QByteArray(b"Accept"), QByteArray(accept))
        request.setRawHeader(QByteArray(b"User-Agent"), QByteArray(USER_AGENT.encode("ascii")))
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(profile.timeout_seconds * 1000)
        if profile.authcfg:
            result = QgsApplication.authManager().updateNetworkRequest(request, profile.authcfg)
            if isinstance(result, tuple):
                ok, request = result
            else:
                ok = bool(result)
            if not ok:
                raise ProtocolError("QGIS Authentication Manager could not apply the selected config.")
        return request

    def fetch_models(self, profile: RouterProfile) -> None:
        self.abort_catalog()
        try:
            url = endpoint_url(profile.base_url, "/v1/models")
            request = self._request(url, profile, b"application/json")
        except ProtocolError as exc:
            self.catalogFailed.emit("configuration", str(exc), 0)
            return

        self.catalogStarted.emit()
        reply = self._manager.get(request)
        self._catalog_reply = reply
        reply.finished.connect(lambda active=reply: self._catalog_finished(active))
        reply.sslErrors.connect(
            lambda errors, active=reply: self._catalog_ssl_errors(active, errors)
        )
        self._catalog_timer.start(profile.timeout_seconds * 1000)

    def _catalog_ssl_errors(self, reply: QNetworkReply, errors: list[Any]) -> None:
        if reply is not self._catalog_reply:
            return
        details = "; ".join(error.errorString() for error in errors[:3])
        reply.setProperty("copilot_tls_error", details or "TLS certificate validation failed.")

    def _catalog_timeout(self) -> None:
        reply = self._catalog_reply
        if reply is not None:
            reply.setProperty("copilot_timeout", True)
            reply.abort()

    def _catalog_finished(self, reply: QNetworkReply) -> None:
        if reply is not self._catalog_reply:
            reply.deleteLater()
            return
        self._catalog_timer.stop()
        self._catalog_reply = None
        status = self._status(reply)
        body = bytes(reply.readAll())
        tls_error = str(reply.property("copilot_tls_error") or "")
        timed_out = bool(reply.property("copilot_timeout"))
        network_error = reply.error() != QNetworkReply.NoError
        if tls_error:
            self.catalogFailed.emit("tls", tls_error, status)
        elif timed_out:
            self.catalogFailed.emit("timeout", "Model catalog request timed out.", status)
        elif status >= 400:
            message = router_error_message(body)
            self.catalogFailed.emit(classify_router_error(status, message), message, status)
        elif network_error:
            message = reply.errorString()
            self.catalogFailed.emit(classify_router_error(status, message, True), message, status)
        else:
            try:
                records = parse_model_catalog(body)
            except ProtocolError as exc:
                self.catalogFailed.emit("protocol", str(exc), status)
            else:
                timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self.catalogLoaded.emit(records, timestamp)
        reply.deleteLater()

    def abort_catalog(self) -> None:
        self._catalog_timer.stop()
        if self._catalog_reply is not None:
            reply = self._catalog_reply
            self._catalog_reply = None
            reply.abort()
            reply.deleteLater()

    def send_chat(self, profile: RouterProfile, payload: dict[str, Any]) -> None:
        self.abort_chat(silent=True)
        try:
            url = endpoint_url(profile.base_url, "/v1/chat/completions")
            accept = b"text/event-stream, application/json" if payload.get("stream") else b"application/json"
            request = self._request(url, profile, accept)
        except ProtocolError as exc:
            self.chatFailed.emit("configuration", str(exc), 0, "")
            return

        request.setHeader(CONTENT_TYPE_HEADER, "application/json")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._chat_streaming = bool(payload.get("stream"))
        self._chat_raw = bytearray()
        self._chat_decoder = SseDecoder()
        self._chat_partial = ""
        self._chat_done = False
        self._chat_cancel_requested = False
        self._chat_forced_error = None

        reply = self._manager.post(request, QByteArray(body))
        self._chat_reply = reply
        reply.readyRead.connect(lambda active=reply: self._chat_ready_read(active))
        reply.finished.connect(lambda active=reply: self._chat_finished(active))
        reply.sslErrors.connect(lambda errors, active=reply: self._chat_ssl_errors(active, errors))
        self._chat_timer.start(profile.timeout_seconds * 1000)
        self.chatStarted.emit()

    def _chat_uses_sse(self, reply: QNetworkReply) -> bool:
        content_type = self._content_type(reply)
        return self._chat_streaming and "application/json" not in content_type

    def _chat_ready_read(self, reply: QNetworkReply) -> None:
        if reply is not self._chat_reply:
            return
        if reply.bytesAvailable() <= 0:
            return
        chunk = bytes(reply.readAll())
        if not chunk:
            return
        status = self._status(reply)
        if status >= 400 or not self._chat_uses_sse(reply):
            self._chat_raw.extend(chunk)
            return
        try:
            for data in self._chat_decoder.feed(chunk):
                kind, value = parse_sse_chat_data(data)
                if kind == "done":
                    self._chat_done = True
                elif kind == "delta":
                    self._chat_partial += value
                    self.chatDelta.emit(value)
        except ProtocolError as exc:
            self._chat_forced_error = ("broken_stream", str(exc))
            reply.abort()

    def _chat_ssl_errors(self, reply: QNetworkReply, errors: list[Any]) -> None:
        if reply is not self._chat_reply:
            return
        details = "; ".join(error.errorString() for error in errors[:3])
        self._chat_forced_error = ("tls", details or "TLS certificate validation failed.")

    def _chat_timeout(self) -> None:
        if self._chat_reply is not None:
            self._chat_forced_error = ("timeout", "Chat request timed out.")
            self._chat_reply.abort()

    def _chat_finished(self, reply: QNetworkReply) -> None:
        if reply is not self._chat_reply:
            reply.deleteLater()
            return
        self._chat_ready_read(reply)
        self._chat_timer.stop()
        self._chat_reply = None
        status = self._status(reply)
        network_error = reply.error() != QNetworkReply.NoError

        if self._chat_cancel_requested:
            self.chatStopped.emit(self._chat_partial)
        elif self._chat_forced_error:
            kind, message = self._chat_forced_error
            self.chatFailed.emit(kind, message, status, self._chat_partial)
        elif status >= 400:
            message = router_error_message(bytes(self._chat_raw))
            self.chatFailed.emit(
                classify_router_error(status, message), message, status, self._chat_partial
            )
        elif network_error:
            message = reply.errorString()
            self.chatFailed.emit(
                classify_router_error(status, message, True), message, status, self._chat_partial
            )
        elif self._chat_uses_sse(reply):
            if not self._chat_done:
                self.chatFailed.emit(
                    "broken_stream",
                    "The streaming response ended before the [DONE] event.",
                    status,
                    self._chat_partial,
                )
            elif not self._chat_partial:
                self.chatFailed.emit("protocol", "The streaming response was empty.", status, "")
            else:
                self.chatCompleted.emit(self._chat_partial, False, {})
        else:
            try:
                content, usage = parse_chat_response(bytes(self._chat_raw))
            except ProtocolError as exc:
                self.chatFailed.emit("protocol", str(exc), status, self._chat_partial)
            else:
                self.chatCompleted.emit(content, True, usage)
        reply.deleteLater()

    def abort_chat(self, silent: bool = False) -> None:
        self._chat_timer.stop()
        if self._chat_reply is None:
            return
        reply = self._chat_reply
        if silent:
            self._chat_reply = None
            reply.abort()
            reply.deleteLater()
            return
        self._chat_cancel_requested = True
        reply.abort()

    def close(self) -> None:
        self.abort_catalog()
        self.abort_chat(silent=True)
