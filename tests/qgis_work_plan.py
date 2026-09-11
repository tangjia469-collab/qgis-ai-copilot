"""Native work-plan presentation for live Chat/Execute responses."""

import os
import tempfile
import unittest
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QLabel
from qgis.core import QgsApplication

from qgis_ai_copilot.styles import build_stylesheet
from qgis_ai_copilot.widgets import MessageCard, WorkPlanPanel
from tests.qgis_runtime import configure_prefix


class WorkPlanTests(unittest.TestCase):
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

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def card(self, status="streaming"):
        card = MessageCard({"role": "assistant", "content": "", "status": status})
        card.setStyleSheet(build_stylesheet(card.palette()))
        card.show()
        QTest.qWait(20)
        return card

    def add(self, card, identifier, kind, text):
        card.add_activity({"id": identifier, "kind": kind, "text": text})

    def test_work_plan_replaces_repeated_log_with_current_and_completed_steps(self):
        card = self.card()
        self.add(card, "context", "local", "Prepared 4 selected QGIS context categories.")
        self.add(card, "summary:one", "summary", "Reviewing QGIS layer setup")
        self.add(card, "summary:two", "summary", "Checking dissolve field behavior")
        card.update_progress("waiting", 9, 0)
        panel = card.activity_panel
        self.assertIsInstance(panel, WorkPlanPanel)
        self.assertEqual(panel.title_label.text(), "Working on your request")
        self.assertEqual(panel.mode_label.text(), "Chat · no QGIS changes")
        self.assertIn("Checking dissolve field behavior", panel.current_label.text())
        self.assertEqual(panel.current_state, "working")
        self.assertEqual(panel.completed_labels(), ["Prepared QGIS context", "Reviewing QGIS layer setup"])
        self.assertIn("Step 3", panel.step_label.text())
        self.assertIn("Details · 3 updates", panel.activity_toggle.text())
        self.assertNotIn("Reasoning summary", panel.activity_view.toPlainText())
        self.assertIn("Checking dissolve field behavior", panel.activity_view.toPlainText())

    def test_transport_state_is_meaningful_before_public_plan_arrives(self):
        card = self.card()
        card.update_progress("sending", 1, 0)
        panel = card.activity_panel
        self.assertIn("Sending the request", panel.current_label.text())
        card.update_progress("waiting", 12, 7)
        self.assertIn("Waiting for the router", panel.current_label.text())
        self.assertIn("00:12", panel.status_label.text())

    def test_stop_stays_available_in_work_plan_header(self):
        card = self.card()
        card.update_progress("receiving", 4, 0)
        self.assertFalse(card.stop_button.isHidden())
        self.assertIs(card.stop_button.parentWidget(), card.activity_panel.header)
        calls = []
        card.stopRequested.connect(lambda: calls.append(True))
        card.stop_button.click()
        self.assertEqual(calls, [True])
        card.finalize("Partial", "stopped")
        self.assertTrue(card.stop_button.isHidden())
        self.assertEqual(card.activity_panel.current_state, "stopped")

    def test_completed_work_collapses_to_one_summary_row_and_keeps_details(self):
        card = self.card()
        for identifier, text in (
            ("one", "Read shared layer details"),
            ("two", "Selecting green-space features"),
            ("three", "Preparing the answer"),
        ):
            self.add(card, identifier, "commentary", text)
        card.finalize("Answer", "complete")
        panel = card.activity_panel
        self.assertEqual(panel.title_label.text(), "Answer ready · 3 steps")
        self.assertFalse(panel.current_label.isVisible())
        self.assertFalse(panel.steps_widget.isVisible())
        self.assertFalse(panel.activity_toggle.isChecked())
        self.assertTrue(panel.activity_panel_visible_details())
        panel.activity_toggle.click()
        self.assertTrue(panel.activity_view.isVisible())

    def test_approval_and_tool_results_are_concrete_steps(self):
        card = self.card()
        self.add(card, "approval", "local", "Awaiting approval: Run Dissolve on green spaces")
        self.assertEqual(card.activity_panel.current_state, "approval")
        self.assertIn("Waiting for your approval", card.activity_panel.status_label.text())
        self.add(card, "run", "local", "Running: Dissolve green spaces into a temporary layer")
        self.assertEqual(card.activity_panel.current_state, "working")
        self.add(card, "done", "local", "Completed: Dissolve green spaces into a temporary layer\nResult: Green_Space")
        self.assertIn("Dissolve green spaces", card.activity_panel.completed_labels()[-1])

    def test_duplicate_updates_replace_one_step_not_many_rows(self):
        card = self.card()
        self.add(card, "step", "commentary", "Checking dissolve fields")
        self.add(card, "step", "commentary", "Checking dissolve fields and selection")
        self.assertEqual(card.activity_panel.step_count(), 1)
        self.assertIn("Checking dissolve fields and selection", card.activity_panel.current_label.text())

    def test_markdown_emphasis_is_clean_and_model_text_stays_plain(self):
        card = self.card()
        self.add(card, "summary", "summary", "**Checking dissolve field behavior**")
        self.assertNotIn("**", card.activity_panel.current_label.text())
        self.assertEqual(card.activity_panel.current_label.textFormat(), Qt.PlainText)
        previous_row = card.activity_panel.steps_layout.itemAt(0).widget()
        self.add(card, "unsafe", "summary", '<img src="file:///tmp/private.png">')
        self.assertEqual(card.activity_panel.current_label.textFormat(), Qt.PlainText)
        rows = [
            label for label in card.activity_panel.steps_widget.findChildren(QLabel)
            if label.property("kind") == "work-step"
        ]
        self.assertTrue(rows)
        self.assertTrue(all(label.textFormat() == Qt.PlainText for label in rows))
        self.assertTrue(previous_row.isHidden())

    def test_terminal_failure_does_not_look_like_running_work(self):
        card = self.card()
        card.update_progress("sending", 2, 0)
        card.finalize("", "error", {"message": "Router unavailable"})
        self.assertEqual(card.activity_panel.title_label.text(), "Request failed")
        self.assertFalse(card.activity_panel.current_label.isVisible())
        self.assertFalse(card.activity_panel.steps_widget.isVisible())
        card.finalize("", "stopped")
        self.assertEqual(card.activity_panel.title_label.text(), "Stopped")

    def test_long_updates_do_not_grow_a_wall_of_steps(self):
        card = self.card()
        for index in range(12):
            self.add(card, str(index), "commentary", f"Step {index}: inspect a different GIS operation")
        self.assertLessEqual(len(card.activity_panel.current_label.text()), 200)
        self.assertLessEqual(card.activity_panel.steps_layout.count(), 4)

    def test_explicit_next_commentary_is_pending_not_completed(self):
        card = self.card()
        self.add(card, "plan", "commentary", "Now: Checking dissolve options\nNext: Write the QGIS steps")
        self.assertIn("Checking dissolve options", card.activity_panel.current_label.text())
        self.assertEqual(card.activity_panel.next_label.text(), "Next · Write the QGIS steps")
        self.assertNotIn("Write the QGIS steps", card.activity_panel.completed_labels())
        self.add(card, "next-only", "commentary", "Next: Write the QGIS steps")
        self.assertNotIn("Write the QGIS steps", card.activity_panel.current_label.text())
        self.add(card, "later", "commentary", "Review the dissolve result")
        self.assertEqual(card.activity_panel.next_label.text(), "")

    def test_terminal_state_is_visible_even_without_activity(self):
        card = self.card()
        card.finalize("", "error", {"message": "Router unavailable"})
        self.assertTrue(card.activity_panel.isVisible())
        self.assertEqual(card.activity_panel.title_label.text(), "Request failed")
        self.assertFalse(card.activity_panel.current_label.isVisible())

    def test_private_or_empty_activity_never_enters_work_plan(self):
        card = self.card()
        self.add(card, "raw", "raw_reasoning", "PRIVATE_REASONING")
        self.add(card, "blank", "local", "")
        self.assertEqual(card.activity_panel.step_count(), 0)
        self.assertFalse(card.activity_panel.isVisible())

    def test_narrow_plan_fits_without_horizontal_scroll(self):
        card = self.card()
        for i in range(8):
            self.add(card, f"s{i}", "commentary", "Checking a useful GIS operation " + str(i))
        for width in (360, 420, 460):
            card.resize(width, 420)
            QTest.qWait(30)
            self.assertLessEqual(card.activity_panel.width(), width)
            self.assertFalse(card.activity_panel.activity_view.horizontalScrollBar().isVisible())

    def test_render_working_and_finished_plan_previews(self):
        output = Path(__file__).resolve().parents[1] / "artifacts"
        output.mkdir(exist_ok=True)
        card = self.card()
        self.add(card, "context", "local", "Prepared 4 selected QGIS context categories.")
        self.add(card, "summary:one", "summary", "Reviewing QGIS layer setup")
        self.add(card, "summary:two", "summary", "Checking dissolve field behavior")
        card.update_progress("waiting", 12, 0)
        card.resize(420, 620)
        QTest.qWait(50)
        self.assertTrue(card.grab().save(str(output / "work-plan-working.png")))
        card.finalize("Leave the Dissolve field empty.", "complete")
        QTest.qWait(50)
        self.assertTrue(card.grab().save(str(output / "work-plan-finished.png")))


if __name__ == "__main__":
    unittest.main()
