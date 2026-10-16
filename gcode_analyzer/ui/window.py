"""Main window: G-code editor on the left, explanation on the right."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
from gi.repository import Adw, Gio, GLib, Gtk, GtkSource  # noqa: E402

from .. import fileio  # noqa: E402
from ..dialects import detect_profile, profiles  # noqa: E402
from ..explain import explain  # noqa: E402
from ..parser import parse_line  # noqa: E402
from ..state import StateTracker  # noqa: E402
from .explain_view import ExplainView  # noqa: E402

UI_DIR = Path(__file__).parent


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, default_width=1400, default_height=850,
                         title="G-code Analyzer")
        self.document: fileio.Document | None = None
        self.profiles = profiles()
        self.profile = self.profiles[0]
        self.tracker = StateTracker([])
        self.dirty = False
        self._loading = False
        self._first_changed: int | None = None
        self._cursor_timeout = 0
        self._edit_timeout = 0
        self._build_idle = 0

        self._build_ui()
        self._install_actions(app)
        self.connect("close-request", self._on_close_request)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        header = Adw.HeaderBar()
        self.window_title = Adw.WindowTitle(title="G-code Analyzer", subtitle="")
        header.set_title_widget(self.window_title)

        open_btn = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Open (Ctrl+O)",
                              action_name="win.open")
        header.pack_start(open_btn)

        save_btn = Adw.SplitButton(label="Save", action_name="win.save",
                                   tooltip_text="Save (Ctrl+S)")
        menu = Gio.Menu()
        menu.append("Save As…", "win.save-as")
        save_btn.set_menu_model(menu)
        header.pack_end(save_btn)

        names = Gtk.StringList.new([p.name for p in self.profiles])
        self.profile_dropdown = Gtk.DropDown(model=names,
                                             tooltip_text="Which machine this G-code is for")
        self.profile_dropdown.connect("notify::selected", self._on_profile_changed)
        header.pack_end(self.profile_dropdown)

        self.goto_entry = Gtk.Entry(placeholder_text="Go to line…", width_chars=11,
                                    input_purpose=Gtk.InputPurpose.DIGITS,
                                    tooltip_text="Jump to a line number (Ctrl+L)")
        self.goto_entry.connect("activate", self._on_goto)
        header.pack_start(self.goto_entry)

        # editor
        lang_manager = GtkSource.LanguageManager.get_default()
        lang_manager.append_search_path(str(UI_DIR))
        self.buffer = GtkSource.Buffer(language=lang_manager.get_language("gcode"))
        self._apply_scheme()
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self._apply_scheme())
        self.view = GtkSource.View(buffer=self.buffer, monospace=True, show_line_numbers=True,
                                   highlight_current_line=True, left_margin=6, top_margin=6)
        self.buffer.connect("notify::cursor-position", self._on_cursor_moved)
        self.buffer.connect("insert-text", self._on_insert_text)
        self.buffer.connect("delete-range", self._on_delete_range)
        self.buffer.connect("changed", self._on_buffer_changed)
        editor_scroll = Gtk.ScrolledWindow(child=self.view, hexpand=True, vexpand=True)

        self.explain_view = ExplainView()

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=620,
                          start_child=editor_scroll, end_child=self.explain_view,
                          shrink_start_child=False, shrink_end_child=False)

        empty = Adw.StatusPage(
            icon_name="document-open-symbolic", title="Open a G-code file",
            description="Choose a .gcode or Bambu .gcode.3mf file. Click any line to "
                        "see what it does.")
        open_big = Gtk.Button(label="Open File…", action_name="win.open",
                              halign=Gtk.Align.CENTER,
                              css_classes=["pill", "suggested-action"])
        empty.set_child(open_big)

        self.stack = Gtk.Stack()
        self.stack.add_named(empty, "empty")
        self.stack.add_named(paned, "editor")

        self.toasts = Adw.ToastOverlay(child=self.stack)
        toolbar = Adw.ToolbarView(content=self.toasts)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)

    def _apply_scheme(self) -> None:
        schemes = GtkSource.StyleSchemeManager.get_default()
        dark = Adw.StyleManager.get_default().get_dark()
        scheme = schemes.get_scheme("Adwaita-dark" if dark else "Adwaita")
        if scheme:
            self.buffer.set_style_scheme(scheme)

    def _install_actions(self, app: Adw.Application) -> None:
        for name, callback, accel in [
            ("open", lambda *_: self.choose_file(), "<Control>o"),
            ("save", lambda *_: self.save(), "<Control>s"),
            ("save-as", lambda *_: self.save_as(), "<Control><Shift>s"),
            ("goto", lambda *_: self.goto_entry.grab_focus(), "<Control>l"),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            app.set_accels_for_action(f"win.{name}", [accel])

    # ------------------------------------------------------------------ files

    def choose_file(self) -> None:
        self._confirm_discard(self._show_open_dialog)

    def _show_open_dialog(self) -> None:
        dialog = Gtk.FileDialog(title="Open G-code")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        gfilter = Gtk.FileFilter(name="G-code, Bambu 3MF and Prusa binary G-code")
        for pattern in ("*.gcode", "*.gco", "*.g", "*.nc", "*.3mf", "*.bgcode"):
            gfilter.add_pattern(pattern)
        filters.append(gfilter)
        all_files = Gtk.FileFilter(name="All files")
        all_files.add_pattern("*")
        filters.append(all_files)
        dialog.set_filters(filters)

        def done(dlg, result):
            try:
                gfile = dlg.open_finish(result)
            except GLib.Error:
                return  # cancelled
            self.open_path(Path(gfile.get_path()))
        dialog.open(self, None, done)

    def open_path(self, path: Path) -> None:
        try:
            doc = fileio.load(path)
        except (OSError, fileio.FileFormatError) as exc:
            self._error("Couldn't open file", str(exc))
            return
        self.document = doc
        self._loading = True
        self.buffer.begin_irreversible_action()
        self.buffer.set_text(doc.text)
        self.buffer.end_irreversible_action()
        self._loading = False
        self.dirty = False

        # The tracker must hold the new lines before the dropdown change below
        # triggers a refresh of the explanation pane.
        self._reset_tracker()
        detected = detect_profile(doc.text[:20000])
        self.profile = detected
        self.profile_dropdown.set_selected(self.profiles.index(detected))
        self.stack.set_visible_child_name("editor")
        self._update_title()
        self.buffer.place_cursor(self.buffer.get_start_iter())
        self.view.grab_focus()
        self._refresh_explanation()
        if doc.is_3mf:
            self._toast(f"Opened {doc.inner_name} from the 3MF archive")
        elif doc.is_bgcode:
            self._toast("Opened Prusa binary G-code — edits are saved as plain .gcode")

    def save(self) -> None:
        if not self.document:
            return
        if self.document.is_bgcode:
            self._toast("Binary G-code can't be written back — choose a .gcode file name")
            self.save_as()
            return
        self._save_to(self.document.path)

    def save_as(self) -> None:
        if not self.document:
            return
        name = self.document.path.name
        if self.document.is_bgcode:
            name = self.document.path.stem + ".gcode"
        dialog = Gtk.FileDialog(title="Save G-code As", initial_name=name)

        def done(dlg, result):
            try:
                gfile = dlg.save_finish(result)
            except GLib.Error:
                return
            self._save_to(Path(gfile.get_path()))
        dialog.save(self, None, done)

    def _save_to(self, path: Path) -> bool:
        try:
            fileio.save(self.document, self._buffer_text(), path)
        except (OSError, fileio.FileFormatError) as exc:
            self._error("Couldn't save file", str(exc))
            return False
        if self.document.is_bgcode:
            # keep editing the new plain-text copy from now on
            self.document = fileio.Document(path, "", None)
        elif fileio.is_3mf(path) or not self.document.is_3mf:
            self.document.path = path
        else:
            # saved a 3mf's G-code out as plain .gcode: keep editing the new file
            self.document = fileio.Document(path, "", None)
        self.dirty = False
        self._update_title()
        extra = " (checksum updated)" if self.document.is_3mf else ""
        self._toast(f"Saved {path.name}{extra}")
        return True

    def _confirm_discard(self, then) -> None:
        if not self.dirty:
            then()
            return
        dialog = Adw.AlertDialog(heading="Save changes?",
                                 body="This file has edits that haven't been saved.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("discard", "Discard")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")

        def responded(dlg, response):
            if response == "save" and self.document.is_bgcode:
                self.save_as()  # needs a new .gcode name; the user retries afterwards
            elif response == "save" and self._save_to(self.document.path):
                then()
            elif response == "discard":
                self.dirty = False
                then()
        dialog.connect("response", responded)
        dialog.present(self)

    def _on_close_request(self, *_):
        if not self.dirty:
            return False
        self._confirm_discard(self.destroy)
        return True

    # ------------------------------------------------------------------ editing

    def _buffer_text(self) -> str:
        start, end = self.buffer.get_bounds()
        return self.buffer.get_text(start, end, True)

    def _mark_changed_line(self, line: int) -> None:
        if self._first_changed is None or line < self._first_changed:
            self._first_changed = line

    def _on_insert_text(self, buffer, location, text, length):
        if not self._loading:
            self._mark_changed_line(location.get_line())

    def _on_delete_range(self, buffer, start, end):
        if not self._loading:
            self._mark_changed_line(start.get_line())

    def _on_buffer_changed(self, *_):
        if self._loading:
            return
        if not self.dirty:
            self.dirty = True
            self._update_title()
        if self._edit_timeout:
            GLib.source_remove(self._edit_timeout)
        self._edit_timeout = GLib.timeout_add(250, self._apply_edits)

    def _apply_edits(self) -> bool:
        self._edit_timeout = 0
        first = self._first_changed or 0
        self._first_changed = None
        self.tracker.update_lines(self._buffer_text().split("\n"), first)
        self._start_background_build()
        self._update_title()
        self._refresh_explanation()
        return GLib.SOURCE_REMOVE

    def _reset_tracker(self) -> None:
        self.tracker = StateTracker(self._buffer_text().split("\n"))
        self._start_background_build()

    def _start_background_build(self) -> None:
        if self._build_idle:
            GLib.source_remove(self._build_idle)

        def step() -> bool:
            if self.tracker.build_step():
                return GLib.SOURCE_CONTINUE
            self._build_idle = 0
            return GLib.SOURCE_REMOVE
        self._build_idle = GLib.idle_add(step, priority=GLib.PRIORITY_LOW)

    # ------------------------------------------------------------------ explanation

    def _on_cursor_moved(self, *_):
        if self._loading or self._cursor_timeout:
            return
        self._cursor_timeout = GLib.timeout_add(40, self._cursor_settled)

    def _cursor_settled(self) -> bool:
        self._cursor_timeout = 0
        self._refresh_explanation()
        return GLib.SOURCE_REMOVE

    def _refresh_explanation(self) -> None:
        if self.document is None or self._edit_timeout:
            return  # edits pending; _apply_edits refreshes when they land
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        index = cursor.get_line()
        start = self.buffer.get_iter_at_line(index)[1]
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        raw = self.buffer.get_text(start, end, True)
        parsed = parse_line(raw)
        before, after = self.tracker.states_around(index)
        changed = StateTracker.changed_fields(before, after)
        exp = explain(parsed, before, after, self.profile)
        self.explain_view.show(index + 1, raw, exp, after, changed)

    def _on_profile_changed(self, dropdown, _param):
        self.profile = self.profiles[dropdown.get_selected()]
        self._update_title()
        self._refresh_explanation()

    def _on_goto(self, entry: Gtk.Entry) -> None:
        text = entry.get_text().strip().replace(",", "")
        if not text.isdigit():
            return
        line = max(0, min(int(text) - 1, self.buffer.get_line_count() - 1))
        it = self.buffer.get_iter_at_line(line)[1]
        self.buffer.place_cursor(it)
        self._scroll_to_cursor()
        entry.set_text("")
        self.view.grab_focus()

    # ------------------------------------------------------------------ helpers

    def _scroll_to_cursor(self) -> None:
        # Wait for layout so the view can compute the target line's position.
        def scroll() -> bool:
            self.view.scroll_to_mark(self.buffer.get_insert(), 0.1, True, 0.0, 0.3)
            return GLib.SOURCE_REMOVE
        GLib.idle_add(scroll, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def _update_title(self) -> None:
        if not self.document:
            return
        name = self.document.path.name
        if self.document.is_3mf:
            name += f" › {Path(self.document.inner_name).name}"
        self.window_title.set_title(("• " if self.dirty else "") + name)
        self.window_title.set_subtitle(
            f"{self.buffer.get_line_count():,} lines · {self.profile.name}")

    def _toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=message, timeout=3))

    def _error(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.present(self)
