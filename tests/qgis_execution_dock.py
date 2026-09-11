"""Native dock consent, actual execution, cancellation, and durable action audit."""

import json
import os
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QEventLoop, QPoint, QRect, Qt, QTimer
from qgis.PyQt.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QToolButton
from qgis.analysis import QgsNativeAlgorithms
from qgis.core import QgsApplication

from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.protocol import ModelRecord, RouterProfile
from qgis_ai_copilot.widgets import ToolResultCard
from tests.qgis_execution_flow import ExecutionRouter
from tests.qgis_runtime import configure_prefix, synthetic_project
from tests.qgis_smoke import FakeIface


class ExecutionDockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()
        if not QgsApplication.processingRegistry().algorithmById("native:buffer"):
            QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ExecutionRouter)
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
        d.profile = RouterProfile(base_url=f"http://127.0.0.1:{self.server.server_port}", adapter="responses")
        d.records = [ModelRecord("fixture")]
        d.selected_model = "fixture"
        d.catalog_ready = True
        d.conversation = d._blank_conversation()
        d._render_conversation()
        d._refresh_model_control()
        d.setFloating(True)
        d.resize(420, 740)
        d.show()
        self.iface.window.show()
        self.app.processEvents()
        self.confirm = patch("qgis_ai_copilot.dock.QMessageBox.question", return_value=QMessageBox.Yes).start()
        self.warn = patch("qgis_ai_copilot.dock.QMessageBox.warning").start()
        ExecutionRouter.layer_id = self.layer.id()
        ExecutionRouter.tool_name = "run_processing"
        ExecutionRouter.requests = []

    def tearDown(self):
        if self.plugin.dock is not None:
            self.plugin.unload()
        self.pause(150)
        self.iface.window.close()
        self.project.clear()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        patch.stopall()

    def pause(self, duration=100):
        loop = QEventLoop()
        QTimer.singleShot(duration, loop.quit)
        loop.exec_()

    def until(self, predicate):
        if predicate():
            return
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: loop.quit() if predicate() else None)
        timer.start()
        QTimer.singleShot(10000, loop.quit)
        loop.exec_()
        timer.stop()
        self.assertTrue(predicate(), "Dock execution timed out")

    def start_execute(self):
        self.dock.execute_mode_button.click()
        self.dock.message_input.setPlainText("Create a 5 metre buffer as a temporary layer.")
        self.dock._send_or_stop()
        self.until(lambda: self.dock._execution_dialog is not None)
        return self.dock._execution_dialog

    def approve_finish(self):
        self.start_execute().accept()
        self.until(lambda: self.dock._active_message is None)
        self.assertEqual(len(self.project.mapLayers()), 3)
        return next(m for m in self.dock.conversation["messages"] if m["role"] == "assistant")

    def test_default_chat_has_no_execution_tools(self):
        self.assertTrue(self.dock.chat_mode_button.isChecked())
        self.assertFalse(self.dock.execute_mode_button.isChecked())
        self.dock.message_input.setPlainText("Explain buffers")
        self.dock._send_or_stop()
        self.until(lambda: self.dock._active_message is None)
        names = [tool["name"] for tool in ExecutionRouter.requests[0]["tools"]]
        self.assertIn("read_layer_data", names)
        self.assertNotIn("run_processing", names)
        self.assertEqual(len(self.project.mapLayers()), 2)
        self.assertEqual(self.dock.conversation["messages"][-1]["content"], "Chat-only answer.")

    def test_new_and_resumed_chats_always_reset_to_read_only(self):
        d = self.dock
        d._persist_conversation()
        saved_id = d.conversation["id"]
        d.execute_mode_button.click()
        d._new_chat()
        self.assertTrue(d.chat_mode_button.isChecked())
        d.execute_mode_button.click()
        d._resume_chat(saved_id)
        self.assertTrue(d.chat_mode_button.isChecked())

    def test_project_change_resets_to_read_only(self):
        d = self.dock
        d.execute_mode_button.click()
        d._apply_project_change(d.project_id, "fixture-new-project", "Other project")
        self.assertTrue(d.chat_mode_button.isChecked())

    def test_approved_removal_and_undo_from_history_restore_real_layer(self):
        from qgis_ai_copilot.recovery import RemovedLayerRecovery
        d = self.dock
        original_id = self.layer.id()
        ExecutionRouter.tool_name = "remove_temporary_layer"
        d.execute_mode_button.click()
        d.message_input.setPlainText("Remove the temporary layer.")
        d._send_or_stop()
        self.until(lambda: d._execution_dialog is not None)
        self.assertEqual(len(self.project.mapLayers()), 2)
        d._execution_dialog.accept()
        self.until(lambda: d._active_message is None)
        self.assertIsNone(self.project.mapLayer(original_id))
        self.assertEqual(len(self.project.mapLayers()), 1)
        saved = d.store.load_conversation(d.project_id, d.conversation["id"])
        action = next(m for m in saved["messages"] if m["role"] == "action")
        recovery_id = action["tool_result"]["result"]["outcome"]["recovery_id"]
        self.assertTrue(d.recovery.available(recovery_id))
        d.recovery = RemovedLayerRecovery(d.project_id)
        d.conversation = saved
        d._render_conversation()
        undo = next(button for card in d.conversation_body.findChildren(ToolResultCard)
                    for button in card.findChildren(QToolButton) if button.text() == "Undo remove")
        undo.click()
        self.assertEqual(len(self.project.mapLayers()), 2)
        restored = [layer for layer in self.project.mapLayers().values() if layer.featureCount() == 2]
        self.assertEqual(len(restored), 1)
        self.assertEqual(sorted(f["name"] for f in restored[0].getFeatures()), ["Example 1", "Example 2"])
        self.assertFalse(d.recovery.available(recovery_id))
        self.assertEqual(d.conversation["messages"][-1]["tool_result"]["tool"], "restore_temporary_layer")

    def test_execute_requires_responses_and_fresh_send_consent(self):
        d = self.dock
        d.execute_mode_button.click()
        d.message_input.setPlainText("Buffer")
        d.profile = replace(d.profile, adapter="chat_completions")
        d._send_or_stop()
        self.warn.assert_called_once()
        self.assertEqual(d.conversation["messages"], [])
        d.profile = replace(d.profile, adapter="responses")
        d.settings.trust_context(d.profile)
        self.confirm.return_value = QMessageBox.Cancel
        d._send_or_stop()
        self.assertEqual(self.confirm.call_args.args[1], "Start Execute mode?")
        self.assertEqual(d.conversation["messages"], [])
        self.assertEqual(d.message_input.toPlainText(), "Buffer")
        self.assertEqual(ExecutionRouter.requests, [])

    def test_approval_nonmodal_real_output_and_sanitized_saved_audit(self):
        dialog = self.start_execute()
        d = self.dock
        self.assertEqual(dialog.windowModality(), Qt.NonModal)
        self.assertIsNone(QApplication.activeModalWidget())
        self.assertTrue(d.send_button.isEnabled())
        self.assertEqual(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).text(), "Approve")
        self.assertEqual(len(self.project.mapLayers()), 2)
        dialog.accept()
        self.until(lambda: d._active_message is None)
        self.assertIsNone(d._execution_dialog)
        self.assertEqual(len(self.project.mapLayers()), 3)
        self.assertEqual(self.layer.extent().width(), 30)
        saved = d.store.load_conversation(d.project_id, d.conversation["id"])
        actions = [m for m in saved["messages"] if m["role"] == "action"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["tool_result"]["risk"], "Execute: complete")
        encoded = json.dumps(saved)
        for private in ("OPAQUE_CONTINUATION", "encrypted_content", "parameters_json", "function_call_output"):
            self.assertNotIn(private, encoded)
        self.assertIn("OPAQUE_CONTINUATION", json.dumps(ExecutionRouter.requests[-1]))

    def test_stop_at_approval_closes_dialog_and_never_continues(self):
        dialog = self.start_execute()
        session = self.dock._execution
        self.dock.send_button.click()
        self.pause()
        self.assertFalse(session.running)
        self.assertIsNone(self.dock._active_message)
        self.assertTrue(sip.isdeleted(dialog) or not dialog.isVisible())
        self.assertEqual(len(self.project.mapLayers()), 2)
        self.assertEqual(len(ExecutionRouter.requests), 1)
        self.assertEqual(self.dock.conversation["messages"][-1]["status"], "stopped")

    def test_stop_just_after_task_start_discards_output_after_session_deletion(self):
        dialog = self.start_execute()
        session = self.dock._execution
        dialog.accept()
        self.assertIsNotNone(session.executor._state)
        self.dock.send_button.click()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.pause(400)
        self.assertEqual(len(self.project.mapLayers()), 2)
        self.assertEqual(len(ExecutionRouter.requests), 1)
        self.assertIsNone(self.dock._execution)
        self.assertFalse(session.running)

    def test_retry_and_edit_are_chat_only_and_keep_independent_action_audit(self):
        answer = self.approve_finish()
        d = self.dock
        audit = next(m for m in d.conversation["messages"] if m["role"] == "action")
        d._retry_message(answer, False)
        self.until(lambda: d._active_message is None)
        self.assertNotIn("run_processing", [tool["name"] for tool in ExecutionRouter.requests[-1]["tools"]])
        user = next(m for m in d.conversation["messages"] if m["role"] == "user")
        d._begin_edit_question(user)
        self.assertIn("chat only", d.edit_status.text().lower())
        d.message_input.setPlainText("Explain the result instead")
        d._send_or_stop()
        self.until(lambda: d._active_message is None)
        self.assertNotIn("run_processing", [tool["name"] for tool in ExecutionRouter.requests[-1]["tools"]])
        self.assertIn("Recorded QGIS action", json.dumps(ExecutionRouter.requests[-1]))
        saved = d.store.load_conversation(d.project_id, d.conversation["id"])
        self.assertIn(audit["id"], [m["id"] for m in saved["messages"]])
        self.assertEqual(len(self.project.mapLayers()), 3)

    def test_profile_change_cancels_pending_approval(self):
        self.start_execute()
        self.dock._profile_saved(RouterProfile())
        self.pause()
        self.assertIsNone(self.dock._execution_dialog)
        self.assertIsNone(self.dock._active_message)
        self.assertEqual(len(self.project.mapLayers()), 2)
        self.assertEqual(len(ExecutionRouter.requests), 1)

    def test_project_clear_cancels_without_continuation(self):
        self.start_execute()
        self.iface.set_active_layer(None)
        self.project.clear()
        self.pause()
        self.assertIsNone(self.dock._execution_dialog)
        self.assertIsNone(self.dock._active_message)
        self.assertEqual(len(ExecutionRouter.requests), 1)

    def test_unload_cancels_approval_and_discards_transient_continuation(self):
        self.start_execute()
        session = self.dock._execution
        self.plugin.unload()
        self.pause()
        self.assertFalse(session.running)
        self.assertIsNone(session.payload)
        self.assertIsNone(session.current_call)
        self.assertIsNone(session.current_plan)
        self.assertEqual(len(self.project.mapLayers()), 2)
        self.assertEqual(len(ExecutionRouter.requests), 1)

    def test_audit_disk_failure_stops_and_unlocks_the_dock(self):
        dialog = self.start_execute()
        with patch.object(self.dock, "_persist_conversation", side_effect=OSError("disk full")):
            dialog.accept()
            self.until(lambda: self.dock._active_message is None)
        self.assertIsNone(self.dock._execution)
        self.assertTrue(self.dock.chat_mode_button.isEnabled())
        self.assertEqual(len(ExecutionRouter.requests), 1)
        self.assertEqual(len(self.project.mapLayers()), 2)
        self.assertTrue(any(m["role"] == "action" for m in self.dock.conversation["messages"]))

    def test_audit_failure_after_action_rolls_back_the_change(self):
        dialog = self.start_execute()
        original = self.dock._persist_conversation
        calls = []
        def fail_after_approval():
            calls.append(True)
            if len(calls) > 1:
                raise OSError("disk full")
            original()
        with patch.object(self.dock, "_persist_conversation", side_effect=fail_after_approval):
            dialog.accept()
            self.until(lambda: self.dock._active_message is None)
        self.assertEqual(len(self.project.mapLayers()), 2)
        self.assertEqual(len(ExecutionRouter.requests), 1)

    def test_header_and_action_cards_fit_narrow_dock(self):
        self.approve_finish()
        d = self.dock
        for width in (360, 420, 460):
            d.resize(width, 740)
            self.app.processEvents()
            self.assertLessEqual(d.width() - width, 24)
            header = d.settings_button.parentWidget()
            bounds = header.rect()
            controls = (d.chat_mode_button, d.execute_mode_button, d.chats_button, d.settings_button)
            previous = None
            for widget in controls:
                rect = QRect(widget.mapTo(header, QPoint()), widget.size())
                self.assertTrue(bounds.contains(rect))
                if previous:
                    self.assertFalse(previous.intersects(rect))
                previous = rect
            for card in d.conversation_body.findChildren(ToolResultCard):
                self.assertLessEqual(card.minimumSizeHint().width(), d.conversation_scroll.viewport().width())
            self.assertTrue(d.grab().save(str(Path(self.temp.name) / f"execute-{width}.png")))


if __name__ == "__main__":
    unittest.main()
