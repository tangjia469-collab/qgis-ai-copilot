# SPDX-License-Identifier: GPL-3.0-or-later
"""Palette-aware composer icons with explicit high-DPI and disabled variants.

Existing SVG paths are from Lucide 0.468.0 (ISC); see THIRD_PARTY_NOTICES.md.
The screen-area crop frame is original artwork.
"""

import weakref

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QByteArray, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QIcon, QIconEngine, QPainter, QPalette, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import QApplication


_PATHS = {
    "paperclip": '<path d="M13.234 20.252 21 12.3"/><path d="m16 6-8.414 8.586a2 2 0 0 0 0 2.828 2 2 0 0 0 2.828 0l8.414-8.586a4 4 0 0 0 0-5.656 4 4 0 0 0-5.656 0l-8.415 8.585a6 6 0 1 0 8.486 8.486"/>',
    "arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    "square": '<rect width="18" height="18" x="3" y="3" rx="2"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    # Original crop-frame artwork; shares the existing palette-aware renderer.
    "screen-area": '<path d="M8 3H4v4M16 3h4v4M20 17v4h-4M8 21H4v-4"/><rect x="7" y="7" width="10" height="10" rx="1"/>',
}


class _ComposerIconEngine(QIconEngine):
    def __init__(self, widget, name, foreground):
        super().__init__()
        self.owner = weakref.ref(widget) if widget is not None else lambda: None
        self.name = name
        self.foreground = foreground

    def clone(self):
        return _ComposerIconEngine(self.owner(), self.name, self.foreground)

    def paint(self, painter, rect, mode, state):
        widget = self.owner()
        palette = (
            widget.palette()
            if widget is not None and not sip.isdeleted(widget)
            else QApplication.palette()
        )
        dark = palette.color(QPalette.Window).lightness() < 128
        if mode == QIcon.Disabled:
            color = QColor("#8ba5c2" if dark else "#7c94af")
        else:
            color = QColor(self.foreground or ("#dce6f2" if dark else "#364252"))
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color.name()}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{_PATHS[self.name]}</svg>'
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        renderer.render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, pixmap.rect(), mode, state)
        painter.end()
        return pixmap


def composer_icon(widget, name, foreground=None):
    if name not in _PATHS:
        raise ValueError("Unknown composer icon")
    return QIcon(_ComposerIconEngine(widget, name, foreground))
