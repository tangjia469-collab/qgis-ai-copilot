# SPDX-License-Identifier: GPL-3.0-or-later
"""Asynchronous native area capture; only a selected, validated image is returned."""

from pathlib import Path
import sys
import tempfile

from qgis.PyQt.QtCore import QCoreApplication, QObject, QProcess, QSize, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QImageReader

from .attachments import AttachmentError, MAX_IMAGE_DIMENSION, MAX_IMAGE_PIXELS, prepare_image


CAPTURE_PROGRAM = "/usr/sbin/screencapture"


def capture_supported():
    return sys.platform == "darwin" and Path(CAPTURE_PROGRAM).is_file()


class AreaCapture(QObject):
    captured = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    busyChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)

    @property
    def busy(self):
        return self._state is not None

    def start(self):
        if self.busy or not capture_supported():
            return
        try:
            temporary = tempfile.TemporaryDirectory(prefix="qgis-copilot-capture-")
        except OSError:
            self.failed.emit("Could not prepare a private screenshot file. Check available disk space.")
            return
        process = QProcess(self)
        state = {
            "process": process,
            "temporary": temporary,
            "output": Path(temporary.name) / "screen-area.png",
            "cancelled": False,
            "failure": "",
        }
        self._state = state
        process.finished.connect(lambda code, status: self._finish(state, code, status))
        process.errorOccurred.connect(lambda error: self._process_error(state, error))
        self.busyChanged.emit(True)
        self._timer.start(120_000)
        # A fixed program and argument list: no shell, clipboard or Desktop output.
        process.start(CAPTURE_PROGRAM, ["-i", "-s", "-x", "-t", "png", str(state["output"])])

    def _process_error(self, state, error):
        if state is not self._state or state["cancelled"]:
            return
        if error == QProcess.FailedToStart:
            state["failure"] = "Screenshot selection could not start. Try again or paste a screenshot."
            self._finish(state, -1, QProcess.CrashExit)

    def _finish(self, state, code, status):
        if state is not self._state:
            return
        self._timer.stop()
        self._state = None
        attachment = None
        failure = state["failure"]
        try:
            if not state["cancelled"] and not failure:
                output = state["output"]
                if code == 0 and status == QProcess.NormalExit and output.is_file() and output.stat().st_size:
                    reader = QImageReader(str(output))
                    size = reader.size()
                    if not size.isValid() or size.width() * size.height() > MAX_IMAGE_PIXELS:
                        raise AttachmentError("The selected screenshot is invalid or exceeds 32 megapixels.")
                    if max(size.width(), size.height()) > MAX_IMAGE_DIMENSION:
                        ratio = MAX_IMAGE_DIMENSION / max(size.width(), size.height())
                        reader.setScaledSize(QSize(round(size.width() * ratio), round(size.height() * ratio)))
                    attachment = prepare_image(reader.read(), "screen-area.png", "screen-area")
                elif code == 0 or status != QProcess.NormalExit or bytes(state["process"].readAllStandardError()).strip():
                    failure = (
                        "Screenshot selection did not complete. Allow QGIS in macOS Privacy & Security "
                        "→ Screen Recording, then retry. Escape cancels without attaching."
                    )
        except (AttachmentError, OSError):
            failure = "The screenshot could not be prepared. Select a smaller area and try again."
        finally:
            state["temporary"].cleanup()
            process = state["process"]
            if process.state() == QProcess.NotRunning:
                process.deleteLater()
            else:
                # Let the already-killed process exit without blocking QGIS or
                # being destroyed with its dock during a plugin reload.
                process.setParent(QCoreApplication.instance())
                process.finished.connect(process.deleteLater)
            self.busyChanged.emit(False)
        if failure:
            self.failed.emit(failure)
        elif attachment is not None:
            self.captured.emit(attachment)
        else:
            self.cancelled.emit()

    def _timeout(self):
        if self._state is not None:
            self._state["failure"] = "Screenshot selection timed out. Click the screenshot button to try again."
            self.cancel()

    def cancel(self):
        state = self._state
        if state is None:
            return
        state["cancelled"] = True
        self._timer.stop()
        process = state["process"]
        if process.state() != QProcess.NotRunning:
            process.kill()
        self._finish(state, -1, QProcess.CrashExit)
