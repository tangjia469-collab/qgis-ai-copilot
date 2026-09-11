# SPDX-License-Identifier: GPL-3.0-or-later
"""Async loopback-only memory transport, separate from router authentication."""

import json
import time

from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest

from .everos_protocol import MAX_RESPONSE_BYTES, note_request, search_request, search_result

SEARCH_TIMEOUT_MS = 15000
ADD_TIMEOUT_MS = 30000
FLUSH_TIMEOUT_MS = 120000


class EverosClient(QObject):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str, bool)
    progress = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.manager.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))
        self._state = None
        self._reply = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self._fail("EverOS request timed out."))

    @property
    def busy(self):
        return self._state is not None

    def _begin(self, config, write=False, **data):
        if self.busy:
            raise ValueError("An EverOS operation is already active.")
        config.validate()
        self._state = {"config": config, "write": write, "accepted": False, **data}

    def check(self, config):
        self._begin(config)
        self._request("health", "/health", None, SEARCH_TIMEOUT_MS)

    def search(self, config, query):
        body = search_request(config, query)
        self._begin(config, query=query)
        self._request("search", "/api/v1/memory/search", body, SEARCH_TIMEOUT_MS)

    def remember(self, config, note, session_id):
        body = note_request(config, session_id, note, int(time.time() * 1000))
        self._begin(config, write=True, session_id=session_id)
        self._request("add", "/api/v1/memory/add", body, ADD_TIMEOUT_MS)

    def _request(self, phase, path, body, timeout):
        state = self._state
        state.update(phase=phase, buffer=bytearray())
        request = QNetworkRequest(QUrl(state["config"].base_url.rstrip("/") + path))
        request.setAttribute(
            QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy
        )
        request.setRawHeader(b"Accept", b"application/json")
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(timeout + 1000)
        # Do not use QgsNetworkAccessManager or the router's auth configuration.
        reply = (
            self.manager.get(request)
            if body is None
            else self.manager.post(request, json.dumps(body, ensure_ascii=False).encode())
        )
        self._reply = reply
        reply.setReadBufferSize(MAX_RESPONSE_BYTES + 1)
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finished(reply))
        self.timer.start(timeout)
        self.progress.emit(
            {
                "health": "Checking local EverOS…",
                "search": "Searching local EverOS…",
                "add": "Sending your note to EverOS…",
                "flush": "Extracting the memory note…",
            }[phase]
        )

    def _read(self, reply):
        if reply is not self._reply or self._state is None:
            return
        data = self._state["buffer"]
        data.extend(bytes(reply.readAll()))
        if len(data) > MAX_RESPONSE_BYTES:
            self._fail("EverOS response exceeded the supported size limit.")

    def _finished(self, reply):
        if reply is not self._reply or self._state is None:
            return
        self._read(reply)
        if reply is not self._reply:
            return
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0
        if 300 <= status < 400:
            self._fail("EverOS redirects are not allowed.")
            return
        if reply.error() != QNetworkReply.NoError or not 200 <= status < 300:
            definite_no_send = (
                reply.error()
                in {
                    QNetworkReply.ConnectionRefusedError,
                    QNetworkReply.HostNotFoundError,
                    QNetworkReply.SslHandshakeFailedError,
                }
                and not self._state["accepted"]
            )
            self._fail(
                f"EverOS connection failed (HTTP {status}). Check the local service.",
                uncertain=False if definite_no_send else None,
            )
            return
        state = self._state
        self.timer.stop()
        self._reply = None
        reply.deleteLater()
        try:
            response = json.loads(bytes(state.pop("buffer")).decode("utf-8"))
            if not isinstance(response, dict):
                raise ValueError("EverOS returned an unexpected response.")
            phase = state["phase"]
            if phase == "health":
                if response.get("status") != "ok":
                    raise ValueError("EverOS health check did not report ready.")
                result = {"ok": True, "status": "connected"}
            elif phase == "search":
                result = search_result(state["config"], state["query"], response)
            else:
                data = response.get("data")
                if not isinstance(data, dict):
                    raise ValueError("EverOS did not confirm the memory operation.")
                if phase == "add":
                    if (
                        type(data.get("message_count")) is not int
                        or data.get("message_count") != 1
                        or data.get("status")
                        not in {
                            "accumulated",
                            "extracted",
                        }
                    ):
                        raise ValueError("EverOS did not confirm the note was accepted.")
                    state["accepted"] = True
                    if data["status"] == "accumulated":
                        config = state["config"]
                        self._request(
                            "flush",
                            "/api/v1/memory/flush",
                            {
                                "session_id": state["session_id"],
                                "app_id": config.app_id,
                                "project_id": config.project_id,
                            },
                            FLUSH_TIMEOUT_MS,
                        )
                        return
                    result = {"ok": True, "status": "saved", "indexed": False}
                else:
                    if data.get("status") not in {"extracted", "no_extraction"}:
                        raise ValueError("EverOS did not confirm memory extraction.")
                    result = {
                        "ok": True,
                        "status": "saved" if data["status"] == "extracted" else "no_extraction",
                        "indexed": data.get("derived_settled") is True,
                    }
                result["session_id"] = state["session_id"]
        except (ValueError, UnicodeError, RecursionError):
            self._fail("EverOS returned an unexpected or incomplete response.")
            return
        self._state = None
        self.completed.emit(result)

    def _fail(self, message, uncertain=None):
        if self._state is None:
            return
        if uncertain is None:
            uncertain = self._state["write"]
        self.cancel()
        self.failed.emit(message, bool(uncertain))

    def cancel(self):
        self.timer.stop()
        reply = self._reply
        self._reply = None
        self._state = None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def close(self):
        self.cancel()
