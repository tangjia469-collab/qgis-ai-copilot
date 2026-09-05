import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from qgis_ai_copilot.storage import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ConversationStore(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_save_and_load_conversation(self):
        conversation = self.store.create_conversation("project-a", "Spatial join")
        conversation["messages"].append({"role": "user", "content": "Check this layer"})
        self.store.save_conversation("project-a", conversation)
        loaded = self.store.load_conversation("project-a", conversation["id"])
        self.assertEqual(loaded["title"], "Spatial join")
        self.assertEqual(loaded["messages"][0]["content"], "Check this layer")

    def test_projects_are_isolated_and_can_be_rebound(self):
        conversation = self.store.create_conversation("unsaved-1", "Draft")
        self.assertEqual(self.store.list_conversations("project-b"), [])
        self.store.rebind_project("unsaved-1", "project-b")
        copied = self.store.load_conversation("project-b", conversation["id"])
        self.assertIsNotNone(copied)

    def test_corrupt_file_is_treated_as_empty_without_deleting_it(self):
        path = Path(self.temporary.name) / "project-c.json"
        path.write_text("not json", encoding="utf-8")
        self.assertEqual(self.store.list_conversations("project-c"), [])
        self.assertEqual(path.read_text(encoding="utf-8"), "not json")

    def test_secret_like_profile_fields_are_not_added_by_store(self):
        conversation = self.store.create_conversation("project-d", "Private")
        path = Path(self.temporary.name) / "project-d.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("api_key", json.dumps(payload).lower())
        self.assertEqual(payload["conversations"][0]["id"], conversation["id"])

    def test_storage_uses_private_permissions(self):
        conversation = self.store.create_conversation("project-private", "Private")
        self.store.save_conversation("project-private", conversation)
        path = Path(self.temporary.name) / "project-private.json"
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(Path(self.temporary.name).stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_expired_conversations_are_pruned_and_project_can_be_cleared(self):
        self.store.create_conversation("project-old", "Old")
        path = Path(self.temporary.name) / "project-old.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["conversations"][0]["updated_at"] = "2000-01-01T00:00:00+00:00"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.store.list_conversations("project-old"), [])
        self.store.create_conversation("project-old", "Current")
        self.store.clear_project("project-old")
        self.assertFalse(path.exists())

    def test_persisted_request_drops_auth_material_and_sanitizes_context(self):
        conversation = self.store.create_conversation("project-safe", "Safe request")
        conversation["messages"].append(
            {
                "role": "assistant",
                "content": "Visible response",
                "request": {
                    "profile_name": "Router",
                    "model": "model-a",
                    "thinking": "Auto",
                    "stream": True,
                    "context_keys": ["active_layer"],
                    "user_message_id": "message-a",
                    "authcfg": "auth-secret",
                    "headers": {"Authorization": "Bearer top-secret-token"},
                    "context": {
                        "active_layer": {"name": "roads"},
                        "authorization": "Bearer another-secret-token",
                        "note": "token=secret-value",
                    },
                },
            }
        )
        self.store.save_conversation("project-safe", conversation)
        path = Path(self.temporary.name) / "project-safe.json"
        encoded = path.read_text(encoding="utf-8").lower()
        self.assertNotIn("authcfg", encoded)
        self.assertNotIn("authorization", encoded)
        self.assertNotIn("top-secret-token", encoded)
        self.assertNotIn("another-secret-token", encoded)
        self.assertNotIn("secret-value", encoded)
        self.assertIn("[redacted]", encoded)

    def test_attachment_persistence_keeps_manifest_but_drops_binary_and_path(self):
        conversation = self.store.create_conversation("project-attachments", "Attachments")
        conversation["messages"].append(
            {
                "role": "user",
                "content": "Inspect this",
                "attachments": [
                    {
                        "id": "attachment-1",
                        "name": "screen.png",
                        "mime_type": "image/png",
                        "source_kind": "file",
                        "size": 42,
                        "sha256": "a" * 64,
                        "path": "/Users/private/screen.png",
                        "data_uri": "data:image/png;base64,SECRET",
                    }
                ],
            }
        )
        conversation["messages"].append(
            {
                "role": "assistant",
                "content": "I can see it.",
                "request": {
                    "profile_name": "Router",
                    "model": "vision-model",
                    "thinking": "Auto",
                    "stream": True,
                    "context": {},
                    "context_keys": [],
                    "user_message_id": "message-a",
                    "attachments": conversation["messages"][0]["attachments"],
                },
            }
        )
        self.store.save_conversation("project-attachments", conversation)
        path = Path(self.temporary.name) / "project-attachments.json"
        encoded = path.read_text(encoding="utf-8")
        self.assertIn("screen.png", encoded)
        self.assertIn("image/png", encoded)
        self.assertNotIn("/Users/private", encoded)
        self.assertNotIn("data_uri", encoded)
        self.assertNotIn("SECRET", encoded)
        self.assertNotIn('"path"', encoded)

    def test_error_echo_drops_inline_images_and_retry_keeps_router_digest(self):
        conversation = self.store.create_conversation("project-error", "Error")
        conversation["messages"].append({
            "role": "assistant", "content": "", "status": "error",
            "error": {"message": "Invalid image data:image/png;base64," + "A" * 250},
            "request": {"router_id": "a" * 64, "destination": ["https://example.com", "private-auth"]},
        })
        self.store.save_conversation("project-error", conversation)
        saved = self.store.load_conversation("project-error", conversation["id"])
        self.assertEqual(saved["messages"][0]["request"], {"router_id": "a" * 64})
        encoded = json.dumps(saved)
        self.assertNotIn("data:image", encoded)
        self.assertNotIn("A" * 160, encoded)
        self.assertNotIn("private-auth", encoded)

    def test_legacy_processing_error_is_sanitized_and_rewritten_on_read(self):
        path = Path(self.temporary.name) / "project-legacy.json"
        payload = {
            "schema": 1,
            "project_id": "project-legacy",
            "conversations": [
                {
                    "id": "legacy-chat",
                    "title": "Legacy",
                    "created_at": "2099-01-01T00:00:00+00:00",
                    "updated_at": "2099-01-01T00:00:00+00:00",
                    "messages": [
                        {
                            "role": "tool",
                            "tool_result": {
                                "tool": "explain_processing_error",
                                "result": {
                                    "error": "Failed at /Users/private/data.gpkg Bearer legacy-secret"
                                },
                            },
                        }
                    ],
                }
            ],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = self.store.read_project("project-legacy")
        result = loaded["conversations"][0]["messages"][0]["tool_result"]["result"]
        self.assertNotIn("error", result)
        self.assertFalse(result["original_error_included"])
        rewritten = path.read_text(encoding="utf-8")
        self.assertNotIn("/Users/private", rewritten)
        self.assertNotIn("legacy-secret", rewritten)

    def test_startup_purge_rewrites_unexpired_legacy_conversation(self):
        path = Path(self.temporary.name) / "project-startup.json"
        payload = {
            "schema": 1,
            "project_id": "project-startup",
            "conversations": [
                {
                    "id": "current-legacy-chat",
                    "title": "Current legacy chat",
                    "created_at": "2099-01-01T00:00:00+00:00",
                    "updated_at": "2099-01-01T00:00:00+00:00",
                    "messages": [
                        {
                            "role": "tool",
                            "tool_result": {
                                "tool": "explain_processing_error",
                                "result": {
                                    "error": (
                                        "Failed at /Users/private/data.gpkg "
                                        "with Bearer startup-secret"
                                    )
                                },
                            },
                        },
                        {
                            "role": "assistant",
                            "error": {
                                "message": "token=startup-token at /tmp/router.log",
                                "headers": {"Authorization": "Bearer header-secret"},
                            },
                        },
                    ],
                }
            ],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

        self.assertEqual(self.store.purge_expired(), 0)

        rewritten = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(rewritten["conversations"]), 1)
        messages = rewritten["conversations"][0]["messages"]
        result = messages[0]["tool_result"]["result"]
        self.assertNotIn("error", result)
        self.assertFalse(result["original_error_included"])
        self.assertNotIn("headers", messages[1]["error"])
        encoded = json.dumps(rewritten)
        self.assertNotIn("/Users/private", encoded)
        self.assertNotIn("startup-secret", encoded)
        self.assertNotIn("startup-token", encoded)
        self.assertNotIn("header-secret", encoded)


if __name__ == "__main__":
    unittest.main()
