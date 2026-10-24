"""QIDI Tech printers, sliced with QIDIStudio, OrcaSlicer or QIDISlicer.

Two firmware families share the QIDI name:
  - Klipper: X-Max 3, X-Plus 3, X-Smart 3, Q1 Pro, X-Plus 4, X-Max 4, Q2, Q2C,
    X-Plus 5 and X-Smart 5. The slicer writes a few lines and QIDI's own Klipper
    macros (PRINT_START, MOVE_TO_TRASH, M1002, ...) do the rest.
  - Marlin-based QIDI firmware: the older X-Plus, X-Max and X-CF Pro.

QIDI publishes its Klipper configuration for the Q1 Pro, X-Plus 4, X-Max 4 and Q2
(github.com/QIDITECH, QIDI_<model>/config). Commands explained from those macros,
and from the Python modules shipped next to them, are marked "vendor". The QIDI
Box (multi-color unit) runs from compiled modules whose source isn't public
(box_extras.so): those commands are explained from their names and from where
QIDI's macros and slicer profiles use them, are marked "community", and say
"believed" where the purpose is a guess.
"""

from __future__ import annotations

import re

from ..parser import ParsedLine
from ..reference import CommandInfo, Profile, num
from . import anycubic, bambu, common, prusa
from .common import COMMUNITY as C, VENDOR as V, marker

_FANS = {1: "part-cooling fan (it cools the freshly printed plastic)",
         2: "auxiliary (side) fan, which blows across the whole bed",
         3: "chamber fan (moves air through the enclosure)",
         4: "“Polar cooler” (X-Max 4 and Q2)"}

_KEY_VALUE = re.compile(r"([A-Za-z_]+)=(\S+)")

_STATUS = {
    "print_start": "starting the print", "printing": "printing", "print_end": "finished",
    "tool_head_reset": "homing", "change_filament": "changing filament",
    "flush_filament": "flushing filament", "clear_nozzle": "cleaning the nozzle",
    "wait_bed_temp": "heating the bed", "wait_chamber_temp": "heating the chamber",
    "z_tilt_adjust": "leveling the gantry", "auto_bed_adjust": "measuring the bed",
    "extruder_heating": "heating the nozzle", "bed_heating": "heating the bed",
}


def _kv(line: ParsedLine) -> dict[str, str]:
    """KEY=value words (Klipper style), keys upper-cased."""
    return {k.upper(): v for k, v in _KEY_VALUE.findall(line.params.get("_args", ""))}


# ---------------------------------------------------------------- describers


def _describe_start(line, before, after) -> str:
    args = _kv(line)
    if not args:
        return ("Run QIDI's start routine: home, heat, clean the nozzle and measure the "
                "bed. The temperatures come from the lines that follow.")
    bed, nozzle = args.get("BED"), args.get("HOTEND")
    chamber = args.get("CHAMBER", "0")
    text = (f"Run QIDI's start routine for a bed at {bed or '?'} °C and a nozzle at "
            f"{nozzle or '?'} °C: the printer homes, heats the bed, cleans the nozzle "
            "over the waste chute, measures the bed and heats the nozzle")
    if chamber not in ("0", "0.0"):
        text += f", and heats the chamber to {chamber} °C"
    else:
        text += "; with no chamber heating it runs the chamber fan to keep the air cool"
    if "EXTRUDER" in args:
        text += (f". With a QIDI Box it first loads filament {int(args['EXTRUDER']) + 1} "
                 f"(T{args['EXTRUDER']}) and flushes the old color")
    return text + "."


def _describe_stats(line, before, after) -> str:
    args = _kv(line)
    parts = []
    if "CURRENT_LAYER" in args:
        parts.append(f"the print is now on layer {args['CURRENT_LAYER']}")
    if "TOTAL_LAYER" in args:
        parts.append(f"it has {args['TOTAL_LAYER']} layers in total")
    if not parts:
        return "Update the layer count shown on the printer's screen."
    return "Tell the printer's screen and app that " + " and ".join(parts) + "."


