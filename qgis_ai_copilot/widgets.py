# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Reusable native Qt widgets for the Copilot dock."""

from __future__ import annotations

import json
import re
from typing import Any

from qgis.PyQt.QtCore import QByteArray, QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QTextCursor, QTextDocument, QTextDocumentFragment, QFontDatabase, QFontMetrics, QIcon, QPainter, QPen, QPixmap, QPalette
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
from .pricing import cost_display
from .typography import monospace_family, reply_sections, style_document, ui_font
from .code_rendering import code_segments, protect_fenced_code, selected_text


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


class ResponseSelectionMenu:
    """Extend native Copy with an explicit quoted follow-up; never send here."""

    def _selection_context_menu(self):
        menu = self.createStandardContextMenu()
        menu.setParent(self)
        selection = self.textCursor().selectedText().replace("\u2029", "\n").replace("\u2028", "\n")
        card = self.parentWidget()
        while card is not None and not isinstance(card, MessageCard):
            card = card.parentWidget()
        if selection.strip() and card is not None and card.message.get("role") == "assistant":
            menu.addSeparator()
            action = menu.addAction("Ask about selection")
            action.triggered.connect(lambda: card.quoteRequested.emit(card.message, selection))
        return menu

    def contextMenuEvent(self, event):  # noqa: N802
        menu = self._selection_context_menu()
        menu.exec_(event.globalPos())
        menu.deleteLater()


