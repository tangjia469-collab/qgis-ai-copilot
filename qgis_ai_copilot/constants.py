# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Shared constants for QGIS AI Copilot."""

PLUGIN_ID = "qgis_ai_copilot"
PLUGIN_NAME = "QGIS AI Copilot"
PLUGIN_VERSION = "0.4.0-alpha"
SETTINGS_PREFIX = "qgis_ai_copilot"
SCHEMA_VERSION = 1

DEFAULT_HISTORY_RETENTION_DAYS = 30
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_CHARACTERS = 32_000
MAX_USER_MESSAGE_CHARACTERS = 12_000

THINKING_VALUES = (
    "Auto",
    "None",
    "Minimal",
    "Low",
    "Medium",
    "High",
    "XHigh",
    "Max",
)

DEFAULT_CONTEXT_KEYS = ("active_layer", "fields", "selection", "canvas")
USER_AGENT = f"QGIS-AI-Copilot/{PLUGIN_VERSION}"