def _describe_status(line, before, after) -> str:
    args = _kv(line)
    value = args.get("MAIN_STATUS", args.get("SUB_STATUS", "")).strip('"')
    if not value:
        return "Clear the step shown on the printer's screen."
    what = _STATUS.get(value.lower(), value.replace("_", " "))
    kind = "status" if "MAIN_STATUS" in args else "current step"
    return f"Show “{what}” as the {kind} on the printer's screen and in the app."


def _describe_wait_temp(direction: str):
    def describe(line, before, after) -> str:
        s = line.number("S")
        if not s:
            return "Do nothing (no temperature given)."
        if direction == "down":
            return (f"Wait until the nozzle has cooled to {num(s)} °C or below "
                    "(only if its target is that low).")
        return (f"Wait until the nozzle has reached about {num(s)} °C, without changing "
                "its target.")
    return describe


def _describe_offset(line, before, after) -> str:
    if line.number("R"):
        return "Clear the nozzle-height (Z) offset before the bed is measured."
    if line.number("A"):
        return ("Apply the nozzle-height (Z) offset saved in the printer, so the first "
                "layer is squished the way you set it on the screen.")
    if line.number("S"):
        return "Save the current nozzle-height (Z) offset for later prints."
    return "Manage the nozzle-height (Z) offset."


def _describe_z_set(line, before, after) -> str:
    z = line.number("Z")
    if z is None:
        return "Correct the printer's idea of the nozzle height."
    text = f"Tell the printer the nozzle is now at Z {num(z)} mm"
    if before.z is not None and abs(before.z - z) > 1e-6:
        text += (f" (it was just moved to Z {num(before.z)} mm, a difference of "
                 f"{num(abs(before.z - z))} mm)")
    return text + (". This is believed to correct for the nozzle growing slightly as it "
                   "heats: the slicer works the amount out from the first-layer nozzle "
                   "temperature.")


def _describe_tool(line, before, after) -> str:
    if not line.code[1:].isdigit():
        return "Tool change command without a slot number."
    n = int(line.code[1:])
    return (f"Switch to filament {n + 1} (T{n}). With a QIDI Box, the printer feeds "
            f"the Box slot you mapped to T{n} into the print head. Without a Box it "
            "does nothing.")


def _describe_unload(line, before, after) -> str:
    n = line.code.removeprefix("UNLOAD_T")
    return (f"Pull filament {int(n) + 1} (T{n}) back out of the print head into its "
            "QIDI Box slot.")


def _describe_heater(line, before, after) -> str:
    args = _kv(line)
    heater = {"extruder": "nozzle", "heater_bed": "bed",
              "chamber": "chamber"}.get(args.get("HEATER", ""), args.get("HEATER", "a heater"))
    target = args.get("TARGET")
    if target is None:
        return f"Change the {heater} temperature."
    if float(target) == 0:
        return f"Turn the {heater} heater off."
    text = f"Heat the {heater} to {target} °C"
    return text + (" and wait until it gets there." if args.get("WAIT") == "1" else ".")


def _describe_fan(line, before, after) -> str:
    if line.number("P") == 4:
        on = line.number("S") is None or line.number("S") > 0
        return f"Turn the “Polar cooler” {'on' if on else 'off'}."
    return common.describe_fan(_FANS)(line, before, after)


def _describe_box_temp(line, before, after) -> str:
    slots = [f"{'off' if float(v) == 0 else v + ' °C'} for filament {int(n) + 1}"
             for n, v in re.findall(r"VT(\d+)=([-\d.]+)", line.params.get("_args", ""), re.I)]
    if not slots:
        return "Set the QIDI Box heater."
    return ("Set the QIDI Box heater (believed to be the drying heater): "
            + ", ".join(slots) + ".")


def _describe_simple_args(text: str):
    def describe(line, before, after) -> str:
        return text.format(**{k.lower(): v for k, v in _kv(line).items()})
    return describe


# ---------------------------------------------------------------- reference

_BOX_NOTE = ("QIDI ships the QIDI Box code compiled, without source; this is "
             "explained from the command's name and where QIDI's macros use it.")

