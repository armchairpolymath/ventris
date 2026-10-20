"""Anycubic Kobra printers, sliced with Anycubic Slicer Next, OrcaSlicer or
PrusaSlicer.

Two firmware families share the Kobra name:
  - Marlin: Kobra, Kobra Plus, Kobra Max, Kobra Neo, Kobra 2 and Kobra 2 Neo.
  - Anycubic's own Klipper-style firmware (GoKlipper on most models): Kobra 2
    Pro/Plus/Max, Kobra 3, 3 V2, 3 Max, Kobra S1, S1 Max and Kobra X. These files
    mix Marlin codes with Klipper commands like SET_VELOCITY_LIMIT.

Anycubic publishes no G-code reference. G9111 (the one-line start routine) is
explained from Anycubic's published Kobra 3 firmware source
(github.com/ANYCUBIC-3D/Kobra3, klipper-go/project/printer_marco.go) and is
marked "vendor". Codes known only from the comments in Anycubic's slicer
profiles are marked "community"; anything still uncertain says "believed".
"""

from __future__ import annotations

import re

from ..parser import ParsedLine
from ..reference import CommandInfo, Profile, num
from . import bambu, common, prusa
from .common import COMMUNITY as C, VENDOR as V, marker

_FANS = {1: "part-cooling fan (it cools the freshly printed plastic)",
         2: "auxiliary (side) fan",
         3: "chamber fan (moves air through the enclosure)"}

_KEY_VALUE = re.compile(r"([A-Za-z_]+)=(\S+)")


def _kv(line: ParsedLine) -> dict[str, str]:
    """KEY=value words (Klipper style), keys upper-cased."""
    return {k.upper(): v for k, v in _KEY_VALUE.findall(line.params.get("_args", ""))}


# ---------------------------------------------------------------- describers


def _describe_start(line, before, after) -> str:
    args = _kv(line)
    bed, nozzle = args.get("BEDTEMP"), args.get("EXTRUDERTEMP")
    bed = f"{bed} °C" if bed else "its target"
    nozzle = f"{nozzle} °C" if nozzle else "printing temperature"
    return ("Anycubic's whole start routine in one line. The printer heats the bed to "
            f"{bed} and the nozzle to its nozzle-wiping temperature, homes X and Y, "
            "homes all axes, turns the part fan to full and wipes the nozzle clean, "
            f"moves to its heating spot and heats the nozzle to {nozzle}, then runs a "
            "step Anycubic calls UNDERLINE — believed to be the priming line.")


def _describe_progress(line, before, after) -> str:
    raw = line.raw.split(";", 1)[0]
    parts = []
    if m := re.search(r"\bP([\d.]+)", raw):
        parts.append(f"the print is {num(float(m.group(1)))}% done")
    if m := re.search(r"(?<![A-Za-z])R([\d.]+)", raw):
        parts.append(f"about {num(float(m.group(1)), digits=0)} minutes remain")
    modes = [f"{num(float(v), digits=0)} min in {name.lower()} mode"
             for name, v in re.findall(r"(Quiet|Sport)R([\d.]+)", raw)]
    if modes:
        parts.append("or " + " / ".join(modes) + " (the speed modes you can pick on "
                     "the printer)")
    if m := re.search(r"\bL(\d+)", raw):
        parts.append(f"it is now on layer {m.group(1)}")
    if not parts:
        return "Update the progress shown on the printer's screen."
    return "Update the printer's screen: " + ", ".join(parts) + "."


def _describe_layer_notice(line, before, after) -> str:
    p = line.params.get("P")
    if not p:
        return "Tell the printer a new layer has started."
    layer = num(float(p) + 1)
    return (f"Tell the printer that layer {layer} has started (P{p} counts from 0). "
            "Anycubic's comment calls it “notify layer change”; it is believed to "
            "update the layer count on the screen and in the app.")


def _describe_message(line, before, after) -> str:
    text = line.params.get("_args", "").strip()
    if not text:
        return "Clear the message line on the printer's screen."
    return f"Show “{text}” on the printer's screen."


def _describe_tool(line, before, after) -> str:
    if not line.code[1:].isdigit():
        return "Tool change command without a slot number."
    n = int(line.code[1:])
    return (f"Switch to filament slot {n + 1} (T{n}). On a Kobra with a multi-color "
            "unit such as the ACE Pro, the printer unloads the current filament, feeds "
            "the new one to the nozzle and purges the old color by itself.")


