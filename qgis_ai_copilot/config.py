# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""QGIS-backed non-secret settings for one Alpha router profile."""

from __future__ import annotations

import json
from typing import Any

from qgis.core import QgsSettings

from .constants import DEFAULT_HISTORY_RETENTION_DAYS, SETTINGS_PREFIX, THINKING_VALUES
from .protocol import RouterProfile


class PluginSettings:
    def __init__(self, settings: QgsSettings | None = None) -> None:
        self.settings = settings or QgsSettings()

    def _key(self, suffix: str) -> str:
        return f"{SETTINGS_PREFIX}/{suffix}"

    def profile(self) -> RouterProfile:
        raw = self.settings.value(self._key("router_profile"), "")
        try:
            value = json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            value = {}
        return RouterProfile.from_dict(value)

    def save_profile(self, profile: RouterProfile) -> None:
        if self._router_identity(self.profile()) != self._router_identity(profile):
            self.clear_context_trust()
        self.settings.setValue(
            self._key("router_profile"),
            json.dumps(profile.to_dict(), separators=(",", ":")),
        )

    @staticmethod
    def _router_identity(profile: RouterProfile) -> dict[str, str]:
        return {
            "base_url": profile.base_url.rstrip("/"),
            "authcfg": profile.authcfg,
        }

    def is_context_trusted(self, profile: RouterProfile) -> bool:
        identity = self._router_identity(profile)
        if not identity["base_url"]:
            return False
        raw = self.settings.value(self._key("context_trust"), "")
        try:
            value = json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            return False
        return (
            isinstance(value, dict)
            and set(value) == {"base_url", "authcfg"}
            and value == identity
        )

    def trust_context(self, profile: RouterProfile) -> None:
        identity = self._router_identity(profile)
        if not identity["base_url"]:
            self.clear_context_trust()
            return
        self.settings.setValue(
            self._key("context_trust"),
            json.dumps(identity, separators=(",", ":"), sort_keys=True),
        )

    def clear_context_trust(self) -> None:
        self.settings.remove(self._key("context_trust"))

    def selected_model(self) -> str:
        return str(self.settings.value(self._key("selected_model"), "") or "")

    def save_selected_model(self, model_id: str) -> None:
        self.settings.setValue(self._key("selected_model"), model_id)

    def selected_thinking(self) -> str:
        value = str(self.settings.value(self._key("selected_thinking"), "Auto") or "Auto")
        return value if value in THINKING_VALUES else "Auto"

    def save_selected_thinking(self, value: str) -> None:
        self.settings.setValue(
            self._key("selected_thinking"), value if value in THINKING_VALUES else "Auto"
        )

    def capabilities(self) -> dict[str, list[str]]:
        raw = self.settings.value(self._key("model_capabilities"), "")
        try:
            value = json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[str]] = {}
        valid = set(THINKING_VALUES) - {"Auto"}
        for model_id, entries in value.items():
            if not isinstance(entries, list):
                continue
            result[str(model_id)] = [str(entry) for entry in entries if str(entry) in valid]
        return result

    def save_capabilities(self, value: dict[str, list[str]]) -> None:
        self.settings.setValue(
            self._key("model_capabilities"),
            json.dumps(value, separators=(",", ":"), sort_keys=True),
        )

    def history_retention_days(self) -> int:
        raw = self.settings.value(
            self._key("history_retention_days"), DEFAULT_HISTORY_RETENTION_DAYS
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = DEFAULT_HISTORY_RETENTION_DAYS
        return max(1, min(value, 365))

    def save_history_retention_days(self, days: int) -> None:
        self.settings.setValue(
            self._key("history_retention_days"), max(1, min(int(days), 365))
        )

    def thinking_values_for(
        self, model_id: str, explicit_values: tuple[str, ...] = ()
    ) -> list[str]:
        configured = self.capabilities().get(model_id, [])
        source = list(explicit_values) if explicit_values else configured
        return ["Auto", *source]

    def sanitized_summary(self) -> dict[str, Any]:
        profile = self.profile()
        return {
            "profile_name": profile.name,
            "base_url_configured": bool(profile.base_url),
            "auth_reference_configured": bool(profile.authcfg),
            "adapter": "chat_completions",
            "streaming": profile.streaming,
            "selected_model": self.selected_model(),
            "selected_thinking": self.selected_thinking(),
            "history_retention_days": self.history_retention_days(),
            "automatic_context_send": self.is_context_trusted(profile),
        }
