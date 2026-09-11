"""Native Responses activity, answer separation, consent-safe storage, and Stop."""

import json
import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QCoreApplication, QEvent

from qgis_ai_copilot.network import RouterClient
from qgis_ai_copilot.protocol import RouterProfile, build_responses_payload
from qgis_ai_copilot.protocol import ModelRecord
from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.storage import sanitized_conversation
from qgis_ai_copilot.widgets import MessageCard
from tests.qgis_network_smoke import wait_for, collect_for
from tests.qgis_runtime import configure_prefix
from tests.qgis_smoke import FakeIface
from qgis.PyQt.QtWidgets import QMessageBox


class ActivityHandler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append((self.path, payload))
        if payload["model"] == "unsupported":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Responses unsupported"}}')
            return
        final = {"status":"completed", "output":[
            {"id":"note", "type":"message", "phase":"commentary", "content":[{"type":"output_text","text":"I will inspect coordinate units."}]},
            {"id":"r", "type":"reasoning", "encrypted_content":"PRIVATE_ENCRYPTED", "summary":[{"type":"summary_text","text":"Checking CRS compatibility"}]},
            {"id":"answer", "type":"message", "phase":"final_answer", "content":[{"type":"output_text","text":"Use a metric CRS."}]},
        ], "usage": {"input_tokens": 42, "output_tokens": 18, "total_tokens": 60}}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if payload.get("stream") else "application/json")
        self.end_headers()
        if not payload.get("stream"):
            self.wfile.write(json.dumps(final).encode())
            return
        events = [
            {"type":"response.created"},
            {"type":"response.output_item.added","output_index":0,"item":{"id":"note","type":"message","phase":"commentary"}},
            {"type":"response.output_text.delta","item_id":"note","delta":"I will inspect coordinate units."},
            {"type":"response.reasoning_summary_text.delta","item_id":"r","summary_index":0,"delta":"Checking CRS compatibility"},
            {"type":"response.reasoning_text.delta","item_id":"r","delta":"PRIVATE_RAW_REASONING"},
            {"type":"response.output_item.added","output_index":2,"item":{"id":"answer","type":"message","phase":"final_answer"}},
            {"type":"response.output_text.delta","item_id":"answer","delta":"Use a metric CRS."},
            {"type":"response.completed","response":final},
        ]
        for event in events:
            try:
                self.wfile.write(("data: "+json.dumps(event)+"\n\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(0.035)


class ActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()
        cls.server = ThreadingHTTPServer(("127.0.0.1",0), ActivityHandler)
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
        self.client = RouterClient()
        self.profile = RouterProfile(base_url=f"http://127.0.0.1:{self.server.server_port}", adapter="responses", reasoning_summaries=True)
        ActivityHandler.calls.clear()

    def tearDown(self):
        self.client.close()

    def test_real_summary_and_commentary_arrive_before_final(self):
        self.assertTrue(hasattr(self.client,"chatActivity"),"No model activity signal")
        updates=[]
        self.client.chatActivity.connect(lambda event:updates.append(event))
        payload=build_responses_payload("fixture",[{"role":"user","content":"Inspect"}],reasoning_summaries=True)
        answer,_,_=wait_for(self.client.chatCompleted,lambda:self.client.send_chat(self.profile,payload))
        self.assertEqual(answer,"Use a metric CRS.")
        self.assertEqual(ActivityHandler.calls[0][0],"/v1/responses")
        self.assertTrue(any(item["kind"]=="summary" for item in updates))
        self.assertTrue(any(item["kind"]=="commentary" for item in updates))
        self.assertNotIn("PRIVATE_",str(updates))

    def test_assistant_footer_shows_official_cost_instead_of_tokens(self):
        message = {
            "role": "assistant",
            "status": "complete",
            "content": "Answer",
            "created_at": "2026-09-07T00:00:00+00:00",
            "finished_at": "2026-09-07T00:01:05+00:00",
            "duration_seconds": 65,
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "cached_tokens": 0, "cache_write_tokens": 0},
            "request": {"model": "gpt-6-astra", "thinking": "High"},
        }
        card = MessageCard(message)
        card.resize(420, 120)
        card.show()
        self.app.processEvents()
        self.assertIn("1m 05s", card.footer_meta.toolTip())
        self.assertIn("Standard", card.footer_meta.toolTip())
        self.assertIn("1m 05s", card.footer_meta.text())
        self.assertIsNotNone(getattr(card, "footer_cost", None), "Cost needs its own non-eliding footer label")
        self.assertIn("Est. $0.0020", card.footer_cost.text())
        card.resize(360, 120)
        self.app.processEvents()
        self.assertGreaterEqual(card.footer_cost.width(), card.footer_cost.sizeHint().width())
        self.assertLessEqual(card.footer_cost.geometry().right(), card.footer.width())
        self.assertNotIn("tokens", card.footer_meta.text())
        card.deleteLater()

    def test_nonstreaming_keeps_activity_separate(self):
        self.assertTrue(hasattr(self.client,"chatActivity"),"No model activity signal")
        updates=[]
        self.client.chatActivity.connect(lambda event:updates.append(event))
        payload=build_responses_payload("fixture",[{"role":"user","content":"Inspect"}],stream=False,reasoning_summaries=True)
        answer,nonstream,_=wait_for(self.client.chatCompleted,lambda:self.client.send_chat(self.profile,payload))
        self.assertTrue(nonstream)
        self.assertEqual(answer,"Use a metric CRS.")
        self.assertTrue(any(item["kind"]=="summary" for item in updates))

    def test_unsupported_adapter_never_silently_falls_back(self):
        self.assertTrue(hasattr(self.client,"chatActivity"),"No model activity signal")
        payload=build_responses_payload("unsupported",[{"role":"user","content":"Inspect"}])
        _,_,status,_=wait_for(self.client.chatFailed,lambda:self.client.send_chat(self.profile,payload))
        self.assertEqual(status,404)
        self.assertEqual([path for path,_ in ActivityHandler.calls],["/v1/responses"])

    def test_stop_during_model_activity_is_immediate(self):
        self.assertTrue(hasattr(self.client,"chatActivity"),"No model activity signal")
        def stop(event):
            if event["kind"]=="summary":
                QTimer.singleShot(0,self.client.abort_chat)
        self.client.chatActivity.connect(stop)
        payload=build_responses_payload("fixture",[{"role":"user","content":"Inspect"}],reasoning_summaries=True)
        events=collect_for([("stop",self.client.chatStopped),("complete",self.client.chatCompleted)],lambda:self.client.send_chat(self.profile,payload),600)
        self.assertEqual(events,[("stop",("",))])

    def test_activity_panel_streams_deduplicates_and_collapses(self):
        message={"role":"assistant","status":"streaming","content":""}
        card=MessageCard(message)
        self.assertTrue(hasattr(card,"add_activity"),"No Activity panel")
        card.add_activity({"id":"s1","kind":"summary","text":"Checking"})
        card.add_activity({"id":"s1","kind":"summary","text":"Checking the CRS"})
        self.assertEqual(len(message["activity"]),1)
        self.assertIn("Checking the CRS",card.activity_view.toPlainText())
        self.assertNotIn("Checking",card.body.toPlainText())
        card.finalize("Answer", "complete")
        self.assertFalse(card.activity_toggle.isChecked())
        card.activity_toggle.click()
        self.assertTrue(card.activity_toggle.isChecked())
        card.deleteLater()

    def test_persistence_accepts_only_sanitized_public_activity(self):
        conversation={"messages":[{"role":"assistant","content":"Answer","activity":[
            {"id":"one","kind":"summary","text":"Bearer synthetic-secret at /Users/private/data.gpkg", "raw_event":"PRIVATE_PAYLOAD"},
            {"id":"two","kind":"raw_reasoning","text":"PRIVATE_REASONING"},
        ]}]}
        safe=sanitized_conversation(conversation)
        encoded=json.dumps(safe)
        self.assertNotIn("synthetic-secret",encoded)
        self.assertNotIn("/Users/private",encoded)
        self.assertNotIn("PRIVATE_",encoded)

    def test_assistant_footer_is_compact_blue_copy_icon_and_latest_question_is_editable(self):
        iface = FakeIface()
        plugin = QgisAiCopilotPlugin(iface)
        plugin.initGui()
        dock = plugin.dock
        user_one = {"id": "user-one", "role": "user", "content": "First question", "created_at": "2026-09-05T12:00:00+00:00"}
        assistant_one = {"id": "assistant-one", "role": "assistant", "content": "First answer", "status": "complete", "request": {"model": "model-a", "thinking": "High"}, "created_at": "2026-09-05T12:00:01+00:00"}
        user_two = {"id": "user-two", "role": "user", "content": "Latest question", "created_at": "2026-09-05T12:01:00+00:00"}
        assistant_two = {"id": "assistant-two", "role": "assistant", "content": "Latest answer", "status": "complete", "request": {"model": "model-b", "thinking": "Auto"}, "created_at": "2026-09-05T12:01:01+00:00"}
        dock.conversation = {"messages": [user_one, assistant_one, user_two, assistant_two]}
        dock._render_conversation()
        cards = dock.conversation_body.findChildren(MessageCard)
        self.assertEqual(len(cards), 4)
        first_user = next(card for card in cards if card.message["id"] == "user-one")
        latest_user = next(card for card in cards if card.message["id"] == "user-two")
        latest_assistant = next(card for card in cards if card.message["id"] == "assistant-two")
        self.assertTrue(first_user.edit_button.isHidden())
        self.assertFalse(latest_user.edit_button.isHidden())
        self.assertEqual(latest_user.footer_meta.toolTip(), "You  |  2026-09-05 12:01")
        self.assertIn("model-b", latest_assistant.footer_meta.toolTip())
        self.assertIn("Thinking: Auto", latest_assistant.footer_meta.toolTip())
        self.assertFalse(latest_assistant.copy_button.text())
        self.assertFalse(latest_assistant.copy_button.icon().isNull())
        self.assertTrue(latest_assistant.property("role") == "assistant")
        dock._begin_edit_question(user_two)
        self.assertEqual(dock.message_input.toPlainText(), "Latest question")
        self.assertEqual(dock._editing_message_id, "user-two")
        self.assertFalse(dock.edit_status.isHidden())
        dock.message_input.setPlainText("Rewritten question")
        dock._cancel_edit_question()
        self.assertEqual(dock.message_input.toPlainText(), "")
        self.assertIsNone(dock._editing_message_id)
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        iface.window.close()

    def test_dock_sends_responses_and_preserves_activity_and_retry_adapter(self):
        iface=FakeIface()
        plugin=QgisAiCopilotPlugin(iface)
        plugin.initGui()
        dock=plugin.dock
        dock.profile=self.profile
        dock.records=[ModelRecord("fixture")]
        dock.selected_model="fixture"
        dock.catalog_ready=True
        dock._refresh_model_control()
        dock.message_input.setPlainText("Inspect this synthetic context")
        with patch("qgis_ai_copilot.dock.QMessageBox.question",return_value=QMessageBox.Yes):
            wait_for(dock.responseCompleted,dock._send_or_stop)
        answer=dock.conversation["messages"][-1]
        self.assertEqual(answer["content"],"Use a metric CRS.")
        self.assertEqual(answer["request"]["adapter"],"responses")
        self.assertTrue(answer["request"]["reasoning_summaries"])
        self.assertTrue(any(item["kind"]=="summary" for item in answer["activity"]))
        self.assertGreaterEqual(answer["duration_seconds"], 0)
        self.assertEqual(answer["usage"]["total_tokens"], 60)
        answer_card = next(
            card
            for card in dock.conversation_body.findChildren(MessageCard)
            if card.message.get("id") == answer.get("id")
        )
        self.assertNotIn("tokens", answer_card.footer_meta.text())
        self.assertEqual(answer["cost_estimate"]["status"], "unavailable")
        saved=dock.store.load_conversation(dock.project_id,dock.conversation["id"])
        self.assertNotIn("PRIVATE_",json.dumps(saved))
        latest_user = next(item for item in reversed(dock.conversation["messages"]) if item.get("role") == "user")
        dock._begin_edit_question(latest_user)
        dock.message_input.setPlainText("Rewrite the synthetic GIS question")
        with patch("qgis_ai_copilot.dock.QMessageBox.question",return_value=QMessageBox.Yes):
            wait_for(dock.responseCompleted,dock._send_or_stop)
        user_messages = [item["content"] for item in dock.conversation["messages"] if item.get("role") == "user"]
        self.assertEqual(user_messages, ["Rewrite the synthetic GIS question"])
        self.assertEqual(len(dock.conversation["messages"]), 2)
        self.assertIsNone(dock._editing_message_id)
        answer = dock.conversation["messages"][-1]
        dock.profile=replace(self.profile,adapter="chat_completions",reasoning_summaries=False)
        wait_for(dock.responseCompleted,lambda:dock._retry_message(answer,False))
        self.assertEqual(ActivityHandler.calls[-1][0],"/v1/responses")
        self.assertEqual(ActivityHandler.calls[-1][1]["reasoning"]["summary"],"auto")
        plugin.unload()
        iface.window.close()


if __name__=="__main__":
    unittest.main()
