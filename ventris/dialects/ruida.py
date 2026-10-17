"""Ruida-controlled laser cutters, e.g. Thunder Laser Nova series (Nova 24/35/51/63).

These machines don't use G-code. Ventris decodes their binary .rd job files
(ventris/ruida.py) into one readable line per command, and this profile explains
those lines. Ruida doesn't publish its command set; everything here comes from
community reverse-engineering (MeerK40t, jnweiger/ruida-laser), so entries are
marked "community", and uncertain ones say "believed".
"""

from __future__ import annotations

import re

from ..reference import CommandInfo, Profile, num
from .common import COMMUNITY as C, marker

def _xy(line) -> str:
    return ", ".join(f"{a} {num(line.number(a))} mm" for a in "XY" if line.has(a))


def _speed_text(before) -> str:
    return f" at {num(before.feed / 60, digits=1)} mm/s" if before.feed else ""


def _describe_move(line, before, after) -> str:
    target = _xy(line)
    if "REL" in line.code:
        return (f"Move the laser head by {target} with the beam off. Nothing is cut; "
                "this just travels to where the next cut starts.")
    return (f"Move the laser head to {target} with the beam off. Nothing is cut; "
            "this just travels to where the next cut starts.")


def _describe_cut(line, before, after) -> str:
    target = _xy(line)
    power = ""
    if before.power_max is not None:
        power = f", up to {num(before.power_max)}% power"
    where = "by" if "REL" in line.code else "to"
    return (f"Cut (or mark) in a straight line {where} {target} with the laser on"
            f"{_speed_text(before)}{power}.")


def _describe_power(which: str, layer: bool):
    def describe(line, before, after) -> str:
        value = line.params.get("S", "?")
        tube = ""
        m = re.search(r"_(\d)$", line.code)
        if m:
            tube = f" for laser tube {m.group(1)}"
        if layer:
            return (f"Layer {line.params.get('L', '?')} setting: {which} power {value}%{tube}. "
                    "This is the layer's recipe, stored at the top of the job.")
        return f"Set the {which} laser power to {value}%{tube} for the cuts that follow."
    return describe


def _describe_speed(line, before, after) -> str:
    return f"Set the cutting speed to {line.params.get('F', '?')} mm/s for the cuts that follow."


def _describe_layer_speed(line, before, after) -> str:
    return (f"Layer {line.params.get('L', '?')} setting: speed {line.params.get('F', '?')} mm/s. "
            "Part of the layer's recipe, stored at the top of the job.")


def _describe_layer(line, before, after) -> str:
    return (f"Start working on layer {line.params.get('L', '?')}. In LightBurn and RDWorks "
            "each color is a layer with its own speed and power; the settings that "
            "follow apply to it.")


def _describe_color(line, before, after) -> str:
    rgb = "".join(f"{int(line.params.get(c, 0)):02x}" for c in "RGB")
    layer = f"Layer {line.params['L']}" if "L" in line.params else "This layer"
    return (f"{layer} is shown in color #{rgb} in the design software. Color only "
            "identifies the layer; it doesn't change how the laser cuts.")


def _describe_area(what: str):
    def describe(line, before, after) -> str:
        layer = f" of layer {line.params['L']}" if "L" in line.params else ""
        return f"The {what} corner{layer} is at {_xy(line)}."
    return describe


def _describe_time(what: str):
    def describe(line, before, after) -> str:
        return f"Set the {what} to {line.params.get('T', '?')} ms."
    return describe


def _describe_work_mode(line, before, after) -> str:
    return f"Set the controller's work mode to {line.params.get('M', '?')} (meaning not public)."


def _describe_origin(line, before, after) -> str:
    mode = line.params.get("M")
    meaning = {"0": "the laser head's current position",
               "1": "the anchor point set on the machine",
               "2": "the machine's absolute zero"}.get(mode, "a reference point")
    return (f"Coordinates in this job are measured from {meaning}. "
            "(Believed meaning of origin mode " f"{mode}.)")


def _describe_setting(line, before, after) -> str:
    return (f"Write a value into controller memory at address {line.params.get('A', '?')}. "
            "RDWorks adds this at the end of a job; the exact setting isn't public.")