def _describe_led(line, before, after) -> str:
    on = line.number("S")
    if on is None:
        return "Change the case light."
    return f"Turn the case light {'on' if on else 'off'}."


def _describe_leveling_state(line, before, after) -> str:
    if line.number("S") == 1:
        return ("Turn on bed leveling using the bed map saved in the printer, so the "
                "nozzle follows the bed's real shape.")
    if line.number("S") == 0:
        return "Turn bed leveling off."
    return "Report or change the bed-leveling settings."


def _describe_pressure_advance(line, before, after) -> str:
    k = line.params.get("K")
    if k in (None, ""):
        return "Change pressure-advance settings."
    if line.number("K") == 0:
        return "Turn pressure advance off."
    return (f"Set pressure advance to {k}. It pushes filament slightly earlier when the "
            "nozzle speeds up and eases off sooner when it slows down, so corners and "
            "line ends come out even.")


def _describe_velocity(line, before, after) -> str:
    args = _kv(line)
    names = {"VELOCITY": ("top speed", "mm/s"), "ACCEL": ("acceleration", "mm/s²"),
             "ACCEL_TO_DECEL": ("accel-to-decel limit", "mm/s²"),
             "MINIMUM_CRUISE_RATIO": ("minimum cruise ratio", ""),
             "SQUARE_CORNER_VELOCITY": ("corner speed", "mm/s")}
    parts = [f"{names[k][0]} {v} {names[k][1]}".strip() for k, v in args.items() if k in names]
    if not parts:
        return "Change the printer's speed limits."
    text = "Change the speed limits: " + ", ".join(parts) + "."
    if "SQUARE_CORNER_VELOCITY" in args:
        text += (" Corner speed is how fast the nozzle may go through a sharp corner "
                 "without stopping — lower means crisper corners.")
    return text


def _describe_exclude(line, before, after) -> str:
    name = _kv(line).get("NAME", "")
    label = f"“{name}”" if name else "an object"
    if line.code == "EXCLUDE_OBJECT_DEFINE":
        return (f"Register {label} so you can cancel just that object from the "
                "printer's screen or app while the rest keeps printing.")
    if line.code == "EXCLUDE_OBJECT_START":
        return (f"The following lines print {label}. If you cancel it, the printer "
                "skips these lines.")
    if line.code == "EXCLUDE_OBJECT_END":
        return f"The lines for {label} end here."
    return "Object-cancel command."


# ---------------------------------------------------------------- reference

