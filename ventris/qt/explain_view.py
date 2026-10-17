"""Right-hand pane: explanation of the current line plus the machine state."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..explain import Explanation
from ..presentation import STATE_ROWS, details, file_note, param_rows, source_badge
from ..state import MachineState


def _label(text: str = "", name: str = "", wrap: bool = True, selectable: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    for child in widget.findChildren(QWidget):
        child.style().unpolish(child)
        child.style().polish(child)


class ExplainView(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(380)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        pane = QWidget()
        pane.setObjectName("explainPane")
        self.setWidget(pane)
        box = QVBoxLayout(pane)
        box.setContentsMargins(20, 18, 20, 24)
        box.setSpacing(14)

        self.line_label = _label(name="lineLabel")
        self.raw_label = _label(name="rawLine", selectable=True)
        self.raw_label.setFont(mono)
        box.addWidget(self.line_label)
        box.addWidget(self.raw_label)

        title_row = QHBoxLayout()
        self.title = _label(name="title")
        self.badge = _label(name="badge", wrap=False)
        self.badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        title_row.addWidget(self.title, 1)
        title_row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(title_row)

        self.sentence = _label(name="sentence", selectable=True)
        self.file_note = _label(name="fileNote")
        box.addWidget(self.sentence)
        box.addWidget(self.file_note)

        self.params_title = _label("What each part means", "sectionTitle")
        self.params_box = QVBoxLayout()
        self.params_box.setSpacing(4)
        box.addWidget(self.params_title)
        box.addLayout(self.params_box)
        self._param_widgets: list[QWidget] = []
        self._mono = mono

        self.details_button = QToolButton()
        self.details_button.setCheckable(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_button.setArrowType(Qt.ArrowType.RightArrow)
        self.details_button.setAutoRaise(True)
        self.details_button.toggled.connect(self._toggle_details)
        self.details_label = _label(selectable=True)
        self.details_label.setVisible(False)
        box.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignLeft)
        box.addWidget(self.details_label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        box.addWidget(line)
        box.addWidget(_label("Machine state after this line", "sectionTitle"))
        box.addWidget(_label("Highlighted values were changed by this line. "
                             "Hover a name for help.", "hint"))

        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(12)
        box.addLayout(self.cards_grid)
        self._cards: list[QFrame] = []
        self._state_widgets = []
        self._state_rows = None
        self._columns = 0
        self.set_state_rows(STATE_ROWS)
        box.addStretch(1)

    def set_state_rows(self, groups) -> None:
        """Rebuild the machine-state cards (printers and lasers show different values)."""
        if groups is self._state_rows:
            return
        self._state_rows = groups
        for card in self._cards:
            self.cards_grid.removeWidget(card)
            card.deleteLater()
        self._cards, self._state_widgets = [], []
        for group_title, rows in groups:
            card = QFrame()
            card.setObjectName("stateCard")
            card_box = QVBoxLayout(card)
            card_box.setContentsMargins(12, 10, 12, 10)
            card_box.setSpacing(2)
            card_box.addWidget(_label(group_title, "stateHeading"))
            for label, field_names, fmt, tip in rows:
                row = QFrame()
                row.setObjectName("stateRow")
                row.setToolTip(tip)
                row_box = QHBoxLayout(row)
                row_box.setContentsMargins(6, 3, 6, 3)
                row_box.addWidget(_label(label, "stateLabel", wrap=False), 1)
                value = _label(name="stateValue", wrap=False)
                value.setAlignment(Qt.AlignmentFlag.AlignRight)
                row_box.addWidget(value)
                card_box.addWidget(row)
                self._state_widgets.append((row, value, field_names, fmt))
            card_box.addStretch(1)
            self._cards.append(card)
        columns, self._columns = self._columns or 2, 0
        self._layout_cards(columns)

    # layout ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_cards(2 if self.viewport().width() >= 560 else 1)

    def _layout_cards(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for card in self._cards:
            self.cards_grid.removeWidget(card)
        for i, card in enumerate(self._cards):
            self.cards_grid.addWidget(card, i // columns, i % columns)

    def _toggle_details(self, shown: bool) -> None:
        self.details_label.setVisible(shown)
        self.details_button.setArrowType(Qt.ArrowType.DownArrow if shown
                                         else Qt.ArrowType.RightArrow)

    # content -------------------------------------------------------------------

    def show_explanation(self, line_no: int, raw: str, exp: Explanation,
                         after: MachineState, changed: set[str]) -> None:
        self.line_label.setText(f"LINE {line_no:,}")
        self.raw_label.setText(raw.strip() or "(empty line)")
        self.title.setText(exp.title)

        badge = source_badge(exp)
        self.badge.setVisible(badge is not None)
        if badge:
            self.badge.setText(badge.text)
            self.badge.setToolTip(badge.tooltip or "")
            self.badge.setProperty("kind", badge.kind)
            _repolish(self.badge)

        self.sentence.setText(exp.sentence)
        note = file_note(exp)
        self.file_note.setVisible(note is not None)
        self.file_note.setText(note or "")

        for widget in self._param_widgets:
            self.params_box.removeWidget(widget)
            widget.deleteLater()
        self._param_widgets = []
        for title, meaning in param_rows(exp):
            row = QFrame()
            row.setObjectName("paramRow")
            row_box = QVBoxLayout(row)
            row_box.setContentsMargins(12, 8, 12, 8)
            row_box.setSpacing(2)
            name = _label(title, selectable=True)
            name.setFont(self._mono)
            row_box.addWidget(name)
            row_box.addWidget(_label(meaning, "paramMeaning"))
            self.params_box.addWidget(row)
            self._param_widgets.append(row)
        self.params_title.setVisible(bool(self._param_widgets))

        label, body = details(exp)
        self.details_button.setText(label)
        self.details_label.setText(body)
        self.details_button.setVisible(bool(body))
        self.details_label.setVisible(bool(body) and self.details_button.isChecked())

        for row, value, field_names, fmt in self._state_widgets:
            value.setText(fmt(after))
            is_changed = bool(changed.intersection(field_names))
            if row.property("changed") != is_changed:
                row.setProperty("changed", is_changed)
                _repolish(row)