def _describe_filename(line, before, after) -> str:
    return f"The job is named “{line.params.get('_args', '')}” on the machine's file list."


_MOVE_PARAMS = {"X": "Left/right distance in mm", "Y": "Front/back distance in mm"}
_POWER = {"S": "Power in % of the laser tube's maximum"}
_LAYER_POWER = {"L": "Layer number (0 = first layer)", "S": "Power in %"}
_AREA = {"L": "Layer number", "X": "X in mm", "Y": "Y in mm"}

_POWER_DETAILS = (
    "Ruida controllers use two power numbers. The laser fires at max power while the "
    "head moves at full speed and drops toward min power as it slows down in corners, "
    "so corners don't burn deeper than straight lines.")


def _power_entries() -> dict[str, CommandInfo]:
    entries = {}
    for suffix, tube in [("", ""), ("_2", " (laser 2)"), ("_3", " (laser 3)"), ("_4", " (laser 4)")]:
        entries[f"MIN_POWER{suffix}"] = CommandInfo(
            f"Minimum power{tube}", "Set the lowest laser power, used when the head slows down.",
            _POWER_DETAILS, _POWER, C, _describe_power("minimum", False))
        entries[f"MAX_POWER{suffix}"] = CommandInfo(
            f"Maximum power{tube}", "Set the highest laser power, used at full speed.",
            _POWER_DETAILS, _POWER, C, _describe_power("maximum", False))
        entries[f"LAYER_MIN_POWER{suffix}"] = CommandInfo(
            f"Layer minimum power{tube}", "A layer's minimum power setting.",
            _POWER_DETAILS, _LAYER_POWER, C, _describe_power("minimum", True))
        entries[f"LAYER_MAX_POWER{suffix}"] = CommandInfo(
            f"Layer maximum power{tube}", "A layer's maximum power setting.",
            _POWER_DETAILS, _LAYER_POWER, C, _describe_power("maximum", True))
        entries[f"THROUGH_POWER{suffix}"] = CommandInfo(
            f"Through power{tube}", "A power setting RDWorks calls “through power”.",
            "Believed to be the power used for “through” (pierce) moves; Ruida doesn't "
            "document it.", _POWER, C)
        entries[f"IMMEDIATE_POWER{suffix}"] = CommandInfo(
            f"Immediate power{tube}", "Set the laser power right now.", "", _POWER, C)
        entries[f"END_POWER{suffix}"] = CommandInfo(
            f"End power{tube}", "Power at the end of a move (believed).", "", _POWER, C)
    return entries


def _simple(name: str, summary: str, details: str = "", params=None, describe=None) -> CommandInfo:
    return CommandInfo(name, summary, details, params or {}, C, describe)


