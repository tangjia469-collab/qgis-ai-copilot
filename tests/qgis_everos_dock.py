"""EverOS as an optional tool and explicit UI write, never automatic memory writes."""

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.core import QgsApplication
from qgis_ai_copilot.everos_protocol import EverosConfig
from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.protocol import ModelRecord, RouterProfile
from tests.qgis_runtime import configure_prefix, synthetic_project
from tests.qgis_smoke import FakeIface
from tests import qgis_execution_dock as _dock_tests
from tests.qgis_everos import MemoryServer


class RecallRouter(BaseHTTPRequestHandler):
    calls = []
    query = "QGIS green area"

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(b'{"data":[{"id":"fixture"}]}')
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append(body)
        results = [i for i in body["input"] if i.get("type") == "function_call_output"]
        output = (
            [
                {
                    "type": "function_call",
                    "id": "fc-memory",
                    "call_id": "call-memory",
                    "name": "search_memory",
                    "arguments": json.dumps({"query": self.query}),
                }
            ]
            if not results
            else [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Memory lookup completed."}],
                }
            ]
        )
        response = {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": output,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(("data: " + json.dumps(response) + "\n\n").encode())


class EverosDockTests(unittest.TestCase):
    pause = _dock_tests.ExecutionDockTests.pause
    until = _dock_tests.ExecutionDockTests.until

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()
        cls.memory = ThreadingHTTPServer(("127.0.0.1", 0), MemoryServer)
        cls.router = ThreadingHTTPServer(("127.0.0.1", 0), RecallRouter)
        cls.threads = []
        for server in (cls.memory, cls.router):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.memory, cls.router):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(timeout=2)
        cls.app.exitQgis()
        cls.temp.cleanup()

    def setUp(self):
        self.question = patch(
            "qgis_ai_copilot.dock.QMessageBox.question", return_value=QMessageBox.Yes
        )
        self.question.start()
        self.project, self.layer = synthetic_project()
        self.iface = FakeIface()
        self.iface.set_active_layer(self.layer)
        self.plugin = QgisAiCopilotPlugin(self.iface)
        self.plugin.initGui()
        self.d = self.plugin.dock
        self.addCleanup(self.cleanup)
        self.d.client.abort_catalog()
        self.d.profile = RouterProfile(
            base_url=f"http://127.0.0.1:{self.router.server_port}", adapter="responses"
        )
        self.d.settings.save_profile(self.d.profile)
        self.assertTrue(
            hasattr(self.d.settings, "save_everos_config"), "Missing optional memory settings"
        )
        self.config = EverosConfig(
            enabled=True,
            base_url=f"http://127.0.0.1:{self.memory.server_port}",
            user_id="fixture-user",
        )
        self.d.settings.save_everos_config(self.config)
        self.d.records = [ModelRecord("fixture")]
        self.d.selected_model = "fixture"
        self.d.catalog_ready = True
        self.d.settings.save_automatic_read_access(True)
        self.d._new_chat()
        self.d._refresh_model_control()
        self.d.settings.settings.remove(self.d.settings._key("everos_note_receipts"))
        MemoryServer.calls = []
        MemoryServer.flush_status = "extracted"
        MemoryServer.flush_delay = 0
        RecallRouter.calls = []
        RecallRouter.query = "QGIS green area"

    def cleanup(self):
        self.plugin.unload()
        self.pause(60)
        self.project.clear()
        self.iface.window.close()
        self.question.stop()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def send(self, text="What did we decide about green area?"):
        self.d.message_input.setPlainText(text)
        self.d._send_or_stop()

    def test_optional_lookup_reaches_model_but_raw_memories_are_not_persisted(self):
        self.send()
        self.until(lambda: self.d._active_message is None)
        self.assertIn("search_memory", [t["name"] for t in RecallRouter.calls[0]["tools"]])
        outputs = [
            i for i in RecallRouter.calls[-1]["input"] if i.get("type") == "function_call_output"
        ]
        self.assertIn("Use square metres", outputs[0]["output"])
        saved = self.d.store.load_conversation(self.d.project_id, self.d.conversation["id"])
        self.assertNotIn("Use square metres", json.dumps(saved))
        self.assertTrue(
            any(
                "memory" in a["text"].lower() or "everos" in a["text"].lower()
                for a in saved["messages"][-1].get("activity", [])
            )
        )
        self.assertEqual(len(self.project.mapLayers()), 2)

    def test_disabled_memory_tool_is_not_advertised_and_cannot_run(self):
        self.d.settings.save_everos_config(EverosConfig(enabled=False, user_id="fixture-user"))
        self.send()
        self.until(lambda: self.d._active_message is None)
        self.assertNotIn("search_memory", [t["name"] for t in RecallRouter.calls[0]["tools"]])
        self.assertEqual(MemoryServer.calls, [])
        output = next(
            i for i in RecallRouter.calls[-1]["input"] if i.get("type") == "function_call_output"
        )
        self.assertFalse(json.loads(output["output"])["ok"])

    def test_stop_during_lookup_prevents_late_model_continuation(self):
        RecallRouter.query = "slow"
        self.send()
        self.until(lambda: self.d._execution is not None and self.d._execution.memory_client.busy)
        self.d._stop_active_request()
        self.pause(550)
        self.assertEqual(len(RecallRouter.calls), 1)
        self.assertIsNone(self.d._active_message)

    def test_remember_is_explicit_and_saves_only_the_note_without_router_call(self):
        with patch("qgis_ai_copilot.dock.RememberDialog.exec_", return_value=QDialog.Accepted):
            self.send("/remember Use metres for QGIS")
        self.until(lambda: not self.d._memory_writer.busy)
        self.assertEqual(
            [c[0] for c in MemoryServer.calls], ["/api/v1/memory/add", "/api/v1/memory/flush"]
        )
        self.assertEqual(MemoryServer.calls[0][1]["messages"][0]["content"], "Use metres for QGIS")
        self.assertEqual(RecallRouter.calls, [])
        self.assertEqual(self.d.conversation["messages"], [])
        with patch("qgis_ai_copilot.dock.RememberDialog.exec_", return_value=QDialog.Accepted):
            self.send("/remember Use metres for QGIS")
        self.pause(50)
        self.assertEqual(
            len(MemoryServer.calls), 2, "Identical saved note must not be silently added twice"
        )

    def test_cancel_remember_preserves_draft_and_writes_nothing(self):
        with patch("qgis_ai_copilot.dock.RememberDialog.exec_", return_value=QDialog.Rejected):
            self.send("/remember Keep this note")
        self.assertEqual(self.d.message_input.toPlainText(), "/remember Keep this note")
        self.assertEqual(MemoryServer.calls, [])
        self.assertEqual(RecallRouter.calls, [])

    def test_ordinary_chat_never_calls_memory_add_or_flush(self):
        self.send("Tell me about QGIS units")
        self.until(lambda: self.d._active_message is None)
        self.assertTrue(MemoryServer.calls)
        self.assertTrue(all(call[0].endswith("/search") for call in MemoryServer.calls))

    def test_manual_note_save_does_not_erase_a_different_remember_draft(self):
        self.d.message_input.setPlainText("/remember Keep this different draft")
        with (
            patch("qgis_ai_copilot.dock.RememberDialog.exec_", return_value=QDialog.Accepted),
            patch(
                "qgis_ai_copilot.dock.RememberDialog.note",
                return_value="Manually entered separate note",
            ),
        ):
            self.d._open_remember_dialog()
        self.until(lambda: not self.d._memory_writer.busy)
        self.assertEqual(self.d.message_input.toPlainText(), "/remember Keep this different draft")

    def test_question_edit_cannot_silently_become_a_memory_write(self):
        self.d._editing_message_id = "fixture-edited-question"
        with patch("qgis_ai_copilot.dock.RememberDialog.exec_", return_value=QDialog.Accepted):
            self.send("/remember An edited question")
        self.assertFalse(self.d._memory_writer.busy)
        self.assertEqual(MemoryServer.calls, [])

    def test_router_change_revokes_memory_connection(self):
        self.d.settings.save_profile(
            RouterProfile(
                base_url=f"http://127.0.0.1:{self.memory.server_port}", adapter="responses"
            )
        )
        self.assertFalse(self.d.settings.everos_config().enabled)

    def test_no_extraction_keeps_note_draft_for_refinement(self):
        MemoryServer.flush_status = "no_extraction"
        with patch("qgis_ai_copilot.dock.RememberDialog.exec_", return_value=QDialog.Accepted):
            self.send("/remember Keep this incomplete note")
        self.until(lambda: not self.d._memory_writer.busy)
        self.assertEqual(self.d.message_input.toPlainText(), "/remember Keep this incomplete note")

    def test_uncertain_save_is_not_blindly_repeated(self):
        MemoryServer.flush_delay = 0.3
        with (
            patch("qgis_ai_copilot.everos.FLUSH_TIMEOUT_MS", 20),
            patch("qgis_ai_copilot.dock.RememberDialog.exec_", return_value=QDialog.Accepted),
        ):
            self.send("/remember A note with delayed confirmation")
            self.until(lambda: not self.d._memory_writer.busy)
            self.send("/remember A note with delayed confirmation")
        self.pause(350)
        self.assertEqual(
            [c[0] for c in MemoryServer.calls], ["/api/v1/memory/add", "/api/v1/memory/flush"]
        )
        self.assertEqual(RecallRouter.calls, [])


if __name__ == "__main__":
    unittest.main()
