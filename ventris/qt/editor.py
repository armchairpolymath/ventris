"""The G-code editor: line numbers, current-line highlight, lazy syntax coloring."""

from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QTextCharFormat, QTextFormat, \
    QTextLayout
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from . import theme

_WORD = re.compile(r"^\s*([GgMm]\d+(?:\.\d+)?|[Tt]\d+|[A-Z][A-Z0-9_]*[A-Z0-9])(?=\s|$|;)")
_PARAM = re.compile(r"([A-Za-z])(0[xX][0-9A-Fa-f]+|[-+]?(?:\d+\.?\d*|\.\d+))")


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class LazyHighlighter:
    """Colors only the lines currently on screen.

    QSyntaxHighlighter colors every line of the document up front, which takes
    seconds for a 900k-line print file. Instead, formats are attached directly to
    the layouts of visible blocks whenever the view scrolls or text changes.
    """

    def __init__(self, editor: QPlainTextEdit):
        self.editor = editor
        self.formats: dict[str, QTextCharFormat] = {}
        self.set_colors(theme.is_dark())
        editor.updateRequest.connect(lambda *_: self.highlight_visible())

    def set_colors(self, dark: bool) -> None:
        c = theme.syntax_colors(dark)
        self.formats = {
            "comment": _fmt(c["comment"], italic=True),
            "G": _fmt(c["g"], bold=True), "M": _fmt(c["m"]), "T": _fmt(c["t"], bold=True),
            "letter": _fmt(c["letter"]), "number": _fmt(c["number"]),
        }
        self.reset()

    def reset(self) -> None:
        block = self.editor.document().firstBlock()
        while block.isValid():
            if block.userState() != -1:
                block.setUserState(-1)
            block = block.next()
        self.highlight_visible()

    def ranges_for(self, text: str) -> list[QTextLayout.FormatRange]:
        ranges = []

        def add(start: int, length: int, key: str) -> None:
            r = QTextLayout.FormatRange()
            r.start, r.length, r.format = start, length, self.formats[key]
            ranges.append(r)

        code_end = text.find(";")
        if code_end == -1:
            code_end = len(text)
        else:
            add(code_end, len(text) - code_end, "comment")
        code = text[:code_end]
        if m := _WORD.match(code):
            word = m.group(1)
            # G/M/T codes get their own colors; word commands (Ruida, macros) look like M codes
            key = word[0].upper() if word[0] in "GgMmTt" and word[1:2].isdigit() else "M"
            add(m.start(1), len(word), key)
            for p in _PARAM.finditer(code, m.end(1)):
                add(p.start(1), 1, "letter")
                add(p.start(2), len(p.group(2)), "number")
        return ranges

    def highlight_visible(self) -> None:
        editor = self.editor
        block = editor.firstVisibleBlock()
        bottom = editor.viewport().rect().bottom()
        doc = editor.document()
        while block.isValid():
            geometry = editor.blockBoundingGeometry(block).translated(editor.contentOffset())
            if geometry.top() > bottom:
                break
            text = block.text()
            stamp = hash(text) & 0x3FFFFFFF  # changes when the line is edited
            if block.userState() != stamp:
                block.setUserState(stamp)
                block.layout().setFormats(self.ranges_for(text))
                doc.markContentsDirty(block.position(), block.length())
            block = block.next()


class _LineNumbers(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self._numbers = _LineNumbers(self)
        self.highlighter = LazyHighlighter(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_numbers)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_margin()
        self._highlight_current_line()

    # line numbers ------------------------------------------------------------

    def line_number_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, *_):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_numbers(self, rect: QRect, dy: int) -> None:
        if dy:
            self._numbers.scroll(0, dy)
        else:
            self._numbers.update(0, rect.y(), self._numbers.width(), rect.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        r = self.contentsRect()
        self._numbers.setGeometry(QRect(r.left(), r.top(), self.line_number_width(), r.height()))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._numbers)
        palette = self.palette()
        painter.fillRect(event.rect(), palette.color(palette.ColorRole.Base))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        dim = palette.color(palette.ColorRole.PlaceholderText)
        strong = palette.color(palette.ColorRole.Text)
        width = self._numbers.width() - 6
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and top + height >= event.rect().top():
                painter.setPen(strong if number == current else dim)
                painter.drawText(0, top, width, self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top += height
            height = round(self.blockBoundingRect(block).height())
            number += 1

    # current line --------------------------------------------------------------

    def _highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(theme.current_line_color(theme.is_dark())))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
        self._numbers.update()

    def go_to_line(self, line: int) -> None:
        block = self.document().findBlockByNumber(max(0, min(line, self.blockCount() - 1)))
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    def refresh_theme(self) -> None:
        self.highlighter.set_colors(theme.is_dark())
        self._highlight_current_line()
