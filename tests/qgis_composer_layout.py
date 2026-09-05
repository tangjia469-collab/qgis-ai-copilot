"""Native regression checks for composer-anchored context/model controls."""

import os
import tempfile
import unittest
from pathlib import Path

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt, QTimer
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QDialogButtonBox
from qgis.core import QgsApplication

from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.protocol import ModelRecord
from tests.qgis_smoke import FakeIface
from tests.qgis_runtime import configure_prefix


class ComposerLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temporary.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()

    @classmethod
    def tearDownClass(cls):
        cls.app.exitQgis()
        cls.temporary.cleanup()

    def setUp(self):
        self.iface = FakeIface()
        self.plugin = QgisAiCopilotPlugin(self.iface)
        self.plugin.initGui()
        self.dock = self.plugin.dock
        self.dock.setFloating(True)
        self.dock.move(80, 40)
        self.dock.resize(420, 740)
        self.iface.window.show()
        self.dock.show()
        QApplication.setActiveWindow(self.dock)
        self.app.processEvents()

    def tearDown(self):
        if self.plugin.dock is not None:
            self.plugin.unload()
        self.iface.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_model_control_is_immediately_left_of_send_at_each_width(self):
        dock = self.dock
        dock.records = [ModelRecord("gemini-3.8-flash-high"), ModelRecord("second-model", explicit_thinking=("High",))]
        dock.selected_model = dock.records[0].id
        dock._refresh_model_control()
        for width in (360, 420, 460):
            dock.resize(width, 740)
            self.app.processEvents()
            self.assertEqual(dock.width(), max(width, dock.minimumSizeHint().width()))
            self.assertLessEqual(dock.width() - width, 24, "Unexpected content growth beyond floating-window chrome")
            model = dock.model_button.mapTo(dock.root, QPoint())
            send = dock.send_button.mapTo(dock.root, QPoint())
            self.assertEqual(dock.model_button.parentWidget(), dock.send_button.parentWidget())
            self.assertLessEqual(abs(model.y() - send.y()), 3)
            self.assertGreaterEqual(send.x() - model.x() - dock.model_button.width(), 0)
            self.assertLessEqual(send.x() - model.x() - dock.model_button.width(), 10)
            self.assertTrue(dock.model_button.isVisible())
            self.assertIn("gemini-3.8-flash-high", dock.model_button.accessibleName())
            self.assertLess(dock.conversation_scroll.mapTo(dock.root, QPoint()).y(), 55)
            self.assertFalse(dock.chips_widget.isVisible())
            self.assertFalse(dock.context_title.isVisible())
            self.assertFalse(dock.freshness_button.isVisible())

    def test_add_context_opens_the_moved_status_and_chips(self):
        dock = self.dock
        self.assertTrue(hasattr(dock, "context_popover"), "Context strip needs an Add context dropdown")
        baseline = dock.conversation_scroll.height()
        dock.add_context_button.click()
        self.app.processEvents()
        self.assertTrue(dock.context_popover.isVisible())
        self.assertTrue(dock.chips_widget.isVisible())
        self.assertTrue(dock.context_title.isVisible())
        self.assertTrue(dock.project_label.isVisible())
        self.assertTrue(dock.freshness_button.isVisible())
        self.assertTrue(dock.preview_context_button.isVisible())
        self.assertTrue(dock.checks_button.isVisible())
        self.assertEqual(dock.conversation_scroll.height(), baseline)
        dock._remove_context("fields")
        self.assertNotIn("fields", dock.attached_keys)
        self.assertIn("3", dock.context_title.text())
        self.assertIn("3", dock.add_context_button.toolTip())
        dock._context_stale_changed(True, "Map changed")
        self.assertEqual(dock.freshness_button.text(), "Refresh")
        self.assertIn("Map changed", dock.add_context_button.toolTip())
        QTest.keyClick(dock.context_popover, Qt.Key_Escape)
        self.app.processEvents()
        self.assertFalse(dock.context_popover.isVisible())
        self.assertEqual(QApplication.focusWidget(), dock.add_context_button)

    def test_model_popup_opens_upward_and_switches_without_sending(self):
        dock = self.dock
        self.assertTrue(hasattr(dock, "context_popover"), "Missing context dropdown")
        dock.records = [ModelRecord("first-model"), ModelRecord("second-model", explicit_thinking=("High",))]
        dock.selected_model = "first-model"
        dock._refresh_model_control()
        dock.add_context_button.click()
        for width in (360, 420, 460):
            dock.resize(width, 740)
            self.app.processEvents()
            dock.model_button.click()
            self.app.processEvents()
            self.assertFalse(dock.context_popover.isVisible())
            popup = dock.model_popover
            self.assertTrue(popup.isVisible())
            anchor = dock.model_button.mapToGlobal(QPoint())
            self.assertLess(popup.geometry().bottom(), anchor.y())
            dock_rect = QRect(dock.root.mapToGlobal(QPoint()), dock.root.size())
            self.assertTrue(dock_rect.contains(popup.geometry()), (dock_rect, popup.geometry()))
            popup.search.setText("second")
            self.assertEqual(popup.models.count(), 1)
            popup._activate_model(popup.models.item(0))
            popup.thinking.setCurrentText("High")
            popup._activate_thinking("High")
            self.app.processEvents()
            self.assertEqual(dock.selected_model, "second-model")
            self.assertEqual(dock.selected_thinking, "High")
            self.assertFalse(popup.isVisible())
            self.assertEqual(QApplication.focusWidget(), dock.model_button)
            self.assertIsNone(dock._active_message)
            self.assertEqual(dock.conversation["messages"], [])

    def test_context_selection_preview_cancel_and_apply_remain_available(self):
        dock = self.dock
        self.assertTrue(hasattr(dock, "context_popover"), "Missing context dropdown")
        outcomes = []

        def edit_and_finish(apply):
            dialog = QApplication.activeModalWidget()
            outcomes.append("preview" if dialog.preview.toPlainText() else "empty")
            dialog.checks["fields"].setChecked(False)
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.Apply if apply else QDialogButtonBox.Cancel).click()
            # Avoid an indefinitely hanging test if Apply is wired incorrectly.
            if dialog.isVisible():
                outcomes.append("button_did_not_finish")
                dialog.reject()

        for apply in (False, True):
            dock.add_context_button.click()
            QTimer.singleShot(20, lambda active=apply: edit_and_finish(active))
            dock.preview_context_button.click()
            self.assertFalse(dock.context_popover.isVisible())
            self.assertEqual("fields" in dock.attached_keys, not apply)
        self.assertEqual(outcomes, ["preview", "preview"])

    def test_dropdowns_are_closed_and_deleted_on_unload(self):
        dock = self.dock
        self.assertTrue(hasattr(dock, "context_popover"), "Missing context dropdown")
        context, model = dock.context_popover, dock.model_popover
        dock.add_context_button.click()
        self.plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertTrue(sip.isdeleted(context))
        self.assertTrue(sip.isdeleted(model))

    def test_dropdown_geometry_and_visible_controls_at_each_width(self):
        dock = self.dock
        self.assertTrue(hasattr(dock, "context_popover"), "Missing context dropdown")
        dock.records = [ModelRecord("gemini-3.8-flash-high"), ModelRecord("gpt-5.6-sol")]
        dock.selected_model = dock.records[0].id
        dock._refresh_model_control()
        artifacts = Path(__file__).resolve().parents[1] / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        for width in (360, 420, 460):
            dock.resize(width, 740)
            self.app.processEvents()
            self.assertTrue(dock.grab().save(str(artifacts / f"composer-layout-{width}.png")))
            dock.add_context_button.click()
            self.app.processEvents()
            popup = dock.context_popover
            anchor = dock.add_context_button.mapToGlobal(QPoint())
            bounds = QRect(dock.root.mapToGlobal(QPoint()), dock.root.size())
            self.assertTrue(bounds.contains(popup.geometry()), (bounds, popup.geometry()))
            self.assertLess(popup.geometry().bottom(), anchor.y())
            for child in (dock.project_label, dock.context_title, dock.chips_widget, dock.choose_context_button):
                self.assertTrue(popup.rect().contains(QRect(child.mapTo(popup, QPoint()), child.size())), child.objectName())
            self.assertTrue(popup.grab().save(str(artifacts / f"context-dropdown-{width}.png")))
            dock.model_button.click()
            self.app.processEvents()
            self.assertFalse(popup.isVisible())
            self.assertFalse(dock.model_popover.models.horizontalScrollBar().isVisible())
            self.assertTrue(dock.model_popover.grab().save(str(artifacts / f"model-dropdown-{width}.png")))
            dock.model_popover.dismiss()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