class SafeTextBrowser(ResponseSelectionMenu, QTextBrowser):
    """Renders Markdown without loading model-supplied remote images."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._formatting = False
        self.setFont(ui_font())
        self.document().setDefaultFont(ui_font())
        self.setProperty("kind", "message")
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.setTextInteractionFlags(Qt.TextBrowserInteraction | Qt.TextSelectableByKeyboard)
        self.setFocusPolicy(Qt.StrongFocus)
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
        cursor = self.textCursor()
        selection = (cursor.anchor(), cursor.position()) if not markdown and cursor.hasSelection() and content.startswith(self.toPlainText()) else None
        self._formatting = True
        if markdown and hasattr(self, "setMarkdown"):
            self.setMarkdown(content)
        else:
            self.setPlainText(content)
        style_document(self.document())
        if selection is not None:
            cursor = QTextCursor(self.document())
            cursor.setPosition(selection[0])
            cursor.setPosition(selection[1], QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
        self._formatting = False
        QTimer.singleShot(0, self._resize_to_document)

    def set_fragment(self, document, start, end) -> None:
        if start < end < document.characterCount() - 1 and document.characterAt(end - 1) == "\u2029":
            end -= 1
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        self._formatting = True
        self.setHtml(QTextDocumentFragment(cursor).toHtml())
        style_document(self.document())
        self._formatting = False
        QTimer.singleShot(0, self._resize_to_document)

    def _resize_to_document(self, *args) -> None:
        if self._formatting:
            return
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


class CodeTextEdit(ResponseSelectionMenu, QPlainTextEdit):
    pass


class CodeBlock(QFrame):
    """Read-only expression/script with its own full, plain-text Copy action."""
    def __init__(self, language, code, parent=None):
        super().__init__(parent)
        self.code = code
        self.setObjectName("ExpressionCodeBox")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(4)
        header = QHBoxLayout()
        labels = {"qgis": "QGIS expression", "expression": "QGIS expression", "sql": "SQL", "python": "Python", "py": "Python", "json": "JSON", "text": "Text"}
        self.label = QLabel(labels.get(str(language).lower(), "Code"), self)
        self.label.setProperty("kind", "meta")
        self.label.setTextFormat(Qt.PlainText)
        header.addWidget(self.label, 1)
        self.feedback = QLabel("", self)
        self.feedback.setProperty("kind", "meta")
        header.addWidget(self.feedback)
        self.copy_button = QToolButton(self)
        self.copy_button.setProperty("kind", "message-action")
        self.copy_button.setIcon(message_action_icon(self, "copy"))
        self.copy_button.setIconSize(QSize(14, 14))
        self.copy_button.setFixedSize(22, 22)
        self.copy_button.setAccessibleName("Copy code only")
        self.copy_button.setToolTip("Copy code only")
        self.copy_button.clicked.connect(self._copy_code)
        header.addWidget(self.copy_button)
        layout.addLayout(header)
        self.editor = CodeTextEdit(self)
        self.editor.setReadOnly(True)
        self.editor.setProperty("kind", "code")
        self.editor.setFrameShape(QFrame.NoFrame)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setFamily(monospace_family())
        font.setFixedPitch(True)
        font.setPixelSize(13)
        self.editor.setFont(font)
        self.editor.setPlainText(code)
        self.editor.document().setDocumentMargin(0)
        self.editor.setFixedHeight(min(240, max(38, self.editor.blockCount() * (self.editor.fontMetrics().lineSpacing() + 1) + 22)))
        layout.addWidget(self.editor)
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self.feedback.clear)

    def _copy_code(self):
        QApplication.clipboard().setText(self.code)
        self.feedback.setText("Copied")
        self._feedback_timer.start(1200)


class ReplyContent(QWidget):
    """Render a document range without losing code or normal link protection."""
    def __init__(self, source, start, end, protected, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._text = selected_text(source, start, end)
        for token, (_, text) in protected.items():
            self._text = self._text.replace(token, text)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        for first, stop, code in code_segments(source, start, end, protected):
            if code is not None:
                widget = CodeBlock(*code, self)
            else:
                widget = SafeTextBrowser(self)
                widget.set_fragment(source, first, stop)
            layout.addWidget(widget)

    def toPlainText(self):  # noqa: N802
        return self._text


class ReplyDisclosure(QWidget):
    def __init__(self, title, source, start, end, parent=None, protected=None):
        super().__init__(parent)
        self.title = title
        self.setObjectName("ReplyDisclosure")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)
        self.toggle = QToolButton(self)
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setArrowType(Qt.RightArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setProperty("kind", "disclosure")
        self.toggle.setToolTip(title)
        self.toggle.setAccessibleName(title)
        self.browser = ReplyContent(source, start, end, protected or {}, self)
        self.browser.hide()
        self.toggle.toggled.connect(self.browser.setVisible)
        self.toggle.toggled.connect(lambda checked: self.toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow))
        layout.addWidget(self.toggle, 0, Qt.AlignLeft)
        layout.addWidget(self.browser)


class ReplyBody(QWidget):
    """Keep full answer text while presenting named technical sections as disclosures."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._source = SafeTextBrowser(self)
        self._source.hide()
        self._render_source = SafeTextBrowser(self)
        self._render_source.hide()
        self.disclosures = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)
        self._plain_browser = None

    def document(self):
        return self._source.document()

    def toPlainText(self):  # noqa: N802
        return self._source.toPlainText()

    def set_content(self, content, markdown=True):
        self._source.set_content(content, markdown)
        if not markdown and self._plain_browser is not None:
            self._plain_browser.set_content(content, False)
            return
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self.disclosures = []
        self._plain_browser = None
        rendered, protected = protect_fenced_code(content) if markdown else (content, {})
        if protected:
            self._render_source.set_content(rendered)
            source = self._render_source.document()
        else:
            source = self.document()
        sections = reply_sections(source) if markdown else []
        has_code = markdown and any(code is not None for _, _, code in code_segments(source, 0, source.characterCount() - 1, protected))
        if not has_code and not any(title for title, _, _ in sections):
            browser = SafeTextBrowser(self)
            browser.set_content(content, markdown)
            self._layout.addWidget(browser)
            self._plain_browser = browser if not markdown else None
            return
        for title, start, end in sections:
            if title:
                widget = ReplyDisclosure(title, source, start, end, self, protected)
                self.disclosures.append(widget)
            else:
                widget = ReplyContent(source, start, end, protected, self)
            self._layout.addWidget(widget)


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
        self._display_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self._render()

    def set_display_text(self, text: str) -> None:
        self._display_text = text
        self._render()

    def _render(self) -> None:
        super().setText(self.fontMetrics().elidedText(self._display_text, Qt.ElideMiddle, max(30, self.width())))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._render()


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