_QIDI_COMMANDS: dict[str, CommandInfo] = {
    "PRINT_START": CommandInfo(
        "Start routine", "Home, heat, clean the nozzle and measure the bed — QIDI's macro.",
        "QIDI's slicer profiles start with this one line and the printer's PRINT_START "
        "macro does the work. On the X-Plus 4 and Q2 it: homes; heats the bed; with a "
        "QIDI Box, loads the first filament and flushes it into the waste chute; "
        "cleans the nozzle by purging, cooling and wiping it on the silicone brush; "
        "waits for the bed; levels the gantry (Z_TILT_ADJUST, Plus 4/Q2); measures "
        "the bed (G29); heats the nozzle; sets the chamber temperature, or runs the "
        "chamber fan at full when there is no chamber heating. The Q1 Pro's version "
        "skips the Box and gantry steps. The X-Max 4, X-Plus 5 and X-Smart 5 profiles "
        "write these steps out in the file instead of calling PRINT_START.",
        {"_args": "BED = bed °C, HOTEND = nozzle °C, CHAMBER = chamber °C (0 = no "
                  "heating), EXTRUDER = first filament slot (counting from 0)"},
        V, _describe_start),
    "PRINT_END": CommandInfo(
        "End routine", "Turn off heaters and fans, switch off the motors and beep.",
        "QIDI's PRINT_END macro saves the nozzle-height offset, waits 5 seconds, "
        "turns off every fan and heater (including the Box heater), resets speed and "
        "flow to 100%, turns off the X, Y and extruder motors (Z stays on so the bed "
        "doesn't drop), clears the bed map and beeps twice.", {}, V),
    "M141": CommandInfo(
        "Set chamber temperature", "Heat the air inside the enclosure.",
        "Only on QIDI printers with a chamber heater (Q1 Pro, X-Max 3, X-Plus 3, "
        "X-Plus 4, X-Max 4, Q2). QIDI's macro caps the target at 60 °C on the Q1 Pro "
        "and 65 °C on the X-Plus 4 and Q2, and does nothing on printers without a "
        "chamber heater. A warm chamber helps ABS, ASA and nylon stick and not warp.",
        {"S": "Target in °C (0 = off)"}, V, common.describe_temp("chamber", wait=False)),
    "M191": CommandInfo(
        "Set chamber temperature and wait", "Heat the enclosure and wait until it is warm.",
        "QIDI's macro sets the chamber heater like M141, then waits until the chamber "
        "is within 2 °C of the target.", {"S": "Target in °C"}, V,
        common.describe_temp("chamber", wait=True)),
    "M106": CommandInfo(
        "Fan on", "Set a fan's speed.",
        "Speed S runs from 0 (off) to 255 (full). QIDI numbers its fans differently "
        "from most printers: no P, or P0, is the part-cooling fan; P2 the auxiliary "
        "(side) fan; P3 the chamber fan. On the X-Max 4 and Q2, P4 switches the part "
        "QIDI's firmware calls the “Polar cooler” (on or off only).",
        {"P": "Which fan: 0 = part, 2 = auxiliary, 3 = chamber, 4 = Polar cooler",
         "S": "Speed 0–255 (255 = 100%)"}, V, _describe_fan),
    "M109.0": CommandInfo(
        "Wait for nozzle to heat", "Wait until the nozzle reaches a temperature.",
        "QIDI's macro waits until the nozzle is within 1 °C of S, but only if the "
        "nozzle's target is already at least S. It doesn't change the target.",
        {"S": "Temperature to wait for (°C)"}, V, _describe_wait_temp("up")),
    "M109.1": CommandInfo(
        "Wait for nozzle to cool", "Wait until the nozzle cools down to a temperature.",
        "QIDI's macro waits until the nozzle is at most 1 °C above S, but only if the "
        "nozzle's target is already S or lower. Used before wiping the nozzle, so "
        "the plastic on it is soft but no longer runny.",
        {"S": "Temperature to wait for (°C)"}, V, _describe_wait_temp("down")),
    "M1002": CommandInfo(
        "Z offset", "Reset, apply or save the nozzle-height offset.",
        "QIDI's X-Max 4 macro: R1 clears the offset, A1 applies the offset saved in "
        "the printer, S1 saves the current one. The offset is the fine adjustment "
        "of the first-layer height you set on the screen. (Bambu printers use M1002 "
        "for something unrelated.)",
        {"R": "1 = reset to 0", "A": "1 = apply the saved offset", "S": "1 = save"},
        V, _describe_offset),
    "M1004": CommandInfo(
        "Polar cooler per settings", "Turn on the “Polar cooler” if it is enabled.",
        "QIDI's X-Max 4 macro turns on the part QIDI's firmware calls the Polar "
        "cooler (M106 P4) if the setting for it is on. QIDI doesn't describe it "
        "further.", {}, V),
    "M1006": CommandInfo(
        "Correct nozzle height (X-Plus 5 / X-Smart 5)",
        "Tell the printer its exact nozzle height after measuring the bed.",
        "QIDI's profiles write it right after moving to Z 10 at the end of bed "
        "leveling, with a value a little off 10 that depends on the first-layer "
        "nozzle temperature (10 at 200 °C, lower when hotter). QIDI hasn't published "
        "the macro; it is believed to compensate for the nozzle growing as it heats.",
        {"Z": "Nozzle height to assume (mm)"}, C, _describe_z_set),
    "G92_": CommandInfo(
        "Correct nozzle height (X-Max 4)",
        "Tell the printer its exact nozzle height after measuring the bed.",
        "The X-Max 4 profile's version of M1006 (see there). QIDI hasn't published "
        "it; it is believed to compensate for the nozzle growing as it heats.",
        {"Z": "Nozzle height to assume (mm)"}, C, _describe_z_set),
    "G29": CommandInfo(
        "Measure the bed", "Probe the bed so the nozzle can follow its shape.",
        "No bed is perfectly flat. QIDI's G29 macro homes, measures the nozzle "
        "height, then probes a grid of points — on the X-Plus 4 and Q1 Pro only the "
        "area the print covers (adaptive mesh) — and saves the map. The printer then "
        "adjusts the nozzle height as it moves.", {}, V),
    "G29.0": CommandInfo("Clear bed map", "Forget the saved bed-leveling map.",
                         "QIDI's X-Max 4 macro: runs BED_MESH_CLEAR, so the bed is "
                         "measured fresh.", {}, V),
    "Z_TILT_ADJUST": CommandInfo(
        "Level the gantry (Klipper)", "Make the bed/gantry level by adjusting each Z motor.",
        "The printer probes the bed at a few points and turns its Z motors "
        "separately until both sides are at the same height."),
    "PROBE": CommandInfo(
        "Probe once (Klipper)", "Lower the nozzle until the bed sensor triggers.",
        "Measures the bed height at the current position. QIDI uses it with "
        "samples=1 just before the purge line.",
        {"_args": "samples = how many times to measure"}),
    "LOG_Z": CommandInfo(
        "Save height for power-loss recovery", "Remember the current nozzle height.",
        "QIDI's Q1 Pro macro writes the current Z to the printer's saved variables at "
        "every layer, so a print can resume after a power cut.", {}, V),
    "MOVE_TO_TRASH": CommandInfo(
        "Park over the waste chute", "Move the nozzle to the back, over the waste chute.",
        "QIDI's macro homes X and Y if needed and moves to the purge spot at the "
        "back of the printer, next to the silicone wiper. Used before flushing "
        "filament or cutting it.", {}, V),
    "EXTRUSION_AND_FLUSH": CommandInfo(
        "Flush new filament", "Push filament through the nozzle until the new color is clean.",
        "QIDI's macro parks over the waste chute, heats the nozzle and pushes "
        "filament out in several rounds, cooling and shaking the blob off "
        "(CLEAR_FLUSH) between rounds.",
        {"_args": "HOTEND = nozzle temperature (°C)"}, V),
    "DISABLE_ALL_SENSOR": CommandInfo(
        "Filament sensors off", "Ignore the filament sensors for now.",
        "QIDI's macro switches off the run-out sensor (and the Box's motion sensor) "
        "so loading, cutting and purging don't trigger a false run-out pause.", {}, V),
    "ENABLE_ALL_SENSOR": CommandInfo(
        "Filament sensors on", "Watch for filament run-out again.",
        "QIDI's macro switches the run-out sensor (and the Box's motion sensor) back "
        "on once printing starts.", {}, V),
    "SET_PRINT_STATS_INFO": CommandInfo(
        "Layer info (Klipper)", "Tell the printer the current or total layer count.",
        "Klipper shows these numbers on the screen and in the web interface.",
        {"_args": "TOTAL_LAYER = layers in the print, CURRENT_LAYER = layer starting now"},
        describe=_describe_stats),
    "SET_PRINT_MAIN_STATUS": CommandInfo(
        "Screen status", "Set the status shown on the printer's screen.",
        "From QIDI's print_stats_manager module (published with the X-Max 4 "
        "firmware). It only changes what the screen and app show.",
        {"_args": "MAIN_STATUS = print_start, printing, print_end, ..."}, V,
        _describe_status),
    "SET_PRINT_SUB_STATUS": CommandInfo(
        "Screen step", "Set the current step shown on the printer's screen.",
        "From QIDI's print_stats_manager module (published with the X-Max 4 "
        "firmware). It only changes what the screen and app show.",
        {"_args": "SUB_STATUS = tool_head_reset, wait_bed_temp, clear_nozzle, ..."}, V,
        _describe_status),
    "SET_HEATER_TEMPERATURE": CommandInfo(
        "Set a heater (Klipper)", "Set the nozzle, bed or chamber temperature.",
        "Klipper's own way of setting a heater. WAIT=1 is a QIDI addition seen in "
        "its X-Plus 4 profile.", {"_args": "HEATER = extruder / heater_bed / chamber, "
                                           "TARGET = °C"},
        describe=_describe_heater),
    "SET_PRESSURE_ADVANCE": CommandInfo(
        "Pressure advance (Klipper)", "Tune how the extruder anticipates speed changes.",
        "Pressure builds up in the nozzle and lags behind the extruder. Pressure "
        "advance compensates so corners and line ends come out even. The value comes "
        "from the filament profile.", {"_args": "ADVANCE = strength (0 = off)"},
        describe=_describe_simple_args("Set pressure advance to {advance}. It pushes "
                                       "filament slightly earlier when the nozzle speeds "
                                       "up, so corners and line ends come out even.")),
    "SET_INPUT_SHAPER": CommandInfo(
        "Input shaping (Klipper)", "Change the vibration-cancelling settings.",
        "Input shaping shapes each move so the frame doesn't ring, which removes "
        "ripples (“ghosting”) next to sharp corners."),
    "TIMELAPSE_TAKE_FRAME": CommandInfo(
        "Timelapse photo", "Take one timelapse picture with the camera.",
        "From the Moonraker timelapse add-on QIDI ships. Ignored if timelapse is off."),
    "CLEAR_PAUSE": CommandInfo("Clear pause (Klipper)",
                               "Forget any earlier pause before starting."),
    "M0": CommandInfo("Pause", "Pause the print until you resume it on the screen.",
                      "On QIDI's Klipper printers M0 runs the PAUSE macro: it pulls the "
                      "filament back, lifts the nozzle and parks it over the waste chute.",
                      source=V),
    "M25": CommandInfo("Pause", "Pause the print until you resume it on the screen.",
                       "On QIDI's Klipper printers M25 runs the same PAUSE macro as M0.",
                       source=V),
    "M84": CommandInfo(
        "Motors off", "Turn off the motors so they can be moved by hand.",
        "QIDI's macro turns off the X, Y and extruder motors but keeps the Z motors "
        "on, so the bed doesn't sink.", source=V),
    "T": CommandInfo(
        "Change filament", "Switch to another filament.",
        "With a QIDI Box, T0–T15 load the Box slot mapped to that filament (each Box "
        "holds four). QIDI's tool-change code around the T line cuts the old filament, "
        "parks over the waste chute, pulls the old filament back (UNLOAD_T…) and "
        "flushes the new one.", {}, V, _describe_tool),
    # QIDI Box: compiled module, no source.
    "BOX_PRINT_START": CommandInfo(
        "Box: prepare first filament", "Load the first filament from the QIDI Box.",
        "Called by PRINT_START before the first flush. " + _BOX_NOTE,
        {"_args": "EXTRUDER = first filament slot, HOTENDTEMP = nozzle °C"}, C),
    "TOOL_CHANGE_START": CommandInfo(
        "Box: filament change starts", "Mark the start of a filament change.",
        "Believed to tell the Box firmware a change is in progress, so a pause or "
        "error during it can be recovered. " + _BOX_NOTE,
        {"_args": "F = filament being replaced, T = new filament (counting from 0)"}, C),
    "TOOL_CHANGE_END": CommandInfo(
        "Box: filament change ends", "Mark the end of a filament change.", _BOX_NOTE,
        {}, C),
    "CUT_FILAMENT": CommandInfo(
        "Cut filament", "Cut the filament above the nozzle.",
        "The print head drives against a lever at the side of the printer, which "
        "works a blade inside the head (QIDI's published CUT_FILAMENT_1 macro shows "
        "the move). " + _BOX_NOTE, {"_args": "T = filament being cut"}, C),
    "UNLOAD_FILAMENT": CommandInfo(
        "Unload filament", "Pull the filament out of the print head at the end.",
        "QIDI's end code uses it with the last filament, believed so the Box can "
        "rewind it. " + _BOX_NOTE, {"_args": "T = filament to unload"}, C),
    "CLEAR_FLUSH": CommandInfo(
        "Shake off purge blob", "Knock the purged plastic off the nozzle into the chute.",
        "QIDI's X-Plus 4 code moves the head a few mm back and forth before it, "
        "believed to break off the purged plastic. " + _BOX_NOTE, {}, C),
    "CLEAR_OOZE": CommandInfo(
        "Wipe ooze", "Wipe off plastic oozing from the nozzle after a flush.",
        "Believed to wipe the nozzle on the silicone brush. " + _BOX_NOTE, {}, C),
    "DISABLE_BOX_HEATER": CommandInfo(
        "Box heater off", "Turn off the QIDI Box's heater.",
        "The Box can heat (dry) its filament. QIDI's PRINT_END and CANCEL_PRINT "
        "macros call this too. " + _BOX_NOTE, {}, C),
    "BOX_TEMP_SET": CommandInfo(
        "Box heater", "Set the QIDI Box heater for a filament.",
        "QIDIStudio writes it at the start. " + _BOX_NOTE,
        {"_args": "VT0, VT1, ... = °C for filament 1, 2, ... (0 = off)"}, C,
        _describe_box_temp),
    "BUFFER_MONITORING": CommandInfo(
        "Box: filament buffer watch", "Turn watching of the Box's filament buffer on or off.",
        "The buffer takes up slack between the Box and the print head. Believed to be "
        "switched off while filament is loaded or cut, so the moves don't look like "
        "a jam. " + _BOX_NOTE, {"_args": "ENABLE = 1 on, 0 off"}, C),
    "INIT_SYNC_BUFFER_STATE": CommandInfo(
        "Box: reset filament buffer", "Reset the Box's filament buffer after a change.",
        _BOX_NOTE, {}, C),
    "INIT_MAPPING_VALUE": CommandInfo(
        "Box: reset slot mapping", "Reset which Box slot feeds which filament.",
        "Believed to load the filament-to-slot mapping chosen when the print was "
        "sent. " + _BOX_NOTE, {}, C),
}

