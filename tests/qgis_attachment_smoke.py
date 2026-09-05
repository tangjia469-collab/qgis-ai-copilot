"""Native attachment intake, privacy, PDF rendering, and local-router round trip."""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from qgis.PyQt.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QMimeData,
    QTimer,
    QUrl,
)
from qgis.PyQt.QtGui import QColor, QImage, QPainter, QPdfWriter, QFont, QPageSize
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QDialog, QSpinBox
from qgis.core import QgsApplication

from qgis_ai_copilot.attachments import AttachmentError, prepare_file
from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.protocol import ModelRecord, RouterProfile, ProtocolError
from tests.mock_router import FixtureHandler, start_fixture
from tests.qgis_network_smoke import wait_for
from tests.qgis_smoke import FakeIface
from tests.qgis_runtime import configure_prefix


def wait_preparation(dock):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(
        lambda: loop.quit() if dock._attachment_task is None else None
    )
    timer.start()
    QTimer.singleShot(15000, loop.quit)
    loop.exec_()
    timer.stop()
    assert dock._attachment_task is None, "Attachment task did not finish"


def make_fixture_pdf(path):
    writer = QPdfWriter(str(path))
    writer.setResolution(72)
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    painter.setFont(QFont("Arial", 26))
    for index, color in enumerate(["red", "green", "blue"]):
        if index:
            assert writer.newPage()
        painter.fillRect(40, 40, 260, 80, QColor(color))
        painter.setPen(QColor("black"))
        painter.drawText(40, 180, f"PDF fixture page {index + 1}")
    painter.end()


