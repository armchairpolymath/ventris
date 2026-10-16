"""Application entry point (Qt / PySide6 — runs on Linux, Windows and macOS)."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication

from . import theme
from .window import APP_NAME, MainWindow


class _FileOpenFilter(QObject):
    """macOS sends a FileOpen event when a file is double-clicked or dropped on the Dock."""

    def __init__(self, window: MainWindow):
        super().__init__()
        self.window = window

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            self.window.open_path(Path(event.file()))
            return True
        return False


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("Patrick Hoskins")
    app.setDesktopFileName("com.patrickhoskins.GcodeAnalyzer")

    theme.refresh()
    window = MainWindow()
    file_filter = _FileOpenFilter(window)
    app.installEventFilter(file_filter)

    def recheck_theme(*_):
        if theme.refresh():
            window.apply_theme()
    app.styleHints().colorSchemeChanged.connect(recheck_theme)
    # Linux portal changes don't reach Qt, so re-check whenever the app is focused.
    app.applicationStateChanged.connect(
        lambda state: recheck_theme() if state == Qt.ApplicationState.ApplicationActive else None)
    window.show()

    files = [a for a in app.arguments()[1:] if not a.startswith("-")]
    if files:
        window.open_path(Path(files[0]))
    return app.exec()
