"""Offscreen QGIS smoke test. Run with the bundled QGIS Python environment."""

import gc
import json
import os
import sys
import tempfile
from unittest.mock import patch

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtWidgets import QMainWindow, QMessageBox
from qgis.analysis import QgsNativeAlgorithms
from qgis.core import QgsApplication
from qgis.gui import QgsMapCanvas

from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.dialogs import ContextDialog, RouterSettingsDialog
from qgis_ai_copilot.protocol import RouterProfile
from qgis_ai_copilot.widgets import SafeTextBrowser
from tests.qgis_runtime import configure_prefix, synthetic_project


class FakeIface(QObject):
    currentLayerChanged = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.window = QMainWindow()
        self.canvas = QgsMapCanvas(self.window)
        self.window.setCentralWidget(self.canvas)
        self._active_layer = None
        self.toolbar_actions = []

    def mainWindow(self):  # noqa: N802
        return self.window

    def mapCanvas(self):  # noqa: N802
        return self.canvas

    def activeLayer(self):  # noqa: N802
        return self._active_layer

    def set_active_layer(self, layer):
        self._active_layer = layer
        self.currentLayerChanged.emit(layer)

    def addDockWidget(self, area, dock):  # noqa: N802
        self.window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):  # noqa: N802
        self.window.removeDockWidget(dock)

    def addPluginToMenu(self, *args):  # noqa: N802
        pass

    def removePluginMenu(self, *args):  # noqa: N802
        pass

    def addToolBarIcon(self, action):  # noqa: N802
        self.toolbar_actions.append(action)

    def removeToolBarIcon(self, action):  # noqa: N802
        if action in self.toolbar_actions:
            self.toolbar_actions.remove(action)


