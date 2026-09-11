# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep fenced code verbatim while letting Qt parse surrounding Markdown."""

import re
import uuid


def protect_fenced_code(markdown):
    """Replace complete unindented fenced blocks with private rendering markers.

    Qt expands tabs and merges adjacent fences. Keep their original contents for
    Copy instead; the saved message and full-answer clipboard are never changed.
    Nested or unfinished blocks remain available through Qt's native code parser.
    """
    lines = markdown.splitlines(keepends=True)
    output = []
    protected = {}
    prefix = "COPILOTCODE" + uuid.uuid4().hex
    index = 0
    while index < len(lines):
        opening = re.match(r"^( {0,3})(`{3,}|~{3,})([^\r\n]*)[\r\n]*$", lines[index])
        if opening is None or (opening[2][0] == "`" and "`" in opening[3]):
            output.append(lines[index])
            index += 1
            continue
        fence = re.escape(opening[2][0]) + "{" + str(len(opening[2])) + ",}"
        closing = re.compile(r"^ {0,3}" + fence + r"[ \t]*[\r\n]*$")
        stop = index + 1
        while stop < len(lines) and not closing.match(lines[stop]):
            stop += 1
        if stop == len(lines):
            output.extend(lines[index:])
            break
        if opening[1]:
            output.extend(lines[index : stop + 1])
            index = stop + 1
            continue
        body = "".join(lines[index + 1 : stop])
        if body.endswith("\r\n"):
            body = body[:-2]
        elif body.endswith("\n"):
            body = body[:-1]
        token = prefix + "X" + str(len(protected))
        language = opening[3].strip().split(maxsplit=1)
        protected[token] = (language[0] if language else "", body)
        output.append("\n\n" + token + "\n\n")
        index = stop + 1
    return "".join(output), protected


def selected_text(document, start, end):
    from qgis.PyQt.QtGui import QTextCursor

    cursor = QTextCursor(document)
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.KeepAnchor)
    return cursor.selectedText().replace("\u2029", "\n").replace("\u2028", "\n")


def code_segments(document, start, end, protected):
    """Return ordinary fragments and copyable code in their original order."""
    from qgis.PyQt.QtGui import QTextFormat

    output = []
    plain_start = start
    block = document.findBlock(start)
    while block.isValid() and block.position() < end:
        marker = protected.get(block.text())
        native = block.blockFormat().hasProperty(QTextFormat.BlockCodeLanguage)
        if marker is None and not native:
            block = block.next()
            continue
        first = max(start, block.position())
        language = block.blockFormat().property(QTextFormat.BlockCodeLanguage)
        following = block.next()
        if marker is None:
            while (
                following.isValid()
                and following.position() < end
                and following.blockFormat().hasProperty(QTextFormat.BlockCodeLanguage)
                and following.blockFormat().property(QTextFormat.BlockCodeLanguage) == language
            ):
                following = following.next()
        stop = min(following.position() if following.isValid() else end, end)
        if first > plain_start and selected_text(document, plain_start, first).strip():
            output.append((plain_start, first, None))
        value = marker or (
            language if isinstance(language, str) else "",
            selected_text(document, first, stop).rstrip("\n"),
        )
        output.append((first, stop, value))
        plain_start = stop
        block = following
    if plain_start < end and selected_text(document, plain_start, end).strip():
        output.append((plain_start, end, None))
    return output
