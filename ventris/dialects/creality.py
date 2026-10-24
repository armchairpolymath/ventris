"""Creality K1 series (K1, K1C, K1 Max, K1 SE), sliced with Creality Print or
OrcaSlicer.

The K1s run Creality's Klipper fork. The slicer writes START_PRINT and END_PRINT
and Creality's macros do the rest. Creality publishes the K1 Klipper source and
each model's macro configuration (github.com/CrealityOfficial/K1_Series_Klipper,
config/K1*/gcode_macro.cfg and klippy/extras/custom_macro.py, prtouch_v2_wrapper.py):
commands explained from those are marked "vendor".

Creality Print 4.x is based on Cura and writes Cura-style comments (;LAYER:0,
;TYPE:WALL-OUTER). Creality Print 5 and later are based on OrcaSlicer and write
OrcaSlicer comments, like the other profiles.

Fans are numbered differently from Bambu: no P (or P0) is the part fan, P1 the
chamber fan at the back and P2 the auxiliary fan on the side.
"""

from __future__ import annotations

import re

from ..parser import ParsedLine
from ..reference import CommandInfo, Profile, num
from . import anycubic, bambu, common, qidi
from .common import COMMUNITY as C, VENDOR as V, marker

FAN_SLOTS = {0: "part_fan", 1: "chamber_fan", 2: "aux_fan"}
_FAN_NAMES = {0: "part-cooling fan (it cools the freshly printed plastic)",
              1: "chamber fan at the back",
              2: "auxiliary (side) fan, which blows across the whole bed"}

_KEY_VALUE = re.compile(r"([A-Za-z_]+)=(\S+)")


def _kv(line: ParsedLine) -> dict[str, str]:
    """KEY=value words (Klipper style), keys upper-cased."""
    return {k.upper(): v for k, v in _KEY_VALUE.findall(line.params.get("_args", ""))}


# ---------------------------------------------------------------- describers


def _describe_start(line, before, after) -> str:
    args = _kv(line)
    nozzle, bed = args.get("EXTRUDER_TEMP"), args.get("BED_TEMP")
    nozzle = f"{nozzle} °C" if nozzle else "its default temperature"
    bed = f"{bed} °C" if bed else "its default temperature"
    return ("Run Creality's start routine: the printer homes with the nozzle warm, "
            "cleans the nozzle on the bed, homes the nozzle height precisely with the "
            "sensors under the bed and checks the saved bed map, then heats the nozzle "
            f"to {nozzle} and the bed to {bed} and draws a priming line along the left "
            "edge.")


def _describe_fan(line, before, after) -> str:
    slot = int(line.number("P") or 0)
    fan = _FAN_NAMES.get(slot, f"fan #{slot}")
    if line.code == "M107":
        if line.has("P"):
            return f"Turn off the {fan}."
        return "Turn off the part-cooling fan and the auxiliary (side) fan."
    speed = line.number("S")
    pct = round((255 if speed is None else speed) / 255 * 100)
    return f"Turn off the {fan}." if pct == 0 else f"Set the {fan} to {pct}% speed."


def _describe_chamber(line, before, after) -> str:
    s = line.number("S")
    if s is None:
        return "Change the chamber-fan setting."
    if s == 0:
        return "Turn the chamber fan off."
    return (f"Keep the chamber at {num(s)} °C or cooler: the fan at the back runs "
            "whenever the air inside gets warmer than that. (The K1 has no chamber "
            "heater.)")


def _describe_corner(line, before, after) -> str:
    value = line.params.get("X") or line.params.get("Y")
    if not value:
        return "Change the corner speed."
    return (f"Set the corner speed to {value} mm/s: how fast the nozzle may go through "
            "a sharp corner without stopping. Lower means crisper corners.")


def _describe_tool(line, before, after) -> str:
    if not line.code[1:].isdigit():
        return "Tool change command without a slot number."
    n = int(line.code[1:])
    return (f"Switch to filament {n + 1} (T{n}). With a Creality CFS multi-color unit "
            "the printer is believed to cut the old filament and load this one itself; "
            "without one it does nothing.")


