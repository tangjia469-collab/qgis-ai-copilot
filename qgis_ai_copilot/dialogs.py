# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Settings, model, and context surfaces for the Copilot dock."""

from __future__ import annotations

import json
from typing import Any

from qgis.PyQt.QtCore import QEvent, QPoint, QRect, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.gui import QgsAuthConfigSelect

from .config import PluginSettings
from .constants import THINKING_VALUES
from .context import CONTEXT_LABELS, ContextCollector
from .network import RouterClient
from .protocol import ModelRecord, ProtocolError, RouterProfile, normalized_base_url


class RouterSettingsDialog(QDialog):
    profileSaved = pyqtSignal(object)

    def __init__(
        self,
        settings: PluginSettings,
        records: list[ModelRecord],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.records = list(records)
        self.capabilities = settings.capabilities()
        self._capability_model = ""
        self.client = RouterClient(self)
        self.setWindowTitle("QGIS AI Copilot settings")
        self.setModal(True)
        self.resize(520, 620)
        self._build_ui()
        self._load()
        self.base_url_edit.textEdited.connect(self._connection_identity_changed)
        self.auth_select.selectedConfigIdChanged.connect(self._connection_identity_changed)
        self.client.catalogStarted.connect(self._test_started)
        self.client.catalogLoaded.connect(self._test_succeeded)
        self.client.catalogFailed.connect(self._test_failed)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget(scroll)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        connection = QGroupBox("Connection", body)
        form = QFormLayout(connection)
        self.name_edit = QLineEdit(connection)
        self.name_edit.setPlaceholderText("Research Router")
        form.addRow("Profile", self.name_edit)
        self.base_url_edit = QLineEdit(connection)
        self.base_url_edit.setPlaceholderText("https://router.example")
        form.addRow("Base URL", self.base_url_edit)
        self.auth_select = QgsAuthConfigSelect(connection)
        form.addRow("Authentication", self.auth_select)
        self.context_trust_check = QCheckBox(
            "Automatically send selected QGIS metadata", connection
        )
        self.context_trust_check.setToolTip(
            "Applies only to this Base URL and Authentication selection."
        )
        form.addRow("Context", self.context_trust_check)
        self.streaming_check = QCheckBox("Stream responses", connection)
        form.addRow("Delivery", self.streaming_check)
        self.adapter_combo = QComboBox(connection)
        self.adapter_combo.addItem("Chat Completions", "chat_completions")
        self.adapter_combo.addItem("Responses (live model activity)", "responses")
        form.addRow("API", self.adapter_combo)
        self.summary_check = QCheckBox("Request model activity summaries", connection)
        self.summary_check.setToolTip("Only public summaries supplied by the model are shown. Requires Responses support; availability and timing vary by router/model. No raw reasoning is displayed.")
        form.addRow("Activity", self.summary_check)
        self.adapter_combo.currentIndexChanged.connect(lambda: self.summary_check.setEnabled(self.adapter_combo.currentData() == "responses"))
        self.timeout_spin = QSpinBox(connection)
        self.timeout_spin.setRange(10, 600)
        self.timeout_spin.setSuffix(" s")
        form.addRow("Catalog timeout", self.timeout_spin)
        self.chat_idle_spin = QSpinBox(connection)
        self.chat_idle_spin.setRange(30, 3600)
        self.chat_idle_spin.setSuffix(" s")
        self.chat_idle_spin.setToolTip("Wait this long without router activity. Active streams reset this timer. Stop is always available; maximum request duration is one hour.")
        form.addRow("Chat idle timeout", self.chat_idle_spin)
        layout.addWidget(connection)

        history = QGroupBox("Local chat history", body)
        history_form = QFormLayout(history)
        self.retention_spin = QSpinBox(history)
        self.retention_spin.setRange(1, 365)
        self.retention_spin.setSuffix(" days")
        history_form.addRow("Keep chats", self.retention_spin)
        history_note = QLabel(
            "Chats stay on this device, are separated by QGIS project, and can be cleared from the Chats menu.",
            history,
        )
        history_note.setWordWrap(True)
        history_note.setProperty("kind", "meta")
        history_form.addRow(history_note)
        layout.addWidget(history)

        test_group = QGroupBox("Connection test", body)
        test_layout = QVBoxLayout(test_group)
        self.test_button = QPushButton("Test and load models", test_group)
        test_layout.addWidget(self.test_button)
        self.test_url = QLabel("URL / TLS: Not tested", test_group)
        self.test_auth = QLabel("Authentication: Not tested", test_group)
        self.test_catalog = QLabel("Model catalog: Not tested", test_group)
        for label in (self.test_url, self.test_auth, self.test_catalog):
            label.setProperty("kind", "meta")
            test_layout.addWidget(label)
        self.test_button.clicked.connect(self._test_connection)
        layout.addWidget(test_group)

        capabilities = QGroupBox("Model Thinking capabilities", body)
        capability_layout = QVBoxLayout(capabilities)
        self.capability_model = QComboBox(capabilities)
        self.capability_model.currentTextChanged.connect(self._capability_model_changed)
        capability_layout.addWidget(self.capability_model)
        helper = QLabel(
            "Auto is always available. Enable only values confirmed by router metadata or configuration.",
            capabilities,
        )
        helper.setWordWrap(True)
        helper.setProperty("kind", "meta")
        capability_layout.addWidget(helper)
        values = QHBoxLayout()
        self.capability_checks: dict[str, QCheckBox] = {}
        for value in THINKING_VALUES:
            if value == "Auto":
                continue
            check = QCheckBox(value, capabilities)
            check.toggled.connect(self._capability_toggled)
            self.capability_checks[value] = check
            values.addWidget(check)
        values.addStretch(1)
        capability_layout.addLayout(values)
        layout.addWidget(capabilities)
        layout.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _load(self) -> None:
        profile = self.settings.profile()
        self.name_edit.setText(profile.name)
        self.base_url_edit.setText(profile.base_url)
        self.auth_select.setConfigId(profile.authcfg)
        self.context_trust_check.setChecked(self.settings.is_context_trusted(profile))
        self.streaming_check.setChecked(profile.streaming)
        self.adapter_combo.setCurrentIndex(self.adapter_combo.findData(profile.adapter))
        self.summary_check.setChecked(profile.reasoning_summaries)
        self.summary_check.setEnabled(profile.adapter == "responses")
        self.timeout_spin.setValue(profile.timeout_seconds)
        self.chat_idle_spin.setValue(profile.chat_idle_timeout_seconds)
        self.retention_spin.setValue(self.settings.history_retention_days())
        self._set_records(self.records)

    def _connection_identity_changed(self, *_args: Any) -> None:
        self.context_trust_check.setChecked(False)

    def _profile_from_form(self) -> RouterProfile:
        base_url = self.base_url_edit.text().strip()
        if base_url:
            base_url = normalized_base_url(base_url)
        return RouterProfile(
            name=self.name_edit.text().strip() or "Router",
            base_url=base_url,
            authcfg=self.auth_select.configId(),
            streaming=self.streaming_check.isChecked(),
            timeout_seconds=self.timeout_spin.value(),
            chat_idle_timeout_seconds=self.chat_idle_spin.value(),
            adapter=str(self.adapter_combo.currentData()),
            reasoning_summaries=self.summary_check.isChecked() and self.adapter_combo.currentData() == "responses",
        )

    def _save(self) -> None:
        try:
            profile = self._profile_from_form()
        except ProtocolError as exc:
            QMessageBox.warning(self, "Invalid connection", str(exc))
            self.base_url_edit.setFocus()
            return
        self._store_current_capabilities()
        self.settings.save_profile(profile)
        if self.context_trust_check.isChecked():
            self.settings.trust_context(profile)
        else:
            self.settings.clear_context_trust()
        self.settings.save_capabilities(self.capabilities)
        self.settings.save_history_retention_days(self.retention_spin.value())
        self.profileSaved.emit(profile)
        self.accept()

    def _test_connection(self) -> None:
        try:
            profile = self._profile_from_form()
        except ProtocolError as exc:
            self._test_failed("configuration", str(exc), 0)
            return
        if not profile.base_url:
            self._test_failed("configuration", "Enter a Base URL first.", 0)
            return
        self.client.fetch_models(profile)

    def _test_started(self) -> None:
        self.test_button.setEnabled(False)
        self.test_url.setText("URL / TLS: Checking...")
        self.test_auth.setText("Authentication: Waiting...")
        self.test_catalog.setText("Model catalog: Waiting...")

    def _test_succeeded(self, records: list[ModelRecord], timestamp: str) -> None:
        self.test_button.setEnabled(True)
        self.test_url.setText("URL / TLS: Passed")
        self.test_auth.setText("Authentication: Passed")
        self.test_catalog.setText(f"Model catalog: {len(records)} models")
        self._set_records(records)

    def _test_failed(self, kind: str, message: str, status: int) -> None:
        self.test_button.setEnabled(True)
        if kind in {"configuration", "tls", "timeout", "network"}:
            self.test_url.setText(f"URL / TLS: {message}")
            self.test_auth.setText("Authentication: Not reached")
            self.test_catalog.setText("Model catalog: Not reached")
        elif kind == "authentication":
            self.test_url.setText("URL / TLS: Passed")
            self.test_auth.setText(f"Authentication: Failed ({status})")
            self.test_catalog.setText("Model catalog: Not reached")
        else:
            self.test_url.setText("URL / TLS: Passed")
            self.test_auth.setText("Authentication: Passed")
            self.test_catalog.setText(f"Model catalog: {message}")

    def _set_records(self, records: list[ModelRecord]) -> None:
        self._store_current_capabilities()
        self.records = list(records)
        current = self.capability_model.currentText()
        self.capability_model.blockSignals(True)
        self.capability_model.clear()
        self.capability_model.addItems([record.id for record in records])
        if current:
            self.capability_model.setCurrentText(current)
        self.capability_model.blockSignals(False)
        self._capability_model_changed(self.capability_model.currentText())

    def _store_current_capabilities(self) -> None:
        if not self._capability_model:
            return
        self.capabilities[self._capability_model] = [
            value for value, check in self.capability_checks.items() if check.isChecked()
        ]

    def _capability_model_changed(self, model_id: str) -> None:
        self._store_current_capabilities()
        self._capability_model = model_id
        enabled = set(self.capabilities.get(model_id, []))
        for value, check in self.capability_checks.items():
            check.blockSignals(True)
            check.setChecked(value in enabled)
            check.setEnabled(bool(model_id))
            check.blockSignals(False)

    def _capability_toggled(self) -> None:
        self._store_current_capabilities()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.client.close()
        super().closeEvent(event)


class ComposerPopover(QFrame):
    """Transient composer panel, opening upward and clamped to visible bounds."""

    def __init__(self, anchor: QToolButton, dock: QWidget) -> None:
        super().__init__(dock.window(), Qt.Popup)
        self.anchor = anchor
        self.dock = dock
        self.setObjectName("ComposerPopover")
        self.installEventFilter(self)

    def show_for_anchor(self) -> None:
        if self.parentWidget() is not self.dock.window():
            self.setParent(self.dock.window(), Qt.Popup)
        bounds = QRect(self.dock.mapToGlobal(QPoint()), self.dock.size())
        screen = QApplication.screenAt(self.anchor.mapToGlobal(self.anchor.rect().center()))
        if screen is not None:
            bounds = bounds.intersected(screen.availableGeometry())
        bounds.adjust(6, 6, -6, -6)
        width = min(434, max(300, self.dock.width() - 20), bounds.width())
        self.setFixedWidth(width)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.show()
        self.adjustSize()
        anchor_top = self.anchor.mapToGlobal(QPoint()).y()
        anchor_bottom = anchor_top + self.anchor.height()
        above = max(0, anchor_top - bounds.top() - 5)
        below = max(0, bounds.bottom() - anchor_bottom - 5)
        preferred_height = self.sizeHint().height()
        upward = above >= preferred_height or above >= below
        height = min(preferred_height, above if upward else below)
        self.setMinimumHeight(0)
        self.setFixedHeight(max(1, height))
        x = max(bounds.left(), min(self.anchor.mapToGlobal(QPoint()).x(), bounds.right() - width + 1))
        y = anchor_top - self.height() - 5 if upward else anchor_bottom + 5
        self.move(x, max(bounds.top(), min(y, bounds.bottom() - self.height() + 1)))
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)
        self.anchor.setChecked(True)
        self.raise_()

    def hideEvent(self, event) -> None:  # noqa: N802
        self.anchor.setChecked(False)
        super().hideEvent(event)

    def dismiss(self) -> None:
        self.hide()
        self.anchor.window().activateWindow()
        self.anchor.setFocus(Qt.PopupFocusReason)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.dismiss()
            return True
        return super().eventFilter(watched, event)


