# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit native rich-text typography and optional technical section boundaries."""

from functools import lru_cache

from qgis.PyQt.QtGui import (
    QFont,
    QFontDatabase,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QTextLength,
    QTextOption,
    QTextTable,
)


REPLY_FORMAT_INSTRUCTIONS = """Use compact, readable Markdown: a short conclusion first, small headings, short paragraphs, and a simple two-column table only when useful for actual results. Put copyable QGIS expressions and scripts in fenced code blocks (qgis, sql, or python), with explanations outside the fence. The code box has a Copy button that copies only its code. Avoid repeating the same log in both languages. Optional technical details may use a separate heading named 'Layers and parameters' or 'Raw log' ('图层与参数' or '原始日志' in Chinese); these sections are collapsed in the interface. Keep meaningful warnings, limitations, approvals, and next steps OUTSIDE those technical sections so they remain visible. Never add invented results, timings, status icons, or field values to fill a layout."""

TECHNICAL_HEADINGS = {
    "layers and parameters",
    "layer parameters",
    "parameter details",
    "raw log",
    "raw logs",
    "original warning",
    "raw warning",
    "technical details",
    "图层与参数",
    "参数详情",
    "原始日志",
    "运行日志",
    "原始警告",
    "技术详情",
}


@lru_cache(maxsize=1)
def ui_family():
    available = set(QFontDatabase().families())
    for name in (
        "PingFang SC",
        "Hiragino Sans GB",
        "Microsoft YaHei",
        "Noto Sans CJK SC",
        "Noto Sans",
        "DejaVu Sans",
    ):
        if name in available:
            return name
    return QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()


def ui_font(size=14):
    font = QFont(ui_family())
    font.setStyleHint(QFont.SansSerif)
    font.setPixelSize(size)
    return font


@lru_cache(maxsize=1)
def monospace_family():
    available = set(QFontDatabase().families())
    for name in ("Menlo", "Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier New", "Monaco"):
        if name in available:
            return name
    return "monospace"


def style_document(document):
    """Normalize Qt's parsed Markdown formats without rewriting its text or links."""
    document.setDefaultFont(ui_font())
    document.setDocumentMargin(0)
    option = document.defaultTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    mono = monospace_family()
    cursor = QTextCursor(document)
    cursor.beginEditBlock()
    block = document.begin()
    lists = set()
    while block.isValid():
        block_format = block.blockFormat()
        heading = block_format.headingLevel()
        block_format.setTopMargin(8 if heading and block.position() else 0)
        block_format.setBottomMargin(5 if heading else 6)
        block_format.setLineHeight(23 if heading else 22, QTextBlockFormat.FixedHeight)
        block_format.setRightMargin(0)
        if block_format.property(QTextFormat.BlockQuoteLevel):
            block_format.setLeftMargin(12)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(block_format)
        if block.textList() and block.textList().objectIndex() not in lists:
            text_list = block.textList()
            lists.add(text_list.objectIndex())
            list_format = text_list.format()
            list_format.setIndent(min(3, max(1, list_format.indent())))
            text_list.setFormat(list_format)
        fragment = block.begin()
        changes = []
        while not fragment.atEnd():
            item = fragment.fragment()
            if item.isValid():
                original = item.charFormat()
                family = original.fontFamily().lower()
                code = original.fontFixedPitch() or any(
                    name in family for name in ("mono", "courier", "menlo", "consolas")
                )
                fmt = QTextCharFormat(original)
                fmt.clearProperty(QTextFormat.FontSizeAdjustment)
                fmt.clearProperty(QTextFormat.FontPointSize)
                font = original.font()
                font.setFamily(mono if code else ui_family())
                font.setStyleHint(QFont.Monospace if code else QFont.SansSerif)
                font.setFixedPitch(code)
                font.setPixelSize(13 if code else 15 if heading else 14)
                font.setWeight(
                    QFont.DemiBold
                    if heading or original.fontWeight() > QFont.Normal
                    else QFont.Normal
                )
                fmt.setFont(font)
                changes.append((item.position(), item.length(), fmt))
            fragment += 1
        for position, length, fmt in changes:
            cursor.setPosition(position)
            cursor.setPosition(position + length, QTextCursor.KeepAnchor)
            cursor.setCharFormat(fmt)
        block = block.next()
    cursor.endEditBlock()
    # Fragment export can leave a mandatory empty table/paragraph boundary.
    # It carries no content and must not inherit a large heading line box.
    block = document.lastBlock()
    while block.isValid() and not block.text():
        fmt = block.blockFormat()
        fmt.setTopMargin(0)
        fmt.setBottomMargin(0)
        fmt.setLineHeight(1, QTextBlockFormat.FixedHeight)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(fmt)
        block = block.previous()
    for frame in document.rootFrame().childFrames():
        if isinstance(frame, QTextTable):
            fmt = frame.format()
            fmt.setBorder(0)
            fmt.setCellPadding(4)
            fmt.setCellSpacing(0)
            fmt.setWidth(QTextLength(QTextLength.PercentageLength, 100))
            fmt.setColumnWidthConstraints(
                [
                    QTextLength(QTextLength.PercentageLength, 100 / frame.columns())
                    for _ in range(frame.columns())
                ]
            )
            frame.setFormat(fmt)


def reply_sections(document):
    """Use parsed heading structure; never infer collapsible content from prose."""
    blocks = []
    block = document.begin()
    while block.isValid():
        blocks.append(block)
        block = block.next()
    end = document.characterCount() - 1
    sections = []
    start = 0
    index = 0
    while index < len(blocks):
        block = blocks[index]
        level = block.blockFormat().headingLevel()
        title = block.text().strip()
        if not level or title.lower().rstrip(":：") not in TECHNICAL_HEADINGS:
            index += 1
            continue
        following = index + 1
        while following < len(blocks):
            next_level = blocks[following].blockFormat().headingLevel()
            if next_level and next_level <= level:
                break
            following += 1
        stop = blocks[following].position() if following < len(blocks) else end
        content_start = block.position() + block.length()
        if content_start < stop:
            if block.position() > start:
                sections.append((None, start, block.position()))
            sections.append((title, content_start, stop))
            start = stop
        index = following
    if start < end:
        sections.append((None, start, end))
    return sections
