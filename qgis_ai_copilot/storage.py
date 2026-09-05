# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Local, project-bound conversation storage with atomic writes."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .constants import DEFAULT_HISTORY_RETENTION_DAYS, SCHEMA_VERSION


_PERSISTED_REQUEST_KEYS = {
    "attachments",
    "router_id",
    "profile_name",
    "model",
    "thinking",
    "stream",
    "context",
    "context_keys",
    "user_message_id",
    "adapter",
    "reasoning_summaries",
}
_ATTACHMENT_MANIFEST_KEYS = {
    "id",
    "name",
    "mime_type",
    "source_kind",
    "size",
    "sha256",
    "page_count",
    "pages",
}
_SENSITIVE_CONTEXT_KEYS = {
    "api_key",
    "apikey",
    "authcfg",
    "authorization",
    "credential",
    "credentials",
    "headers",
    "password",
    "path",
    "secret",
    "source",
    "token",
    "uri",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact_context_text(value: str) -> str:
    value = re.sub(r"(?i)data:(?:image|application)/[^\s,]+,[A-Za-z0-9+/=]*", "[attachment data redacted]", value)
    value = re.sub(r"[A-Za-z0-9+/]{160,}={0,2}", "[encoded data redacted]", value)
    value = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [redacted]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[redacted]", value)
    value = re.sub(
        r"((?:[?&]|\b)(?:key|token|api_key|password|secret)\s*[:=]\s*)[^&\s]+",
        r"\1[redacted]",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"(?i)(?:file://)?(?:/Users|/home|/private|/Volumes|/tmp)/[^\s,;]+",
        "[path redacted]",
        value,
    )
    value = re.sub(r"\b[A-Za-z]:\\[^\r\n,;]+", "[path redacted]", value)
    return value


def _sanitize_context_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_context_value(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_CONTEXT_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_context_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_context_value(item) for item in value]
    if isinstance(value, str):
        return _redact_context_text(value)
    return value


def _sanitize_attachment_manifests(value: Any) -> list[dict[str, Any]]:
    """Persist only non-secret attachment metadata, never bytes or paths."""

    if not isinstance(value, list):
        return []
    manifests: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        manifest: dict[str, Any] = {}
        for key in _ATTACHMENT_MANIFEST_KEYS:
            raw = item.get(key)
            if key in {"id", "name", "mime_type", "source_kind", "sha256"}:
                if isinstance(raw, str) and raw:
                    if key == "name":
                        raw = raw.replace("\\", "/").split("/")[-1]
                    manifest[key] = _redact_context_text(raw)[:512]
            elif key in {"size", "page_count"}:
                try:
                    number = int(raw)
                except (TypeError, ValueError):
                    continue
                if number >= 0:
                    manifest[key] = number
            elif key == "pages" and isinstance(raw, list):
                manifest[key] = [page for page in raw[:20] if isinstance(page, int) and not isinstance(page, bool) and page > 0]
        if manifest.get("id") and manifest.get("name") and manifest.get("mime_type"):
            manifests.append(manifest)
    return manifests


def sanitized_activity(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    output = []
    remaining = 24000
    for item in value[:40]:
        if not isinstance(item, dict) or item.get("kind") not in {"local", "commentary", "summary"}:
            continue
        raw = item.get("text")
        if not isinstance(raw, str) or not raw:
            continue
        text = _redact_context_text(raw)[:min(8000, remaining)]
        if not text:
            break
        identity = re.sub(r"[^A-Za-z0-9_.:-]", "", str(item.get("id") or ""))[:160]
        output.append({"id": identity or str(len(output)), "kind": item["kind"], "text": text})
        remaining -= len(text)
    return output


def sanitized_conversation(conversation: dict[str, Any]) -> dict[str, Any]:
    """Copy a conversation while enforcing a narrow persisted request schema."""

    value = deepcopy(conversation)
    messages = value.get("messages")
    if not isinstance(messages, list):
        value["messages"] = []
        return value
    for message in messages:
        if not isinstance(message, dict):
            continue
        if isinstance(message.get("request"), dict):
            request = message["request"]
            safe_request = {
                key: deepcopy(request[key]) for key in _PERSISTED_REQUEST_KEYS if key in request
            }
            if "context" in safe_request:
                safe_request["context"] = _sanitize_context_value(safe_request["context"])
            if "attachments" in safe_request:
                safe_request["attachments"] = _sanitize_attachment_manifests(
                    safe_request["attachments"]
                )
            message["request"] = safe_request
        if "attachments" in message:
            message["attachments"] = _sanitize_attachment_manifests(message["attachments"])
        if "activity" in message:
            message["activity"] = sanitized_activity(message["activity"])
        if isinstance(message.get("tool_result"), dict):
            tool_result = _sanitize_context_value(message["tool_result"])
            if tool_result.get("tool") == "explain_processing_error" and isinstance(
                tool_result.get("result"), dict
            ):
                tool_result["result"].pop("error", None)
                tool_result["result"]["original_error_included"] = False
            message["tool_result"] = tool_result
        if isinstance(message.get("error"), dict):
            message["error"] = _sanitize_context_value(message["error"])
    return value


def _sanitized_project(project_id: str, value: dict[str, Any]) -> dict[str, Any]:
    conversations = value.get("conversations")
    return {
        "schema": SCHEMA_VERSION,
        "project_id": project_id,
        "conversations": [
            sanitized_conversation(item)
            for item in conversations
            if isinstance(item, dict)
        ]
        if isinstance(conversations, list)
        else [],
    }


class ConversationStore:
    def __init__(
        self,
        root: str | os.PathLike[str],
        retention_days: int = DEFAULT_HISTORY_RETENTION_DAYS,
    ) -> None:
        self.root = Path(root)
        self.retention_days = max(1, min(int(retention_days), 365))
        self._ensure_root()

    def _ensure_root(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def set_retention_days(self, days: int) -> None:
        self.retention_days = max(1, min(int(days), 365))

    def _is_expired(self, conversation: dict[str, Any], now: datetime) -> bool:
        raw = conversation.get("updated_at") or conversation.get("created_at")
        if not isinstance(raw, str):
            return True
        try:
            timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return True
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp < now - timedelta(days=self.retention_days)

    def _prune(self, value: dict[str, Any]) -> bool:
        conversations = value.get("conversations")
        if not isinstance(conversations, list):
            return False
        now = datetime.now(timezone.utc)
        retained = [
            item
            for item in conversations
            if isinstance(item, dict) and not self._is_expired(item, now)
        ]
        changed = len(retained) != len(conversations)
        value["conversations"] = retained
        return changed

    def _path(self, project_id: str) -> Path:
        safe_id = "".join(ch for ch in project_id if ch.isalnum() or ch in "-_")
        if not safe_id:
            raise ValueError("Project identity is empty.")
        return self.root / f"{safe_id}.json"

    def _empty(self, project_id: str) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "project_id": project_id,
            "conversations": [],
        }

    def read_project(self, project_id: str) -> dict[str, Any]:
        path = self._path(project_id)
        if not path.exists():
            return self._empty(project_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return self._empty(project_id)
        if not isinstance(value, dict) or not isinstance(value.get("conversations"), list):
            return self._empty(project_id)
        sanitized = _sanitized_project(project_id, value)
        changed = sanitized != value
        value = sanitized
        if self._prune(value):
            changed = True
        if changed:
            self._write_project(project_id, value)
        return value

    def _write_project(self, project_id: str, value: dict[str, Any]) -> None:
        self._ensure_root()
        target = self._path(project_id)
        value = _sanitized_project(project_id, value)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=self.root)
        try:
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list_conversations(self, project_id: str) -> list[dict[str, Any]]:
        conversations = self.read_project(project_id)["conversations"]
        return sorted(
            (deepcopy(item) for item in conversations if isinstance(item, dict)),
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )

    def create_conversation(self, project_id: str, title: str = "New chat") -> dict[str, Any]:
        now = utc_now()
        conversation = {
            "id": uuid.uuid4().hex,
            "title": title.strip()[:80] or "New chat",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        project = self.read_project(project_id)
        project["conversations"].append(conversation)
        self._write_project(project_id, project)
        return deepcopy(conversation)

    def load_conversation(self, project_id: str, conversation_id: str) -> dict[str, Any] | None:
        for conversation in self.read_project(project_id)["conversations"]:
            if isinstance(conversation, dict) and conversation.get("id") == conversation_id:
                return deepcopy(conversation)
        return None

    def save_conversation(self, project_id: str, conversation: dict[str, Any]) -> None:
        value = sanitized_conversation(conversation)
        value["updated_at"] = utc_now()
        project = self.read_project(project_id)
        self._prune(project)
        replaced = False
        for index, existing in enumerate(project["conversations"]):
            if isinstance(existing, dict) and existing.get("id") == value.get("id"):
                project["conversations"][index] = value
                replaced = True
                break
        if not replaced:
            project["conversations"].append(value)
        self._write_project(project_id, project)

    def clear_project(self, project_id: str) -> None:
        path = self._path(project_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def purge_expired(self) -> int:
        removed = 0
        for path in self.root.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict) or not isinstance(value.get("conversations"), list):
                continue
            before = len(value["conversations"])
            sanitized = _sanitized_project(path.stem, value)
            changed = sanitized != value
            value = sanitized
            if self._prune(value):
                changed = True
            if changed:
                self._write_project(path.stem, value)
            removed += before - len(value["conversations"])
        return removed

    def rebind_project(self, previous_id: str, project_id: str) -> None:
        if previous_id == project_id:
            return
        previous = self.read_project(previous_id)
        if not previous["conversations"]:
            return
        current = self.read_project(project_id)
        existing_ids = {
            item.get("id") for item in current["conversations"] if isinstance(item, dict)
        }
        for item in previous["conversations"]:
            if isinstance(item, dict) and item.get("id") not in existing_ids:
                current["conversations"].append(item)
        self._write_project(project_id, current)