class ModelPopover(ComposerPopover):
    refreshRequested = pyqtSignal()
    modelSelected = pyqtSignal(str)
    thinkingSelected = pyqtSignal(str)
    configureRequested = pyqtSignal()

    def __init__(self, anchor: QToolButton, dock: QWidget) -> None:
        super().__init__(anchor, dock)
        self.records: list[ModelRecord] = []
        self.current_model = ""
        self._thinking_values = ["Auto"]
        self.setObjectName("ModelPopover")
        self.setMinimumHeight(330)
        self._build_ui()
        for widget in (self, self.search, self.models, self.thinking):
            widget.installEventFilter(self)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)
        search_row = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search router models")
        self.search.setAccessibleName("Search router models")
        self.search.textChanged.connect(self._filter)
        search_row.addWidget(self.search, 1)
        refresh = QToolButton(self)
        refresh.setText("Refresh")
        refresh.setToolTip("Refresh model catalog")
        refresh.clicked.connect(self.refreshRequested)
        search_row.addWidget(refresh)
        layout.addLayout(search_row)

        self.models = QListWidget(self)
        self.models.setObjectName("ModelList")
        self.models.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.models.setTextElideMode(Qt.ElideRight)
        self.models.itemActivated.connect(self._activate_model)
        self.models.itemClicked.connect(self._activate_model)
        layout.addWidget(self.models, 1)

        thinking_row = QHBoxLayout()
        label = QLabel("Thinking", self)
        label.setProperty("kind", "project")
        thinking_row.addWidget(label)
        self.thinking = QComboBox(self)
        self.thinking.setAccessibleName("Thinking level")
        self.thinking.activated[str].connect(self._activate_thinking)
        thinking_row.addWidget(self.thinking, 1)
        layout.addLayout(thinking_row)
        self.capability = QLabel("Capability unknown - Auto only", self)
        self.capability.setProperty("kind", "meta")
        layout.addWidget(self.capability)

        footer = QHBoxLayout()
        self.updated = QLabel("Model catalog not loaded", self)
        self.updated.setProperty("kind", "meta")
        footer.addWidget(self.updated, 1)
        configure = QToolButton(self)
        configure.setText("Settings")
        configure.clicked.connect(self.configureRequested)
        footer.addWidget(configure)
        layout.addLayout(footer)

    def set_models(self, records: list[ModelRecord], updated: str = "") -> None:
        self.records = list(records)
        self.updated.setText(f"Catalog updated {updated.replace('T', ' ')[:16]}" if updated else "Model catalog not loaded")
        self._populate_models()

    def set_current(self, model_id: str, thinking: str, values: list[str]) -> None:
        self.current_model = model_id
        self._thinking_values = values or ["Auto"]
        self.thinking.blockSignals(True)
        self.thinking.clear()
        self.thinking.addItems(self._thinking_values)
        self.thinking.setCurrentText(thinking if thinking in self._thinking_values else "Auto")
        self.thinking.blockSignals(False)
        self.capability.setText(
            "Configured capability" if len(self._thinking_values) > 1 else "Capability unknown - Auto only"
        )
        self._select_current_item()

    def _populate_models(self) -> None:
        query = self.search.text().strip().lower()
        self.models.clear()
        for record in self.records:
            if query and query not in record.id.lower():
                continue
            detail = (
                f"{len(record.explicit_thinking)} router-provided Thinking values"
                if record.explicit_thinking
                else "Capability configured locally or Auto only"
            )
            item = QListWidgetItem(f"{record.id}\n{detail}", self.models)
            item.setData(Qt.UserRole, record.id)
            item.setToolTip(record.id)
        self._select_current_item()

    def _select_current_item(self) -> None:
        for index in range(self.models.count()):
            item = self.models.item(index)
            if item.data(Qt.UserRole) == self.current_model:
                self.models.setCurrentItem(item)
                return

    def _filter(self) -> None:
        self._populate_models()

    def _activate_model(self, item: QListWidgetItem) -> None:
        model_id = str(item.data(Qt.UserRole) or "")
        if model_id:
            self.current_model = model_id
            self.modelSelected.emit(model_id)

    def _activate_thinking(self, value: str) -> None:
        self.thinkingSelected.emit(value)
        self.dismiss()

    def show_for_anchor(self) -> None:
        super().show_for_anchor()
        self.search.setFocus()
        self.search.selectAll()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.dismiss()
            return True
        return super().eventFilter(watched, event)


