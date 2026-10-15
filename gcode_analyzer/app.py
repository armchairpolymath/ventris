"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .ui.window import UI_DIR, MainWindow  # noqa: E402

APP_ID = "com.patrickhoskins.GcodeAnalyzer"


class GcodeAnalyzerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_path(str(UI_DIR / "style.css"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        self._window().present()

    def do_open(self, files, n_files, hint):
        window = self._window()
        window.present()
        if files:
            window.open_path(Path(files[0].get_path()))

    def _window(self) -> MainWindow:
        return self.get_active_window() or MainWindow(self)


def main() -> int:
    return GcodeAnalyzerApp().run(sys.argv)