_ANYCUBIC_COMMANDS: dict[str, CommandInfo] = {
    "G9111": CommandInfo(
        "Start routine (Kobra 3 / S1 / X)", "Heat, home, wipe the nozzle and prime — all in one line.",
        "Anycubic Slicer Next replaces the usual start code with this single line and "
        "the printer runs the steps itself. Anycubic's published Kobra 3 firmware "
        "source lists them: set nozzle to the wipe temperature and bed to bedTemp; "
        "home X and Y; wait for the wipe temperature; run G9112 (home all axes, part "
        "fan to 100%, wipe the nozzle); move to the heating position; heat the nozzle "
        "to extruderTemp and wait; run UNDERLINE. Anycubic doesn't describe "
        "UNDERLINE; it is believed to print the priming line. The Kobra S1 and X are "
        "believed to run the same routine (the Kobra X's newer firmware isn't "
        "public). Anycubic warns against removing this line: without it the printer "
        "reports error 10133.",
        {"_args": "bedTemp = bed °C, extruderTemp = nozzle °C for the first layer "
                  "(optional wipeTemp = nozzle °C while wiping)"},
        V, _describe_start),
    "G9112": CommandInfo(
        "Home and wipe nozzle", "Home all axes, run the part fan at full and wipe the nozzle.",
        "Part of G9111 in Anycubic's published Kobra 3 firmware source.", {}, V),
    "G29": CommandInfo(
        "Auto bed leveling", "Measure the bed's shape so the nozzle can follow it.",
        "No bed is perfectly flat. The printer touches the bed at a grid of points and "
        "remembers the heights. Anycubic calls its system LeviQ: the nozzle itself "
        "senses the bed on most Kobras. Standard Marlin command."),
    "M420": CommandInfo(
        "Bed leveling on/off", "Turn bed-leveling compensation on (S1) or off (S0).",
        "With S1 the printer reuses the bed map saved by an earlier leveling run, "
        "instead of measuring again before every print. Standard Marlin command.",
        {"S": "1 = on, 0 = off", "Z": "Fade height (mm)"},
        describe=_describe_leveling_state),
    "M355": CommandInfo(
        "Case light", "Turn the printer's light on (S1) or off (S0).",
        "Anycubic's Kobra Plus and Max start code turns the light on; the end code "
        "turns it off. Standard Marlin command.", {"S": "1 = on, 0 = off",
                                                   "P": "Brightness 0–255"},
        describe=_describe_led),
    "M73": CommandInfo(
        "Progress update", "Update the progress bar, time remaining or layer number.",
        "Anycubic Slicer Next adds remaining times for the printer's other speed "
        "modes (QuietR, SportR). On the Kobra 2 Pro/Plus/Max Anycubic's layer-change "
        "code writes M73 L with the layer number (comment: “update layer progress”).",
        {"P": "Percent done", "R": "Minutes remaining", "L": "Current layer",
         "_args": "Progress values, including QuietR/SportR remaining minutes"},
        C, _describe_progress),
    "M991": CommandInfo(
        "Layer change notice (Kobra 2 Pro/Plus/Max)", "Tell the printer a new layer started.",
        "Written by Anycubic's layer-change code with the comment “notify layer "
        "change”. Anycubic doesn't document it.",
        {"S": "Believed to be a mode flag (always 0)", "P": "Layer number, counting from 0"},
        C, _describe_layer_notice),
    "M117": CommandInfo("Show message", "Show a text message on the printer's screen.",
                        "Anycubic's start code ends with an empty M117, which clears "
                        "the message.", {"_args": "The message"},
                        describe=_describe_message),
    "M600": CommandInfo(
        "Filament change", "Pause and ask you to swap the filament (e.g. a color change).",
        "The printer parks, unloads the filament and waits for you. Anycubic Slicer "
        "Next inserts it for a color change you add in the preview. Anycubic lists "
        "M600 and M601 as the pause commands for Kobra 3 series printers; the printer "
        "waits until you confirm on the screen.",
        {"X": "Park X", "Y": "Park Y", "Z": "Lift Z", "E": "Retract (mm)"}, V),
    "M601": CommandInfo(
        "Pause print", "Pause the print until you resume it on the screen.",
        "Anycubic Slicer Next inserts this for a pause you add in the preview. "
        "Anycubic lists it as a supported pause command for Kobra 3 series printers.",
        source=V),
    "M900": CommandInfo(
        "Pressure advance", "Tune how the extruder anticipates speed changes.",
        "Pressure builds up in the nozzle and lags behind the extruder. Pressure "
        "advance (Marlin calls it linear advance) compensates so corners and line "
        "ends come out even. K comes from the printer or filament profile. Anycubic's "
        "Klipper-based firmware maps M900 onto Klipper's SET_PRESSURE_ADVANCE.",
        {"K": "Strength (0 = off)"}, describe=_describe_pressure_advance),
    "T": CommandInfo(
        "Change filament", "Switch to another filament slot.",
        "T0–T3 are the four slots of an ACE Pro (Anycubic Color Engine); a second ACE "
        "Pro adds T4–T7. The printer does the swap itself. In Anycubic's profiles the "
        "moves of the swap appear disabled (;;;) around the T line between "
        "FLUSH_START and FLUSH_END.", {}, C, _describe_tool),
    # Klipper commands written by Anycubic Slicer Next / OrcaSlicer for the
    # Klipper-based Kobras (Klipper's G-code reference documents them).
    "SET_VELOCITY_LIMIT": CommandInfo(
        "Speed limits (Klipper)", "Change the printer's top speed, acceleration or corner speed.",
        "Klipper's way of setting motion limits. Slicers change ACCEL often — gentle "
        "for outer walls, faster for infill and travel.",
        {"_args": "VELOCITY (mm/s), ACCEL (mm/s²), ACCEL_TO_DECEL, "
                  "SQUARE_CORNER_VELOCITY (mm/s), MINIMUM_CRUISE_RATIO"},
        describe=_describe_velocity),
    "EXCLUDE_OBJECT_DEFINE": CommandInfo(
        "Define cancellable object (Klipper)", "Register an object that can be cancelled on its own.",
        "Written once at the start for every object, with its name, center and "
        "outline. Lets you cancel one failed object while the rest keep printing.",
        {"_args": "NAME, CENTER (x,y), POLYGON (outline)"}, describe=_describe_exclude),
    "EXCLUDE_OBJECT_START": CommandInfo(
        "Object starts (Klipper)", "The following lines print one named object.",
        "", {"_args": "NAME of the object"}, describe=_describe_exclude),
    "EXCLUDE_OBJECT_END": CommandInfo(
        "Object ends (Klipper)", "The lines for one named object end here.",
        "", {"_args": "NAME of the object"}, describe=_describe_exclude),
    "EXCLUDE_OBJECT": CommandInfo(
        "Cancel object (Klipper)", "Cancel one object; the printer skips its lines from now on.",
        "", {"_args": "NAME of the object to cancel"}),
    "PAUSE": CommandInfo("Pause (Klipper)", "Pause the print."),
    "RESUME": CommandInfo("Resume (Klipper)", "Resume a paused print."),
    "CANCEL_PRINT": CommandInfo("Cancel print (Klipper)", "Stop the print."),
    "TURN_OFF_HEATERS": CommandInfo("Heaters off (Klipper)", "Turn off every heater."),
    "G10": CommandInfo("Retract (firmware)", "Pull the filament back by the printer's set amount.",
                       "The retraction length is set in the printer instead of the file."),
    "G11": CommandInfo("Un-retract (firmware)", "Push the filament back after a G10 retract."),
}

