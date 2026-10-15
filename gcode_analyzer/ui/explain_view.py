"""Right-hand pane: explanation of the current line plus the machine state."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango  # noqa: E402

from ..explain import Explanation  # noqa: E402
from ..reference import num  # noqa: E402
from ..state import MachineState  # noqa: E402


def _speed(s: MachineState) -> str:
    return f"{num(s.feed / 60, digits=1)} mm/s" if s.feed else "—"


def _temp(value: float | None) -> str:
    if value is None:
        return "—"
    return "off" if value == 0 else f"{num(value)} °C"


def _pct(value: int | None) -> str:
    return "—" if value is None else ("off" if value == 0 else f"{value}%")


def _pos(s: MachineState, axis: str) -> str:
    value = getattr(s, axis)
    if value is None:
        return "unknown (homed)" if s.homed else "unknown"
    return num(value, s.units)


# (group title, [(label, fields that drive it, formatter, beginner tooltip)])
STATE_ROWS = [
    ("Position", [
        ("X (left ↔ right)", ["x"], lambda s: _pos(s, "x"), "Where the nozzle is left/right."),
        ("Y (front ↔ back)", ["y"], lambda s: _pos(s, "y"), "Where the nozzle is front/back."),
        ("Z (height)", ["z"], lambda s: _pos(s, "z"), "How far the nozzle is above the bed."),
        ("Filament counter (E)", ["e"], lambda s: num(s.e, "mm") if s.e is not None else "—",
         "Running total of filament pushed since the last reset (G92 E0)."),
    ]),
    ("Motion", [
        ("Speed", ["feed"], _speed, "The speed used for moves (set by F)."),
        ("Acceleration", ["acceleration"],
         lambda s: num(s.acceleration, "mm/s²") if s.acceleration else "—",
         "How quickly the printer speeds up and slows down (M204)."),
        ("Speed multiplier", ["speed_factor"], lambda s: _pct(s.speed_factor),
         "A % applied to all speeds (M220). 100% is normal."),
        ("Flow multiplier", ["flow_factor"], lambda s: _pct(s.flow_factor),
         "A % applied to all extrusion (M221). 100% is normal."),
    ]),
    ("Heat", [
        ("Nozzle target", ["hotend_target"], lambda s: _temp(s.hotend_target),
         "The temperature the nozzle is heating to."),
        ("Bed target", ["bed_target"], lambda s: _temp(s.bed_target),
         "The temperature the bed is heating to."),
        ("Chamber target", ["chamber_target"], lambda s: _temp(s.chamber_target),
         "Enclosure air temperature (only some printers)."),
    ]),
    ("Fans", [
        ("Part cooling", ["part_fan"], lambda s: _pct(s.part_fan),
         "The fan on the toolhead that cools freshly printed plastic."),
        ("Auxiliary (side)", ["aux_fan"], lambda s: _pct(s.aux_fan),
         "The big side fan that blows across the bed."),
        ("Chamber (exhaust)", ["chamber_fan"], lambda s: _pct(s.chamber_fan),
         "The fan that moves air out of the enclosure."),
    ]),
    ("Print", [
        ("Layer", ["layer", "total_layers"],
         lambda s: "—" if s.layer is None else
         (f"{s.layer} of {s.total_layers}" if s.total_layers else str(s.layer)),
         "Which layer is printing."),
        ("Layer top", ["z_height"], lambda s: num(s.z_height, "mm") if s.z_height else "—",
         "Height of this layer's top surface (from slicer notes)."),
        ("Printing", ["feature"], lambda s: s.feature or "—",
         "Which part of the model is printing — wall, infill, support…"),
        ("Filament", ["filament"],
         lambda s: "—" if s.filament is None else f"T{s.filament} (AMS slot {s.filament + 1})",
         "Which filament is loaded (T command)."),
        ("Progress", ["progress", "remaining_min"],
         lambda s: "—" if s.progress is None else
         f"{s.progress}%" + (f", {s.remaining_min} min left" if s.remaining_min is not None else ""),
         "What the printer's screen would show (M73)."),
    ]),
    ("Modes", [
        ("Coordinates", ["positioning"], lambda s: s.positioning,
         "absolute: numbers are positions (G90). relative: numbers are distances (G91)."),
        ("Extrusion", ["extrusion"], lambda s: s.extrusion,
         "absolute: E is a running total (M82). relative: E is per move (M83)."),
        ("Units", ["units"], lambda s: s.units, "Millimetres (G21) or inches (G20)."),
        ("Homed", ["homed"], lambda s: "yes" if s.homed else "not yet",
         "Whether the printer has found its reference position (G28)."),
    ]),
]


class ExplainView(Gtk.ScrolledWindow):
    def __init__(self):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.set_size_request(380, -1)
        clamp = Adw.Clamp(maximum_size=720, tightening_threshold=500)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      margin_top=18, margin_bottom=24, margin_start=18, margin_end=18)
        clamp.set_child(box)
        self.set_child(clamp)

        self.line_label = Gtk.Label(xalign=0, css_classes=["dim-label", "caption-heading"])
        self.raw_label = Gtk.Label(xalign=0, wrap=True, selectable=True,
                                   wrap_mode=Pango.WrapMode.WORD_CHAR,
                                   css_classes=["monospace", "raw-line"])
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header.append(self.line_label)
        header.append(self.raw_label)
        box.append(header)

        title_row = Gtk.Box(spacing=10)
        self.title = Gtk.Label(xalign=0, wrap=True, hexpand=True, css_classes=["title-2"])
        self.source_pill = Gtk.Label(valign=Gtk.Align.CENTER, css_classes=["pill"])
        title_row.append(self.title)
        title_row.append(self.source_pill)
        box.append(title_row)

        self.sentence = Gtk.Label(xalign=0, wrap=True, selectable=True,
                                  css_classes=["sentence"])
        box.append(self.sentence)

        self.comment_label = Gtk.Label(xalign=0, wrap=True, css_classes=["file-note"])
        box.append(self.comment_label)

        self.params_group = Adw.PreferencesGroup(title="What each part means")
        self._param_rows: list[Adw.ActionRow] = []
        box.append(self.params_group)

        self.details_expander = Gtk.Expander(label="More background")
        self.details_label = Gtk.Label(xalign=0, wrap=True, selectable=True,
                                       margin_top=8, css_classes=["details"])
        self.details_expander.set_child(self.details_label)
        box.append(self.details_expander)

        box.append(Gtk.Separator(margin_top=6))
        state_title = Gtk.Label(label="Machine state after this line", xalign=0,
                                css_classes=["title-4"])
        state_hint = Gtk.Label(
            label="Highlighted values were changed by this line. Hover a name for help.",
            xalign=0, wrap=True, css_classes=["dim-label", "caption"])
        box.append(state_title)
        box.append(state_hint)

        self._state_widgets = []
        grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2,
                           min_children_per_line=1, column_spacing=12, row_spacing=12,
                           homogeneous=True)
        for group_title, rows in STATE_ROWS:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                           css_classes=["card", "state-card"])
            card.append(Gtk.Label(label=group_title, xalign=0,
                                  css_classes=["heading", "state-heading"]))
            for label, field_names, fmt, tip in rows:
                row = Gtk.Box(spacing=8, css_classes=["state-row"], tooltip_text=tip)
                row.append(Gtk.Label(label=label, xalign=0, hexpand=True,
                                     css_classes=["dim-label"]))
                value = Gtk.Label(xalign=1, css_classes=["numeric", "state-value"],
                                  ellipsize=Pango.EllipsizeMode.END, max_width_chars=22)
                row.append(value)
                card.append(row)
                self._state_widgets.append((row, value, field_names, fmt))
            grid.append(card)
        box.append(grid)

    def show(self, line_no: int, raw: str, exp: Explanation,
             after: MachineState, changed: set[str]) -> None:
        self.line_label.set_label(f"LINE {line_no:,}")
        self.raw_label.set_label(raw.strip() or "(empty line)")
        self.title.set_label(exp.title)

        pill = {"documented": ("Standard G-code", "pill-standard"),
                "community": ("Bambu-specific · community knowledge", "pill-community")}
        kind_pill = {"comment": ("Note — not a command", "pill-note"),
                     "blank": ("Not a command", "pill-note"),
                     "unknown": ("Unknown", "pill-unknown")}
        text, css = pill.get(exp.source) or kind_pill.get(exp.kind, ("", ""))
        self.source_pill.set_label(text)
        self.source_pill.set_css_classes(["pill", css])
        self.source_pill.set_visible(bool(text))
        self.source_pill.set_tooltip_text(
            "Bambu doesn't publish documentation for its own commands. This explanation "
            "comes from Bambu's comments in its G-code and community research."
            if exp.source == "community" else None)

        self.sentence.set_label(exp.sentence)
        show_comment = exp.kind in ("command", "unknown") and bool(exp.comment)
        self.comment_label.set_visible(show_comment)
        if show_comment:
            self.comment_label.set_label(f"Note written in the file: “{exp.comment}”")

        for row in self._param_rows:
            self.params_group.remove(row)
        self._param_rows = []
        for p in exp.params:
            title = f"{p.letter} = {p.value}" if p.letter else p.value
            if p.letter and not p.value:
                title = f"{p.letter} (no value)"
            row = Adw.ActionRow(title=title, subtitle=p.meaning or "No description available",
                                title_selectable=True)
            row.add_css_class("monospace-title")
            self.params_group.add(row)
            self._param_rows.append(row)
        self.params_group.set_visible(bool(exp.params))

        body = exp.details or ""
        if exp.summary and exp.summary not in exp.sentence:
            body = f"{exp.summary}\n\n{body}".strip()
        self.details_label.set_label(body)
        self.details_expander.set_visible(bool(body))
        code = exp.title.split(" — ")[0]
        self.details_expander.set_label(f"More about {code}" if exp.kind == "command"
                                        else "More background")

        for row, value, field_names, fmt in self._state_widgets:
            value.set_label(fmt(after))
            if changed.intersection(field_names):
                row.add_css_class("changed")
            else:
                row.remove_css_class("changed")
