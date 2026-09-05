"""Regression checks for compact footers and transactional latest-question edits."""

import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPoint
from qgis.PyQt.QtGui import QColor, QImage
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QWidget, QVBoxLayout
from qgis.core import QgsApplication

from qgis_ai_copilot.attachments import prepare_image
from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.protocol import ModelRecord, RouterProfile
from qgis_ai_copilot.styles import build_stylesheet
from qgis_ai_copilot.widgets import MessageCard
from tests.qgis_runtime import configure_prefix
from tests.qgis_smoke import FakeIface


class MessageEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()

    @classmethod
    def tearDownClass(cls):
        cls.app.exitQgis()
        cls.temp.cleanup()

    def setUp(self):
        self.iface = FakeIface()
        self.plugin = QgisAiCopilotPlugin(self.iface)
        self.plugin.initGui()
        self.dock = self.plugin.dock
        d = self.dock
        d.client.abort_catalog()
        d.profile = RouterProfile(
            base_url="http://127.0.0.1:9870", adapter="responses", reasoning_summaries=True
        )
        d.records = [ModelRecord("test-model", supports_images=True)]
        d.selected_model = "test-model"
        d.catalog_ready = True
        d.conversation = d._blank_conversation()
        self.early_user = {"id": "u0", "role": "user", "content": "Earlier prompt"}
        self.early_answer = {
            "id": "a0",
            "role": "assistant",
            "content": "Earlier answer",
            "status": "complete",
        }
        self.user = {
            "id": "u1",
            "role": "user",
            "content": "Original latest question",
            "router_id": d._router_identity(),
        }
        self.answer = {
            "id": "a1",
            "role": "assistant",
            "content": "Outdated latest answer",
            "status": "complete",
            "request": {
                "model": "test-model",
                "user_message_id": "u1",
                "router_id": d._router_identity(),
                "context": {},
                "adapter": "responses",
                "reasoning_summaries": True,
            },
        }
        d.conversation["messages"] = [self.early_user, self.early_answer, self.user, self.answer]
        d._persist_conversation()
        d._render_conversation()
        self.before = deepcopy(d.conversation)
        self.send = patch.object(d.client, "send_chat").start()
        self.warn = patch("qgis_ai_copilot.dock.QMessageBox.warning").start()
        self.confirm = patch(
            "qgis_ai_copilot.dock.QMessageBox.question", return_value=QMessageBox.Yes
        ).start()
        self.iface.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.plugin.unload()
        self.iface.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        patch.stopall()

    def saved(self):
        return self.dock.store.load_conversation(self.dock.project_id, self.dock.conversation["id"])

    def image(self, color):
        pixels = QImage(32, 32, QImage.Format_RGB32)
        pixels.fill(QColor(color))
        return prepare_image(pixels, color + ".png")

    def begin(self):
        self.dock._begin_edit_question(self.user)
        self.dock.message_input.setPlainText("Revised latest question")

    def test_edit_send_replaces_latest_pair_and_never_sends_stale_answer(self):
        self.begin()
        self.dock._send_or_stop()
        messages = self.dock.conversation["messages"]
        self.assertEqual(
            [m["content"] for m in messages if m["role"] == "user"],
            ["Earlier prompt", "Revised latest question"],
        )
        self.assertEqual(messages[:2], self.before["messages"][:2])
        self.assertNotIn("a1", [m["id"] for m in messages])
        self.assertNotIn("u1", [m["id"] for m in messages])
        self.assertIsNone(self.dock._editing_message_id)
        self.assertEqual(self.send.call_count, 1)
        outgoing = json.dumps(self.send.call_args.args[1])
        self.assertIn("Revised latest question", outgoing)
        self.assertNotIn("Original latest question", outgoing)
        self.assertNotIn("Outdated latest answer", outgoing)
        saved = self.saved()["messages"]
        self.assertEqual([m["id"] for m in saved], [m["id"] for m in messages])
        self.assertEqual(
            [m["content"] for m in saved if m["role"] == "user"],
            ["Earlier prompt", "Revised latest question"],
        )
        self.assertNotIn("Outdated latest answer", json.dumps(saved))

    def test_cancel_edit_restores_preexisting_text_and_attachments(self):
        d = self.dock
        draft = self.image("red")
        d._add_attachment(draft)
        d.message_input.setPlainText("Unsent draft")
        self.begin()
        d._cancel_edit_question()
        self.assertEqual(d.message_input.toPlainText(), "Unsent draft")
        self.assertEqual(list(d.attachments), [draft.attachment_id])
        self.assertEqual(d.conversation, self.before)
        self.assertEqual(self.saved()["messages"], self.before["messages"])
        self.assertFalse(self.send.called)

    def test_send_confirmation_cancel_keeps_old_history_and_edit_draft(self):
        self.confirm.return_value = QMessageBox.Cancel
        self.begin()
        self.dock._send_or_stop()
        self.assertEqual(self.dock.conversation, self.before)
        self.assertEqual(self.saved()["messages"], self.before["messages"])
        self.assertEqual(self.dock._editing_message_id, "u1")
        self.assertEqual(self.dock.message_input.toPlainText(), "Revised latest question")
        self.assertFalse(self.send.called)

    def test_missing_visual_requires_reattach_or_explicit_remove(self):
        d = self.dock
        lost = self.image("blue")
        self.user["attachments"] = [lost.manifest()]
        original = deepcopy(d.conversation)
        self.begin()
        d._send_or_stop()
        self.assertEqual(d.conversation, original)
        self.assertFalse(self.send.called)
        d._remove_attachment(lost.attachment_id)
        d._send_or_stop()
        self.assertEqual(self.send.call_count, 1)
        self.assertNotIn(
            "attachments", [m for m in d.conversation["messages"] if m["role"] == "user"][-1]
        )

    def test_removing_visual_from_edit_does_not_erase_original_cache(self):
        d = self.dock
        item = self.image("green")
        self.user["attachments"] = [item.manifest()]
        d._attachment_payloads[item.attachment_id] = item
        self.begin()
        d._remove_attachment(item.attachment_id)
        d._cancel_edit_question()
        self.assertIs(d._attachment_payloads.get(item.attachment_id), item)
        self.assertEqual(self.user["attachments"], [item.manifest()])

    def test_cancel_edit_invalidates_pending_capture_and_keeps_original_history(self):
        self.begin()
        self.dock._schedule_screen_capture()
        self.dock._cancel_edit_question()
        self.assertFalse(self.dock._capture_timer.isActive())
        self.assertEqual(self.dock.conversation, self.before)

    def test_repeat_edit_click_does_not_reset_ongoing_revision(self):
        self.begin()
        self.dock._begin_edit_question(self.user)
        self.assertEqual(self.dock.message_input.toPlainText(), "Revised latest question")

    def test_old_question_is_not_editable_and_retry_is_blocked_while_editing(self):
        self.dock._begin_edit_question(self.early_user)
        self.assertIsNone(self.dock._editing_message_id)
        self.begin()
        self.dock._retry_message(self.answer, False)
        self.assertFalse(self.send.called)

    def test_local_tool_results_survive_revision(self):
        tool = {
            "id": "t1",
            "role": "tool",
            "tool_result": {
                "tool": "check_crs_consistency",
                "risk": "R0 read-only",
                "result": {"consistent": True},
            },
        }
        self.dock.conversation["messages"].append(tool)
        self.dock._render_conversation()
        self.begin()
        self.dock._send_or_stop()
        self.assertIn(tool, self.dock.conversation["messages"])
        self.assertNotIn(self.answer, self.dock.conversation["messages"])

    def test_old_retry_is_rejected_after_revision(self):
        self.begin()
        self.dock._send_or_stop()
        self.dock._chat_completed("New answer", False, {})
        self.send.reset_mock()
        self.dock._retry_message(self.answer, False)
        self.assertFalse(self.send.called)

    def test_reattached_original_visual_is_carried_in_revision(self):
        lost = self.image("blue")
        self.user["attachments"] = [lost.manifest()]
        self.begin()
        self.dock._add_attachment(lost)
        self.dock._send_or_stop()
        self.assertEqual(self.send.call_count, 1)
        sent = json.dumps(self.send.call_args.args[1])
        self.assertIn(lost.parts[0]["image_url"]["url"], sent)
        self.assertFalse(self.dock._edit_missing_attachments)

    def test_profile_change_during_consent_prevents_commit(self):
        self.begin()

        def change_profile(*_args):
            self.dock.profile = RouterProfile(base_url="https://another.example")
            return QMessageBox.Yes

        self.confirm.side_effect = change_profile
        self.dock._send_or_stop()
        self.assertFalse(self.send.called)
        self.assertEqual(self.dock.conversation, self.before)
        self.assertEqual(self.dock.message_input.toPlainText(), "Revised latest question")

    def test_invalid_revision_and_storage_failure_preserve_existing_answer(self):
        self.begin()
        self.dock.message_input.setPlainText("x" * 12001)
        self.dock._send_or_stop()
        self.assertEqual(self.dock.conversation, self.before)
        self.assertFalse(self.send.called)
        self.dock.message_input.setPlainText("A valid revision")
        with patch.object(self.dock, "_persist_conversation", side_effect=OSError("disk full")):
            self.dock._send_or_stop()
        self.assertEqual(self.dock.conversation, self.before)
        self.assertFalse(self.send.called)
        self.assertEqual(self.dock._editing_message_id, "u1")

    def test_revision_and_pending_answer_are_committed_once_before_dispatch(self):
        self.begin()
        snapshots = []
        real_save = self.dock._persist_conversation

        def save_once():
            snapshots.append(deepcopy(self.dock.conversation["messages"]))
            if len(snapshots) > 1:
                raise OSError("No second pre-dispatch write allowed")
            real_save()

        with patch.object(self.dock, "_persist_conversation", side_effect=save_once):
            self.dock._send_or_stop()
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0][-1]["role"], "assistant")
        self.assertEqual(snapshots[0][-1]["status"], "streaming")
        self.assertEqual(self.send.call_count, 1)

    def test_navigation_drops_revision_and_restores_preedit_text(self):
        d = self.dock
        for change in (d._new_chat, lambda: d._profile_saved(RouterProfile())):
            d.conversation = deepcopy(self.before)
            d.message_input.setPlainText("Pre-edit draft")
            current = next(m for m in d.conversation["messages"] if m["id"] == "u1")
            d._begin_edit_question(current)
            d.message_input.setPlainText("Do not leak this revision")
            change()
            self.assertIsNone(d._editing_message_id)
            self.assertEqual(d.message_input.toPlainText(), "Pre-edit draft")

    def test_long_question_collapses_and_expands_without_hiding_content(self):
        text = "Long question line\n" * 50
        card = MessageCard({"role": "user", "content": text}, editable=True)
        card.setStyleSheet(build_stylesheet(card.palette()))
        card.resize(340, 500)
        card.show()
        self.app.processEvents()
        self.assertLessEqual(card.body.height(), 90)
        self.assertEqual(card.body.toPlainText(), text)
        self.assertTrue(hasattr(card, "question_toggle"))
        card.question_toggle.click()
        self.app.processEvents()
        self.assertGreater(card.body.height(), 300)
        card.question_toggle.click()
        self.app.processEvents()
        self.assertLessEqual(card.body.height(), 90)
        card.close()
        card.deleteLater()

    def test_metadata_and_small_copy_icon_belong_below_the_answer(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        message = {
            "role": "assistant",
            "content": "A useful answer.\n" * 6,
            "status": "complete",
            "created_at": "2026-09-05T18:00:00+00:00",
            "request": {"model": "long-model-id-" * 9, "thinking": "Max"},
        }
        card = MessageCard(message, container)
        layout.addWidget(card)
        container.setStyleSheet(build_stylesheet(container.palette()))
        container.resize(360, 500)
        container.show()
        self.app.processEvents()
        self.assertGreater(
            card.copy_button.mapTo(card, QPoint()).y(), card.body.geometry().bottom()
        )
        self.assertGreater(
            card.footer_meta.mapTo(card, QPoint()).y(), card.body.geometry().bottom()
        )
        self.assertLessEqual(card.copy_button.width(), 24)
        self.assertLessEqual(card.copy_button.height(), 24)
        self.assertEqual(card.copy_button.text(), "")
        self.assertFalse(card.copy_button.icon().isNull())
        self.assertIn(message["request"]["model"], card.footer_meta.toolTip())
        card.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), message["content"])
        card._restore_copy_feedback()
        artifacts = Path(__file__).resolve().parents[1] / "artifacts"
        artifacts.mkdir(exist_ok=True)
        for width in (360, 420, 460):
            container.resize(width, 500)
            self.app.processEvents()
            for child in (card.copy_button, card.footer_meta):
                self.assertLessEqual(child.mapTo(card, QPoint()).x() + child.width(), card.width())
            card.grab().save(str(artifacts / f"message-footer-{width}.png"))
        container.close()
        container.deleteLater()

    def test_compact_user_and_blue_answer_in_actual_dock(self):
        d = self.dock
        self.user["content"] = "How do I measure a 500 m buffer?\n" * 10
        self.answer["content"] = (
            "Use a projected CRS whose units are metres.\n\nThen run **Buffer** with a distance of **500**. Save the result if you need it later."
        )
        self.answer["created_at"] = "2026-09-05T18:00:00+00:00"
        self.answer["request"].update(model="gpt-6-astra", thinking="Max")
        d.conversation["messages"] = [self.user, self.answer]
        d._render_conversation()
        d.setFloating(True)
        d.resize(420, 720)
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        for _ in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
            self.app.processEvents()
        cards = d.conversation_body.findChildren(MessageCard)
        question = next(card for card in cards if card.message is self.user)
        answer = next(card for card in cards if card.message is self.answer)
        self.assertLessEqual(question.height(), 125)
        self.assertFalse(question.question_toggle.isHidden())
        d.grab().save(
            str(Path(__file__).resolve().parents[1] / "artifacts" / "message-cards-compact.png")
        )
        self.assertLess(
            answer.height(),
            220,
            (
                answer.body.height(),
                answer.body.width(),
                answer.body.document().size().height(),
                answer.sizeHint().height(),
            ),
        )


if __name__ == "__main__":
    unittest.main()