COMMANDS: dict[str, CommandInfo] = {
    **common.marlin_commands(
        "Anycubic Slicer Next", _FANS,
        "Speed S runs from 0 (off) to 255 (full). Without P (or P1) this is the part-"
        "cooling fan. On the Kobra S1 P2 is the auxiliary (side) fan and P3 the "
        "chamber fan."),
    **_ANYCUBIC_COMMANDS,
}

# ---------------------------------------------------------------- comments

_FEATURES = {
    **prusa._FEATURES,  # PrusaSlicer names (Kobra 2 profiles sliced in PrusaSlicer)
    **bambu._FEATURES,  # OrcaSlicer / Anycubic Slicer Next names
    "Internal Bridge": "A bridge printed inside the part, over sparse infill, so the "
                       "solid layers above have something to rest on.",
    "Custom": "Code from the printer or filament profile (start/end code), not "
              "generated from the model.",
}

COMMENT_MARKERS = [
    *(marker(rf"^TYPE:\s*{re.escape(name)}\s*$", f"Section: {name}",
             f"Slicer note: the following lines print the “{name}”. {text} "
             "The printer itself ignores comments.")
      for name, text in _FEATURES.items()),
    marker(r"^TYPE:\s*(.+)$", "Section: {0}",
           "Slicer note: the following lines print the “{0}” part of the model."),
    marker(r"^LAYER_CHANGE$", "Layer change",
           "Slicer note: a new layer starts here. Everything until the next layer change "
           "is printed at one height."),
    *(marker(rf"^{when.upper()}_LAYER_CHANGE\s+(\d+)\s*@\s*([-\d.]+)\s*mm",
             f"{when} layer change",
             "Note from Anycubic's printer profile: layer index {0} (counting from 0) "
             "is printed at Z = {1} mm.")
      for when in ("After", "Before")),
    *(marker(rf"^{when.upper()}_LAYER_CHANGE$", f"{when} layer change",
             "Slicer note: the printer profile's layer-change code follows.")
      for when in ("After", "Before")),
    marker(r"^layer num/total_layer_count:\s*(\d+)\s*/\s*(\d+)", "Layer {0} of {1}",
           "Note from Anycubic's layer-change code: layer {0} of {1} starts here."),
    marker(r"^update layer progress", "Layer progress",
           "Anycubic's heading: the next lines tell the printer which layer it is on."),
    marker(r"^(start|end) of layer_num:\s*(\d+).*print_z:\s*([-\d.]+)", "Layer {1} {0}",
           "Slicer note: the {0} of layer {1}, printed at Z = {2} mm."),
    marker(r"^Z:([-\d.]+)$", "Layer height marker",
           "Slicer note: this layer is printed at Z = {0} mm."),
    marker(r"^HEIGHT:([-\d.]+)$", "Layer thickness",
           "Slicer note: lines here are {0} mm thick."),
    marker(r"^WIDTH:([-\d.]+)$", "Line width",
           "Slicer note: lines here are {0} mm wide (the nozzle is usually 0.4 mm)."),
    marker(r"^WIPE_START", "Wipe starts",
           "Slicer note: the nozzle drags back along the line it just printed while "
           "pulling filament in, to avoid a blob or string."),
    marker(r"^WIPE_END", "Wipe ends", "Slicer note: end of the wipe move."),
    marker(r"^_SET_FAN_SPEED_CHANGING_LAYER", "Fan speed marker",
           "Slicer note: a marker the slicer uses while working out fan speeds per "
           "layer. The printer ignores it."),
    marker(r'^printing object "?(.+?)"?(?: id:(\d+))?(?: copy \d+)?$', "Object: {0}",
           "Slicer note: the following lines print the object “{0}”."),
    marker(r"^stop printing object", "Object ends",
           "Slicer note: the lines for this object end here."),
    marker(r"^PURGE LINE", "Purge line",
           "Anycubic's heading: a short line is printed outside the model so plastic "
           "is flowing evenly before the real print starts."),
    marker(r"^FLUSH_START", "Filament swap starts",
           "Slicer note: a filament change follows. The printer does the swap itself "
           "when it reaches the T line; the disabled (;;;) lines around it describe the "
           "swap's moves and waits without the printer running them. They are believed "
           "to be there so the slicer can estimate how long the swap takes."),
    marker(r"^FLUSH_END", "Filament swap ends", "Slicer note: end of the filament change."),
    marker(r"^;+\s*([GMT]\d+(?:\.\d+)?\b.*)$", "Disabled command (filament swap)",
           "A command (“{0}”) switched off with extra semicolons, so the printer skips "
           "it. Anycubic's profiles write the moves of a filament swap this way: the "
           "printer does the swap itself when it reaches the T line."),
    marker(r"^_GP_\w+", "Time estimate placeholder",
           "Slicer note: a placeholder the slicer fills in with a time estimate. The "
           "printer ignores it."),
    marker(r"^generated by (\S+ \S+)", "Made by {0}", "This file was sliced with {0}."),
    marker(r"^(HEADER|THUMBNAIL|EXECUTABLE|CONFIG)_BLOCK_(START|END)", "{0} block {1}",
           "Slicer note: marks the {0} section of the file (header, preview image, "
           "printable code or settings). The printer ignores it."),
    marker(r"^EXECUTABLE_BLOCK_HEAD", "End of start code",
           "Slicer note: the printer profile's start code ends here."),
    marker(r"^thumbnail\w* (?:begin|end|\d+x\d+)", "Preview image",
           "Slicer note: an encoded preview picture of the model for the printer's screen."),
    marker(r"^[A-Za-z0-9+/]{40,}={0,2}$", "Preview image data",
           "Part of the encoded preview picture. The printer ignores it."),
    marker(r"^(AnycubicSlicer|prusaslicer)_config = (begin|end)", "Slicer settings block",
           "Slicer note: a record of every slicer setting used. The printer ignores it."),
    marker(r"^filament (start|end) gcode", "Filament {0} code",
           "Slicer note: commands from the filament profile follow."),
    marker(r"^total layer number:\s*(\d+)", "Layer count",
           "Slicer note: this print has {0} layers."),
    marker(r"^max_z_height:\s*([-\d.]+)", "Print height",
           "Slicer note: the print is {0} mm tall."),
    *common.GENERIC_MARKERS,
    marker(r"^([a-z_]+):\s*(.+)$", "Slicer info: {0}",
           "Written by the slicer: {0} = {1}. The printer ignores it."),
    marker(r"^([A-Za-z][A-Za-z0-9 _()\[\]^/%.-]*?)\s*=\s*(.*)$", "Slicer info: {0}",
           "Written by the slicer: {0} = {1}. The printer ignores it."),
]

# ---------------------------------------------------------------- detection

_KOBRA = re.compile(r"Anycubic Kobra|printer_settings_id = [^\n]*Kobra|^\s*G9111\b", re.M)


def _detect(sample: str) -> float:
    if _KOBRA.search(sample):
        return 1.0
    if "Anycubic" in sample:
        return 0.5
    return 0.1


PROFILE = Profile(
    key="kobra",
    name="Anycubic Kobra",
    description=("Anycubic Kobra, Kobra Plus/Max/Neo, Kobra 2 series, Kobra 3 series, "
                 "Kobra S1 series and Kobra X (Anycubic Slicer Next, OrcaSlicer or "
                 "PrusaSlicer G-code)"),
    commands=COMMANDS,
    comment_markers=COMMENT_MARKERS,
    detect=_detect,
    vendor="Anycubic",
)
