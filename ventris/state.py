"""Simulate what the machine knows/does as it runs the file, line by line."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field, fields

from .parser import ParsedLine, parse_line

_LAYER_COMMENT = re.compile(r"layer num/total_layer_count:\s*(\d+)\s*/\s*(\d+)", re.I)
_Z_HEIGHT = re.compile(r"Z_HEIGHT:\s*([-\d.]+)", re.I)
_FEATURE = re.compile(r"(?:FEATURE|TYPE):\s*(.+)", re.I)  # Bambu Studio / PrusaSlicer
_PRUSA_Z = re.compile(r"Z:([-\d.]+)$")
_CURA_LAYER = re.compile(r"LAYER:(\d+)$")  # Cura / Creality Print 4: counts from 0
_CURA_LAYER_COUNT = re.compile(r"LAYER_COUNT:(\d+)$")
_PROGRESS_WORD = re.compile(r"(?<![A-Za-z])([PRL])([\d.]+)")  # skips QuietR / SportR
_KEY_VALUE = re.compile(r"([A-Za-z_]+)=([-\d.]+)")


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
    # M106 P number -> fan field; set from the profile (makers number fans differently)
    fan_slots: dict[int, str] | None = field(default=None, compare=False, repr=False)

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
        elif m := _CURA_LAYER.match(comment):
            self.layer = int(m.group(1)) + 1
        elif m := _CURA_LAYER_COUNT.match(comment):
            self.total_layers = int(m.group(1))


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


# No P means P0. Bambu-style numbering: P0/P1 part fan, P2 auxiliary, P3 chamber.
DEFAULT_FAN_SLOTS = {0: "part_fan", 1: "part_fan", 2: "aux_fan", 3: "chamber_fan"}


def _fan_attr(s: MachineState, line: ParsedLine) -> str | None:
    return (s.fan_slots or DEFAULT_FAN_SLOTS).get(int(line.number("P") or 0))


def _fan_on(s: MachineState, line: ParsedLine) -> None:
    attr = _fan_attr(s, line)
    speed = line.number("S")
    if attr:
        setattr(s, attr, round((255 if speed is None else speed) / 255 * 100))


def _fan_off(s: MachineState, line: ParsedLine) -> None:
    attr = _fan_attr(s, line)
    if attr:
        setattr(s, attr, 0)


def _progress(s: MachineState, line: ParsedLine) -> None:
    values = {k: line.number(k) for k in "PRL"}
    if "_args" in line.params:  # Anycubic: M73 P1 R14 QuietR27 SportR11
        values = {k: float(v) for k, v in _PROGRESS_WORD.findall(line.params["_args"])}
    if (p := values.get("P")) is not None:
        s.progress = int(p)
    if (r := values.get("R")) is not None:
        s.remaining_min = int(r)
    if (layer := values.get("L")) is not None:
        s.layer = int(layer)


def _anycubic_start(s: MachineState, line: ParsedLine) -> None:
    """G9111: Anycubic's start routine heats, homes and primes."""
    args = {k.upper(): float(v) for k, v in _KEY_VALUE.findall(line.params.get("_args", ""))}
    _home(s, ParsedLine(raw="G28"))
    if "BEDTEMP" in args:
        s.bed_target = args["BEDTEMP"]
    if "EXTRUDERTEMP" in args:
        s.hotend_target = args["EXTRUDERTEMP"]


def _start_macro(**keys: str):
    """A Klipper start macro that homes and heats: KEY=value words -> state fields."""
    def handler(s: MachineState, line: ParsedLine) -> None:
        args = {k.upper(): float(v)
                for k, v in _KEY_VALUE.findall(line.params.get("_args", ""))}
        _home(s, ParsedLine(raw="G28"))
        for key, attr in keys.items():
            if key in args:
                setattr(s, attr, args[key])
    return handler


def _print_stats(s: MachineState, line: ParsedLine) -> None:
    """SET_PRINT_STATS_INFO CURRENT_LAYER=3 TOTAL_LAYER=120 (Klipper)."""
    args = {k.upper(): float(v) for k, v in _KEY_VALUE.findall(line.params.get("_args", ""))}
    if "CURRENT_LAYER" in args:
        s.layer = int(args["CURRENT_LAYER"])
    if "TOTAL_LAYER" in args:
        s.total_layers = int(args["TOTAL_LAYER"])


_HEATERS = {"extruder": "hotend_target", "heater_bed": "bed_target", "chamber": "chamber_target"}


def _set_heater(s: MachineState, line: ParsedLine) -> None:
    """SET_HEATER_TEMPERATURE HEATER=extruder TARGET=220 (Klipper)."""
    heater = re.search(r"HEATER=(\w+)", line.params.get("_args", ""), re.I)
    target = re.search(r"TARGET=([-\d.]+)", line.params.get("_args", ""), re.I)
    if heater and target and heater.group(1) in _HEATERS:
        setattr(s, _HEATERS[heater.group(1)], float(target.group(1)))


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
    "G28": _home, "G9111": _anycubic_start,
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
    # Klipper / QIDI
    "PRINT_START": _start_macro(BED="bed_target", HOTEND="hotend_target",  # QIDI
                                CHAMBER="chamber_target"),
    "START_PRINT": _start_macro(BED_TEMP="bed_target",  # Creality
                                EXTRUDER_TEMP="hotend_target"),
    "SET_PRINT_STATS_INFO": _print_stats,
    "SET_HEATER_TEMPERATURE": _set_heater,
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

FIELD_NAMES = [f.name for f in fields(MachineState) if f.name != "fan_slots"]


class StateTracker:
    """Answers "what is the machine state around line N?" for large files.

    Stores a snapshot every `interval` lines and replays from the nearest one,
    so memory stays flat even for files with hundreds of thousands of lines.
    checkpoint[k] is the state *before* line k * interval runs.
    """

    def __init__(self, lines: list[str], interval: int = 500,
                 fan_slots: dict[int, str] | None = None):
        self.interval = interval
        self.lines = lines
        self._checkpoints: list[MachineState] = [MachineState(fan_slots=fan_slots)]

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
