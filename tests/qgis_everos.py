"""Native local-memory transport, cancellation and write semantics with fixtures."""

import importlib
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from qgis.core import QgsApplication
from tests.qgis_runtime import configure_prefix
from tests.qgis_network_smoke import wait_for, collect_for
from qgis_ai_copilot.everos_protocol import EverosConfig


class MemoryServer(BaseHTTPRequestHandler):
    calls = []
    flush_status = "extracted"
    flush_delay = 0

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        self.reply({"status": "ok"})

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.calls.append((self.path, body, self.headers.get("Authorization")))
        if self.path.endswith("/search"):
            query = body["query"]
            if query == "slow":
                time.sleep(0.4)
            if query == "redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/unexpected")
                self.end_headers()
                return
            if query == "huge":
                self.reply({"data": {"episodes": [], "padding": "a" * 600000}})
                return
            response = {
                "request_id": "fixture-search",
                "data": {
                    "episodes": [
                        {
                            "id": "qgis-note",
                            "user_id": "fixture-user",
                            "app_id": "default",
                            "project_id": "default",
                            "subject": "QGIS units",
                            "episode": "Use square metres for green area.",
                            "score": 0.9,
                        }
                    ],
                    "profiles": [],
                    "agent_cases": [],
                    "agent_skills": [],
                    "unprocessed_messages": [],
                },
            }
        elif self.path.endswith("/add"):
            response = {
                "request_id": "fixture-add",
                "data": {"status": "accumulated", "message_count": 1},
            }
        else:
            if self.flush_delay:
                time.sleep(self.flush_delay)
            response = {
                "request_id": "fixture-flush",
                "data": {"status": self.flush_status, "derived_settled": True},
            }
        self.reply(response)

    def reply(self, value):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(json.dumps(value).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


class EverosNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MemoryServer)
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
        self.assertIsNotNone(
            importlib.util.find_spec("qgis_ai_copilot.everos"), "Missing async EverOS client"
        )
        module = importlib.import_module("qgis_ai_copilot.everos")
        self.client = module.EverosClient()
        self.addCleanup(self.client.close)
        self.config = EverosConfig(
            enabled=True,
            base_url=f"http://127.0.0.1:{self.server.server_port}",
            user_id="fixture-user",
        )
        MemoryServer.calls = []
        MemoryServer.flush_status = "extracted"
        MemoryServer.flush_delay = 0

    def test_scoped_search_and_local_health(self):
        (health,) = wait_for(self.client.completed, lambda: self.client.check(self.config))
        self.assertTrue(health["ok"])
        (result,) = wait_for(
            self.client.completed, lambda: self.client.search(self.config, "QGIS units")
        )
        self.assertEqual(result["sources"][0]["id"], "qgis-note")
        path, body, auth = MemoryServer.calls[0]
        self.assertEqual(path, "/api/v1/memory/search")
        self.assertEqual(body["user_id"], "fixture-user")
        self.assertIsNone(auth)

    def test_cancel_discards_late_memory(self):
        result = []
        self.client.completed.connect(result.append)
        self.client.search(self.config, "slow")
        self.client.cancel()
        collect_for({}, lambda: None, duration_ms=500)
        self.assertEqual(result, [])
        self.assertFalse(self.client.busy)

    def test_redirect_and_oversize_are_not_followed_or_returned(self):
        for query in ("redirect", "huge"):
            with self.subTest(query=query):
                error, uncertain = wait_for(
                    self.client.failed, lambda: self.client.search(self.config, query)
                )
                self.assertTrue(error)
                self.assertFalse(uncertain)
                self.assertFalse(self.client.busy)

    def test_timeout_is_bounded(self):
        with patch("qgis_ai_copilot.everos.SEARCH_TIMEOUT_MS", 20):
            error, uncertain = wait_for(
                self.client.failed, lambda: self.client.search(self.config, "slow")
            )
        self.assertIn("timed out", error)
        self.assertFalse(uncertain)

    def test_explicit_note_add_and_flush_confirm_saved(self):
        (result,) = wait_for(
            self.client.completed,
            lambda: self.client.remember(self.config, "Use metres", "qgis-note-fixture"),
        )
        self.assertEqual(result["status"], "saved")
        self.assertEqual(
            [c[0] for c in MemoryServer.calls], ["/api/v1/memory/add", "/api/v1/memory/flush"]
        )
        self.assertEqual(MemoryServer.calls[0][1]["messages"][0]["content"], "Use metres")
        self.assertEqual(MemoryServer.calls[1][1]["session_id"], "qgis-note-fixture")

    def test_no_extraction_is_not_reported_as_saved(self):
        MemoryServer.flush_status = "no_extraction"
        (result,) = wait_for(
            self.client.completed,
            lambda: self.client.remember(self.config, "Unclear note", "qgis-note-fixture"),
        )
        self.assertEqual(result["status"], "no_extraction")

    def test_timeout_after_add_is_uncertain_and_never_readds(self):
        MemoryServer.flush_delay = 0.3
        with patch("qgis_ai_copilot.everos.FLUSH_TIMEOUT_MS", 20):
            error, uncertain = wait_for(
                self.client.failed,
                lambda: self.client.remember(self.config, "Use metres", "qgis-note-uncertain"),
            )
        self.assertTrue(uncertain)
        self.assertIn("timed out", error)
        collect_for({}, lambda: None, duration_ms=350)
        self.assertEqual(
            [c[0] for c in MemoryServer.calls], ["/api/v1/memory/add", "/api/v1/memory/flush"]
        )


if __name__ == "__main__":
    unittest.main()
