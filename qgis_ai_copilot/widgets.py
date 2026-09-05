# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Reusable native Qt widgets for the Copilot dock."""

from __future__ import annotations

import json
from typing import Any

from qgis.PyQt.QtCore import QByteArray, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QTextDocument, QFontMetrics, QIcon, QPainter, QPen, QPixmap, QPalette
from qgis.PyQt.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QStyle,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .protocol import ProtocolError, normalized_external_link
from .storage import sanitized_activity


# FlowLayout follows Qt's BSD-3-Clause example; see THIRD_PARTY_NOTICES.md.
# Copyright (C) 2013 Riverbank Computing Limited; 2022 The Qt Company Ltd.
class FlowLayout(QLayout):
    """Small wrapping layout based on Qt's canonical Flow Layout example."""

    def __init__(self, parent: QWidget | None = None, margin: int = 0, spacing: int = 5):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_height = 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            space_x = self.spacing()
            space_y = self.spacing()
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y()


class ContextChip(QWidget):
    previewRequested = pyqtSignal(str)
    removeRequested = pyqtSignal(str)

    def __init__(self, key: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QToolButton(self)
        body.setText(label)
        body.setProperty("kind", "chip")
        body.setToolTip(f"Preview {label} context")
        body.clicked.connect(lambda: self.previewRequested.emit(self.key))
        layout.addWidget(body)

        close = QToolButton(self)
        close.setText("x")
        close.setProperty("kind", "chip-close")
        close.setToolTip(f"Remove {label} context")
        close.setAccessibleName(f"Remove {label} context")
        close.clicked.connect(lambda: self.removeRequested.emit(self.key))
        layout.addWidget(close)


class AttachmentChip(QWidget):
    previewRequested = pyqtSignal(str)
    removeRequested = pyqtSignal(str)

    def __init__(self, attachment_id: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.attachment_id = attachment_id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QToolButton(self)
        self.body = body
        body.setFixedSize(162, 40)
        body.setText(QFontMetrics(body.font()).elidedText(label, Qt.ElideMiddle, 104))
        body.setAccessibleName(f"Preview {label}")
        body.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        body.setProperty("kind", "attachment")
        body.setToolTip(f"Preview {label}")
        body.clicked.connect(lambda: self.previewRequested.emit(self.attachment_id))
        layout.addWidget(body)

        close = QToolButton(self)
        close.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        close.setProperty("kind", "chip-close")
        close.setToolTip(f"Remove {label}")
        close.setAccessibleName(f"Remove {label}")
        close.clicked.connect(lambda: self.removeRequested.emit(self.attachment_id))
        layout.addWidget(close)


class SafeTextBrowser(QTextBrowser):
    """Renders Markdown without loading model-supplied remote images."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("kind", "message")
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._confirm_external_link)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(self._resize_to_document)

    def loadResource(self, resource_type: int, name):  # noqa: N802
        if resource_type == QTextDocument.ImageResource:
            return QByteArray()
        return super().loadResource(resource_type, name)

    def _confirm_external_link(self, url: QUrl) -> None:
        try:
            normalized, host = normalized_external_link(url.toString())
        except ProtocolError as exc:
            QMessageBox.warning(self, "Link blocked", str(exc))
            return
        answer = QMessageBox.question(
            self,
            "Open external link",
            f"Open this link in your browser?\n\nHost: {host}\n{normalized}",
            QMessageBox.Open | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Open:
            QDesktopServices.openUrl(QUrl(normalized))

    def set_content(self, content: str, markdown: bool = True) -> None:
        if markdown and hasattr(self, "setMarkdown"):
            self.setMarkdown(content)
        else:
            self.setPlainText(content)
        QTimer.singleShot(0, self._resize_to_document)

    def _resize_to_document(self, *args) -> None:
        width = max(80, self.viewport().width())
        self.document().setTextWidth(width)
        height = int(self.document().size().height()) + 5
        self.setFixedHeight(max(24, height))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        QTimer.singleShot(0, self._resize_to_document)


class CompactQuestionBrowser(SafeTextBrowser):
    overflowChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        self.expanded = False
        self._resizing = False
        self._overflow = False
        super().__init__(parent)

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        self._resize_to_document()

    def _resize_to_document(self, *_args) -> None:
        if self._resizing:
            return
        self._resizing = True
        try:
            self.document().setTextWidth(max(80, self.viewport().width()))
            natural = max(24, int(self.document().size().height()) + 5)
            limit = min(84, self.fontMetrics().lineSpacing() * 4 + 8)
            overflow = natural > limit
            self.setFixedHeight(natural if self.expanded else min(natural, limit))
            if overflow != self._overflow:
                self._overflow = overflow
                self.overflowChanged.emit(overflow)
        finally:
            self._resizing = False


class FooterLabel(QLabel):
    """One-line metadata with its full value in tooltip and accessibility text."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        super().setText(self.fontMetrics().elidedText(text, Qt.ElideMiddle, max(30, self.width())))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.setText(self._full_text)


def message_action_icon(widget: QWidget, action: str) -> QIcon:
    """Small palette-aware outline copy (two sheets) or pencil icon."""
    pixmap = QPixmap(32, 32)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(widget.palette().color(QPalette.WindowText), 1.2))
    if action == "copy":
        painter.drawRoundedRect(QRectF(2, 2, 8, 10), 1, 1)
        painter.setBrush(widget.palette().color(QPalette.Window))
        painter.drawRoundedRect(QRectF(6, 5, 8, 9), 1, 1)
    else:
        painter.drawLine(4, 10, 11, 3)
        painter.drawLine(6, 12, 13, 5)
        painter.drawLine(11, 3, 13, 5)
        painter.drawLine(4, 10, 3, 13)
        painter.drawLine(3, 13, 6, 12)
    painter.end()
    return QIcon(pixmap)


class ActivityBrowser(QPlainTextEdit):
    """Bounded plain-text activity log that cannot recursively relayout the dock."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setMaximumHeight(230)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setProperty("kind", "activity")

    def set_content(self, content: str) -> None:
        self.setPlainText(content)

    def scroll_to_end(self) -> None:
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class MessageCard(QFrame):
    retryRequested = pyqtSignal(object, bool)
    stopRequested = pyqtSignal()
    editRequested = pyqtSignal(object)

    def __init__(
        self,
        message: dict[str, Any],
        parent: QWidget | None = None,
        available_attachment_ids: set[str] | None = None,
        editable: bool = False,
    ) -> None:
        super().__init__(parent)
        self.message = message
        role = str(message.get("role") or "assistant")
        self.setProperty("role", "user" if role == "user" else "assistant")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            8 if role == "user" else 9,
            4 if role == "user" else 7,
            8 if role == "user" else 9,
            4 if role == "user" else 7,
        )
        layout.setSpacing(3)

        self.activity_panel = QFrame(self)
        self.activity_panel.setProperty("role", "activity")
        activity_layout = QVBoxLayout(self.activity_panel)
        activity_layout.setContentsMargins(7, 4, 7, 4)
        activity_layout.setSpacing(3)
        self.activity_toggle = QToolButton(self.activity_panel)
        self.activity_toggle.setCheckable(True)
        self.activity_toggle.setChecked(message.get("status") == "streaming")
        self.activity_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.activity_toggle.setAccessibleName("Expand or collapse model activity")
        self.activity_view = ActivityBrowser(self.activity_panel)
        self.activity_toggle.toggled.connect(self.activity_view.setVisible)
        self.activity_toggle.toggled.connect(lambda checked: self.activity_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow))
        activity_layout.addWidget(self.activity_toggle, 0, Qt.AlignLeft)
        activity_layout.addWidget(self.activity_view)
        layout.addWidget(self.activity_panel)
        self._render_activity()

        self.body = CompactQuestionBrowser(self) if role == "user" else SafeTextBrowser(self)
        self.body.set_content(str(message.get("content") or ""), role == "assistant")
        self.body.setVisible(bool(message.get("content")))
        layout.addWidget(self.body)
        attachments = message.get("attachments")
        if isinstance(attachments, list) and attachments:
            names = [
                str(item.get("name") or "attachment") + (" (re-attach)" if available_attachment_ids is not None and item.get("id") not in available_attachment_ids else "")
                for item in attachments
                if isinstance(item, dict)
            ]
            if names:
                attached = QLabel("Attachments: " + ", ".join(names), self)
                attached.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                attached.setProperty("kind", "meta")
                attached.setTextFormat(Qt.PlainText)
                attached.setWordWrap(True)
                layout.addWidget(attached)

        self.status_widget = QWidget(self)
        self.status_row = QHBoxLayout(self.status_widget)
        self.status_row.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel(self._status_text(), self.status_widget)
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status_label.setProperty("kind", "meta")
        self.status_row.addWidget(self.status_label, 1)
        self.stop_button = QToolButton(self)
        self.stop_button.setText("Stop")
        self.stop_button.setAccessibleName("Stop this response")
        self.stop_button.clicked.connect(self.stopRequested)
        self.stop_button.hide()
        self.status_row.addWidget(self.stop_button)
        layout.addWidget(self.status_widget)
        self.status_widget.setVisible(role == "assistant" and message.get("status") in {"streaming", "stopped", "error"})
        self.footer = QWidget(self)
        self.footer.setObjectName("MessageFooter")
        footer_row = QHBoxLayout(self.footer)
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(3)
        self.footer_meta = FooterLabel(self._meta_text(), self.footer)
        self.footer_meta.setProperty("kind", "user-meta" if role == "user" else "meta")
        footer_row.addWidget(self.footer_meta, 1)
        self.question_toggle = QToolButton(self.footer)
        self.question_toggle.setText("Show more")
        self.question_toggle.setCheckable(True)
        self.question_toggle.setProperty("kind", "question-toggle")
        self.question_toggle.setAccessibleName("Show full question")
        self.question_toggle.hide()
        if role == "user":
            self.body.overflowChanged.connect(self.question_toggle.setVisible)
            self.question_toggle.toggled.connect(self.body.set_expanded)
            self.question_toggle.toggled.connect(lambda expanded: self.question_toggle.setText("Show less" if expanded else "Show more"))
        footer_row.addWidget(self.question_toggle)
        self.copy_button = QToolButton(self.footer)
        self.copy_button.setIcon(message_action_icon(self, "copy"))
        self.copy_button.setProperty("kind", "message-action")
        self.copy_button.setFixedSize(22, 22)
        self.copy_button.setIconSize(QSize(14, 14))
        self.copy_button.setToolTip("Copy response")
        self.copy_button.setAccessibleName("Copy response")
        self.copy_button.clicked.connect(self._copy)
        self.copy_button.setVisible(role == "assistant")
        footer_row.addWidget(self.copy_button)
        self.edit_button = QToolButton(self.footer)
        self.edit_button.setIcon(message_action_icon(self, "edit"))
        self.edit_button.setProperty("kind", "message-action")
        self.edit_button.setFixedSize(22, 22)
        self.edit_button.setIconSize(QSize(14, 14))
        self.edit_button.setToolTip("Edit this question")
        self.edit_button.setAccessibleName("Edit latest question")
        self.edit_button.clicked.connect(lambda: self.editRequested.emit(self.message))
        self.edit_button.setVisible(role == "user" and editable)
        footer_row.addWidget(self.edit_button)
        layout.addWidget(self.footer)
        self._add_retry_controls()

    def _meta_text(self) -> str:
        if self.message.get("role") == "user":
            timestamp = str(self.message.get("created_at") or "").replace("T", " ")[:16]
            return f"You  |  {timestamp}"
        detail = self.message.get("request") or {}
        model = detail.get("model") or "Unknown model"
        thinking = detail.get("thinking") or "Auto"
        timestamp = str(self.message.get("created_at") or "").replace("T", " ")[:16]
        return f"{model}  ·  Thinking: {thinking}  ·  {timestamp}"

    def set_editable(self, editable: bool) -> None:
        self.edit_button.setVisible(self.message.get("role") == "user" and editable)

    def add_activity(self, event: dict[str, Any]) -> None:
        safe = sanitized_activity([event])
        if not safe:
            return
        entries = list(self.message.get("activity") or [])
        entry = safe[0]
        for index, old in enumerate(entries):
            if old.get("id") == entry["id"]:
                if old == entry:
                    return
                entries[index] = entry
                break
        else:
            entries.append(entry)
        self.message["activity"] = sanitized_activity(entries)
        self._render_activity()

    def _render_activity(self) -> None:
        items = sanitized_activity(self.message.get("activity"))
        self.activity_panel.setVisible(bool(items))
        self.activity_toggle.setText(f"Activity · {len(items)} updates")
        self.activity_toggle.setArrowType(Qt.DownArrow if self.activity_toggle.isChecked() else Qt.RightArrow)
        headings = {"local": "QGIS / connection", "commentary": "Model update", "summary": "Reasoning summary"}
        text = "\n\n".join(f"{headings[item['kind']]}\n{item['text']}" for item in items)
        bar = self.activity_view.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 4
        self.activity_view.set_content(text)
        self.activity_view.setVisible(self.activity_toggle.isChecked())
        if follow and items:
            QTimer.singleShot(0, self.activity_view.scroll_to_end)

    def _status_text(self) -> str:
        status = str(self.message.get("status") or "complete")
        if status == "streaming":
            return "Generating..."
        if status == "stopped":
            return "Stopped - partial response preserved" if self.message.get("content") else "Stopped before an answer arrived"
        if status == "error":
            error = self.message.get("error") or {}
            return str(error.get("message") or "Request failed")
        if status == "non_streaming":
            return "Complete - non-streaming response"
        return "Complete" if self.message.get("role") == "assistant" else ""

    def _add_retry_controls(self) -> None:
        status = self.message.get("status")
        if status not in {"stopped", "error"}:
            return
        retry = QToolButton(self)
        retry.setText("Retry")
        retry.clicked.connect(lambda: self.retryRequested.emit(self.message, False))
        self.status_row.addWidget(retry)
        error = self.message.get("error") or {}
        if error.get("kind") == "thinking_unsupported":
            retry_auto = QToolButton(self)
            retry_auto.setText("Retry with Auto")
            retry_auto.clicked.connect(lambda: self.retryRequested.emit(self.message, True))
            self.status_row.addWidget(retry_auto)

    def append_delta(self, text: str) -> None:
        self.body.show()
        self.message["content"] = str(self.message.get("content") or "") + text
        self.body.set_content(self.message["content"], markdown=False)

    def update_progress(self, phase: str, elapsed_seconds: int, idle_seconds: int) -> None:
        if self.message.get("status") != "streaming":
            return
        labels = {
            "sending": "Sending request",
            "waiting": "Waiting for answer",
            "receiving": "Receiving answer",
            "stopping": "Stopping",
        }
        label = labels.get(phase, "Waiting for answer")
        milestones = {"sending": "Sending the prepared request to the router.", "receiving": "Receiving the final answer.", "stopping": "Stopping the request."}
        if phase in milestones:
            self.add_activity({"id": f"transport:{phase}", "kind": "local", "text": milestones[phase]})
        elapsed = f"{elapsed_seconds // 60:02d}:{elapsed_seconds % 60:02d}"
        activity = f" · Last activity {idle_seconds}s ago" if idle_seconds >= 5 else ""
        self.status_label.setText(f"{label} · {elapsed}{activity}")
        self.status_label.setToolTip("Elapsed time and observed router activity—not the model's private reasoning. You can Stop at any time.")
        self.stop_button.setVisible(True)
        self.stop_button.setEnabled(phase != "stopping")

    def finalize(self, content: str, status: str, error: dict[str, Any] | None = None) -> None:
        self.stop_button.hide()
        self.status_widget.setVisible(status in {"error", "stopped"})
        self.message["content"] = content
        self.message["status"] = status
        if error:
            self.message["error"] = error
            self.setProperty("role", "error")
            self.style().unpolish(self)
            self.style().polish(self)
        self.body.set_content(content, markdown=status != "streaming")
        self.body.setVisible(bool(content))
        self.status_label.setText(self._status_text())
        self.footer_meta.setText(self._meta_text())
        self._add_retry_controls()
        if status in {"complete", "non_streaming"}:
            self.activity_toggle.setChecked(False)

    def _copy(self) -> None:
        QApplication.clipboard().setText(str(self.message.get("content") or ""))
        self.copy_button.setToolTip("Copied")
        self.footer_meta.setText("Copied")
        QTimer.singleShot(1200, self._restore_copy_feedback)

    def _restore_copy_feedback(self) -> None:
        self.footer_meta.setText(self._meta_text())
        self.copy_button.setToolTip("Copy response")


class ToolResultCard(QFrame):
    def __init__(self, result: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "tool")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        row = QHBoxLayout()
        title = QLabel(str(result.get("tool") or "Local check"), self)
        title.setProperty("kind", "project")
        row.addWidget(title, 1)
        risk = QLabel("R0 read-only", self)
        risk.setProperty("kind", "meta")
        row.addWidget(risk)
        layout.addLayout(row)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlainText(json.dumps(result.get("result"), ensure_ascii=False, indent=2))
        self.details.setFixedHeight(130)
        self.details.hide()
        toggle = QToolButton(self)
        toggle.setText("Show safe summary")
        toggle.setCheckable(True)
        toggle.toggled.connect(self.details.setVisible)
        toggle.toggled.connect(
            lambda checked: toggle.setText("Hide safe summary" if checked else "Show safe summary")
        )
        layout.addWidget(toggle, 0, Qt.AlignLeft)
        layout.addWidget(self.details)


class ComposerTextEdit(QTextEdit):
    sendRequested = pyqtSignal()
    filesDropped = pyqtSignal(object)
    imagePasted = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAcceptRichText(False)

    def canInsertFromMimeData(self, source) -> bool:  # noqa: N802
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        if mime.hasImage():
            self.imagePasted.emit(mime.imageData())
            event.acceptProposedAction()
            return
        if mime.hasUrls():
            event.ignore()
            return
        super().dropEvent(event)

    def insertFromMimeData(self, source) -> None:  # noqa: N802
        paths = [url.toLocalFile() for url in source.urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            return
        if source.hasImage():
            self.imagePasted.emit(source.imageData())
            return
        super().insertFromMimeData(source)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in {Qt.Key_Return, Qt.Key_Enter} and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.sendRequested.emit()
            return
        super().keyPressEvent(event)