COMMANDS: dict[str, CommandInfo] = {
    **{code: CommandInfo(
        "Travel move", "Move the laser head with the beam off.",
        "Travel moves position the head for the next cut. ABS moves go to a position; "
        "REL moves go a distance from where the head is now.", _MOVE_PARAMS, C, _describe_move)
       for code in ("MOVE_ABS", "MOVE_REL", "MOVE_REL_X", "MOVE_REL_Y")},
    **{code: CommandInfo(
        "Cut", "Move in a straight line with the laser firing.",
        "This is where material is cut or marked. Speed and power come from the "
        "SPEED and MIN/MAX_POWER lines before it. Engraving jobs are made of thousands "
        "of short CUT_REL lines, one per scan stroke.", _MOVE_PARAMS, C, _describe_cut)
       for code in ("CUT_ABS", "CUT_REL", "CUT_REL_X", "CUT_REL_Y")},
    **_power_entries(),
    "SPEED": _simple("Speed", "Set the cutting speed.",
                     "Slower means deeper cuts; faster means lighter marks.",
                     {"F": "Speed in mm/s"}, _describe_speed),
    "LAYER_SPEED": _simple("Layer speed", "A layer's speed setting.", "",
                           {"L": "Layer number", "F": "Speed in mm/s"}, _describe_layer_speed),
    "AXIS_SPEED": _simple("Axis speed", "Speed for moving an axis (believed).", "", {"F": "mm/s"}),
    "AXIS_MOVE_SPEED": _simple("Axis move speed", "Speed for axis moves (believed).", "", {"F": "mm/s"}),
    "FORCE_ENGRAVE_SPEED": _simple("Engrave speed", "Speed used for engraving (believed).", "", {"F": "mm/s"}),
    "LAYER": _simple("Select layer", "Start the next layer.", "", {"L": "Layer number"}, _describe_layer),
    "LAYER_END": _simple("Layer end", "End of a layer's settings block (believed).",
                         "RDWorks writes this right before selecting a layer to work on."),
    "LAYER_COUNT": _simple("Last layer", "The number of the last layer in the job (believed).",
                           "", {"L": "Layer number (0 = only one layer)"}),
    "LAYER_COLOR": _simple("Layer color", "The color that identifies a layer in the design software.",
                           "", {"L": "Layer number", "R": "Red 0–255", "G": "Green 0–255",
                                "B": "Blue 0–255"}, _describe_color),
    "LAYER_WORK_MODE": _simple("Layer work mode", "A layer's work-mode setting (meaning not public).",
                               "", {"L": "Layer number", "M": "Mode"}),
    "LAYER_FREQUENCY": _simple("Laser frequency", "Set the laser pulse frequency for a layer.",
                               "Mostly used by fiber/RF lasers.",
                               {"P": "Laser tube", "L": "Layer", "F": "Frequency (Hz)"}),
    "AIR_ASSIST_ON": _simple("Air assist on", "Turn on air assist.",
                             "Air assist blows a jet of air at the cut. It keeps flames down, "
                             "clears smoke and gives cleaner cuts."),
    "AIR_ASSIST_OFF": _simple("Air assist off", "Turn off air assist.",
                              "Often off for engraving, which gives darker marks."),
    "LASER_ON_DELAY": _simple("Laser on delay", "Pause before the beam turns on.", "",
                              {"T": "Milliseconds"}, _describe_time("delay before the beam turns on")),
    "LASER_OFF_DELAY": _simple("Laser off delay", "Pause before the beam turns off.", "",
                               {"T": "Milliseconds"}, _describe_time("delay before the beam turns off")),
    "LASER_ON_DELAY_2": _simple("Laser on delay 2", "Second laser-on delay setting.", "", {"T": "ms"}),
    "LASER_OFF_DELAY_2": _simple("Laser off delay 2", "Second laser-off delay setting.", "", {"T": "ms"}),
    "LASER_INTERVAL": _simple("Laser interval", "Interval between laser pulses (believed).", "", {"T": "ms"}),
    "ADD_DELAY": _simple("Extra delay", "Add a pause (believed).", "", {"T": "ms"}),
    "LASER_TUBE_ENABLE": _simple("Laser tubes in use", "Which laser tubes this job uses (believed).",
                                 "Shown as a bit pattern: 15 means all four outputs enabled.",
                                 {"N": "Bit pattern"}),
    "LASER2_OFFSET": _simple("Laser 2 offset", "Turn the second-laser position offset on/off (believed).",
                             "", {"S": "1 = on, 0 = off"}),
    "LAYER_DEVICE": _simple("Layer device", "Controller setting for the layer (believed).", "",
                            {"N": "Value"}),
    "DOUBLE_HEAD": _simple("Double head", "Enable a second laser head (believed)."),
    "EXTERNAL_IO": _simple("External output", "Controller I/O setting (believed).", "", {"N": "Value"}),
    "WORK_MODE": _simple("Work mode", "Set the controller's work mode.", "",
                         {"M": "Mode"}, _describe_work_mode),
    "ORIGIN_MODE": _simple("Origin", "Choose where coordinates are measured from.",
                           "The first line of every Ruida job.", {"M": "Mode"}, _describe_origin),
    "REFERENCE_POINT": _simple("Reference point", "Set the reference point for the job (believed)."),
    "START_PROCESS": _simple("Start of job", "Marks the start of the job data."),
    "END_OF_FILE": _simple("End of job", "The last command: the job is complete."),
    "BLOCK_END": _simple("End of block", "End of the cutting data."),
    "SET_ABSOLUTE": _simple("Absolute positions", "Positions that follow are absolute (believed)."),
    "FILENAME": _simple("Job name", "The name shown on the machine's file list.", "",
                        {"_args": "Name"}, _describe_filename),
    "FILE_TRANSFER": _simple("File transfer", "Start of a file sent over the network (believed)."),
    "JOB_TOP_LEFT": _simple("Job corner", "One corner of the job area.", "", _AREA, _describe_area("top-left")),
    "JOB_BOTTOM_RIGHT": _simple("Job corner", "The opposite corner of the job area.", "", _AREA,
                                _describe_area("bottom-right")),
    "JOB_MIN_POINT": _simple("Job bounds", "Smallest X/Y used by the job.",
                             "The machine uses the bounds for “Frame”, which traces the "
                             "outline so you can check placement.", _AREA, _describe_area("lowest")),
    "JOB_MAX_POINT": _simple("Job bounds", "Largest X/Y used by the job.", "", _AREA,
                             _describe_area("highest")),
    "LAYER_MIN_POINT": _simple("Layer bounds", "Smallest X/Y used by a layer.", "", _AREA,
                               _describe_area("lowest")),
    "LAYER_MAX_POINT": _simple("Layer bounds", "Largest X/Y used by a layer.", "", _AREA,
                               _describe_area("highest")),
    "LAYER_MIN_POINT_EX": _simple("Layer bounds", "Smallest X/Y of a layer (extended).", "", _AREA,
                                  _describe_area("lowest")),
    "LAYER_MAX_POINT_EX": _simple("Layer bounds", "Largest X/Y of a layer (extended).", "", _AREA,
                                  _describe_area("highest")),
    "JOB_REPEAT": _simple("Job repeat", "How many times to repeat the job (array settings).",
                          "Raw values are shown in the bytes; their exact layout isn't public."),
    "FEED_REPEAT": _simple("Feed repeat", "Material-feed settings (for roll-feed machines).", "",
                           {"A": "Value", "B": "Value"}),
    "FEED_LENGTH": _simple("Feed length", "Material-feed length (roll-feed machines).", "", {"N": "Value"}),
    "ARRAY_DIRECTION": _simple("Array direction", "Direction for repeated copies.", "", {"N": "Value"}),
    "ARRAY_START": _simple("Array start", "Start of the cutting data for a (possibly repeated) part."),
    "ARRAY_END": _simple("Array end", "End of the cutting data for that part."),
    "ARRAY_REPEAT": _simple("Array repeat", "Repeat settings for copies of the part."),
    "ARRAY_MIN_POINT": _simple("Array bounds", "Smallest X/Y of the part.", "", _AREA,
                               _describe_area("lowest")),
    "ARRAY_MAX_POINT": _simple("Array bounds", "Largest X/Y of the part.", "", _AREA,
                               _describe_area("highest")),
    "ARRAY_ADD": _simple("Array offset", "Offset between repeated copies.", "", _AREA),
    "ARRAY_MIRROR": _simple("Array mirror", "Mirror setting for copies.", "", {"N": "Value"}),
    "PEN_OFFSET": _simple("Pen offset", "Offset for a second head or pen (believed).", "",
                          {"N": "Axis", "V": "Offset in mm"}),
    "LAYER_OFFSET": _simple("Layer offset", "Position offset for a layer (believed).", "",
                            {"N": "Axis", "V": "Offset in mm"}),
    "DISPLAY_OFFSET": _simple("Display offset", "Offset used for the machine's preview display.", "", _AREA),
    "BLOCK_CUTTING": _simple("Block cutting", "Block-cutting option (believed).", "", {"N": "Value"}),
    "FEED_AUTO_CALC": _simple("Feed auto-calc", "Feed option (believed).", "", {"N": "Value"}),
    "ELEMENT": _simple("Element", "Element (part) index.", "", {"N": "Index"}),
    "ELEMENT_INDEX": _simple("Element index", "Current element (part) index.", "", {"N": "Index"}),
    "ELEMENT_MAX_INDEX": _simple("Element count", "Highest element index.", "", {"N": "Index"}),
    "ELEMENT_NAME_INDEX": _simple("Element name index", "Element name index.", "", {"N": "Index"}),
    "ELEMENT_NAME_MAX_INDEX": _simple("Element name count", "Highest element name index.", "",
                                      {"N": "Index"}),
    "ELEMENT_NAME": _simple("Element name", "An encoded part name (not decoded)."),
    "ELEMENT_MIN_POINT": _simple("Element bounds", "Smallest X/Y of the element.", "", _AREA,
                                 _describe_area("lowest")),
    "ELEMENT_MAX_POINT": _simple("Element bounds", "Largest X/Y of the element.", "", _AREA,
                                 _describe_area("highest")),
    "ELEMENT_ARRAY": _simple("Element array", "Repeat settings for the element."),
    "ELEMENT_ARRAY_ADD": _simple("Element array offset", "Offset between element copies.", "", _AREA),
    "ELEMENT_ARRAY_MIRROR": _simple("Element mirror", "Mirror setting for element copies.", "",
                                    {"N": "Value"}),
    "SET_SETTING": _simple("Controller setting", "Write a value into controller memory.", "",
                           {"A": "Memory address", "V": "Value", "W": "Value"}, _describe_setting),
    "GET_SETTING": _simple("Read setting", "Read a value from controller memory.", "",
                           {"A": "Memory address"}),
    "DOCUMENT_PAGE": _simple("Document page", "Page number of an uploaded file.", "", {"N": "Page"}),
    "DOCUMENT_DATA_END": _simple("Document end", "End of an uploaded file's data."),
    "FILE_CHECKSUM": _simple("File checksum", "Checksum of the uploaded file.", "", {"N": "Sum"}),
    "AXIS_MOVE_X": _simple("Axis move X", "Move the X axis directly.", "", {"X": "mm"}),
    "AXIS_MOVE_Y": _simple("Axis move Y", "Move the Y axis directly.", "", {"Y": "mm"}),
    "AXIS_MOVE_Z": _simple("Axis move Z", "Move the Z axis (bed height) directly.", "", {"Z": "mm"}),
    "AXIS_MOVE_U": _simple("Axis move U", "Move the U (rotary) axis directly.", "", {"U": "mm"}),
    **{f"RAPID_MOVE_{a}": _simple(f"Rapid move {a}", f"Move quickly on {a} with the beam off.",
                                  "", {"O": "Option", a: "mm"}) for a in ("X", "Y", "Z", "U")},
    "RAPID_MOVE_XY": _simple("Rapid move", "Move quickly with the beam off.", "",
                             {"O": "Option", "X": "mm", "Y": "mm"}),
    "INHALE_ZONE": _simple("Exhaust zone", "Choose an exhaust/suction zone (believed).", "", {"N": "Zone"}),
    "X_SIGN_MAP": _simple("X direction", "X axis direction setting (believed).", "", {"N": "Value"}),
    "ZU_MAP": _simple("Z/U mapping", "Z/U axis setting (believed).", "", {"N": "Value"}),
    "U_FILE_ID": _simple("File ID", "File identifier (believed).", "", {"N": "ID"}),
}

COMMENT_MARKERS = [
    marker(r"^Ruida laser job \(\.rd\) decoded by Ventris", "About this view",
           "Ruida laser controllers don't use G-code. Their job files (.rd) are scrambled "
           "binary data; Ventris decoded this one into one readable line per command. "
           "The view is read-only — Ventris doesn't write .rd files."),
    marker(r"^scramble key: (0x[0-9a-f]+), (\d+) commands", "File details",
           "The file was unscrambled with key {0} and holds {1} commands. Different Ruida "
           "controller models use different keys; 0x88 is the most common."),
    marker(r"^Each line is one controller command", "How to read this",
           "Each line shows a command name and its values converted to mm, mm/s and %. "
           "The raw bytes from the file follow “bytes:” so nothing is hidden."),
]


def _detect(sample: str) -> float:
    return 1.0 if "; Ruida laser job (.rd)" in sample else 0.0


PROFILE = Profile(
    key="ruida",
    name="Thunder Laser / Ruida",
    description="Ruida-controlled laser cutters such as the Thunder Laser Nova series (.rd files)",
    commands=COMMANDS,
    comment_markers=COMMENT_MARKERS,
    detect=_detect,
    vendor="Ruida",
    kind="laser",
)