# ---------------------------------------------------------------- reference

_CREALITY_COMMANDS: dict[str, CommandInfo] = {
    "START_PRINT": CommandInfo(
        "Start routine", "Home, clean the nozzle, check the bed and prime — Creality's macro.",
        "Creality's slicer profiles start with this line and the printer's START_PRINT "
        "macro does the work: it heats the nozzle to a homing temperature (90 °C below "
        "the print temperature, at most 180 °C) and the bed, homes (CX_ROUGH_G28), "
        "cleans the nozzle by wiping it on the bed (NOZZLE_CLEAR), homes Z precisely "
        "with the pressure sensors under the bed (ACCURATE_HOME_Z), probes four points "
        "to check the saved bed map and measures the bed again if it has changed "
        "(CHECK_BED_MESH), and finally heats to the print temperatures and draws a "
        "priming line along the left edge (CX_PRINT_DRAW_ONE_LINE). If you ran the "
        "preparation from the screen first, it skips straight to the priming line.",
        {"_args": "EXTRUDER_TEMP = nozzle °C, BED_TEMP = bed °C"}, V, _describe_start),
    "END_PRINT": CommandInfo(
        "End routine", "Turn off the heaters, park the nozzle and cool down.",
        "Creality's END_PRINT macro leaves quiet mode, forgets the object list, resets "
        "speed to 100%, turns off the heaters and the chamber and side fans, pulls the "
        "filament back, lifts the nozzle (to half the printer's height if it is low), "
        "parks it at the right side, runs the part fan until the nozzle is below 40 °C, "
        "and turns off the motors.", {}, V),
    "M106": CommandInfo(
        "Fan on", "Set a fan's speed.",
        "Speed S runs from 0 (off) to 255 (full). Creality numbers the K1's fans: no P "
        "(or P0) is the part-cooling fan, P1 the chamber fan at the back, P2 the "
        "auxiliary fan on the side (the K1 SE has no chamber fan). Creality's macro "
        "rescales S so that any speed above 0 starts above the fan's minimum spinning "
        "speed.", {"P": "Which fan: 0 = part, 1 = chamber, 2 = side",
                   "S": "Speed 0–255 (255 = 100%)"}, V, _describe_fan),
    "M107": CommandInfo(
        "Fan off", "Turn a fan off.",
        "Without P, Creality's macro turns off both the part fan and the side fan.",
        {"P": "Which fan: 0 = part, 1 = chamber, 2 = side"}, V, _describe_fan),
    "M141": CommandInfo(
        "Chamber fan target", "Set how warm the chamber may get before the back fan runs.",
        "The K1, K1C and K1 Max have no chamber heater. Creality's M141 macro sets the "
        "target of the chamber fan instead: the fan at the back cools the enclosure "
        "down to S °C. S0 turns the fan off. The K1 SE has no chamber fan and doesn't "
        "define M141.", {"S": "Highest chamber temperature (°C), 0 = fan off"}, V,
        _describe_chamber),
    "M204": CommandInfo(
        "Acceleration", "Set how quickly the printer speeds up and slows down.",
        "Creality's macro passes the value on to Klipper, but caps it at 2500 mm/s² "
        "while quiet mode is on.", {"S": "Acceleration (mm/s²)"}, V),
    "M205": CommandInfo(
        "Corner speed", "Set how fast the nozzle may go through sharp corners.",
        "Creality's macro turns X (or Y) into Klipper's square-corner velocity.",
        {"X": "Corner speed (mm/s)", "Y": "Corner speed (mm/s)"}, V, _describe_corner),
    "M900": CommandInfo(
        "Pressure advance", "Tune how the extruder anticipates speed changes.",
        "Creality's macro passes K to Klipper's SET_PRESSURE_ADVANCE. Pressure builds "
        "up in the nozzle and lags behind the extruder; pressure advance compensates so "
        "corners and line ends come out even.", {"K": "Strength (0 = off)",
                                                  "E": "Extruder name (optional)"}, V),
    "G29": CommandInfo(
        "Measure the bed", "Home, clean the nozzle and measure the whole bed.",
        "Creality's G29 macro homes, cleans the nozzle, homes Z precisely, probes a "
        "grid of points with the pressure sensors under the bed, saves the map and "
        "turns the heaters off. Prints normally use the saved map (START_PRINT only "
        "checks it).", {}, V),
    "PAUSE": CommandInfo(
        "Pause", "Pause the print and park the nozzle.",
        "Creality's PAUSE macro pulls the filament back, lifts the nozzle to at least "
        "50 mm, parks it at the right side, lowers the nozzle to 140 °C while waiting "
        "and turns off the side fan. RESUME heats it back up and carries on.", {}, V),
    "RESUME": CommandInfo("Resume", "Reheat, return to the print and carry on.",
                          "Creality's macro restores the nozzle temperature and fans, "
                          "lowers the nozzle back and continues.", {}, V),
    "CANCEL_PRINT": CommandInfo("Cancel print", "Stop the print and run the end routine.",
                                "Creality's macro runs END_PRINT, then cancels.", {}, V),
    "T": CommandInfo(
        "Change filament", "Switch to another filament.",
        "Creality Print writes T0–T3 for the slots of a Creality CFS (multi-color "
        "unit) on the K1 series. Creality hasn't published the K1's CFS code, so "
        "what the printer does is believed, not documented.", {}, C, _describe_tool),
}

