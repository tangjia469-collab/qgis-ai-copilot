"""Text selection and explicit quoted follow-ups never send or alter history."""

import os
import tempfile
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsApplication

from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.widgets import CodeBlock, MessageCard, SafeTextBrowser
from tests.qgis_runtime import configure_prefix
from tests.qgis_smoke import FakeIface


class ResponseSelectionTests(unittest.TestCase):
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
        self.dock.client.abort_catalog()
        self.message = {"id": "answer", "role": "assistant", "status": "complete", "content": "Inspect the coordinate system before analysis.\n\n选中这段文字，继续提问。"}
        self.dock.conversation = self.dock._blank_conversation()
        self.dock.conversation["messages"] = [self.message]
        self.dock._render_conversation()
        self.iface.window.show()
        self.dock.show()
        QTest.qWait(30)
        self.card = next(c for c in self.dock.conversation_body.findChildren(MessageCard) if c.message is self.message)
        self.browser = next(b for b in self.card.body.findChildren(SafeTextBrowser) if b.isVisible())

    def tearDown(self):
        self.plugin.unload()
        self.iface.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def select(self, text):
        cursor = self.browser.document().find(text)
        self.assertFalse(cursor.isNull())
        self.browser.setTextCursor(cursor)

    def quote_action(self):
        self.assertTrue(hasattr(self.browser, "_selection_context_menu"), "Missing selected-passage follow-up action")
        menu = self.browser._selection_context_menu()
        return next((a for a in menu.actions() if a.text() == "Ask about selection"), None)

    def test_selection_menu_has_native_copy_and_select_all(self):
        self.select("coordinate")
        menu = self.browser._selection_context_menu()
        actions = {action.text().split("\t")[0].replace("&", ""): action for action in menu.actions()}
        self.assertIn("Select All", actions)
        actions["Copy"].trigger()
        self.assertEqual(QApplication.clipboard().text(), "coordinate")

    def test_code_selection_can_be_quoted_without_copying_the_entire_box(self):
        self.card.finalize('```qgis\n"field" > 10\n```', "complete")
        editor = self.card.body.findChild(CodeBlock).editor
        editor.setTextCursor(editor.document().find('"field"'))
        menu = editor._selection_context_menu()
        next(a for a in menu.actions() if a.text() == "Ask about selection").trigger()
        self.assertEqual(self.dock.message_input.toPlainText(), 'About this passage:\n> "field"\n\n')

    def test_expanded_technical_details_selection_can_be_quoted(self):
        self.card.finalize('Result.\n\n### Raw log\n\nA specific warning.\n\n### Next\n\nContinue.', "complete")
        self.card.body.disclosures[0].toggle.click()
        QTest.qWait(20)
        self.browser = next(b for b in self.card.body.disclosures[0].browser.findChildren(SafeTextBrowser) if b.isVisible())
        self.select("specific warning")
        self.quote_action().trigger()
        self.assertIn("> specific warning", self.dock.message_input.toPlainText())

    def test_quote_length_limit_preserves_draft(self):
        self.dock.message_input.setPlainText("x" * 11990)
        self.select("coordinate system")
        self.quote_action().trigger()
        self.assertEqual(self.dock.message_input.toPlainText(), "x" * 11990)

    def test_mouse_double_click_and_shift_keyboard_select_text(self):
        self.browser.setFocus()
        cursor = self.browser.document().find("coordinate")
        position = self.browser.cursorRect(cursor).center()
        QTest.mouseDClick(self.browser.viewport(), Qt.LeftButton, Qt.NoModifier, position)
        self.assertTrue(self.browser.textCursor().hasSelection())
        cursor.setPosition(0)
        self.browser.setTextCursor(cursor)
        QTest.keyClick(self.browser, Qt.Key_Right, Qt.ShiftModifier)
        self.assertEqual(self.browser.textCursor().selectedText(), "I")

    def test_selected_copy_only_copies_highlighted_phrase(self):
        self.select("coordinate system")
        self.browser.copy()
        self.assertEqual(QApplication.clipboard().text(), "coordinate system")
        self.assertEqual(self.message["content"], "Inspect the coordinate system before analysis.\n\n选中这段文字，继续提问。")

    def test_ask_about_selection_appends_quote_preserves_draft_and_never_sends(self):
        self.dock.message_input.setPlainText("My existing draft")
        self.select("选中这段文字")
        with patch.object(self.dock.client, "send_chat") as send:
            action = self.quote_action()
            self.assertIsNotNone(action)
            action.trigger()
            send.assert_not_called()
        self.assertEqual(self.dock.message_input.toPlainText(), "My existing draft\n\nAbout this passage:\n> 选中这段文字\n\n")
        self.assertIsNone(self.dock._active_message)
        self.assertEqual(self.dock.conversation["messages"], [self.message])

    def test_menu_has_no_quote_action_without_selection(self):
        self.assertIsNone(self.quote_action())

    def test_streaming_append_preserves_highlighted_passage(self):
        self.card.message.update(status="streaming", content="First words")
        self.card.body.set_content("First words", False)
        self.browser = self.card.body._plain_browser
        self.select("First")
        self.card.append_delta(" and more tokens")
        self.assertEqual(self.browser.textCursor().selectedText(), "First")

    def test_latest_question_edit_does_not_get_overwritten_by_quoted_followup(self):
        self.dock._editing_message_id = "question"
        self.dock.message_input.setPlainText("Edited question draft")
        self.select("coordinate system")
        self.quote_action().trigger()
        self.assertEqual(self.dock.message_input.toPlainText(), "Edited question draft")
        self.dock._editing_message_id = None


if __name__ == "__main__":
    unittest.main()
