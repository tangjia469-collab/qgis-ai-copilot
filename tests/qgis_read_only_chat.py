"""End-to-end read-only Chat data access, consent and mutation rejection."""

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsApplication
from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.protocol import ModelRecord, RouterProfile
from tests import qgis_execution_dock as _dock_tests
from tests.qgis_runtime import configure_prefix, synthetic_project
from tests.qgis_smoke import FakeIface


class ReadRouter(BaseHTTPRequestHandler):
    requests = []
    layer_id = ""
    tool_name = "read_layer_data"

    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(body)
        outputs = [item for item in body["input"] if item.get("type") == "function_call_output"]
        if not outputs:
            args = {
                "layer_id": self.layer_id,
                "fields": ["id", "name"],
                "offset": 0,
                "limit": 20,
                "selected_only": False,
            }
            if self.tool_name == "run_processing":
                args = {
                    "algorithm_id": "native:buffer",
                    "parameters_json": json.dumps({"INPUT": self.layer_id, "DISTANCE": 5}),
                    "result_name": "Not allowed",
                }
            elif self.tool_name == "field_statistics":
                args = {"layer_id": self.layer_id, "field_name": "id"}
            elif self.tool_name == "inspect_layer_geometry":
                args = {"layer_id": self.layer_id, "offset": 0, "limit": 20}
            elif self.tool_name == "inspect_layer_joins":
                args = {"layer_id": self.layer_id}
            elif self.tool_name == "style_layer":
                args = {"layer_id": self.layer_id, "color": "#ff0000", "opacity": 0.5}
            elif self.tool_name == "set_layer_visibility":
                args = {"layer_id": self.layer_id, "visible": False}
            elif self.tool_name in {"zoom_to_layer", "remove_temporary_layer"}:
                args = {"layer_id": self.layer_id}
            result = [
                {
                    "type": "function_call",
                    "id": "fc1",
                    "call_id": "call1",
                    "name": self.tool_name,
                    "arguments": json.dumps(args),
                }
            ]
        else:
            result = [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Inspected the available data."}],
                }
            ]
        response = {
            "status": "completed",
            "output": result,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            },
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(
            (
                "data: " + json.dumps({"type": "response.completed", "response": response}) + "\n\n"
            ).encode()
        )