COMMANDS: dict[str, CommandInfo] = {
    **common.marlin_commands("Creality Print", {1: _FAN_NAMES[0]}, ""),
    # Klipper commands written by Creality Print / OrcaSlicer, shared with other profiles.
    **{code: anycubic.COMMANDS[code] for code in (
        "SET_VELOCITY_LIMIT", "EXCLUDE_OBJECT_DEFINE", "EXCLUDE_OBJECT_START",
        "EXCLUDE_OBJECT_END", "EXCLUDE_OBJECT")},
    **{code: qidi.COMMANDS[code] for code in (
        "SET_PRESSURE_ADVANCE", "TIMELAPSE_TAKE_FRAME", "SET_PRINT_STATS_INFO")},
    **_CREALITY_COMMANDS,
}

# ---------------------------------------------------------------- comments

# Creality Print 4.x (Cura) section names -> the plain-language text used elsewhere.
_CURA_FEATURES = {
    "WALL-OUTER": ("Outer wall", bambu._FEATURES["Outer wall"]),
    "WALL-INNER": ("Inner wall", bambu._FEATURES["Inner wall"]),
    "SKIN": ("Top/bottom skin", "The solid layers on the top and bottom of the part."),
    "FILL": ("Infill", bambu._FEATURES["Sparse infill"]),
    "SKIRT": ("Skirt/brim", "A loop around the part (a skirt) or attached to it (a "
                            "brim). It primes the nozzle or helps the part stick."),
    "SUPPORT": ("Support", bambu._FEATURES["Support"]),
    "SUPPORT-INTERFACE": ("Support interface", bambu._FEATURES["Support interface"]),
    "PRIME-TOWER": ("Prime tower", bambu._FEATURES["Prime tower"]),
}

