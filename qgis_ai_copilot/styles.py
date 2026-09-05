# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 QGIS AI Copilot contributors
"""Palette-derived styling for the native QGIS dock."""

from qgis.PyQt.QtGui import QColor, QPalette


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

    return f"""
    QWidget#CopilotRoot {{
        background: {_hex(window)};
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
    QLabel[kind="meta"] {{ color: {_hex(subtle)}; font-size: 10px; }}
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
    QToolButton[kind="profile"] {{
        min-height: 30px;
        max-height: 30px;
        border-color: {_hex(border)};
        color: {_hex(text)};
        background: {_hex(surface)};
        font-size: 10px;
        font-weight: 550;
    }}
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
        border-color: {_hex(highlight)};
        color: {_hex(highlighted_text)};
        background: {_hex(highlight)};
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
        border: 1px solid {_hex(highlight)};
        border-radius: 8px;
        background: {_hex(_mix(window, highlight, 0.10 if dark else 0.07))};
    }}
    QFrame[role="activity"] {{
        border: 0;
        border-left: 2px solid {_hex(border)};
        background: {_hex(surface)};
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
    QFrame#Composer {{
        margin: 8px 10px;
        border: 1px solid {_hex(strong_border)};
        border-radius: 7px;
        background: {_hex(surface)};
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
