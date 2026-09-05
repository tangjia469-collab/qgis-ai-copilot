# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""QGIS plugin entry point."""


def classFactory(iface):  # noqa: N802 - QGIS plugin API name
    from .plugin import QgisAiCopilotPlugin

    return QgisAiCopilotPlugin(iface)