# UNLOAD_T0 ... UNLOAD_T15: QIDI's box1.cfg-box4.cfg macros, one per filament.
_QIDI_COMMANDS.update({
    f"UNLOAD_T{n}": CommandInfo(
        "Unload filament to the Box", "Pull one filament back into its QIDI Box slot.",
        "QIDI's macro runs EXTRUDER_UNLOAD for the Box slot mapped to this filament.",
        {}, V, _describe_unload)
    for n in range(16)})

COMMANDS: dict[str, CommandInfo] = {
    **common.marlin_commands(
        "QIDIStudio", _FANS,
        "Speed S runs from 0 (off) to 255 (full)."),
    # Klipper commands written by OrcaSlicer/QIDIStudio, shared with the Kobra profile.
    **{code: anycubic.COMMANDS[code] for code in (
        "SET_VELOCITY_LIMIT", "EXCLUDE_OBJECT_DEFINE", "EXCLUDE_OBJECT_START",
        "EXCLUDE_OBJECT_END", "EXCLUDE_OBJECT", "PAUSE", "RESUME", "CANCEL_PRINT")},
    **_QIDI_COMMANDS,
}

# ---------------------------------------------------------------- comments

_FEATURES = {
    **prusa._FEATURES,  # QIDISlicer (PrusaSlicer) names
    **bambu._FEATURES,  # QIDIStudio / OrcaSlicer names
    "Internal Bridge": "A bridge printed inside the part, over sparse infill, so the "
                       "solid layers above have something to rest on.",
    "Custom": "Code from the printer or filament profile (start/end code), not "
              "generated from the model.",
}