class WorkPlanPanel(QFrame):
    """Compact live plan: one current step, completed steps, and folded details."""

    MAX_VISIBLE_COMPLETED = 3

    PHASES = {
        "sending": "Sending the request",
        "waiting": "Waiting for the router",
        "receiving": "Receiving the answer",
        "stopping": "Stopping",
        "approval": "Waiting for your approval",
        "executing": "Running the QGIS step",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "activity")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.current_state = "idle"
        self._items = []
        self._completed = []
        self._current = ""
        self._current_is_transport = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 5)
        outer.setSpacing(3)
        self.header = QWidget(self)
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(5)
        self.title_label = QLabel("Working on your request", self.header)
        self.title_label.setProperty("kind", "work-title")
        self.title_label.setTextFormat(Qt.PlainText)
        self.header_layout.addWidget(self.title_label, 1)
        outer.addWidget(self.header)
        self.mode_label = QLabel("", self)
        self.mode_label.setProperty("kind", "work-mode")
        self.mode_label.setTextFormat(Qt.PlainText)
        outer.addWidget(self.mode_label)
        self.step_label = QLabel("", self)
        self.step_label.setProperty("kind", "work-phase")
        self.step_label.setTextFormat(Qt.PlainText)
        self.step_label.setWordWrap(True)
        outer.addWidget(self.step_label)
        self.status_label = QLabel("", self)
        self.status_label.setProperty("kind", "work-status")
        self.status_label.setTextFormat(Qt.PlainText)
        outer.addWidget(self.status_label)
        self.current_label = QLabel("", self)
        self.current_label.setProperty("kind", "work-current")
        self.current_label.setTextFormat(Qt.PlainText)
        self.current_label.setWordWrap(True)
        outer.addWidget(self.current_label)
        self.next_label = QLabel("", self)
        self.next_label.setProperty("kind", "work-next")
        self.next_label.setTextFormat(Qt.PlainText)
        self.next_label.setWordWrap(True)
        self.next_label.hide()
        outer.addWidget(self.next_label)
        self.steps_widget = QWidget(self)
        self.steps_layout = QVBoxLayout(self.steps_widget)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(2)
        outer.addWidget(self.steps_widget)
        self.activity_toggle = QToolButton(self)
        self.activity_toggle.setProperty("kind", "disclosure")
        self.activity_toggle.setCheckable(True)
        self.activity_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.activity_toggle.setAccessibleName("Expand or collapse work details")
        self.activity_toggle.toggled.connect(lambda checked: self.activity_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow))
        outer.addWidget(self.activity_toggle, 0, Qt.AlignLeft)
        self.activity_view = ActivityBrowser(self)
        self.activity_view.hide()
        self.activity_toggle.toggled.connect(self.activity_view.setVisible)
        outer.addWidget(self.activity_view)
        self.setVisible(False)

    def attach_stop_button(self, button):
        button.setParent(self.header)
        self.header_layout.addWidget(button)
        self.stop_button = button

    def set_mode(self, execute=False):
        self.mode_label.setText("Execute · QGIS changes require approval" if execute else "Chat · no QGIS changes")
        self.mode_label.setVisible(True)

    def activity_panel_visible_details(self):
        return self.activity_toggle.isVisible()

    def step_count(self):
        return len(self._completed) + bool(self._current)

    def completed_labels(self):
        return list(self._completed)

    @staticmethod
    def _compact(text):
        value = str(text or "")
        value = re.sub(r"(\*\*|__)(.+?)\1", r"\2", value)
        value = re.sub(r"`([^`]+)`", r"\1", value)
        value = next((line.strip() for line in value.splitlines() if line.strip()), value)
        value = " ".join(value.split()).rstrip(".")
        if value.startswith("Prepared "):
            value = re.sub(r"^Prepared \d+ selected QGIS context categories$", "Prepared QGIS context", value)
        for prefix in ("Awaiting approval: ", "Running: ", "Completed: ", "Failed: "):
            if value.startswith(prefix):
                return value[len(prefix) :].strip()
        replacements = {
            "Sending the prepared request to the router": "Sending the request",
            "Router accepted the request": "Request accepted",
            "Receiving the final answer": "Receiving the answer",
        }
        value = replacements.get(value, value)
        return value if len(value) <= 180 else value[:177].rstrip() + "..."

    def _rebuild_steps(self):
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            if item.widget() is not None:
                old_row = item.widget()
                old_row.hide()
                old_row.deleteLater()
        visible_completed = self._completed[-self.MAX_VISIBLE_COMPLETED :]
        rows = [("complete", value) for value in visible_completed]
        if self._current:
            rows.append(("current", self._current))
        for state, value in rows:
            row = QWidget(self.steps_widget)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            icon = QLabel("✓" if state == "complete" else "→", row)
            icon.setProperty("kind", "work-complete" if state == "complete" else "work-active")
            icon.setTextFormat(Qt.PlainText)
            icon.setFixedWidth(15)
            row_layout.addWidget(icon)
            label = QLabel(value, row)
            label.setProperty("kind", "work-step")
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            row_layout.addWidget(label, 1)
            if state == "current":
                current = QLabel("Current", row)
                current.setProperty("kind", "work-state")
                current.setTextFormat(Qt.PlainText)
                row_layout.addWidget(current)
            self.steps_layout.addWidget(row)

    def _render_details(self):
        self.activity_toggle.setText(f"Details · {len(self._items)} updates")
        self.activity_toggle.setArrowType(Qt.DownArrow if self.activity_toggle.isChecked() else Qt.RightArrow)
        self.activity_toggle.setVisible(bool(self._items))
        details = "\n".join(f"• {self._compact(item['text'])}" for item in self._items)
        bar = self.activity_view.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 4
        self.activity_view.set_content(details)
        self.activity_view.setVisible(self.activity_toggle.isChecked() and bool(self._items))
        if follow and self._items:
            QTimer.singleShot(0, self.activity_view.scroll_to_end)

    def set_items(self, items, status="streaming"):
        self._items = list(items)
        completed = []
        current = ""
        next_value = ""
        state = "working"
        for item in self._items:
            original = item["text"]
            next_value = ""
            next_match = re.search(r"(?im)^\s*(?:next step|next|下一步)\s*[:：]\s*(.+)$", original)
            if next_match:
                next_value = self._compact(next_match.group(1))
            without_next = re.sub(r"(?im)^\s*(?:next step|next|下一步)\s*[:：].*$", "", original)
            original = re.sub(r"(?im)^\s*(?:now|current|当前|目前)\s*[:：]\s*", "", without_next)
            value = self._compact(original)
            if not value:
                continue
            if item["kind"] in {"summary", "commentary"}:
                if current and current != value:
                    completed.append(current)
                current = value
                self._current_is_transport = False
            elif original.startswith("Prepared ") or original.startswith("Completed:"):
                if value not in completed:
                    completed.append(value)
                if original.startswith("Completed:"):
                    current = ""
            elif original.startswith("Awaiting approval:"):
                current = value
                state = "approval"
                self._current_is_transport = False
            elif original.startswith("Running:"):
                current = value
                state = "working"
                self._current_is_transport = False
            elif original.startswith("Failed:"):
                current = value
                state = "error"
                self._current_is_transport = False
            elif original.startswith("Stopped"):
                current = "Stopped"
                state = "stopped"
                self._current_is_transport = False
            elif original.startswith(("Sending ", "Router accepted", "Receiving ")):
                if not current:
                    current = value
                    self._current_is_transport = True
            elif not current:
                current = value
        self._completed = list(dict.fromkeys(completed))
        self._current = current
        self.next_label.setText("Next · " + next_value if next_value else "")
        self.next_label.setVisible(bool(next_value) and status not in {"complete", "non_streaming", "stopped", "error"})
        self.current_state = status if status in {"complete", "non_streaming", "stopped", "error"} else state
        self._rebuild_steps()
        self._render_details()
        self.setVisible(bool(self._items) or self.current_state in {"error", "stopped"})
        if self.current_state in {"complete", "non_streaming"}:
            self.title_label.setText(f"Answer ready · {self.step_count()} steps")
            self.status_label.clear()
            self.step_label.clear()
            self.step_label.hide()
            self.current_label.hide()
            self.next_label.hide()
            self.steps_widget.hide()
            self.activity_toggle.setChecked(False)
        else:
            self.title_label.setText("Working on your request")
            self.step_label.setText(f"Step {len(self._completed) + 1}" + (f" · {self._current}" if self._current else ""))
            self.step_label.show()
            self.current_label.setText("NOW  " + self._current if self._current else "")
            self.current_label.setVisible(bool(self._current))
            self.status_label.setText(self.PHASES.get(self.current_state, "Working on your request"))
            self.steps_widget.setVisible(bool(self._completed) or bool(self._current))
        if self.current_state == "error":
            self.title_label.setText("Request failed")
            self.status_label.setText("No further steps will run")
            self.step_label.hide()
            self.current_label.hide()
            self.next_label.hide()
            self.steps_widget.hide()
        elif self.current_state == "stopped":
            self.title_label.setText("Stopped")
            self.status_label.setText("Completed steps remain unchanged")
            self.step_label.hide()
            self.current_label.hide()
            self.next_label.hide()
            self.steps_widget.hide()

    def set_transport(self, phase, elapsed, idle):
        self.current_state = "approval" if phase == "approval" else "working"
        if not self._current or self._current_is_transport:
            self._current = self.PHASES.get(phase, "Working on your request")
            self._current_is_transport = True
        self.title_label.setText("Working on your request")
        elapsed_text = f"{int(elapsed) // 60:02d}:{int(elapsed) % 60:02d}"
        idle_text = f" · last activity {int(idle)}s ago" if int(idle) >= 5 else ""
        self.status_label.setText(self.PHASES.get(phase, "Working on your request") + f" · {elapsed_text}" + idle_text)
        self.step_label.setText(f"Step {len(self._completed) + 1} · {self.PHASES.get(phase, 'Working on your request')}")
        self.step_label.show()
        self.current_label.setText("NOW  " + self._current)
        self.current_label.show()
        self.setVisible(True)
        if hasattr(self, "stop_button"):
            self.stop_button.setVisible(True)
            self.stop_button.setEnabled(phase != "stopping")

    def set_terminal(self, status):
        self.current_state = status
        self.set_items(self._items, status=status)
        if hasattr(self, "stop_button"):
            self.stop_button.hide()


