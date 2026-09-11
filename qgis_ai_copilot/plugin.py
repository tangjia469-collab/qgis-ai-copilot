# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""QGIS plugin lifecycle."""

from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QStyle
from qgis.core import QgsApplication

from .constants import PLUGIN_NAME
from .dock import CopilotDock


def _assist_icon(iface) -> QIcon:
    icon = QIcon(str(Path(__file__).with_name("icon.svg")))
    if not icon.isNull():
        return icon
    icon = QgsApplication.getThemeIcon("/mActionChat.svg")
    if not icon.isNull():
        return icon
    return iface.mainWindow().style().standardIcon(QStyle.SP_MessageBoxInformation)


class QgisAiCopilotPlugin:
    def __init__(self, iface) -> None:
        self.iface = iface
        self.action: QAction | None = None
        self.dock: CopilotDock | None = None

    def initGui(self) -> None:  # noqa: N802 - QGIS plugin API name
        self.action = QAction(_assist_icon(self.iface), "Assist", self.iface.mainWindow())
        self.action.setObjectName("QgisAiCopilotAssistAction")
        self.action.setIconText("Assist")
        self.action.setIconVisibleInMenu(True)
        self.action.setCheckable(True)
        self.action.setToolTip("Open Assist")
        self.action.setStatusTip("Open or hide the QGIS AI Copilot assistant panel")
        self.action.triggered.connect(self._set_visible)
        self.iface.addPluginToMenu(f"&{PLUGIN_NAME}", self.action)
        self.iface.addToolBarIcon(self.action)

        self.dock = CopilotDock(self.iface, self.iface.mainWindow())
        self.dock.visibilityChanged.connect(self.action.setChecked)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.action.setChecked(True)

    def _set_visible(self, visible: bool) -> None:
        if self.dock is None:
            return
        self.dock.setVisible(visible)
        if visible:
            self.dock.raise_()

    def unload(self) -> None:
        if self.action is not None:
            self.iface.removePluginMenu(f"&{PLUGIN_NAME}", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.dock is not None:
            self.dock.close_plugin()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