class ReadOnlyChatTests(unittest.TestCase):
    pause = _dock_tests.ExecutionDockTests.pause
    until = _dock_tests.ExecutionDockTests.until

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ReadRouter)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.app.exitQgis()
        cls.temp.cleanup()

    def setUp(self):
        self.project, self.layer = synthetic_project()
        self.iface = FakeIface()
        self.iface.set_active_layer(self.layer)
        self.plugin = QgisAiCopilotPlugin(self.iface)
        self.plugin.initGui()
        d = self.dock = self.plugin.dock
        d.client.abort_catalog()
        d.profile = RouterProfile(
            base_url=f"http://127.0.0.1:{self.server.server_port}", adapter="responses"
        )
        d.settings.trust_context(d.profile)
        d.settings.settings.remove(d.settings._key("automatic_read_access"))
        d.records = [ModelRecord("fixture")]
        d.selected_model = "fixture"
        d.catalog_ready = True
        d._new_chat()
        d._refresh_model_control()
        d.show()
        ReadRouter.requests = []
        ReadRouter.layer_id = self.layer.id()
        ReadRouter.tool_name = "read_layer_data"
        self.question = patch(
            "qgis_ai_copilot.dock.QMessageBox.question", return_value=QMessageBox.Yes
        )
        self.question.start()
        self.before = [
            (f.id(), f.attributes(), f.geometry().asWkt()) for f in self.layer.getFeatures()
        ]

    def tearDown(self):
        self.plugin.unload()
        self.pause(80)
        self.question.stop()
        self.project.clear()
        self.iface.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def send(self):
        self.dock.message_input.setPlainText("Inspect the layer values.")
        self.dock._send_or_stop()

    def test_default_chat_gets_read_tools_not_write_tools(self):
        self.send()
        self.until(lambda: bool(ReadRouter.requests))
        names = [t["name"] for t in ReadRouter.requests[0].get("tools", [])]
        self.assertIn("read_layer_data", names)
        self.assertNotIn("run_processing", names)
        self.assertNotIn("remove_temporary_layer", names)

    def test_data_is_shared_only_after_specific_layer_consent(self):
        self.dock.settings.settings.setValue(
            self.dock.settings._key("automatic_read_access"), False
        )
        self.send()
        self.until(lambda: self.dock._execution_dialog is not None)
        self.assertNotIn("Example 1", json.dumps(ReadRouter.requests))
        dialog = self.dock._execution_dialog
        self.assertIn("data", dialog.windowTitle().lower())
        dialog.accept()
        self.until(lambda: self.dock._active_message is None)
        self.assertIn("Example 1", json.dumps(ReadRouter.requests[-1]))
        self.assertIn("Example 2", json.dumps(ReadRouter.requests[-1]))
        self.assertEqual(len(self.project.mapLayers()), 2)
        self.assertEqual(
            self.before,
            [(f.id(), f.attributes(), f.geometry().asWkt()) for f in self.layer.getFeatures()],
        )
        saved = self.dock.store.load_conversation(
            self.dock.project_id, self.dock.conversation["id"]
        )
        self.assertNotIn("Example 1", json.dumps(saved))

    def test_declining_data_consent_never_sends_rows(self):
        self.dock.settings.settings.setValue(
            self.dock.settings._key("automatic_read_access"), False
        )
        self.send()
        self.until(lambda: self.dock._execution_dialog is not None)
        self.dock._execution_dialog.reject()
        self.until(lambda: self.dock._active_message is None)
        self.assertEqual(len(ReadRouter.requests), 1)
        self.assertNotIn("Example 1", json.dumps(ReadRouter.requests))
        self.assertEqual(len(self.project.mapLayers()), 2)

    def test_official_cost_includes_each_model_call_and_survives_reload(self):
        self.dock.records = [ModelRecord("gpt-6-astra")]
        self.dock.selected_model = "gpt-6-astra"
        self.dock._refresh_model_control()
        self.send()
        self.until(lambda: self.dock._active_message is None)
        answer = self.dock.conversation["messages"][-1]
        self.assertEqual(answer["cost_estimate"]["min_usd"], "0.004")
        self.assertEqual(answer["cost_estimate"]["max_usd"], "0.004")
        self.assertEqual(len(answer["usage_rounds"]), 2)
        saved = self.dock.store.load_conversation(
            self.dock.project_id, self.dock.conversation["id"]
        )
        self.assertEqual(saved["messages"][-1]["cost_estimate"], answer["cost_estimate"])

    def test_default_reads_all_data_without_confirmation_across_requests(self):
        for tool in (
            "read_layer_data",
            "field_statistics",
            "inspect_layer_geometry",
            "inspect_layer_joins",
        ):
            with self.subTest(tool=tool):
                if self.dock._active_message is not None:
                    self.dock._stop_active_request()
                    self.until(lambda: self.dock._active_message is None)
                ReadRouter.tool_name = tool
                ReadRouter.requests = []
                self.dock._new_chat()
                self.send()
                self.until(
                    lambda: (
                        self.dock._active_message is None or self.dock._execution_dialog is not None
                    )
                )
                self.assertIsNone(
                    self.dock._execution_dialog,
                    "Read-only work must not ask for approval by default",
                )
                self.assertIsNone(self.dock._active_message)
                outputs = [
                    item
                    for item in ReadRouter.requests[-1]["input"]
                    if item.get("type") == "function_call_output"
                ]
                self.assertTrue(json.loads(outputs[0]["output"])["ok"])
                self.assertFalse(self.dock.execute_mode_button.isChecked())
        self.assertEqual(
            self.before,
            [(f.id(), f.attributes(), f.geometry().asWkt()) for f in self.layer.getFeatures()],
        )

    def test_default_metadata_needs_no_trust_popup(self):
        self.dock.settings.clear_context_trust()
        with patch(
            "qgis_ai_copilot.dock.QMessageBox.question",
            side_effect=AssertionError("Unexpected read confirmation"),
        ):
            self.assertTrue(self.dock._confirm_context_send())

    def test_read_access_setting_survives_reopen_and_can_restore_review_mode(self):
        from qgis_ai_copilot.config import PluginSettings

        self.assertTrue(getattr(self.dock.settings, "automatic_read_access", lambda: False)())
        self.dock.settings.save_automatic_read_access(False)
        self.assertFalse(PluginSettings().automatic_read_access())
        self.dock.settings.save_automatic_read_access(True)
        self.assertTrue(PluginSettings().automatic_read_access())

    def test_malicious_write_call_is_denied_in_read_only_chat(self):
        for tool in (
            "run_processing",
            "style_layer",
            "set_layer_visibility",
            "zoom_to_layer",
            "remove_temporary_layer",
        ):
            with self.subTest(tool=tool):
                ReadRouter.tool_name = tool
                ReadRouter.requests = []
                self.send()
                self.until(lambda: self.dock._active_message is None)
                self.assertEqual(len(self.project.mapLayers()), 2)
                self.assertIsNone(self.dock._execution_dialog)
                outputs = [
                    item
                    for item in ReadRouter.requests[-1]["input"]
                    if item.get("type") == "function_call_output"
                ]
                self.assertTrue(outputs)
                result = json.loads(outputs[0]["output"])
                self.assertFalse(result["ok"])
                self.assertIn("read-only", result["error"])

    def test_settings_checkbox_saves_read_access_without_granting_writes(self):
        from qgis_ai_copilot.dialogs import RouterSettingsDialog
        from qgis_ai_copilot.config import PluginSettings

        self.dock.settings.save_profile(self.dock.profile)
        dialog = RouterSettingsDialog(self.dock.settings, self.dock.records, self.dock)
        self.assertTrue(dialog.automatic_read_check.isChecked())
        self.assertFalse(dialog.context_trust_check.isEnabled())
        dialog.automatic_read_check.setChecked(False)
        self.assertTrue(dialog.context_trust_check.isEnabled())
        dialog._save()
        self.assertFalse(PluginSettings().automatic_read_access())
        self.assertFalse(self.dock.execute_mode_button.isChecked())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