class MessageCard(QFrame):
    retryRequested = pyqtSignal(object, bool)
    stopRequested = pyqtSignal()
    editRequested = pyqtSignal(object)
    quoteRequested = pyqtSignal(object, str)

    def has_text_selection(self):
        return any(editor.isVisible() and editor.textCursor().hasSelection() for editor in self.findChildren(QTextEdit) + self.findChildren(QPlainTextEdit))

    def __init__(
        self,
        message: dict[str, Any],
        parent: QWidget | None = None,
        available_attachment_ids: set[str] | None = None,
        editable: bool = False,
    ) -> None:
        super().__init__(parent)
        self.message = message
        self.setFont(ui_font(12))
        role = str(message.get("role") or "assistant")
        self.setProperty("role", "user" if role == "user" else "assistant")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            10 if role == "user" else 14,
            6 if role == "user" else 12,
            10 if role == "user" else 14,
            6 if role == "user" else 12,
        )
        layout.setSpacing(3)

        self.activity_panel = WorkPlanPanel(self)
        self.activity_panel.set_mode(bool((message.get("request") or {}).get("execute")))
        self.activity_toggle = self.activity_panel.activity_toggle
        self.activity_view = self.activity_panel.activity_view
        layout.addWidget(self.activity_panel)
        self._render_activity()

        self.body = CompactQuestionBrowser(self) if role == "user" else ReplyBody(self)
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
        self.stop_button.setProperty("kind", "work-stop")
        self.stop_button.setAccessibleName("Stop this response")
        self.stop_button.clicked.connect(self.stopRequested)
        self.stop_button.hide()
        self.activity_panel.attach_stop_button(self.stop_button)
        layout.addWidget(self.status_widget)
        self.status_widget.setVisible(role == "assistant" and message.get("status") in {"stopped", "error"})
        self.footer = QWidget(self)
        self.footer.setObjectName("MessageFooter")
        footer_row = QHBoxLayout(self.footer)
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(3)
        self.footer_meta = FooterLabel(self._meta_text(), self.footer)
        self.footer_cost = QLabel(self.footer)
        self.footer_cost.setTextFormat(Qt.PlainText)
        self.footer_cost.setProperty("kind", "meta")
        self.footer_cost.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self._compact_footer()
        self.footer_meta.setProperty("kind", "user-meta" if role == "user" else "meta")
        footer_row.addWidget(self.footer_meta, 1)
        footer_row.addWidget(self.footer_cost)
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
        if role == "user" and parent is not None:
            parent.installEventFilter(self)
            QTimer.singleShot(0, self._fit_question_width)

    def _fit_question_width(self):
        parent = self.parentWidget()
        if parent is None:
            return
        margins = parent.layout().contentsMargins() if parent.layout() else parent.contentsMargins()
        available = max(120, parent.width() - margins.left() - margins.right())
        text = str(self.message.get("content") or "")
        desired = max((self.body.fontMetrics().horizontalAdvance(line) for line in text.splitlines()), default=140) + 24
        self.setFixedWidth(max(120, min(int(available * 0.82), max(180, desired))))

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self._fit_question_width()
        return super().eventFilter(watched, event)

    def _compact_footer(self):
        self.footer_cost.hide()
        if self.message.get("role") == "user":
            self.footer_meta.set_display_text("You")
        else:
            detail = self.message.get("request") or {}
            values = [
                f"{detail.get('model') or 'Unknown model'} · {detail.get('thinking') or 'Auto'}"
            ]
            duration = self._duration_text(self.message.get("duration_seconds"))
            cost, detail_text = cost_display(self.message)
            if duration:
                values.append(duration)
            if cost:
                self.footer_cost.setText(cost)
                self.footer_cost.setToolTip(detail_text)
                self.footer_cost.show()
            self.footer_meta.set_display_text(" · ".join(values))

    @staticmethod
    def _duration_text(value: Any) -> str:
        try:
            seconds = max(0, int(value))
        except (TypeError, ValueError):
            return ""
        if seconds < 60:
            return f"{seconds}s"
        return f"{seconds // 60}m {seconds % 60:02d}s"

    def _meta_text(self) -> str:
        if self.message.get("role") == "user":
            timestamp = str(self.message.get("created_at") or "").replace("T", " ")[:16]
            return f"You  |  {timestamp}"
        detail = self.message.get("request") or {}
        model = detail.get("model") or "Unknown model"
        thinking = detail.get("thinking") or "Auto"
        timestamp = str(self.message.get("created_at") or "").replace("T", " ")[:16]
        values = [f"{model}  ·  Thinking: {thinking}  ·  {timestamp}"]
        duration = self._duration_text(self.message.get("duration_seconds"))
        cost, cost_detail = cost_display(self.message)
        if duration:
            values.append(f"Duration: {duration}")
        if cost:
            values.append(cost_detail)
        finished_at = str(self.message.get("finished_at") or "").replace("T", " ")[:16]
        if finished_at:
            values.append(f"Finished: {finished_at}")
        return "  ·  ".join(values)

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
        self.activity_panel.set_items(items, status=self.message.get("status", "complete"))

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
        self.activity_panel.set_transport(phase, elapsed_seconds, idle_seconds)

    def finalize(self, content: str, status: str, error: dict[str, Any] | None = None) -> None:
        self.activity_panel.set_terminal(status)
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
        self._compact_footer()
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
        self._compact_footer()
        self.copy_button.setToolTip("Copy response")