COMMENT_MARKERS = [
    # Creality Print 4.x (Cura-based)
    *(marker(rf"^TYPE:{re.escape(code)}\s*$", f"Section: {name}",
             f"Slicer note: the following lines print the “{name}”. {text} "
             "The printer itself ignores comments.")
      for code, (name, text) in _CURA_FEATURES.items()),
    marker(r"^LAYER:(-?\d+)$", "Layer change",
           "Slicer note: a new layer starts here. Creality Print numbers layers from 0, "
           "so LAYER:0 is the first layer."),
    marker(r"^LAYER_COUNT:(\d+)$", "Layer count", "Slicer note: this print has {0} layers."),
    marker(r"^MESH:NONMESH$", "Travel between objects",
           "Slicer note: the following moves don't belong to any object."),
    marker(r"^MESH:$", "Object starts",
           "Slicer note: the following lines print an object (the slicer left its "
           "name out)."),
    marker(r"^MESH:(.+)$", "Object: {0}",
           "Slicer note: the following lines print the object “{0}”."),
    marker(r"^TIME_ELAPSED:([\d.]+)", "Time so far",
           "Slicer estimate: about {0} seconds of printing have passed at this point."),
    marker(r"^TIME:([\d.]+)$", "Print time",
           "Slicer estimate: the whole print takes about {0} seconds."),
    marker(r"^;(retract(?: move)?);;$", "Retraction note",
           "Creality Print note: the next lines are a {0}. The printer ignores it."),
    marker(r"^BRIDGE$", "Bridge",
           "Slicer note: the next lines bridge across open air, printed with more "
           "cooling so they don't sag."),
    marker(r"^FLAVOR:(.+)$", "G-code flavor",
           "Slicer note: the file was written for “{0}” firmware."),
    marker(r"^Creality Print GCode Generated by (.+)$", "Made by Creality Print",
           "This file was sliced with Creality Print (slicing engine {0})."),
    marker(r"^Creality Print Version\s*:\s*(\S+)", "Made by Creality Print {0}",
           "This file was sliced with Creality Print version {0}."),
    marker(r"^generated by Creality_Print (\S+)", "Made by Creality Print {0}",
           "This file was sliced with Creality Print version {0}."),
    marker(r"^(?:png|thumbnail) (?:begin|end)", "Preview image",
           "Slicer note: an encoded preview picture of the model for the printer's screen."),
    marker(r"^End of Gcode$", "End of file", "Slicer note: the file ends here."),
    marker(r"^;+$", "Divider", "A divider line to make the file easier to read."),
    marker(r'^printing object "?(.+?)"?(?: id:(\d+))?(?: copy \d+)?$', "Object: {0}",
           "Slicer note: the following lines print the object “{0}”."),
    marker(r"^stop printing object", "Object ends",
           "Slicer note: the lines for this object end here."),
    marker(r"^Pre-Processed for Cancel-Object support", "Cancel-object support",
           "Note from a preprocessing step: object labels (EXCLUDE_OBJECT lines) were "
           "added so single objects can be cancelled from the printer's screen."),
    marker(r"^(\d+) known objects?$", "Object count",
           "Note from the cancel-object preprocessing: the file has {0} object(s)."),
    marker(r"^AFTER_LAYER_CHANGE$", "After layer change",
           "Slicer note: the printer profile's after-layer-change code follows."),
    marker(r"^-{3,}\s*(.*?)\s*-*$", "Section label",
           "A heading in the slicer's settings summary: “{0}”. The printer ignores it."),
    marker(r"^([-\d.]+)$", "Layer height marker",
           "Note from Creality's layer-change code: this layer is printed at Z = {0} mm."),
    # Creality Print 5+ / OrcaSlicer: the markers shared with the QIDI profile, minus
    # QIDI's own notes.
    *(m for m in qidi.COMMENT_MARKERS if "QIDI" not in m.title + m.explanation),
    marker(r"^([A-Za-z][A-Za-z0-9 /_()\[\].-]*?)\s*:\s*(.+)$", "Slicer info: {0}",
           "Written by the slicer: {0} = {1}. The printer ignores it."),
]

# ---------------------------------------------------------------- detection

_K1 = re.compile(
    r"Machine Name:\s*K1\b|printer_(?:model|settings_id) = (?:Creality[ @])?K1\b|"
    r"@Creality K1\b", re.M)


def _detect(sample: str) -> float:
    if _K1.search(sample):
        return 1.0
    if "START_PRINT EXTRUDER_TEMP=" in sample or "Creality" in sample:
        return 0.5  # another Creality printer (Ender-3 V3, K2, ...)
    return 0.1


PROFILE = Profile(
    key="k1",
    name="Creality K1",
    description=("Creality K1, K1C, K1 Max and K1 SE, with or without a CFS "
                 "(Creality Print or OrcaSlicer G-code)"),
    commands=COMMANDS,
    comment_markers=COMMENT_MARKERS,
    detect=_detect,
    vendor="Creality",
    fan_slots=FAN_SLOTS,
)
