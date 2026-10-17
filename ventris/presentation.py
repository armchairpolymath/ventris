"""What the right-hand pane shows, independent of any GUI toolkit.

The Qt window only lays these out; the wording and logic live here so they can be
tested without a display.
"""

from __future__ import annotations

from dataclasses import dataclass

from .explain import Explanation
from .reference import num
from .state import MachineState


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
         lambda s: "—" if s.filament is None else f"T{s.filament} (slot {s.filament + 1})",
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


LASER_STATE_ROWS = [
    ("Laser head", [
        ("X", ["x"], lambda s: "—" if s.x is None else num(s.x, "mm"),
         "Left/right position of the laser head, measured from the job origin."),
        ("Y", ["y"], lambda s: "—" if s.y is None else num(s.y, "mm"),
         "Front/back position of the laser head, measured from the job origin."),
        ("Beam", ["laser"], lambda s: {"on": "on — cutting", "off": "off — travelling"}
         .get(s.laser, "—"), "Whether the laser is firing during this move."),
    ]),
    ("Settings", [
        ("Speed", ["feed"], _speed, "How fast the head moves while cutting."),
        ("Min power", ["power_min"], lambda s: _pct_float(s.power_min),
         "Power used when the head slows down (corners)."),
        ("Max power", ["power_max"], lambda s: _pct_float(s.power_max),
         "Power used at full speed."),
        ("Air assist", ["air_assist"],
         lambda s: "—" if s.air_assist is None else ("on" if s.air_assist else "off"),
         "A jet of air at the cut that keeps flames down and clears smoke."),
        ("Layer", ["layer"], lambda s: "—" if s.layer is None else str(s.layer),
         "Which layer (color in the design software) is being cut."),
    ]),
]


def _pct_float(value: float | None) -> str:
    return "—" if value is None else f"{num(value)}%"


def state_rows(kind: str):
    """Machine-state panel layout for a profile kind ("printer" or "laser")."""
    return LASER_STATE_ROWS if kind == "laser" else STATE_ROWS


@dataclass
class Badge:
    text: str
    kind: str  # "standard", "community", "note", "unknown"
    tooltip: str | None = None


def source_badge(exp: Explanation) -> Badge | None:
    vendor = exp.vendor or "Machine"
    if exp.source == "documented":
        return Badge("Standard G-code", "standard")
    if exp.source == "vendor":
        return Badge(f"{vendor}-specific · documented by {vendor}", "standard",
                     f"Based on {vendor}'s published G-code documentation and the "
                     f"comments {vendor} writes in its slicer profiles.")
    if exp.source == "community":
        return Badge(f"{vendor}-specific · community knowledge", "community",
                     f"{vendor} doesn't publish documentation for this command. The "
                     f"explanation comes from {vendor}'s own comments in its G-code "
                     "and community research.")
    if exp.kind == "comment":
        return Badge("Note — not a command", "note")
    if exp.kind == "blank":
        return Badge("Not a command", "note")
    if exp.kind == "unknown":
        return Badge("Unknown", "unknown")
    return None


def file_note(exp: Explanation) -> str | None:
    """A comment written after a command on the same line."""
    if exp.kind in ("command", "unknown") and exp.comment:
        if exp.comment.startswith("bytes:"):
            return f"Raw bytes in the file: {exp.comment[6:].strip()}"
        return f"Note written in the file: “{exp.comment}”"
    return None


def param_rows(exp: Explanation) -> list[tuple[str, str]]:
    rows = []
    for p in exp.params:
        title = f"{p.letter} = {p.value}" if p.letter else p.value
        if p.letter and not p.value:
            title = f"{p.letter} (no value)"
        rows.append((title, p.meaning or "No description available"))
    return rows


def details(exp: Explanation) -> tuple[str, str]:
    """(expander label, body); body is empty when there is nothing more to say."""
    body = exp.details or ""
    if exp.summary and exp.summary not in exp.sentence:
        body = f"{exp.summary}\n\n{body}".strip()
    code = exp.title.split(" — ")[0]
    label = f"More about {code}" if exp.kind == "command" else "More background"
    return label, body