class ToolResultCard(QFrame):
    undoRequested = pyqtSignal(str)

    def __init__(self, result: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "tool")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        row = QHBoxLayout()
        title = QLabel(str(result.get("tool") or "Local check").replace("_", " "), self)
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setProperty("kind", "project")
        row.addWidget(title, 1)
        risk = QLabel(
            result["risk"].replace(":", " ·", 1) if result.get("risk", "").startswith("Execute") else "R0 read-only",
            self,
        )
        risk.setProperty("kind", "meta")
        row.addWidget(risk)
        layout.addLayout(row)
        summary = result.get("result", {}).get("summary", "") if isinstance(result.get("result"), dict) else ""
        if result.get("risk", "").startswith("Execute") and summary:
            description = QLabel(str(summary).splitlines()[0][:240], self)
            description.setTextFormat(Qt.PlainText)
            description.setWordWrap(True)
            description.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            layout.addWidget(description)

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
        recovery_id = (result.get("result") or {}).get("outcome", {}).get("recovery_id")
        self.recovery_id = recovery_id
        self.undo_button = None
        if result.get("tool") == "remove_temporary_layer" and isinstance(recovery_id, str):
            undo = QToolButton(self)
            self.undo_button = undo
            undo.setText("Undo remove")
            undo.setToolTip("Restore the removed temporary layer")
            undo.clicked.connect(lambda: self.undoRequested.emit(recovery_id))
            layout.addWidget(undo, 0, Qt.AlignLeft)


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
