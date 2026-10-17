"""Simulate what the machine knows/does as it runs the file, line by line."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, fields

from .parser import ParsedLine, parse_line

_LAYER_COMMENT = re.compile(r"layer num/total_layer_count:\s*(\d+)\s*/\s*(\d+)", re.I)
_Z_HEIGHT = re.compile(r"Z_HEIGHT:\s*([-\d.]+)", re.I)
_FEATURE = re.compile(r"(?:FEATURE|TYPE):\s*(.+)", re.I)  # Bambu Studio / PrusaSlicer
_PRUSA_Z = re.compile(r"Z:([-\d.]+)$")


@dataclass
class MachineState:
    units: str = "mm"
    positioning: str = "absolute"
    extrusion: str = "absolute"
    homed: bool = False
    x: float | None = None
    y: float | None = None
    z: float | None = None
    e: float | None = None
    feed: float | None = None
    hotend_target: float | None = None
    bed_target: float | None = None
    chamber_target: float | None = None
    part_fan: int | None = None
    aux_fan: int | None = None
    chamber_fan: int | None = None
    layer: int | None = None
    total_layers: int | None = None
    z_height: float | None = None
    feature: str | None = None
    filament: int | None = None
    progress: int | None = None
    remaining_min: int | None = None
    acceleration: float | None = None
    speed_factor: int | None = None
    flow_factor: int | None = None
    # laser cutters (Ruida)
    laser: str | None = None  # "on" while cutting, "off" while travelling
    power_min: float | None = None
    power_max: float | None = None
    air_assist: bool | None = None

    def apply(self, line: ParsedLine) -> None:
        if line.comment:
            self._apply_comment(line.comment)
        if line.code:
            handler = _HANDLERS.get(line.code)
            if handler:
                handler(self, line)
            elif line.code.startswith("T"):
                _tool(self, line)

    def _apply_comment(self, comment: str) -> None:
        if m := _LAYER_COMMENT.search(comment):
            self.layer, self.total_layers = int(m.group(1)), int(m.group(2))
        elif m := _Z_HEIGHT.match(comment):
            self.z_height = float(m.group(1))
        elif m := _FEATURE.match(comment):
            self.feature = m.group(1).strip()
        elif comment == "LAYER_CHANGE":  # PrusaSlicer doesn't number its layers
            self.layer = (self.layer or 0) + 1
        elif m := _PRUSA_Z.match(comment):
            self.z_height = float(m.group(1))


def _move(s: MachineState, line: ParsedLine) -> None:
    relative = s.positioning == "relative"
    for axis in ("x", "y", "z"):
        value = line.number(axis.upper())
        if value is not None:
            current = getattr(s, axis)
            setattr(s, axis, (current or 0.0) + value if relative else value)
    e = line.number("E")
    if e is not None:
        if relative or s.extrusion == "relative":
            s.e = (s.e or 0.0) + e
        else:
            s.e = e
    f = line.number("F")
    if f is not None:
        s.feed = f


def _home(s: MachineState, line: ParsedLine) -> None:
    axes = [a for a in "XYZ" if line.has(a)] or list("XYZ")
    for axis in axes:
        setattr(s, axis.lower(), None)
    s.homed = True


def _set_position(s: MachineState, line: ParsedLine) -> None:
    for axis in "XYZE":
        value = line.number(axis)
        if value is not None:
            setattr(s, axis.lower(), value)


def _setter(attr: str, value: str):
    def handler(s: MachineState, line: ParsedLine) -> None:
        setattr(s, attr, value)
    return handler


def _number_setter(attr: str, letter: str = "S", cast=float, alt: str | None = None):
    def handler(s: MachineState, line: ParsedLine) -> None:
        value = line.number(letter)
        if value is None and alt:
            value = line.number(alt)
        if value is not None:
            setattr(s, attr, cast(value))
    return handler


_FAN_SLOTS = {1: "part_fan", 2: "aux_fan", 3: "chamber_fan"}


def _fan_on(s: MachineState, line: ParsedLine) -> None:
    slot = int(line.number("P") or 1)
    attr = _FAN_SLOTS.get(slot)
    speed = line.number("S")
    if attr:
        setattr(s, attr, round((255 if speed is None else speed) / 255 * 100))


def _fan_off(s: MachineState, line: ParsedLine) -> None:
    attr = _FAN_SLOTS.get(int(line.number("P") or 1))
    if attr:
        setattr(s, attr, 0)


def _progress(s: MachineState, line: ParsedLine) -> None:
    if (p := line.number("P")) is not None:
        s.progress = int(p)
    if (r := line.number("R")) is not None:
        s.remaining_min = int(r)
    if (layer := line.number("L")) is not None:
        s.layer = int(layer)


def _tool(s: MachineState, line: ParsedLine) -> None:
    try:
        slot = int(line.code[1:])
    except ValueError:
        return
    if slot < 255:  # T255, T1000, T1100 etc. are Bambu special tool commands
        s.filament = slot


def _laser_move(beam: str, relative: bool):
    def handler(s: MachineState, line: ParsedLine) -> None:
        for axis in ("x", "y"):
            value = line.number(axis.upper())
            if value is not None:
                setattr(s, axis, (getattr(s, axis) or 0.0) + value if relative else value)
        s.laser = beam
    return handler


def _laser_speed(s: MachineState, line: ParsedLine) -> None:
    if (f := line.number("F")) is not None:
        s.feed = f * 60  # Ruida speeds are mm/s; feed is stored in mm/min like G-code


_HANDLERS = {
    "G0": _move, "G1": _move, "G2": _move, "G3": _move,
    "G20": _setter("units", "inch"), "G21": _setter("units", "mm"),
    "G28": _home,
    "G90": _setter("positioning", "absolute"), "G91": _setter("positioning", "relative"),
    "G92": _set_position,
    "M82": _setter("extrusion", "absolute"), "M83": _setter("extrusion", "relative"),
    "M104": _number_setter("hotend_target"), "M109": _number_setter("hotend_target", alt="R"),
    "M140": _number_setter("bed_target"), "M190": _number_setter("bed_target", alt="R"),
    "M141": _number_setter("chamber_target"), "M191": _number_setter("chamber_target", alt="R"),
    "M106": _fan_on, "M107": _fan_off,
    "M73": _progress,
    "M204": _number_setter("acceleration"),
    "M220": _number_setter("speed_factor", cast=int),
    "M221": _number_setter("flow_factor", cast=int),
    # Ruida laser jobs (lines produced by ventris.ruida)
    "MOVE_ABS": _laser_move("off", False), "MOVE_REL": _laser_move("off", True),
    "MOVE_REL_X": _laser_move("off", True), "MOVE_REL_Y": _laser_move("off", True),
    "CUT_ABS": _laser_move("on", False), "CUT_REL": _laser_move("on", True),
    "CUT_REL_X": _laser_move("on", True), "CUT_REL_Y": _laser_move("on", True),
    "SPEED": _laser_speed,
    "MIN_POWER": _number_setter("power_min"), "MAX_POWER": _number_setter("power_max"),
    "AIR_ASSIST_ON": _setter("air_assist", True), "AIR_ASSIST_OFF": _setter("air_assist", False),
    "LAYER": _number_setter("layer", letter="L", cast=int),
    "END_OF_FILE": _setter("laser", "off"),
}

FIELD_NAMES = [f.name for f in fields(MachineState)]


class StateTracker:
    """Answers "what is the machine state around line N?" for large files.

    Stores a snapshot every `interval` lines and replays from the nearest one,
    so memory stays flat even for files with hundreds of thousands of lines.
    checkpoint[k] is the state *before* line k * interval runs.
    """

    def __init__(self, lines: list[str], interval: int = 500):
        self.interval = interval
        self.lines = lines
        self._checkpoints: list[MachineState] = [MachineState()]

    def update_lines(self, lines: list[str], first_changed: int) -> None:
        self.lines = lines
        keep = first_changed // self.interval + 1
        del self._checkpoints[keep:]

    def states_around(self, index: int) -> tuple[MachineState, MachineState]:
        """Return (state before line `index` runs, state after it runs)."""
        index = max(0, min(index, len(self.lines)))
        k = min(index // self.interval, self._extend_to(index // self.interval))
        state = copy.copy(self._checkpoints[k])
        for i in range(k * self.interval, index):
            state.apply(parse_line(self.lines[i]))
        before = copy.copy(state)
        if index < len(self.lines):
            state.apply(parse_line(self.lines[index]))
        return before, state

    def build_step(self, max_checkpoints: int = 20) -> bool:
        """Add a few checkpoints ahead of time. Returns True while more remain.

        The UI calls this when idle so jumping to the end of a big file is instant.
        """
        target = len(self._checkpoints) - 1 + max_checkpoints
        return self._extend_to(target) < len(self.lines) // self.interval

    def _extend_to(self, k: int) -> int:
        while len(self._checkpoints) <= k:
            last = len(self._checkpoints) - 1
            start = last * self.interval
            if start + self.interval > len(self.lines):
                break
            state = copy.copy(self._checkpoints[last])
            for i in range(start, start + self.interval):
                state.apply(parse_line(self.lines[i]))
            self._checkpoints.append(state)
        return len(self._checkpoints) - 1

    @staticmethod
    def changed_fields(before: MachineState, after: MachineState) -> set[str]:
        return {n for n in FIELD_NAMES if getattr(before, n) != getattr(after, n)}
