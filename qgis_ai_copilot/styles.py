# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Palette-derived styling for the native QGIS dock."""

from qgis.PyQt.QtGui import QColor, QPalette

from .typography import monospace_family, ui_family


def _hex(color: QColor) -> str:
    return color.name(QColor.HexRgb)


def _mix(first: QColor, second: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    return QColor(
        round(first.red() * (1 - amount) + second.red() * amount),
        round(first.green() * (1 - amount) + second.green() * amount),
        round(first.blue() * (1 - amount) + second.blue() * amount),
    )


def build_stylesheet(palette: QPalette) -> str:
    window = palette.color(QPalette.Window)
    base = palette.color(QPalette.Base)
    text = palette.color(QPalette.WindowText)
    muted = palette.color(QPalette.Disabled, QPalette.WindowText)
    highlight = palette.color(QPalette.Highlight)
    highlighted_text = palette.color(QPalette.HighlightedText)
    dark = window.lightness() < 128
    border = _mix(window, text, 0.16 if dark else 0.13)
    strong_border = _mix(window, text, 0.28 if dark else 0.23)
    surface = _mix(window, text, 0.055 if dark else 0.025)
    surface_2 = _mix(window, text, 0.10 if dark else 0.055)
    subtle = _mix(window, text, 0.55 if dark else 0.62)
    success = QColor("#65B891" if dark else "#2D7A58")
    warning = QColor("#D7A74A" if dark else "#8A5A00")
    danger = QColor("#E27878" if dark else "#B23B3B")
    answer_blue = QColor("#ADCFFF" if dark else "#214F80")
    answer_surface = _mix(base, QColor("#5395ed"), 0.12 if dark else 0.055)
    answer_border = _mix(base, QColor("#5395ed"), 0.38 if dark else 0.26)

    return f"""
    QWidget#CopilotRoot, QWidget#CopilotRoot QWidget {{
        font-family: "{ui_family()}";
    }}
    QWidget#CopilotRoot {{
        background: {_hex(base)};
        color: {_hex(text)};
        font-size: 12px;
    }}
    QFrame[section="true"] {{
        border: 0;
        border-bottom: 1px solid {_hex(border)};
        background: {_hex(window)};
    }}
    QLabel[kind="brand"] {{ font-size: 13px; font-weight: 650; }}
    QLabel[kind="project"] {{ font-weight: 600; }}
    QLabel[kind="meta"] {{ color: {_hex(subtle)}; font-size: 11px; }}
    QLabel[kind="work-title"] {{ color: {_hex(text)}; font-size: 13px; font-weight: 600; }}
    QLabel[kind="work-phase"], QLabel[kind="work-status"] {{ color: {_hex(subtle)}; font-size: 10px; }}
    QLabel[kind="work-mode"] {{ color: {_hex(subtle)}; font-size: 10px; }}
    QLabel[kind="work-next"] {{ color: {_hex(subtle)}; font-size: 10px; padding-left: 7px; }}
    QLabel[kind="work-current"] {{ color: {_hex(answer_blue)}; background: {_hex(answer_surface)}; border-left: 2px solid {_hex(answer_border)}; padding: 5px 7px; }}
    QLabel[kind="work-step"] {{ color: {_hex(text)}; font-size: 11px; }}
    QLabel[kind="work-state"] {{ color: {_hex(subtle)}; font-size: 10px; }}
    QLabel[kind="work-complete"] {{ color: {_hex(success)}; font-size: 13px; font-weight: 650; }}
    QLabel[kind="work-active"] {{ color: {_hex(highlight)}; font-size: 13px; font-weight: 650; }}
    QLabel[kind="user-meta"] {{ color: {_hex(subtle)}; font-size: 10px; }}
    QPlainTextEdit[kind="activity"] {{ color: {_hex(subtle)}; font-size: 10px; padding: 1px 3px; background: transparent; }}
    QLabel[kind="muted"] {{ color: {_hex(muted)}; }}
    QLabel[state="connected"] {{ color: {_hex(success)}; }}
    QLabel[state="warning"] {{ color: {_hex(warning)}; }}
    QLabel[state="error"] {{ color: {_hex(danger)}; }}
    QToolButton {{
        min-height: 28px;
        padding: 0 7px;
        border: 1px solid transparent;
        border-radius: 6px;
        color: {_hex(subtle)};
        background: transparent;
    }}
    QToolButton:hover, QToolButton:focus, QToolButton:checked {{
        border-color: {_hex(border)};
        color: {_hex(text)};
        background: {_hex(surface_2)};
    }}
    QToolButton[kind="model-selector"] {{
        min-height: 30px;
        max-height: 30px;
        border: 1px solid transparent;
        padding: 0 3px;
        color: {_hex(subtle)};
        background: transparent;
        font-size: 11px;
        font-weight: 400;
    }}
    QToolButton[kind="model-selector"]:hover,
    QToolButton[kind="model-selector"]:focus {{
        color: {_hex(text)};
        background: {_hex(surface)};
    }}
    QToolButton[kind="model-selector"]:focus {{ border-color: {_hex(strong_border)}; }}
    QToolButton#ComposerAttach, QToolButton#ComposerAreaCapture {{
        padding: 0;
        border: 1px solid transparent;
        background: transparent;
    }}
    QToolButton#ComposerAttach::menu-indicator {{ image: none; width: 0; height: 0; }}
    QToolButton#ComposerAttach:hover, QToolButton#ComposerAttach:focus,
    QToolButton#ComposerAreaCapture:hover, QToolButton#ComposerAreaCapture:focus {{
        background: {_hex(surface)};
        border-color: {_hex(border)};
    }}
    QToolButton[kind="message-action"] {{
        min-width: 20px;
        max-width: 20px;
        min-height: 20px;
        max-height: 20px;
        padding: 0;
        border-radius: 4px;
    }}
    QToolButton[kind="mode"] {{ min-height: 24px; padding: 0 3px; font-size: 10px; }}
    QToolButton[kind="mode"]:checked {{ background: {_hex(surface_2)}; border-color: {_hex(strong_border)}; color: {_hex(text)}; }}
    QToolButton[kind="question-toggle"] {{
        min-height: 18px;
        padding: 0 3px;
        font-size: 10px;
    }}
    QToolButton[kind="disclosure"] {{
        min-height: 24px;
        padding: 1px 2px;
        font-size: 12px;
        text-align: left;
    }}
    QToolButton[kind="work-stop"] {{ min-height: 24px; padding: 0 7px; border-color: {_hex(border)}; color: {_hex(subtle)}; background: transparent; }}
    QToolButton[kind="work-stop"]:hover, QToolButton[kind="work-stop"]:focus {{ border-color: {_hex(strong_border)}; color: {_hex(text)}; background: {_hex(surface)}; }}
    QToolButton[kind="context-toggle"] {{
        min-height: 30px;
        padding: 0 5px;
        font-size: 11px;
    }}
    QFrame#ContextPopover, QFrame#ModelPopover {{
        background: {_hex(window)};
        color: {_hex(text)};
        border: 1px solid {_hex(border)};
        border-radius: 8px;
    }}
    QToolButton[kind="primary"] {{
        min-width: 32px;
        min-height: 32px;
        max-width: 32px;
        max-height: 32px;
        padding: 0;
        border-color: #0879e9;
        color: white;
        background: #0879e9;
    }}
    QToolButton[kind="danger"] {{
        min-width: 32px;
        min-height: 32px;
        max-width: 32px;
        max-height: 32px;
        padding: 0;
        border-color: {_hex(danger)};
        color: white;
        background: {_hex(danger)};
    }}
    QToolButton[kind="primary"]:hover {{ background: #006bd6; border-color: #006bd6; }}
    QToolButton[kind="primary"]:focus {{ border-color: #004f9e; }}
    QToolButton[kind="primary"]:disabled {{
        border-color: {"#30465e" if dark else "#e1e9f2"};
        background: {"#30465e" if dark else "#e1e9f2"};
    }}
    QToolButton[kind="danger"]:hover, QToolButton[kind="danger"]:focus {{
        border-color: {_hex(_mix(danger, text, 0.2))};
        background: {_hex(_mix(danger, text, 0.08))};
    }}
    QToolButton[kind="chip"] {{
        min-height: 23px;
        max-height: 23px;
        padding: 0 7px;
        border-color: {_hex(border)};
        border-top-right-radius: 0;
        border-bottom-right-radius: 0;
        background: {_hex(surface)};
        font-size: 10px;
    }}
    QToolButton[kind="attachment"] {{
        min-height: 34px;
        max-height: 34px;
        padding: 0 5px;
        border-color: {_hex(border)};
        background: {_hex(surface)};
        font-size: 10px;
    }}
    QToolButton[kind="chip-close"] {{
        min-width: 19px;
        max-width: 19px;
        min-height: 23px;
        max-height: 23px;
        padding: 0;
        border-color: {_hex(border)};
        border-left: 0;
        border-top-left-radius: 0;
        border-bottom-left-radius: 0;
        background: {_hex(surface)};
        font-size: 13px;
    }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QListWidget, QTreeWidget, QSpinBox {{
        padding: 5px 7px;
        border: 1px solid {_hex(border)};
        border-radius: 6px;
        color: {_hex(text)};
        background: {_hex(base)};
        selection-color: {_hex(highlighted_text)};
        selection-background-color: {_hex(highlight)};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus {{
        border-color: {_hex(highlight)};
    }}
    QFrame[role="user"] {{
        border: 1px solid {_hex(border)};
        border-radius: 8px;
        background: {_hex(surface)};
    }}
    QFrame[role="assistant"] {{
        border: 1px solid {_hex(answer_border)};
        border-radius: 8px;
        background: {_hex(answer_surface)};
    }}
    QFrame[role="activity"] {{
        border: 0;
        background: transparent;
    }}
    QFrame#ExpressionCodeBox {{
        border: 1px solid {_hex(border)};
        border-radius: 6px;
        background: {_hex(base)};
    }}
    QPlainTextEdit[kind="code"], QWidget#CopilotRoot QPlainTextEdit[kind="code"] {{
        padding: 0;
        border: 0;
        border-radius: 0;
        background: transparent;
        color: {_hex(answer_blue)};
        font-size: 13px;
        font-family: "{monospace_family()}";
    }}
    QFrame[role="tool"] {{
        border: 1px solid {_hex(border)};
        border-left: 2px solid {_hex(success)};
        border-radius: 6px;
        background: {_hex(surface)};
    }}
    QFrame[role="error"] {{
        border: 1px solid {_hex(border)};
        border-left: 2px solid {_hex(danger)};
        border-radius: 6px;
        background: {_hex(surface)};
    }}
    QTextBrowser[kind="message"] {{
        padding: 0;
        border: 0;
        color: {_hex(text)};
        background: transparent;
    }}
    QFrame[role="assistant"] QTextBrowser[kind="message"],
    QFrame[role="assistant"] QToolButton[kind="disclosure"] {{
        color: {_hex(answer_blue)};
    }}
    QFrame#Composer {{
        margin: 8px 10px;
        border: 1px solid {_hex(strong_border)};
        border-radius: 7px;
        background: {_hex(base)};
    }}
    QTextEdit#MessageInput {{
        padding: 7px 8px;
        border: 0;
        background: transparent;
    }}
    QFrame#ModelPopover {{
        border: 1px solid {_hex(strong_border)};
        border-radius: 8px;
        background: {_hex(base)};
    }}
    QListWidget#ModelList {{ border-radius: 0; border-right: 0; border-left: 0; }}
    QListWidget#ModelList::item {{ padding: 6px 8px; }}
    QListWidget#ModelList::item:selected {{
        color: {_hex(highlighted_text)};
        background: {_hex(highlight)};
    }}
    QFrame#PrivacyFooter {{
        border-top: 1px solid {_hex(border)};
        background: {_hex(window)};
    }}
    QDialog, QMessageBox, QMenu {{ color: {_hex(text)}; background: {_hex(window)}; }}
    QGroupBox {{
        margin-top: 10px;
        padding-top: 10px;
        border: 1px solid {_hex(border)};
        border-radius: 7px;
        font-weight: 600;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
    QPushButton {{
        min-height: 28px;
        padding: 0 10px;
        border: 1px solid {_hex(border)};
        border-radius: 6px;
        color: {_hex(text)};
        background: {_hex(surface)};
    }}
    QPushButton:hover, QPushButton:focus {{ border-color: {_hex(highlight)}; }}
    QPushButton[primary="true"] {{
        border-color: {_hex(highlight)};
        color: {_hex(highlighted_text)};
        background: {_hex(highlight)};
    }}
    """
