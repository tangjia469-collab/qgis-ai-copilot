"""Area screenshot button: native capture boundary, draft safety and cleanup."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qgis.PyQt.QtCore import QByteArray, QCoreApplication, QEvent, QObject, QPoint, QRect, pyqtSignal
from qgis.PyQt.QtGui import QColor, QImage
from qgis.core import QgsApplication

from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.protocol import ModelRecord, RouterProfile
from tests.qgis_runtime import configure_prefix
from tests.qgis_smoke import FakeIface


class CaptureProcess(QObject):
    """Only replace the external interactive process; use real attachment handling."""

    finished = pyqtSignal(int, int)
    errorOccurred = pyqtSignal(int)
    NotRunning, Running, NormalExit, CrashExit, FailedToStart = 0, 2, 0, 1, 0
    instances = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instances.append(self)
        self.running = False
        self.stderr = b""

    def start(self, program, arguments):
        self.program = program
        self.arguments = arguments
        self.output = Path(arguments[-1])
        self.running = True

    def state(self):
        return self.Running if self.running else self.NotRunning

    def readAllStandardError(self):
        return QByteArray(self.stderr)

    def kill(self):
        self.finish(9, self.CrashExit)

    def waitForFinished(self, _milliseconds):
        return not self.running

    def finish(self, code=0, status=NormalExit):
        self.running = False
        self.finished.emit(code, status)

    def selected_image(self):
        image = QImage(160, 100, QImage.Format_ARGB32)
        image.fill(QColor("#2377aa"))
        image.setPixelColor(159, 99, QColor("#cc1133"))
        assert image.save(str(self.output), "PNG")
        self.finish()


class AreaCaptureTests(unittest.TestCase):
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
        self.assertIsNotNone(
            importlib.util.find_spec("qgis_ai_copilot.screen_capture"),
            "Interactive screenshot capture has not been implemented",
        )
        self.process_patch = patch("qgis_ai_copilot.screen_capture.QProcess", CaptureProcess)
        self.platform_patch = patch("qgis_ai_copilot.screen_capture.capture_supported", return_value=True)
        self.process_patch.start()
        self.platform_patch.start()
        self.addCleanup(self.process_patch.stop)
        self.addCleanup(self.platform_patch.stop)
        CaptureProcess.instances.clear()
        self.iface = FakeIface()
        self.plugin = QgisAiCopilotPlugin(self.iface)
        self.plugin.initGui()
        self.dock = self.plugin.dock
        self.dock.client.abort_catalog()
        self.dock.profile = RouterProfile(base_url="http://127.0.0.1:9870")
        self.dock.records = [ModelRecord("fixture-model")]
        self.dock.selected_model = "fixture-model"
        self.dock.catalog_ready = True
        self.dock._new_chat()
        self.dock._refresh_model_control()
        self.dock.message_input.setPlainText("Keep this draft")
        self.dock.setFloating(True)
        self.dock.resize(420, 720)
        self.dock.show()
        self.app.processEvents()
        self.addCleanup(self.cleanup_plugin)

    def cleanup_plugin(self):
        if self.plugin.dock is not None:
            self.plugin.unload()
        self.iface.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def begin(self):
        self.assertTrue(hasattr(self.dock, "screenshot_button"), "Missing direct screenshot button")
        self.dock.screenshot_button.click()
        self.assertTrue(self.dock._area_capture.busy)
        return CaptureProcess.instances[-1]

    def test_selected_region_attaches_without_sending_or_changing_draft(self):
        process = self.begin()
        folder = process.output.parent
        self.assertEqual(process.program, "/usr/sbin/screencapture")
        self.assertIn("-i", process.arguments)
        self.assertNotIn("-c", process.arguments)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.dock.send_button.isEnabled())
        self.dock._send_or_stop()
        self.assertEqual(self.dock.conversation["messages"], [])
        process.selected_image()
        self.assertEqual(self.dock.message_input.toPlainText(), "Keep this draft")
        self.assertEqual(self.dock.conversation["messages"], [])
        self.assertEqual(len(self.dock.attachments), 1)
        item = next(iter(self.dock.attachments.values()))
        self.assertEqual(item.source_kind, "screen-area")
        self.assertNotIn(str(folder), str(item.manifest()))
        image = QImage.fromData(item.preview_bytes)
        self.assertEqual((image.width(), image.height()), (160, 100))
        self.assertEqual(image.pixelColor(159, 99), QColor("#cc1133"))
        self.assertFalse(folder.exists())
        self.assertTrue(self.dock.send_button.isEnabled())
        self.assertTrue(self.dock.screenshot_button.isEnabled())

    def test_escape_adds_nothing_and_restores_controls(self):
        process = self.begin()
        folder = process.output.parent
        process.finish(1)
        self.assertFalse(self.dock.attachments)
        self.assertEqual(self.dock.message_input.toPlainText(), "Keep this draft")
        self.assertTrue(self.dock.screenshot_button.isEnabled())
        self.assertTrue(self.dock.send_button.isEnabled())
        self.assertFalse(folder.exists())

    def test_double_click_does_not_start_second_selector(self):
        process = self.begin()
        self.dock._start_area_capture()
        self.assertEqual(len(CaptureProcess.instances), 1)
        process.finish(1)

    def test_switching_chat_discards_late_capture(self):
        process = self.begin()
        folder = process.output.parent
        self.dock._new_chat()
        self.assertFalse(process.running)
        process.finished.emit(0, 0)
        self.assertFalse(self.dock.attachments)
        self.assertFalse(self.dock._area_capture.busy)
        self.assertFalse(folder.exists())

    def test_unload_cancels_selector_and_cleans_temporary_file(self):
        process = self.begin()
        folder = process.output.parent
        self.plugin.unload()
        process.finished.emit(0, 0)
        self.assertFalse(process.running)
        self.assertFalse(folder.exists())

    def test_bad_output_is_not_attached(self):
        process = self.begin()
        process.output.write_bytes(b"not a screenshot")
        process.finish()
        self.assertFalse(self.dock.attachments)
        self.assertTrue(self.dock.screenshot_button.isEnabled())
        self.assertFalse(process.output.parent.exists())

    def test_process_launch_error_cleans_up(self):
        process = self.begin()
        process.running = False
        process.errorOccurred.emit(process.FailedToStart)
        self.assertFalse(self.dock._area_capture.busy)
        self.assertFalse(process.output.parent.exists())
        self.assertTrue(self.dock.screenshot_button.isEnabled())

    def test_success_exit_without_an_image_reports_failure(self):
        failures = []
        self.dock._area_capture.failed.connect(failures.append)
        process = self.begin()
        process.finish(0)
        self.assertEqual(len(failures), 1)
        self.assertFalse(self.dock.attachments)

    def test_cancel_never_waits_for_the_interactive_process(self):
        process = self.begin()
        with patch.object(process, "waitForFinished", side_effect=AssertionError("GUI wait")):
            self.dock._area_capture.cancel()
        self.assertFalse(self.dock._area_capture.busy)
        self.assertFalse(self.dock.attachments)

    def test_timeout_discards_result_and_preserves_draft(self):
        process = self.begin()
        self.dock._area_capture._timer.timeout.emit()
        self.assertFalse(process.running)
        self.assertFalse(self.dock.attachments)
        self.assertEqual(self.dock.message_input.toPlainText(), "Keep this draft")
        self.assertFalse(process.output.parent.exists())

    def test_unsupported_platform_does_not_launch_capture(self):
        with patch("qgis_ai_copilot.screen_capture.capture_supported", return_value=False):
            self.dock._refresh_send_enabled()
            self.assertFalse(self.dock.screenshot_button.isEnabled())
            self.dock._start_area_capture()
        self.assertEqual(CaptureProcess.instances, [])

    def test_button_fits_narrow_composer_next_to_attachment(self):
        for width in (360, 420, 460):
            self.dock.resize(width, 720)
            self.app.processEvents()
            self.assertLessEqual(self.dock.width() - width, 24)
            composer = self.dock.attach_button.parentWidget()
            controls = (
                self.dock.attach_button, self.dock.screenshot_button,
                self.dock.add_context_button, self.dock.model_button, self.dock.send_button,
            )
            previous = None
            for widget in controls:
                rect = QRect(widget.mapTo(composer, QPoint()), widget.size())
                self.assertTrue(composer.rect().contains(rect))
                if previous is not None:
                    self.assertLessEqual(previous.right(), rect.left())
                previous = rect
            self.assertLessEqual(self.dock.screenshot_button.width(), 32)
            self.assertTrue(self.dock.screenshot_button.accessibleName())
            self.assertFalse(self.dock.screenshot_button.icon().isNull())


if __name__ == "__main__":
    unittest.main()
