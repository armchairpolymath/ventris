"""Main window: G-code editor on the left, explanation on the right."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIntValidator, QKeySequence
from PySide6.QtWidgets import (QComboBox, QFileDialog, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPushButton, QSizePolicy, QSplitter,
                               QStackedWidget, QToolBar, QVBoxLayout, QWidget)

from .. import APP_NAME, SOURCE_URL, __version__, fileio
from ..dialects import detect_profile, profiles
from ..explain import explain
from ..parser import parse_line
from ..state import StateTracker
from . import theme
from .editor import CodeEditor
from .explain_view import ExplainView

FILE_FILTER = ("G-code files (*.gcode *.gco *.g *.nc *.3mf *.bgcode);;"
               "Plain G-code (*.gcode);;All files (*)")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.document: fileio.Document | None = None
        self.profiles = profiles()
        self.profile = self.profiles[0]
        self.tracker = StateTracker([])
        self._loading = False
        self._first_changed: int | None = None

        self._cursor_timer = self._single_shot(40, self._refresh_explanation)
        self._edit_timer = self._single_shot(250, self._apply_edits)
        self._build_timer = QTimer(self)
        self._build_timer.setInterval(0)
        self._build_timer.timeout.connect(self._build_step)

        self.resize(1400, 850)
        self.setAcceptDrops(True)
        self._build_ui()
        self._build_actions()
        self.apply_theme()
        self._update_title()

    def _single_shot(self, ms: int, slot) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(ms)
        timer.timeout.connect(slot)
        return timer

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.editor = CodeEditor()
        self.editor.cursorPositionChanged.connect(self._on_cursor_moved)
        self.editor.document().contentsChange.connect(self._on_contents_change)
        self.editor.document().modificationChanged.connect(self._on_modified)

        self.explain_view = ExplainView()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.explain_view)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([620, 780])

        empty = QWidget()
        empty_box = QVBoxLayout(empty)
        empty_box.addStretch(1)
        for text, name in [("Open a G-code file", "emptyTitle"),
                           ("Choose a .gcode, Bambu .gcode.3mf or Prusa .bgcode file — or "
                            "drop one here. Click any line to see what it does.", "emptyText")]:
            label = QLabel(text)
            label.setObjectName(name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            empty_box.addWidget(label)
        open_button = QPushButton("Open File…")
        open_button.setDefault(True)
        open_button.clicked.connect(self.choose_file)
        empty_box.addWidget(open_button, 0, Qt.AlignmentFlag.AlignCenter)
        empty_box.addStretch(1)

        self.stack = QStackedWidget()
        self.stack.addWidget(empty)
        self.stack.addWidget(splitter)
        self.setCentralWidget(self.stack)

        self.status_info = QLabel()
        self.statusBar().addPermanentWidget(self.status_info)

    def _build_actions(self) -> None:
        self.open_action = QAction("&Open…", self, shortcut=QKeySequence.StandardKey.Open,
                                   triggered=self.choose_file)
        self.save_action = QAction("&Save", self, shortcut=QKeySequence.StandardKey.Save,
                                   triggered=self.save)
        self.save_as_action = QAction("Save &As…", self,
                                      shortcut=QKeySequence.StandardKey.SaveAs,
                                      triggered=self.save_as)
        quit_action = QAction("&Quit", self, shortcut=QKeySequence.StandardKey.Quit,
                              triggered=self.close)
        about_action = QAction(f"&About {APP_NAME}", self, triggered=self.show_about)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        goto_action = QAction("&Go to Line…", self, shortcut=QKeySequence("Ctrl+L"),
                              triggered=lambda: (self.goto_entry.setFocus(),
                                                 self.goto_entry.selectAll()))
        file_menu = self.menuBar().addMenu("&File")
        for action in (self.open_action, self.save_action, self.save_as_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)
        self.menuBar().addMenu("&Go").addAction(goto_action)
        self.menuBar().addMenu("&Help").addAction(about_action)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.addAction(self.open_action)
        self.goto_entry = QLineEdit()
        self.goto_entry.setPlaceholderText("Go to line…")
        self.goto_entry.setValidator(QIntValidator(1, 10**9, self))
        self.goto_entry.setFixedWidth(120)
        self.goto_entry.setToolTip("Jump to a line number (Ctrl+L)")
        self.goto_entry.returnPressed.connect(self._on_goto)
        toolbar.addWidget(self.goto_entry)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addWidget(QLabel("Machine: "))
        self.profile_combo = QComboBox()
        self.profile_combo.addItems([p.name for p in self.profiles])
        self.profile_combo.setToolTip("Which machine this G-code is for")
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        toolbar.addWidget(self.profile_combo)
        toolbar.addAction(self.save_action)
        self.addToolBar(toolbar)

    def apply_theme(self) -> None:
        dark = theme.is_dark()
        self.setStyleSheet(theme.stylesheet(dark))
        self.editor.refresh_theme()

    # ------------------------------------------------------------------ files

    def choose_file(self) -> None:
        if not self._confirm_discard():
            return
        start = str(self.document.path.parent) if self.document else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open G-code", start, FILE_FILTER)
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path) -> None:
        try:
            doc = fileio.load(path)
        except (OSError, fileio.FileFormatError) as exc:
            QMessageBox.warning(self, "Couldn't open file", str(exc))
            return
        self.document = doc
        self._loading = True
        self.editor.setPlainText(doc.text)  # also clears undo history
        self.editor.document().setModified(False)
        self._loading = False
        self._first_changed = None
        self._edit_timer.stop()

        # Load the tracker before changing the profile, which refreshes the pane.
        self._reset_tracker()
        detected = detect_profile(doc.text[:20000])
        self.profile = detected
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(self.profiles.index(detected))
        self.profile_combo.blockSignals(False)

        self.stack.setCurrentIndex(1)
        self.editor.go_to_line(0)
        self._update_title()
        self._refresh_explanation()
        if doc.is_3mf:
            self.statusBar().showMessage(f"Opened {doc.inner_name} from the 3MF archive", 4000)
        elif doc.is_bgcode:
            self.statusBar().showMessage(
                "Opened Prusa binary G-code — edits are saved as plain .gcode", 6000)

    def save(self) -> bool:
        if not self.document:
            return False
        if self.document.is_bgcode:
            self.statusBar().showMessage(
                "Binary G-code can't be written back — choose a .gcode file name", 6000)
            return self.save_as()
        return self._save_to(self.document.path)

    def save_as(self) -> bool:
        if not self.document:
            return False
        path = self.document.path
        suggested = path.with_suffix(".gcode") if self.document.is_bgcode else path
        target, _ = QFileDialog.getSaveFileName(self, "Save G-code As", str(suggested),
                                                FILE_FILTER)
        return bool(target) and self._save_to(Path(target))

    def _save_to(self, path: Path) -> bool:
        try:
            fileio.save(self.document, self.editor.toPlainText(), path)
        except (OSError, fileio.FileFormatError) as exc:
            QMessageBox.warning(self, "Couldn't save file", str(exc))
            return False
        if self.document.is_bgcode or (self.document.is_3mf and not fileio.is_3mf(path)):
            # keep editing the new plain-text copy from now on
            self.document = fileio.Document(path, "", None)
        else:
            self.document.path = path
        self.editor.document().setModified(False)
        self._update_title()
        extra = " (checksum updated)" if self.document.is_3mf else ""
        self.statusBar().showMessage(f"Saved {path.name}{extra}", 4000)
        return True

    def _confirm_discard(self) -> bool:
        """True if it is fine to drop the current text (saved, discarded, or clean)."""
        if not self.isWindowModified():
            return True
        answer = QMessageBox.question(
            self, "Save changes?", "This file has edits that haven't been saved.",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = [u for u in event.mimeData().urls() if u.isLocalFile()]
        if urls and self._confirm_discard():
            self.open_path(Path(urls[0].toLocalFile()))

    # ------------------------------------------------------------------ editing

    def _on_modified(self, modified: bool) -> None:
        self.setWindowModified(modified)

    def _on_contents_change(self, position: int, removed: int, added: int) -> None:
        if self._loading or self.document is None:
            return
        line = self.editor.document().findBlock(position).blockNumber()
        if self._first_changed is None or line < self._first_changed:
            self._first_changed = line
        self._edit_timer.start()

    def _apply_edits(self) -> None:
        first = self._first_changed or 0
        self._first_changed = None
        self.tracker.update_lines(self.editor.toPlainText().split("\n"), first)
        self._build_timer.start()
        self._update_title()
        self._refresh_explanation()

    def _reset_tracker(self) -> None:
        self.tracker = StateTracker(self.editor.toPlainText().split("\n"))
        self._build_timer.start()

    def _build_step(self) -> None:
        if not self.tracker.build_step():
            self._build_timer.stop()

    # ------------------------------------------------------------------ explanation

    def _on_cursor_moved(self) -> None:
        if not self._loading and not self._cursor_timer.isActive():
            self._cursor_timer.start()

    def _refresh_explanation(self) -> None:
        if self.document is None or self._edit_timer.isActive():
            return  # edits pending; _apply_edits refreshes when they land
        block = self.editor.textCursor().block()
        index = block.blockNumber()
        raw = block.text()
        before, after = self.tracker.states_around(index)
        changed = StateTracker.changed_fields(before, after)
        exp = explain(parse_line(raw), before, after, self.profile)
        self.explain_view.show_explanation(index + 1, raw, exp, after, changed)

    def _on_profile_changed(self, index: int) -> None:
        self.profile = self.profiles[index]
        self._update_title()
        self._refresh_explanation()

    def _on_goto(self) -> None:
        text = self.goto_entry.text().strip()
        if text.isdigit():
            self.editor.go_to_line(int(text) - 1)
        self.goto_entry.clear()

    # ------------------------------------------------------------------ helpers

    def show_about(self) -> None:
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Explains G-code line by line, for Bambu Lab and Prusa 3D printers.</p>"
            "<p>Copyright © 2026 Patrick Hoskins.<br>"
            "Licensed under the GNU Affero General Public License v3.0. This program "
            "comes with ABSOLUTELY NO WARRANTY.</p>"
            f'<p>Source code: <a href="{SOURCE_URL}">{SOURCE_URL}</a></p>'
            "<p>Binary G-code support is adapted from Prusa Research's libbgcode "
            "(AGPL-3.0).</p>")

    def _update_title(self) -> None:
        if not self.document:
            self.setWindowTitle(f"{APP_NAME}[*]")
            self.status_info.setText("")
            return
        name = self.document.path.name
        if self.document.is_3mf:
            name += f" › {Path(self.document.inner_name).name}"
        self.setWindowTitle(f"{name}[*] — {APP_NAME}")
        self.status_info.setText(
            f"{self.editor.blockCount():,} lines · {self.profile.name}")