def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = directory
        configure_prefix()
        app = QgsApplication([arg.encode() for arg in sys.argv], True)
        app.initQgis()
        iface = FakeIface()
        plugin = QgisAiCopilotPlugin(iface)
        plugin.initGui()
        dock = plugin.dock
        assert dock is not None
        iface.window.resize(1100, 760)
        iface.window.show()
        app.processEvents()

        image = QImage(500, 260, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        image.setText("private_source", "/Users/private/geodata.png")
        painter = QPainter(image)
        painter.fillRect(20, 20, 120, 80, QColor("red"))
        painter.setPen(QColor("black"))
        painter.setFont(QFont("Arial", 24))
        painter.drawText(20, 160, "Layer: Roads")
        painter.drawText(20, 210, "Distance: 250 metres")
        painter.end()
        image_path = Path(directory) / "a-long-screenshot-name-for-a-narrow-sidebar.png"
        assert image.save(str(image_path))
        attachment = prepare_file(image_path)
        clean = QImage.fromData(attachment.preview_bytes)
        assert clean.textKeys() == []
        assert clean.pixelColor(40, 40) == QColor("red")
        assert attachment.mime_type == "image/png"
        bad_path = Path(directory) / "bad.png"
        bad_path.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-image")
        try:
            prepare_file(bad_path)
            raise AssertionError("Corrupt image accepted")
        except AttachmentError:
            pass

        pdf_path = Path(directory) / "pages.pdf"
        make_fixture_pdf(pdf_path)
        pdf = prepare_file(pdf_path, pdf_pages="3,1")
        assert pdf.page_count == 3 and pdf.pages == [1, 3]
        assert pdf.image_count == 2
        assert len(pdf.parts) == 4
        assert "page 3 of 3" in pdf.parts[2]["text"]
        assert not list(
            Path(tempfile.gettempdir()).glob("qgis-ai-copilot-pdf-*/input.pdf")
        )
        with patch(
            "qgis_ai_copilot.attachments._pdf_tool",
            side_effect=AttachmentError("PDF helper unavailable"),
        ):
            try:
                prepare_file(pdf_path)
                raise AssertionError("Missing PDF dependency hidden")
            except AttachmentError:
                pass

        with patch(
            "qgis_ai_copilot.dock.QFileDialog.getOpenFileNames", return_value=([], "")
        ):
            dock._open_attachment_dialog()
        assert not dock.attachments
        with patch(
            "qgis_ai_copilot.dock.QFileDialog.getOpenFileNames",
            return_value=([str(image_path)], ""),
        ):
            dock._open_attachment_dialog()
        assert dock._attachment_task is not None
        assert not dock.send_button.isEnabled()
        wait_preparation(dock)
        assert len(dock.attachments) == 1
        dock._clear_attachment_payloads()

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(image_path))])
        dock.message_input.insertFromMimeData(mime)
        wait_preparation(dock)
        assert not dock.message_input.toPlainText()
        assert len(dock.attachments) == 1
        dock._remove_attachment(next(iter(dock.attachments)))
        mime = QMimeData()
        mime.setImageData(image)
        dock.message_input.insertFromMimeData(mime)
        assert len(dock.attachments) == 1
        QApplication.clipboard().setImage(image)
        dock._paste_clipboard_image()
        assert len(dock.attachments) == 1, "Duplicate clipboard image was added"
        dock._clear_attachment_payloads()
        dock._capture_qgis_window_now()
        assert next(iter(dock.attachments.values())).source_kind == "qgis-window"
        dock._clear_attachment_payloads()

        dock._add_attachment(attachment)
        dock._add_attachment(pdf)
        app.processEvents()
        assert dock.attachment_scroll.isVisible()
        assert dock.attachments_layout.count() == 2
        preview_pages = []

        def inspect_preview():
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, QDialog)
            page = dialog.findChild(QSpinBox)
            assert page is not None and page.maximum() == 2
            page.setValue(2)
            preview_pages.append(page.value())
            dialog.reject()

        QTimer.singleShot(20, inspect_preview)
        dock._preview_attachment(pdf.attachment_id)
        assert preview_pages == [2]

        server = start_fixture()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        profile = RouterProfile(
            name="Local attachment fixture",
            base_url=f"http://127.0.0.1:{server.server_port}",
            streaming=False,
            timeout_seconds=10,
        )
        dock.profile = profile
        dock.settings.save_profile(profile)
        dock.settings.trust_context(profile)
        dock.selected_model = "fixture-model"
        dock.records = [ModelRecord("fixture-model", supports_images=True)]
        dock.catalog_ready = True
        dock._refresh_model_control()
        dock._schedule_screen_capture()
        assert not dock.send_button.isEnabled()
        dock.message_input.setPlainText("Wait for capture")
        dock._send_or_stop()
        assert not dock.conversation["messages"]
        dock._capture_timer.stop()
        dock.attachment_status.clear()
        dock._refresh_send_enabled()

        with patch(
            "qgis_ai_copilot.dock.QMessageBox.question", return_value=QMessageBox.Cancel
        ) as question:
            dock.message_input.setPlainText("Describe the red block and the PDF pages.")
            dock._send_or_stop()
            assert not dock.conversation["messages"] and len(dock.attachments) == 2
            assert dock.message_input.toPlainText()
            question.assert_called_once()
        with patch(
            "qgis_ai_copilot.dock.QMessageBox.question", return_value=QMessageBox.Yes
        ):
            wait_for(dock.client.chatCompleted, dock._send_or_stop)
        assert dock._active_message is None and not dock.attachments
        sent = FixtureHandler.last_payload
        assert (
            len(
                [p for p in sent["messages"][-1]["content"] if p["type"] == "image_url"]
            )
            == 3
        )
        assert str(image_path) not in json.dumps(sent)
        assert "/Users/private" not in json.dumps(sent)
        stored = json.dumps(
            dock.store.load_conversation(dock.project_id, dock.conversation["id"])
        )
        assert (
            "data:image" not in stored
            and "base64" not in stored
            and str(image_path) not in stored
        )
        assert '"pages": [1, 3]' in stored

        with patch(
            "qgis_ai_copilot.dock.QMessageBox.question", return_value=QMessageBox.Cancel
        ) as question:
            dock.message_input.setPlainText("Which PDF pages did I share?")
            before = len(dock.conversation["messages"])
            dock._send_or_stop()
            assert len(dock.conversation["messages"]) == before
            assert "pages.pdf" in question.call_args.args[2]
        with patch(
            "qgis_ai_copilot.dock.QMessageBox.question", return_value=QMessageBox.Yes
        ):
            wait_for(dock.client.chatCompleted, dock._send_or_stop)
        assert any(
            isinstance(m["content"], list)
            for m in FixtureHandler.last_payload["messages"]
        )

        original = dock.conversation["messages"][1]
        saved_request = dock.store.load_conversation(dock.project_id, dock.conversation["id"])["messages"][1]["request"]
        assert saved_request["router_id"] == dock._router_identity()
        dock._validate_request_router(saved_request)
        with patch(
            "qgis_ai_copilot.dock.QMessageBox.question", return_value=QMessageBox.Yes
        ):
            wait_for(
                dock.client.chatCompleted, lambda: dock._retry_message(original, False)
            )
        assert FixtureHandler.last_payload == sent, (
            "Retry changed the original multimodal payload"
        )

        dock.records = [ModelRecord("fixture-model", supports_images=False)]
        with patch("qgis_ai_copilot.dock.QMessageBox.warning") as warning:
            dock.message_input.setPlainText("Inspect this again")
            dock._send_or_stop()
            warning.assert_called_once()
            assert dock.message_input.toPlainText() == "Inspect this again"
        dock.records = [ModelRecord("fixture-model", supports_images=True)]

        dock.setFloating(True)
        dock._add_attachment(attachment)
        widths = []
        for width in [360, 420, 460]:
            dock.resize(width, 740)
            app.processEvents()
            assert dock.width() == max(width, dock.minimumSizeHint().width()), (
                width,
                dock.width(),
                dock.minimumSizeHint().width(),
            )
            assert dock.width() - width <= 24, "Unexpected content growth beyond floating-window chrome"
            for child in [dock.send_button, dock.attach_button, dock.model_button]:
                pos = child.mapTo(dock.root, child.rect().topLeft())
                assert pos.x() >= 0 and pos.x() + child.width() <= dock.root.width()
            assert (
                dock.attachments_layout.itemAt(0).widget().width()
                <= dock.attachments_widget.width()
            )
            target = (
                Path(__file__).resolve().parents[1]
                / "artifacts"
                / f"attachments-native-{width}.png"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            assert dock.grab().save(str(target))
            widths.append(width)

        dock._profile_saved(RouterProfile(name="Changed", base_url="", authcfg=""))
        assert not dock.attachments and not dock._attachment_payloads
        try:
            dock._validate_request_router(saved_request)
            raise AssertionError("Persisted retry lost router binding")
        except ProtocolError:
            pass
        dock.conversation["messages"].append({"id": "new-router", "role": "user", "content": "Hello", "router_id": dock._router_identity()})
        new_payload = dock._canonical_messages({"context": {}, "user_message_id": "new-router"})
        assert "pages.pdf" not in json.dumps(new_payload)
        assert image_path.name not in json.dumps(new_payload)
        try:
            dock._canonical_messages(original["request"])
            raise AssertionError("Retry silently lost its image")
        except ProtocolError:
            pass
        with patch("qgis_ai_copilot.dock.QMessageBox.warning") as warning:
            dock._retry_message(original, False)
            warning.assert_called_once()
        dock._new_chat()
        assert not dock._attachment_payloads
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        iface.window.close()
        iface.canvas.setLayers([])
        app.processEvents()
        app.exitQgis()
        print(
            json.dumps(
                {
                    "image_decode": True,
                    "pdf_selected_pages": [1, 3],
                    "paste_files_and_images": True,
                    "background_preparation": True,
                    "local_router_image_roundtrip": True,
                    "retry_preserved": True,
                    "manifest_only_storage": True,
                    "router_change_clears_pixels": True,
                    "widths": widths,
                }
            )
        )


if __name__ == "__main__":
    main()