class ContextDialog(QDialog):
    contextApplied = pyqtSignal(object)

    def __init__(
        self,
        collector: ContextCollector,
        attached_keys: set[str],
        local_results: list[dict[str, Any]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.collector = collector
        self.local_results = local_results
        self.setWindowTitle("Outgoing QGIS context")
        self.setModal(True)
        self.resize(500, 560)
        layout = QVBoxLayout(self)
        heading = QLabel("Context attached to the next request", self)
        heading.setProperty("kind", "brand")
        layout.addWidget(heading)
        self.checks: dict[str, QCheckBox] = {}
        row = QGridLayout()
        for index, (key, label) in enumerate(CONTEXT_LABELS.items()):
            check = QCheckBox(label, self)
            check.setChecked(key in attached_keys)
            check.toggled.connect(self._refresh_preview)
            self.checks[key] = check
            row.addWidget(check, index // 2, index % 2)
        row.setColumnStretch(1, 1)
        layout.addLayout(row)
        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Outgoing context payload preview")
        layout.addWidget(self.preview, 1)
        privacy = QLabel(
            "Raw attributes, geometries, exact paths, screenshots, credentials, and exact coordinates are excluded.",
            self,
        )
        privacy.setWordWrap(True)
        privacy.setProperty("kind", "meta")
        layout.addWidget(privacy)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_preview()

    def selected_keys(self) -> set[str]:
        return {key for key, check in self.checks.items() if check.isChecked()}

    def _refresh_preview(self) -> None:
        keys = self.selected_keys()
        snapshot = self.collector.snapshot(
            keys, self.local_results if "local_results" in keys else []
        )
        self.preview.setPlainText(json.dumps(snapshot, ensure_ascii=False, indent=2))

    def _apply(self) -> None:
        self.contextApplied.emit(self.selected_keys())
        self.accept()
