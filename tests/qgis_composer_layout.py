"""Native regression checks for composer-anchored context/model controls."""

import os
import tempfile
import unittest
from pathlib import Path

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt, QTimer
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtGui import QFont, QIcon, QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QDialogButtonBox
from qgis.core import QgsApplication

from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.protocol import ModelRecord, RouterProfile
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
        dock.records = [
            ModelRecord("gemini-3.8-flash-high"),
            ModelRecord("second-model", explicit_thinking=("High",)),
        ]
        dock.selected_model = dock.records[0].id
        dock._refresh_model_control()
        for width in (360, 420, 460):
            dock.resize(width, 740)
            self.app.processEvents()
            QTest.qWait(30)
            self.assertEqual(dock.width(), max(width, dock.minimumSizeHint().width()))
            self.assertLessEqual(
                dock.width() - width, 24, "Unexpected content growth beyond floating-window chrome"
            )
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
        self.assertTrue(
            hasattr(dock, "context_popover"), "Context strip needs an Add context dropdown"
        )
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
        dock.records = [
            ModelRecord("first-model"),
            ModelRecord("second-model", explicit_thinking=("High",)),
        ]
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
            for child in (
                dock.project_label,
                dock.context_title,
                dock.chips_widget,
                dock.choose_context_button,
            ):
                self.assertTrue(
                    popup.rect().contains(QRect(child.mapTo(popup, QPoint()), child.size())),
                    child.objectName(),
                )
            self.assertTrue(popup.grab().save(str(artifacts / f"context-dropdown-{width}.png")))
            dock.model_button.click()
            self.app.processEvents()
            self.assertFalse(popup.isVisible())
            self.assertFalse(dock.model_popover.models.horizontalScrollBar().isVisible())
            self.assertTrue(
                dock.model_popover.grab().save(str(artifacts / f"model-dropdown-{width}.png"))
            )
            dock.model_popover.dismiss()
            self.app.processEvents()

    def test_attachment_icon_is_monochrome_not_the_qgis_folder(self):
        picture = self.dock.attach_button.icon().pixmap(24, 24).toImage()
        colors = [
            picture.pixelColor(x, y)
            for x in range(picture.width())
            for y in range(picture.height())
            if picture.pixelColor(x, y).alpha() > 128
        ]
        self.assertTrue(colors)
        self.assertFalse(
            any(c.saturationF() > 0.4 for c in colors),
            "The paperclip must not fall back to a colored folder",
        )
        self.assertEqual(
            [a.text() for a in self.dock.attachment_menu.actions()],
            [
                "Image or PDF...",
                "Paste image",
                "Capture map canvas",
                "Capture QGIS window",
                "Capture screen in 3 seconds",
            ],
        )

    def test_send_arrow_has_white_strokes_instead_of_native_triangle(self):
        d = self.dock
        d.profile = RouterProfile(base_url="http://127.0.0.1:9870")
        d.records = [ModelRecord("gpt-6-astra")]
        d.selected_model = "gpt-6-astra"
        d.catalog_ready = True
        d._refresh_model_control()
        picture = d.send_button.icon().pixmap(24, 24, QIcon.Normal).toImage()
        pixels = [
            picture.pixelColor(x, y)
            for x in range(picture.width())
            for y in range(picture.height())
        ]
        self.assertGreater(
            sum(c.alpha() > 128 and min(c.red(), c.green(), c.blue()) > 240 for c in pixels), 25
        )
        old = d.send_button.icon().cacheKey()
        d._set_generating(True)
        self.assertNotEqual(d.send_button.icon().cacheKey(), old)
        self.assertEqual(d.send_button.accessibleName(), "Stop generation")
        d._set_generating(False)
        self.assertEqual(d.send_button.accessibleName(), "Send message")

    def test_model_selector_is_normal_weight_and_flat(self):
        d = self.dock
        d.records = [ModelRecord("gpt-6-astra")]
        d.selected_model = "gpt-6-astra"
        d.selected_thinking = "Max"
        d._refresh_model_control()
        self.app.processEvents()
        self.assertLessEqual(d.model_button.font().weight(), QFont.Normal)
        picture = d.model_button.grab().toImage()
        color = picture.pixelColor(4, picture.height() - 4)
        base = d.palette().color(QPalette.Base)
        self.assertTrue(
            color.alpha() == 0
            or sum(abs(a - b) for a, b in zip(color.getRgb()[:3], base.getRgb()[:3])) < 12
        )
        self.assertNotIn("▾", d.model_button.text())
        self.assertFalse(d.model_button.icon().isNull())

    def test_composer_icons_keep_dark_and_disabled_states_and_fit(self):
        d = self.dock
        d.records = [ModelRecord("gpt-6-astra")]
        d.selected_model = "gpt-6-astra"
        d.selected_thinking = "Max"
        d._refresh_model_control()
        artifacts = Path(__file__).resolve().parents[1] / "artifacts"
        artifacts.mkdir(exist_ok=True)
        for dark in (False, True):
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor("#24282e" if dark else "#ffffff"))
            palette.setColor(QPalette.Base, QColor("#20242a" if dark else "#ffffff"))
            palette.setColor(QPalette.WindowText, QColor("#e5eaf1" if dark else "#364252"))
            d.setPalette(palette)
            from qgis_ai_copilot.styles import build_stylesheet

            d.setStyleSheet(build_stylesheet(palette))
            picture = d.attach_button.icon().pixmap(24, 24).toImage()
            ink = [
                picture.pixelColor(x, y).lightness()
                for x in range(picture.width())
                for y in range(picture.height())
                if picture.pixelColor(x, y).alpha() > 128
            ]
            if dark:
                self.assertGreater(
                    min(ink), 150, "Outline icons must remain legible on dark surfaces"
                )
            for width in (360, 420, 460):
                d.resize(width, 740)
                QTest.qWait(30)
                self.assertLessEqual(d.width() - width, 24)
                composer = d.send_button.parentWidget()
                self.assertTrue(
                    composer.rect().contains(
                        QRect(d.model_button.mapTo(composer, QPoint()), d.model_button.size())
                    )
                )
                for enabled in (False, True):
                    d.send_button.setEnabled(enabled)
                    QTest.qWait(20)
                    self.assertTrue(
                        composer.grab().save(
                            str(
                                artifacts
                                / f"composer-refined-{width}-{'dark' if dark else 'light'}-{'ready' if enabled else 'disabled'}.png"
                            )
                        )
                    )


if __name__ == "__main__":
    unittest.main()