COMMENT_MARKERS = [
    *(marker(rf"^(?:TYPE|FEATURE):\s*{re.escape(name)}\s*$", f"Section: {name}",
             f"Slicer note: the following lines print the “{name}”. {text} "
             "The printer itself ignores comments.")
      for name, text in _FEATURES.items()),
    marker(r"^(?:TYPE|FEATURE):\s*(.+)$", "Section: {0}",
           "Slicer note: the following lines print the “{0}” part of the model."),
    marker(r"^(?:LAYER_CHANGE|CHANGE_LAYER)$", "Layer change",
           "Slicer note: a new layer starts here. Everything until the next layer change "
           "is printed at one height."),
    marker(r"^BEFORE_LAYER_CHANGE$", "Before layer change",
           "Slicer note: the printer profile's layer-change code follows."),
    marker(r"^Z:([-\d.]+)$", "Layer height marker",
           "Slicer note: this layer is printed at Z = {0} mm."),
    marker(r"^Z_HEIGHT:\s*([-\d.]+)", "Layer height marker",
           "Slicer note: this layer's top is {0} mm above the bed."),
    marker(r"^([-\d.]+)$", "Layer height marker",
           "Note from QIDI's layer-change code: this layer is printed at Z = {0} mm."),
    marker(r"^(?:LAYER_)?HEIGHT:\s*([-\d.]+)$", "Layer thickness",
           "Slicer note: lines here are {0} mm thick."),
    marker(r"^(?:LINE_)?WIDTH:\s*([-\d.]+)$", "Line width",
           "Slicer note: lines here are {0} mm wide (the nozzle is usually 0.4 mm)."),
    marker(r"^WIPE_START", "Wipe starts",
           "Slicer note: the nozzle drags back along the line it just printed while "
           "pulling filament in, to avoid a blob or string."),
    marker(r"^WIPE_END", "Wipe ends", "Slicer note: end of the wipe move."),
    marker(r"^OBJECT_ID:\s*(\d+)", "Object #{0}",
           "Slicer note: the following lines belong to object #{0} on the plate."),
    marker(r"^_SET_FAN_SPEED_CHANGING_LAYER", "Fan speed marker",
           "Slicer note: a marker the slicer uses while working out fan speeds per "
           "layer. The printer ignores it."),
    marker(r"^FLUSH_START", "Flush starts",
           "Slicer note: after a filament change the old color is pushed out through "
           "the nozzle into the waste chute until the new color comes out clean."),
    marker(r"^FLUSH_END", "Flush ends", "Slicer note: end of the color flush."),
    marker(r"^VT(\d+)(?:\s+H(-?\d+))?", "Filament marker",
           "QIDIStudio note: filament {0} (counting from 0) is in use from here. "
           "QIDIStudio reads it back to color the preview; the printer ignores it."),
    marker(r"^MACHINE_START_GCODE_END", "Start code ends",
           "Slicer note: the printer's start routine is finished. The model itself "
           "starts printing after this."),
    marker(r"^MACHINE_END_GCODE_START", "End code starts",
           "Slicer note: the model is done. What follows parks the nozzle, cools down "
           "and unloads the filament."),
    marker(r"^(?:filament (start|end) gcode|filament gcode)", "Filament code",
           "Slicer note: commands from the filament profile follow."),
    marker(r"^(?:Filament-specific end gcode|END gcode for filament)", "Filament code",
           "Slicer note: commands from the filament profile follow."),
    marker(r"^timelapse", "Timelapse",
           "Slicer note: the camera takes a timelapse picture at this layer."),
    marker(r"^TIMELAPSE_TAKE_FRAME$", "Timelapse (disabled)",
           "A switched-off timelapse command written by the slicer. The printer "
           "ignores it."),
    marker(r"^QIDIStudio\s+(\S+)", "Made by QIDIStudio {0}",
           "This file was sliced with QIDIStudio (QIDI's slicer) version {0}."),
    marker(r"^generated by (\S+ \S+)", "Made by {0}", "This file was sliced with {0}."),
    marker(r"^(HEADER|THUMBNAIL|EXECUTABLE|CONFIG)_BLOCK_(START|END)", "{0} block {1}",
           "Slicer note: marks the {0} section of the file (header, preview image, "
           "printable code or settings). The printer ignores it."),
    marker(r"^thumbnail\w* (?:begin|end|\d+x\d+)", "Preview image",
           "Slicer note: an encoded preview picture of the model for the printer's screen."),
    marker(r"^[A-Za-z0-9+/]{16,}={0,2}$|^[A-Za-z0-9+/]+={1,2}$", "Preview image data",
           "Part of the encoded preview picture. The printer ignores it."),
    marker(r"^total filament (\w+) \[(.+?)\]\s*:\s*(.+)$", "Filament {0}",
           "Slicer estimate: the print uses {2} {1} of filament ({0})."),
    marker(r"^(?:prusaslicer|qidislicer)_config = (begin|end)", "Slicer settings block",
           "Slicer note: a record of every slicer setting used. The printer ignores it."),
    marker(r"^total layer number:\s*(\d+)", "Layer count",
           "Slicer note: this print has {0} layers."),
    marker(r"^max_z_height:\s*([-\d.]+)", "Print height",
           "Slicer note: the print is {0} mm tall."),
    marker(r"^(.+?) extrusion width = (.+)$", "Line width: {0}",
           "Slicer note: {0} lines are {1} wide."),
    marker(r"^Override pressure advance value", "Pressure-advance note",
           "Note from the filament profile: this line sets the filament's own "
           "pressure-advance value."),
    *common.GENERIC_MARKERS,
    marker(r"^([a-z_]+):\s*(.+)$", "Slicer info: {0}",
           "Written by the slicer: {0} = {1}. The printer ignores it."),
    marker(r"^([A-Za-z][A-Za-z0-9 _()\[\]^/%.-]*?)\s*=\s*(.*)$", "Slicer info: {0}",
           "Written by the slicer: {0} = {1}. The printer ignores it."),
]

# ---------------------------------------------------------------- detection

_QIDI = re.compile(
    r"QIDIStudio|QIDISlicer|printer_(?:model|settings_id) = (?:Qidi |QIDI )?"
    r"(?:X-Max|X-Plus|X-Smart|X-CF|Q1 Pro|Q2)|^\s*(?:MOVE_TO_TRASH|SET_PRINT_MAIN_STATUS)\b",
    re.M)


def _detect(sample: str) -> float:
    if _QIDI.search(sample):
        return 1.0
    if "qidi" in sample.lower():
        return 0.5
    return 0.1


PROFILE = Profile(
    key="qidi",
    name="QIDI",
    description=("QIDI Q1 Pro, Q2/Q2C, X-Max 3/4, X-Plus 3/4/5, X-Smart 3/5 and the "
                 "older X-Plus, X-Max and X-CF Pro (QIDIStudio, OrcaSlicer or "
                 "QIDISlicer G-code)"),
    commands=COMMANDS,
    comment_markers=COMMENT_MARKERS,
    detect=_detect,
    vendor="QIDI",
)
