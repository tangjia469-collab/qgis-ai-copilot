"""Real loopback streaming tests for long waits, progress, and immediate Stop."""

import json
import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from qgis.PyQt.QtCore import QTimer
from qgis.core import QgsApplication, QgsNetworkAccessManager

from qgis_ai_copilot.network import RouterClient
from qgis_ai_copilot.protocol import RouterProfile, build_chat_payload
from qgis_ai_copilot.widgets import MessageCard
from tests.qgis_network_smoke import wait_for, collect_for
from tests.qgis_runtime import configure_prefix


class ProgressRouter(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = payload["model"]
        if model in {"delayed", "long-wait"}:
            time.sleep(1.2 if model == "long-wait" else 0.45)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()

        def event(text):
            self.wfile.write(text.encode())
            self.wfile.flush()

        try:
            if model in {"heartbeat", "deadline"}:
                for _ in range(6):
                    event(": heartbeat\n\n")
                    time.sleep(0.05)
            if model == "private-reasoning":
                event('data: {"choices":[{"delta":{"reasoning_content":"PRIVATE_REASONING_NOT_FOR_UI"}}]}\n\n')
                time.sleep(0.08)
            event('data: {"choices":[{"delta":{"content":"First"}}]}\n\n')
            if model == "silent":
                time.sleep(0.5)
            if model == "slow":
                for _ in range(5):
                    time.sleep(0.06)
                    event('data: {"choices":[{"delta":{"content":"."}}]}\n\n')
            event("data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass


class RequestProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ProgressRouter)
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

    def tearDown(self):
        self.client.close()

    def profile(self):
        self.assertTrue(hasattr(self.client, "chatProgress"), "No visible request-progress signal")
        return RouterProfile(base_url=f"http://127.0.0.1:{self.server.server_port}", timeout_seconds=0.1, chat_idle_timeout_seconds=0.18)

    def payload(self, model):
        return build_chat_payload(model, [{"role": "user", "content": "Synthetic test"}])

    def test_active_stream_outlives_old_absolute_timeout(self):
        profile = self.profile()
        updates = []
        self.client.chatProgress.connect(lambda *values: updates.append(values))
        text, _, _ = wait_for(self.client.chatCompleted, lambda: self.client.send_chat(profile, self.payload("slow")))
        self.assertEqual(text, "First.....")
        self.assertIn("receiving", [row[0] for row in updates])

    def test_heartbeats_keep_wait_alive_before_first_answer(self):
        profile = self.profile()
        text, _, _ = wait_for(self.client.chatCompleted, lambda: self.client.send_chat(profile, self.payload("heartbeat")))
        self.assertEqual(text, "First")

    def test_silent_stream_times_out_with_partial_answer(self):
        profile = self.profile()
        kind, message, _, partial = wait_for(self.client.chatFailed, lambda: self.client.send_chat(profile, self.payload("silent")))
        self.assertEqual(kind, "timeout")
        self.assertIn("activity", message)
        self.assertEqual(partial, "First")

    def test_stop_before_first_byte_is_immediate_and_single(self):
        profile = replace(self.profile(), chat_idle_timeout_seconds=1)
        def trigger():
            self.client.send_chat(profile, self.payload("delayed"))
            self.client.abort_chat()
            self.assertIsNone(self.client._chat_reply)
            self.client.abort_chat()
        events = collect_for([("stopped", self.client.chatStopped), ("done", self.client.chatCompleted), ("failed", self.client.chatFailed)], trigger, 600)
        self.assertEqual(events, [("stopped", ("",))])

    def test_stop_during_stream_preserves_partial_and_ignores_late_events(self):
        profile = self.profile()
        def stop(_text):
            self.client.chatDelta.disconnect(stop)
            QTimer.singleShot(0, self.client.abort_chat)
        self.client.chatDelta.connect(stop)
        events = collect_for([("stopped", self.client.chatStopped), ("done", self.client.chatCompleted), ("failed", self.client.chatFailed)], lambda:self.client.send_chat(profile, self.payload("slow")), 650)
        self.assertEqual(events, [("stopped", ("First",))])

    def test_progress_omits_provider_private_reasoning(self):
        profile = self.profile()
        updates = []
        self.client.chatProgress.connect(lambda *values: updates.append(values))
        text, _, _ = wait_for(self.client.chatCompleted, lambda:self.client.send_chat(profile, self.payload("private-reasoning")))
        self.assertEqual(text, "First")
        self.assertNotIn("PRIVATE_REASONING", str(updates))
        self.assertTrue(all(row[0] in {"sending", "waiting", "receiving", "stopping"} for row in updates))

    def test_elapsed_updates_during_silence_without_changing_global_qgis_timeout(self):
        profile = replace(self.profile(), chat_idle_timeout_seconds=3)
        original_timeout = QgsNetworkAccessManager.timeout()
        updates = []
        self.client.chatProgress.connect(lambda *values: updates.append(values))
        text, _, _ = wait_for(self.client.chatCompleted, lambda:self.client.send_chat(profile, self.payload("long-wait")))
        self.assertEqual(text, "First")
        self.assertTrue(any(row[0] in {"sending", "waiting"} and row[1] >= 1 for row in updates))
        self.assertEqual(QgsNetworkAccessManager.timeout(), original_timeout)
        self.assertFalse(self.client._progress_timer.isActive())

    def test_hard_deadline_bounds_even_active_connections(self):
        profile = self.profile()
        with patch("qgis_ai_copilot.network.MAX_CHAT_DURATION_MS", 180):
            kind, message, _, _ = wait_for(self.client.chatFailed, lambda:self.client.send_chat(profile, self.payload("deadline")))
        self.assertEqual(kind, "timeout")
        self.assertIn("maximum", message)

    def test_message_card_shows_elapsed_and_clickable_stop(self):
        card = MessageCard({"role":"assistant", "content":"", "status":"streaming"})
        self.assertTrue(hasattr(card, "update_progress"), "Message card has no progress UI")
        card.update_progress("waiting", 125, 8)
        self.assertIn("02:05", card.status_label.text())
        self.assertIn("Waiting", card.status_label.text())
        self.assertFalse(card.stop_button.isHidden())
        calls = []
        card.stopRequested.connect(lambda:calls.append(True))
        card.stop_button.click()
        self.assertEqual(calls, [True])
        card.finalize("", "error", {"message":"Example timeout"})
        self.assertTrue(card.stop_button.isHidden())
        self.assertEqual(card.body.toPlainText().count("Example timeout")+card.status_label.text().count("Example timeout"), 1)
        card.deleteLater()


if __name__ == "__main__":
    unittest.main()