def main() -> int:
    temporary = tempfile.TemporaryDirectory()
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = temporary.name
    configure_prefix()
    app = QgsApplication([arg.encode("utf-8") for arg in sys.argv], True)
    app.initQgis()
    native_provider = None
    if QgsApplication.processingRegistry().algorithmById("native:checkvalidity") is None:
        native_provider = QgsNativeAlgorithms()
        QgsApplication.processingRegistry().addProvider(native_provider)
    project, active = synthetic_project()
    iface = FakeIface()
    iface.canvas.setLayers(list(project.mapLayers().values()))
    iface.set_active_layer(active)
    plugin = QgisAiCopilotPlugin(iface)
    plugin.initGui()
    dock = plugin.dock
    assert dock is not None
    assert plugin.action is not None
    assert plugin.action.text() == "Assist"
    assert plugin.action.iconText() == "Assist"
    assert plugin.action.toolTip() == "Open Assist"
    assert not plugin.action.icon().isNull()
    assert plugin.action in iface.toolbar_actions
    iface.window.resize(1100, 760)
    iface.window.show()
    app.processEvents()

    snapshot = dock.collector.snapshot(set(dock.attached_keys), [])
    encoded = json.dumps(snapshot, ensure_ascii=False)
    overview = dock.collector.snapshot({"project_overview"}, [])
    inventory = dock.collector.snapshot({"layer_inventory"}, [])
    unrelated = next(
        layer.name() for layer in project.mapLayers().values() if layer.name() != active.name()
    )
    assert dock.objectName() == "QgisAiCopilotDock"
    assert dock.model_button.height() >= 30
    assert "project_overview" not in snapshot
    assert "layer_inventory" not in snapshot
    assert unrelated not in encoded
    assert overview["project_overview"]["name"] == "Synthetic test project"
    assert "layer_inventory" not in overview
    assert len(inventory["layer_inventory"]) == len(project.mapLayers())
    assert snapshot["active_layer"]["name"] == "example_polygons"
    assert "source" not in encoded.lower()
    assert snapshot["privacy"]["exact_coordinates"] is False
    assert dock.collector.run_tool("check_crs_consistency")["risk"] == "R0 read-only"
    explained = dock.collector.run_tool(
        "explain_processing_error",
        error_text="Geometry failed at /Users/private/data.gpkg with Bearer secret-token",
    )
    explained_json = json.dumps(explained)
    assert explained["result"]["original_error_included"] is False
    assert "/Users/private" not in explained_json
    assert "secret-token" not in explained_json

    fixture_profile = RouterProfile(
        name="Fixture Router",
        base_url="https://router.example",
        authcfg="fixture-auth",
        streaming=True,
        timeout_seconds=90,
    )
    dock.settings.save_profile(fixture_profile)
    dock.settings.save_automatic_read_access(False)  # Explicitly exercise optional review mode.
    dock.settings.clear_context_trust()
    dock.settings.clear_visual_trust()
    dock.profile = fixture_profile
    with patch("qgis_ai_copilot.dock.QMessageBox") as message_box:
        message_box.Yes = QMessageBox.Yes
        message_box.Cancel = QMessageBox.Cancel
        message_box.question.return_value = QMessageBox.Cancel
        assert dock._confirm_context_send() is False
        message_box.question.return_value = QMessageBox.Yes
        assert dock._confirm_context_send() is True
        message_box.question.reset_mock()
        assert dock._confirm_context_send() is True
        message_box.question.assert_not_called()

        dock._confirmed_context_signature = None
        dock.settings.trust_context(fixture_profile)
        stored_trust = json.loads(
            dock.settings.settings.value(dock.settings._key("context_trust"), "")
        )
        assert stored_trust == {
            "authcfg": "fixture-auth",
            "base_url": "https://router.example",
        }
        assert set(stored_trust) == {"base_url", "authcfg"}
        assert dock._confirm_context_send() is True
        message_box.question.assert_not_called()

        dock.settings.clear_visual_trust()
        assert not dock.settings.is_visual_trusted(fixture_profile)
        assert dock.settings.has_visual_trust_decision()
        dock.settings.trust_visuals(fixture_profile)
        assert dock.settings.is_visual_trusted(fixture_profile)
        visual_trust = json.loads(
            dock.settings.settings.value(dock.settings._key("visual_trust"), "")
        )
        assert visual_trust == {
            "authcfg": "fixture-auth",
            "base_url": "https://router.example",
        }

        harmless_change = RouterProfile(
            name="Renamed Fixture",
            base_url=fixture_profile.base_url,
            authcfg=fixture_profile.authcfg,
            streaming=False,
            timeout_seconds=120,
        )
        dock.settings.save_profile(harmless_change)
        assert dock.settings.is_context_trusted(harmless_change)

        changed_url = RouterProfile(
            name=harmless_change.name,
            base_url="https://other-router.example",
            authcfg=harmless_change.authcfg,
            streaming=harmless_change.streaming,
            timeout_seconds=harmless_change.timeout_seconds,
        )
        dock.settings.save_profile(changed_url)
        assert not dock.settings.is_context_trusted(changed_url)
        dock.settings.trust_context(changed_url)

        changed_auth = RouterProfile(
            name=changed_url.name,
            base_url=changed_url.base_url,
            authcfg="other-auth",
            streaming=changed_url.streaming,
            timeout_seconds=changed_url.timeout_seconds,
        )
        dock.settings.save_profile(changed_auth)
        assert not dock.settings.is_context_trusted(changed_auth)
        assert not dock.settings.is_visual_trusted(changed_auth)

        dock.profile = changed_auth
        dock._confirmed_context_signature = None
        dock.settings.settings.setValue(dock.settings._key("context_trust"), "{bad-json")
        message_box.question.return_value = QMessageBox.Cancel
        assert dock._confirm_context_send() is False
        message_box.question.assert_called_once()

    dock.settings.trust_context(changed_auth)

    browser = SafeTextBrowser(iface.window)
    with (
        patch("qgis_ai_copilot.widgets.QMessageBox") as message_box,
        patch("qgis_ai_copilot.widgets.QDesktopServices") as desktop,
    ):
        message_box.Open = QMessageBox.Open
        message_box.Cancel = QMessageBox.Cancel
        browser._confirm_external_link(QUrl("file:///tmp/private.txt"))
        message_box.warning.assert_called_once()
        desktop.openUrl.assert_not_called()
        message_box.question.return_value = QMessageBox.Cancel
        browser._confirm_external_link(QUrl("https://docs.qgis.org/"))
        desktop.openUrl.assert_not_called()
        message_box.question.return_value = QMessageBox.Open
        browser._confirm_external_link(QUrl("https://docs.qgis.org/"))
        desktop.openUrl.assert_called_once()

    source_modified = active.isModified()
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    dock._run_tool("check_geometry_health")
    tool_tasks = dock._tool_tasks
    task_loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(10)
    poll.timeout.connect(lambda: task_loop.quit() if not tool_tasks else None)
    poll.start()
    QTimer.singleShot(15_000, task_loop.quit)
    task_loop.exec_()
    poll.stop()
    assert heartbeat
    assert not dock._tool_tasks
    assert dock.local_results[-1]["tool"] == "check_geometry_health"
    assert dock.local_results[-1]["result"]["source_modified"] is False
    assert active.isModified() == source_modified

    settings_dialog = RouterSettingsDialog(dock.settings, dock.records, dock)
    settings_dialog.show()
    context_dialog = ContextDialog(
        dock.collector, set(dock.attached_keys), list(dock.local_results), dock
    )
    context_dialog.show()
    dock._toggle_model_popover()
    app.processEvents()
    assert settings_dialog.auth_select is not None
    assert hasattr(settings_dialog, "visual_trust_check")
    assert settings_dialog.context_trust_check.isChecked()
    settings_dialog._connection_identity_changed()
    assert not settings_dialog.context_trust_check.isChecked()
    assert not settings_dialog.visual_trust_check.isChecked()
    assert context_dialog.preview.toPlainText()
    assert dock.model_popover is not None and dock.model_popover.isVisible()
    popover = dock.model_popover
    dock.model_popover.hide()
    settings_dialog.close()
    context_dialog.close()

    result = {
        "dock_width": dock.width(),
        "project": overview["project_overview"]["name"],
        "layer_count": overview["project_overview"]["layer_count"],
        "active_layer": snapshot["active_layer"]["name"],
        "fields": len(snapshot["fields"]),
        "model_button_height": dock.model_button.height(),
        "privacy_safe": True,
    }
    print(json.dumps(result, sort_keys=True))
    plugin.unload()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    assert sip.isdeleted(popover)
    iface.canvas.setLayers([])
    iface.window.close()
    iface.window.deleteLater()
    project.clear()
    app.processEvents()
    del dock
    del plugin
    del iface
    gc.collect()
    if native_provider is not None:
        QgsApplication.processingRegistry().removeProvider(native_provider)
    app.exitQgis()
    temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
