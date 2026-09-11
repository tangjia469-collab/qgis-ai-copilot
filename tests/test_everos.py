"""Optional memory boundaries without needing a live memory store."""

import importlib
import unittest


class EverosTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("qgis_ai_copilot.everos_protocol"),
            "Missing EverOS integration",
        )
        self.memory = importlib.import_module("qgis_ai_copilot.everos_protocol")

    def config(self):
        return self.memory.EverosConfig(enabled=True, user_id="fixture-user")

    def test_search_is_scoped_and_never_uploads_the_whole_chat(self):
        body = self.memory.search_request(self.config(), "QGIS green area")
        self.assertEqual(
            body,
            {
                "user_id": "fixture-user",
                "app_id": "default",
                "project_id": "default",
                "query": "QGIS green area",
                "top_k": 5,
                "include_profile": False,
                "method": "hybrid",
            },
        )

    def test_only_loopback_origins_and_path_safe_scope_ids_are_accepted(self):
        for url in (
            "https://remote.example",
            "http://127.0.0.1@remote.example",
            "http://localhost:8000/api",
            "http://localhost:8000?token=secret",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.memory.EverosConfig(
                    enabled=True, base_url=url, user_id="fixture-user"
                ).validate()
        with self.assertRaises(ValueError):
            self.memory.EverosConfig(user_id="../another-user").validate()
        self.config().validate()

    def test_recall_filters_unrelated_and_credential_notes_and_bounds_text(self):
        response = {
            "request_id": "r1",
            "data": {
                "episodes": [
                    {
                        "id": "qgis-1",
                        "user_id": "fixture-user",
                        "app_id": "default",
                        "project_id": "default",
                        "timestamp": "2026-09-01T00:00:00Z",
                        "subject": "QGIS green area",
                        "episode": "Green area is measured in square metres. "
                        + "Readable extra words. " * 200,
                        "score": 0.7,
                    },
                    {
                        "id": "other",
                        "subject": "Homepage marketing design",
                        "episode": "Homepage carousel uses blue buttons.",
                        "score": 0.1,
                    },
                    {
                        "id": "secret",
                        "subject": "QGIS API key",
                        "episode": "QGIS API key sk-not-a-real-secret-1234",
                        "score": 0.8,
                    },
                    {
                        "id": "other-user",
                        "user_id": "somebody-else",
                        "subject": "QGIS green area",
                        "episode": "Do not share another user's data",
                        "score": 0.8,
                    },
                    {
                        "id": "unscoped",
                        "subject": "QGIS green area",
                        "episode": "This matching note has no verified user or scope.",
                        "score": 0.9,
                    },
                ],
                "profiles": [],
                "agent_cases": [],
                "agent_skills": [],
                "unprocessed_messages": [],
            },
        }
        result = self.memory.search_result(self.config(), "QGIS green area", response)
        self.assertEqual([s["id"] for s in result["sources"]], ["qgis-1"])
        self.assertLessEqual(len(result["sources"][0]["text"]), 1200)
        self.assertTrue(result["sources"][0]["truncated"])
        self.assertNotIn("sk-not", str(result))

    def test_empty_results_and_bad_envelopes_are_distinguished(self):
        result = self.memory.search_result(self.config(), "QGIS", {"data": {"episodes": []}})
        self.assertTrue(result["ok"])
        self.assertEqual(result["sources"], [])
        with self.assertRaises(ValueError):
            self.memory.search_result(self.config(), "QGIS", {"error": "bad request"})

    def test_only_explicit_remember_commands_open_the_write_flow(self):
        self.assertEqual(
            self.memory.remember_command("/remember Use metres in QGIS"), "Use metres in QGIS"
        )
        self.assertEqual(self.memory.remember_command("Remember this: use metres"), "use metres")
        self.assertEqual(self.memory.remember_command("记住：使用米"), "使用米")
        self.assertIsNone(self.memory.remember_command("What do you remember about QGIS?"))
        self.assertIsNone(self.memory.remember_command("Don't remember this"))

    def test_write_contains_only_the_note_and_never_a_whole_conversation(self):
        body = self.memory.note_request(
            self.config(), "qgis-note-fixture", "Use metres", 1234567890000
        )
        self.assertEqual(
            body,
            {
                "session_id": "qgis-note-fixture",
                "app_id": "default",
                "project_id": "default",
                "messages": [
                    {
                        "sender_id": "fixture-user",
                        "role": "user",
                        "timestamp": 1234567890000,
                        "content": "Use metres",
                    }
                ],
            },
        )
        with self.assertRaises(ValueError):
            self.memory.note_request(
                self.config(),
                "qgis-note-fixture",
                "API key: sk-not-a-real-secret-1234",
                1234567890000,
            )


if __name__ == "__main__":
    unittest.main()
