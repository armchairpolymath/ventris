"""Bambu Lab printers (X1, P1, A1 families).

Bambu firmware is Marlin-derived: standard codes (G1, M104, ...) behave like
Marlin and are marked "documented". Bambu also adds many private codes that it
does not publish documentation for; those are marked "community" and the text
is based on the comments Bambu Studio writes next to them plus community
reverse-engineering. Treat "community" explanations as best understanding.
"""

from __future__ import annotations

import re

from ..parser import ParsedLine
from ..reference import CommandInfo, CommentMarker, Profile, num
from ..state import MachineState

C = "community"

# ---------------------------------------------------------------- describers


def _speed(feed: float | None) -> str:
    return f"{num(feed / 60, digits=1)} mm/s" if feed else ""


def _describe_move(line: ParsedLine, before: MachineState, after: MachineState) -> str:
    relative = before.positioning == "relative"
    axes = [(a, line.number(a)) for a in "XYZ" if line.number(a) is not None]
    e = line.number("E")
    if e is not None and before.extrusion == "absolute" and not relative:
        e = (after.e - before.e) if before.e is not None else e
    feed = line.number("F")

    if not axes and e is None:
        if feed is not None:
            return (f"Set the speed for the next moves to {_speed(feed)} "
                    f"({num(feed)} mm/min). Nothing moves on this line.")
        return "A move command with nothing to move. The printer does nothing."

    if not axes:
        if e > 0:
            text = (f"Push {num(e)} mm of filament out of the nozzle without moving. "
                    "This refills the nozzle after a retraction (or primes it).")
        else:
            text = (f"Retract: the printer pulls the filament back {num(-e)} mm so "
                    "molten plastic doesn't ooze or string while the nozzle travels.")
        return text + (f" Speed {_speed(feed)}." if feed else "")

    if relative:
        where = "Move the nozzle by " + ", ".join(
            f"{a} {'+' if v >= 0 else ''}{num(v)} mm" for a, v in axes)
    else:
        where = "Move the nozzle to " + ", ".join(f"{a} {num(v)} mm" for a, v in axes)
    if axes == [("Z", line.number("Z"))]:
        where = where.replace("Move the nozzle to", "Change the nozzle height to", 1)
        where = where.replace("Move the nozzle by", "Change the nozzle height by", 1)

    if e is None:
        what = " without printing (a “travel” move)"
    elif e > 0:
        what = f" while pushing out {num(e)} mm of filament — this is the actual printing"
    else:
        what = (f" while pulling the filament back {num(-e)} mm (a “wipe”, which "
                "cleans the nozzle on the part)")
    speed = f" at {_speed(feed)}" if feed else ""
    return f"{where}{what}{speed}."


def _describe_arc(line: ParsedLine, before: MachineState, after: MachineState) -> str:
    direction = "clockwise" if line.code == "G2" else "counter-clockwise"
    end = ", ".join(f"{a} {num(line.number(a))}" for a in "XYZ" if line.has(a))
    center = ", ".join(f"{a} {num(line.number(a))}" for a in "IJ" if line.has(a))
    if end:
        text = f"Move along a {direction} curve ending at {end} mm"
    else:
        text = f"Move in a full {direction} circle back to where the nozzle started"
    if center:
        text += f", turning around a center point offset by {center} mm from the start"
    if line.has("E"):
        text += f", extruding {num(line.number('E'))} mm of filament"
    return text + "."


def _describe_temp(heater: str, wait: bool):
    def describe(line: ParsedLine, before: MachineState, after: MachineState) -> str:
        target = line.number("S")
        if target is None:
            return f"Change the {heater} temperature (no target given)."
        if target == 0:
            return f"Turn the {heater} heater off."
        if wait and line.has("H"):
            limit = line.params["H"]
            return (f"Bambu variant: set the {heater} target to {num(target)} °C and wait, "
                    f"with H{limit} as a temperature limit. Bambu doesn't document H; it "
                    f"is believed to let the wait finish once the {heater} is within the "
                    f"{num(target)}–{limit} °C range (e.g. “cool to at most {limit} °C” "
                    "before the nozzle touches the bed).")
        if wait:
            return (f"Set the {heater} to {num(target)} °C and wait until it gets there. "
                    "The printer pauses here until the temperature is reached.")
        return (f"Set the {heater} to {num(target)} °C and carry on right away — "
                "it heats in the background.")
    return describe


_FANS = {1: "part-cooling fan (on the toolhead)", 2: "auxiliary (side) fan",
         3: "chamber (exhaust) fan"}


def _describe_fan(line: ParsedLine, before: MachineState, after: MachineState) -> str:
    fan = _FANS.get(int(line.number("P") or 1), f"fan #{num(line.number('P'))}")
    if line.code == "M107":
        return f"Turn off the {fan}."
    speed = line.number("S")
    speed = 255 if speed is None else speed
    pct = round(speed / 255 * 100)
    return f"Turn off the {fan}." if pct == 0 else f"Set the {fan} to {pct}% speed."


def _describe_dwell(line: ParsedLine, before: MachineState, after: MachineState) -> str:
    if line.has("S"):
        return f"Pause for {num(line.number('S'))} seconds."
    if line.has("P"):
        return f"Pause for {num(line.number('P'))} milliseconds."
    return "Pause briefly."


def _describe_wait(line: ParsedLine, before: MachineState, after: MachineState) -> str:
    text = ("Wait until every move already queued has finished before reading the "
            "next line.")
    if line.has("S"):
        text += f" Then wait another {num(line.number('S'))} seconds."
    elif line.has("P"):
        text += f" Then wait another {num(line.number('P'))} ms."
    return text


def _describe_home(line: ParsedLine, before: MachineState, after: MachineState) -> str:
    axes = [a for a in "XYZ" if line.has(a)]
    text = ("Home " + (" and ".join(axes) + " only" if axes else "all axes") +
            ": move until the printer finds its reference position, so it knows "
            "exactly where the nozzle is.")
    if line.has("T"):
        text += f" T{num(line.number('T'))} allows the nozzle to be that hot while homing."
    if line.has("P") and line.number("P") == 0:
        text += " P0 means a quicker, low-precision home."
    return text


def _describe_set_position(line, before, after) -> str:
    parts = [f"{a} = {num(line.number(a))}" for a in "XYZE" if line.number(a) is not None]
    if parts == ["E = 0"]:
        return ("Reset the filament counter to zero. Nothing moves; the printer just "
                "starts counting extrusion from 0 again.")
    return ("Tell the printer its current position is " + ", ".join(parts) +
            ". Nothing moves — it just relabels where it is.")


def _describe_progress(line, before, after) -> str:
    parts = []
    if line.has("P"):
        parts.append(f"the print is {num(line.number('P'))}% done")
    if line.has("R"):
        parts.append(f"about {num(line.number('R'))} minutes remain")
    if line.has("L"):
        parts.append(f"it is now on layer {num(line.number('L'))}")
    if not parts:
        return "Update the progress shown on the printer's screen."
    return "Update the printer's screen: " + ", ".join(parts) + "."


def _describe_percent(what: str):
    def describe(line, before, after) -> str:
        if line.code == "M220" and line.has("B"):
            return "Remember the current speed multiplier so it can be restored later."
        if line.code == "M220" and line.has("R"):
            return "Restore the speed multiplier saved earlier with M220 B."
        if line.code == "M221":
            soft = _describe_soft_endstops(line)
            if soft:
                return soft
        value = line.number("S")
        if value is None:
            return f"Adjust the {what} multiplier."
        return f"Set the {what} multiplier to {num(value)}% ({'normal' if value == 100 else 'not normal'})."
    return describe


def _describe_soft_endstops(line: ParsedLine, before=None, after=None) -> str | None:
    # P1/X1 firmware reuses M221 for software travel limits ("soft endstops");
    # A1 firmware uses the Marlin-standard M211 the same way.
    code = line.code
    if line.has("S") and line.params["S"] == "":
        return ("Save the current soft-endstop settings (Bambu's “push”), so they can "
                f"be restored later with {code} R.")
    if line.has("R"):
        return f"Restore the soft-endstop settings saved earlier with {code} S (“pop”)."
    if code == "M211" and line.has("S"):
        return f"Turn {'on' if line.number('S') else 'off'} the software travel limits."
    axes = [a for a in "XYZ" if line.has(a)]
    if axes:
        state = "off" if all(line.number(a) == 0 for a in axes) else "on"
        return (f"Turn {state} the software travel limits for {', '.join(axes)}. With them "
                "off the printer will move past its normal limits — used for nozzle "
                "wiping and calibration.")
    return None


def _describe_motor_current(line, before, after) -> str:
    if line.has("S") and not line.params["S"]:
        return "Remember the current motor power settings (so M17 R can restore them)."
    if line.has("R"):
        return "Restore the motor power settings saved by M17 S."
    axes = [f"{a} {line.params[a]}" for a in "XYZE" if line.has(a) and line.params[a]]
    if axes:
        return ("Set motor current (power) for " + ", ".join(axes) +
                ". Lower current makes a motor gentler — Bambu does this so a crash "
                "into the bed does less damage.")
    if line.has("D"):
        return ("Bambu variant M17 D. Not documented; it follows a step where motor "
                "current was lowered, so it is believed to restore the default currents.")
    return "Turn the stepper motors on (they hold their position firmly)."


def _args(line: ParsedLine) -> str:
    return line.params.get("_args", "")


_CLAIM_ACTIONS = {
    "0": "clear the status message (normal printing)",
    "1": "“Auto bed leveling”",
    "2": "“Heatbed preheating”",
    "3": "“Checking the motion system” (vibration test)",
    "4": "“Changing filament”",
    "8": "“Calibrating extrusion”",
    "24": "“Preparing temperature and material”",
    "13": "“Homing toolhead”",
    "14": "“Cleaning nozzle tip”",
    "54": "“Heatbed preheating”",
}

_FLAGS = {
    "g29_before_print_flag": "whether “Bed leveling” was ticked when the print was sent",
    "timelapse_record_flag": "whether timelapse recording is turned on",
    "extrude_cali_flag": "whether flow calibration was ticked when the print was sent",
    "filament_need_cali_flag": "whether this filament still needs calibrating",
    "build_plate_detect_flag": "whether build-plate detection is turned on",
    "g39_detection_flag": "whether nozzle clump detection is turned on",
    "g39_3rd_layer_detect_flag": "whether the nozzle clump check on layer 3 is turned on",
    "g39_mass_exceed_flag": "whether the printer estimates too much plastic is stuck "
                            "to the nozzle (see M1007)",
}


def _describe_m1002(line, before, after) -> str:
    args = _args(line)
    key, _, value = (part.strip() for part in args.partition(":"))
    if key.startswith("gcode_claim_action"):
        label = _CLAIM_ACTIONS.get(value)
        if label is None:
            return f"Show status stage #{value} on the printer's screen."
        if value == "0":
            return f"Tell the printer's screen to {label}."
        return f"Show the status {label} on the printer's screen."
    if key.startswith("judge_flag"):
        flag = key.split(None, 1)[1] if " " in key else value
        meaning = _FLAGS.get(flag, "a printer setting")
        return (f"Check the flag “{flag}” ({meaning}). The M622 block that follows only "
                "runs if the answer matches.")
    if key.startswith("set_filament_type"):
        return f"Tell the printer the filament type is {value}."
    if key.startswith("set_gcode_claim_speed_level"):
        return (f"Set Bambu's internal speed level to {value}. The exact meaning isn't "
                "public; it appears to tie into the speed mode shown on the printer.")
    if key.startswith("judge_last_extrude_cali_success"):
        return ("Check whether the last extrusion calibration succeeded. The M622 "
                "block that follows runs based on the answer — here, J0 repeats the "
                "calibration if it failed.")
    if key.startswith("set_flag"):
        return f"Set the printer flag {value or key.split(None, 1)[-1]}."
    return "A Bambu control command (" + args + ")."


def _describe_tool(line, before, after) -> str:
    n = int(line.code[1:])
    if n < 255:
        return (f"Switch to filament T{n} — AMS slot {n + 1} (if the slicer mapping "
                "matches). The AMS swaps the filament feeding the nozzle.")
    if n == 255:
        return ("Unload: pull the current filament out of the nozzle and back toward "
                "the AMS/spool, leaving the nozzle empty.")
    if n == 1000:
        return ("Bambu special tool select used before the purge line: keep using the "
                "filament that is already loaded.")
    return f"Bambu special tool command T{n} (internal use)."


def _describe_conditional(line, before, after) -> str:
    j = line.params.get("J", line.params.get("S", ""))  # A1 firmware writes S
    want = {"1": "yes (the flag is on)", "0": "no (the flag is off)"}.get(j, j)
    return (f"Start a conditional block: the lines up to the next M623 only run if the "
            f"last M1002 check answered {want}. Otherwise the printer skips them.")


def _describe_ams_start(line, before, after) -> str:
    if line.has("S"):
        s = line.params["S"]
        if s == "255":
            return ("Begin the AMS unload sequence (everything until M621 S255 pulls the "
                    "filament back out).")
        if s.isdigit():
            return (f"Begin an AMS filament change to T{s} (slot {int(s) + 1}). "
                    "Lines until the matching M621 perform the swap"
                    + ("; the A means only if an AMS is connected." if line.has("A") else "."))
    if line.has("M"):
        return "Bambu AMS setup command (M620 M) — prepares the AMS before the first filament change."
    return "Bambu AMS (automatic material system) control command."


def _describe_lamp(line, before, after) -> str:
    state = "on" if line.number("P") == 1 else "off"
    lights = {"1": "laser 1 (Bambu's comment: “turn off laser”)",
              "2": "laser 2 (Bambu's comment: “turn off laser”)",
              "4": "the nozzle light", "5": "the logo light"}
    which = lights.get(line.params.get("S", ""), f"light #{line.params.get('S', '?')}")
    return f"Turn {state} {which}."


def _describe_pressure_advance(line, before, after) -> str:
    if line.has("K") and line.params["K"]:
        return (f"Set pressure advance to K = {line.params['K']}. Higher K pushes "
                "filament slightly earlier when speeding up and eases off sooner when "
                "slowing down, so corners and line ends come out even.")
    if line.has("S") and not line.params["S"]:
        return ("Bambu variant M900 S: believed to save the current pressure-advance "
                "settings before a calibration test (M900 R restores them).")
    if line.has("R") and not line.params["R"]:
        return "Bambu variant M900 R: believed to restore the pressure-advance settings saved by M900 S."
    if line.has("C") and not line.params["C"]:
        return ("Bambu variant M900 C: undocumented; used just before the extrusion "
                "calibration test line, believed to clear the current compensation.")
    return "Change pressure-advance (linear advance) settings."


def _unknown_purpose(context: str):
    def describe(line, before, after) -> str:
        return f"Bambu command whose exact purpose isn't public. {context}"
    return describe


def _switch(feature: str):
    """Describer for commands whose S1/S0 turns something on/off."""
    def describe(line, before, after) -> str:
        value = line.number("S")
        if value is None:
            return f"Change the {feature} setting."
        return f"Turn {'on' if value else 'off'} {feature}."
    return describe


# ---------------------------------------------------------------- reference

_MOVE_PARAMS = {
    "X": "Left/right position (mm)",
    "Y": "Front/back position (mm)",
    "Z": "Height (mm). On P1/X1 printers the bed moves down; on A1 the gantry moves up.",
    "E": "Filament to push (positive) or pull back (negative), in mm",
    "F": "Speed in mm per minute (divide by 60 for mm/s). Stays in effect for later moves.",
}

COMMANDS: dict[str, CommandInfo] = {
    "G0": CommandInfo(
        "Move", "Move the nozzle in a straight line.",
        "G0 is the “rapid move”. On Bambu printers it behaves exactly like G1. "
        "Slicers use it mostly for travel moves.",
        _MOVE_PARAMS, describe=_describe_move),
    "G1": CommandInfo(
        "Move", "Move the nozzle in a straight line, optionally extruding plastic.",
        "G1 is the workhorse of a print — usually over 95% of the lines. Each G1 moves "
        "to a new point. If it has an E value, the extruder pushes filament at the same "
        "time, laying down a line of plastic. Without E it is a “travel” move. A "
        "negative E pulls filament back (“retraction”) to stop dripping. Whether the "
        "numbers are absolute positions or relative distances depends on G90/G91 and "
        "M82/M83 — see the machine state panel.",
        _MOVE_PARAMS, describe=_describe_move),
    "G2": CommandInfo(
        "Arc (clockwise)", "Move along a clockwise curve.",
        "Arcs let one line describe a smooth curve instead of many tiny straight "
        "segments. I and J give the curve's center relative to the start point.",
        {**_MOVE_PARAMS, "I": "Center offset in X from the start point (mm)",
         "J": "Center offset in Y from the start point (mm)", "P": "Number of full turns",
         "R": "Radius (mm), instead of I/J"}, describe=_describe_arc),
    "G3": CommandInfo(
        "Arc (counter-clockwise)", "Move along a counter-clockwise curve.",
        "Same as G2, but turning the other way. Bambu Studio uses G3 with a Z value for "
        "a quick spiral lift (“spiral Z hop”) before travelling.",
        {**_MOVE_PARAMS, "I": "Center offset in X from the start point (mm)",
         "J": "Center offset in Y from the start point (mm)", "P": "Number of full turns",
         "R": "Radius (mm), instead of I/J"}, describe=_describe_arc),
    "G4": CommandInfo("Dwell (pause)", "Do nothing for a set time.", "",
                      {"S": "Seconds", "P": "Milliseconds"}, describe=_describe_dwell),
    "G17": CommandInfo("Select XY plane for arcs",
                       "Arcs (G2/G3) will curve flat, in the left/right + front/back plane.",
                       "This is the normal setting for 3D printers; the slicer writes it "
                       "as a safety reset before arc moves."),
    "G20": CommandInfo("Use inches", "Numbers from here on are in inches.",
                       "Almost never used on 3D printers."),
    "G21": CommandInfo("Use millimetres", "Numbers from here on are in millimetres.",
                       "This is the normal setting; slicers write it to be explicit."),
    "G28": CommandInfo(
        "Home", "Find the printer's reference position (home).",
        "After power-on the printer doesn't know where the nozzle is. Homing moves each "
        "axis until a sensor triggers, then sets that point as known. With axis letters "
        "only those axes are homed.",
        {"X": "Home X", "Y": "Home Y", "Z": "Home Z",
         "P": "Bambu: precision (P0 = quick, low precision)",
         "T": "Bambu: highest nozzle temperature allowed while homing"},
        describe=_describe_home),
    "G29": CommandInfo(
        "Auto bed leveling", "Probe the bed at many points to map how flat it is.",
        "No bed is perfectly flat. The printer touches the bed in a grid and remembers "
        "the heights, then slightly raises or lowers the nozzle while printing to "
        "follow the surface. Bambu's version takes the area to probe.",
        {"A": "Bambu: probe only the area that will be printed (believed)",
         "X": "Bambu: start corner X of the probed area",
         "Y": "Bambu: start corner Y of the probed area",
         "I": "Bambu: width of the probed area (mm)",
         "J": "Bambu: depth of the probed area (mm)"}),
    "G29.1": CommandInfo(
        "Set Z offset (Bambu)", "Nudge the nozzle height slightly up or down.",
        "Bambu uses this to fine-tune first-layer height for a given plate — for "
        "example a small negative value for the Textured PEI plate, whose bumps make "
        "the probe read slightly high.",
        {"Z": "Offset in mm (negative = closer to the bed)"}, C),
    "G29.2": CommandInfo(
        "Bed leveling on/off (Bambu)",
        "Turn bed-leveling compensation on (S1) or off (S0).", "",
        {"S": "1 = use the bed map, 0 = ignore it"}, C, _switch("bed-leveling compensation (following the bed map)")),
    "G380": CommandInfo(
        "Probe move (Bambu)", "Move until something is touched, then stop.",
        "Bambu's own comment says this is the same as G38 (a probing move). It's used "
        "at startup to safely move the bed without crashing into the nozzle.",
        {"S": "Probe mode", "Z": "Distance to try to move (mm)", "F": "Speed (mm/min)"}, C),
    "G90": CommandInfo(
        "Absolute positioning", "Coordinates from here on are exact positions.",
        "With G90, “X100” means “go to the spot 100 mm from the origin”. "
        "Compare G91.", describe=None),
    "G91": CommandInfo(
        "Relative positioning", "Coordinates from here on are distances from where the nozzle is now.",
        "With G91, “X10” means “move 10 mm to the right of here”. Bambu's start "
        "script switches to G91 briefly to nudge the bed, then back to G90."),
    "G92": CommandInfo(
        "Set position", "Tell the printer “consider your current position to be …”.",
        "No motion happens. The most common use is G92 E0, which zeroes the "
        "extruder's counter.",
        {"X": "New X value", "Y": "New Y value", "Z": "New Z value", "E": "New extruder value"},
        describe=_describe_set_position),
    "M17": CommandInfo(
        "Motors on / motor current", "Turn on the motors or change how hard they push.",
        "In standard Marlin M17 just energizes the motors. Bambu also uses it to set "
        "motor current per axis (S saves the current setting, R restores it).",
        {"X": "Current factor for X", "Y": "Current factor for Y",
         "Z": "Current factor for Z", "S": "Save settings", "R": "Restore settings"},
        describe=_describe_motor_current),
    "M18": CommandInfo("Motors off", "Turn the motors off so they can be moved by hand."),
    "M84": CommandInfo("Motors off", "Turn the motors off so they can be moved by hand."),
    "M73": CommandInfo(
        "Progress update", "Update the progress bar and time remaining on the screen.",
        "The slicer sprinkles these through the file so the printer can show accurate "
        "progress.",
        {"P": "Percent done", "R": "Minutes remaining", "L": "Bambu: current layer",
         "E": "Bambu: internal (meaning not public)"}, describe=_describe_progress),
    "M73.2": CommandInfo("Time-estimate scale (Bambu)",
                         "Reset the multiplier used for the time-remaining estimate.", "",
                         {"R": "Multiplier (1.0 = normal)"}, C),
    "M82": CommandInfo(
        "Absolute extrusion", "E values from here on are a running total of filament used.",
        "Compare M83. Bambu Studio normally uses M83 (relative)."),
    "M83": CommandInfo(
        "Relative extrusion", "Each E value is the amount of filament for that move only.",
        "This is what Bambu Studio uses: “E.5” means “push 0.5 mm during this move”, "
        "rather than a running total."),
    "M104": CommandInfo("Set nozzle temperature", "Start heating (or cooling) the nozzle; don't wait.",
                        "", {"S": "Target temperature in °C (0 = off)"},
                        describe=_describe_temp("nozzle", wait=False)),
    "M109": CommandInfo("Set nozzle temperature and wait",
                        "Heat the nozzle and wait until it reaches the target.", "",
                        {"S": "Target temperature in °C",
                         "H": "Bambu: temperature limit (believed; undocumented)"},
                        describe=_describe_temp("nozzle", wait=True)),
    "M140": CommandInfo("Set bed temperature", "Start heating the bed; don't wait.",
                        "A warm bed helps the first layer stick.",
                        {"S": "Target temperature in °C (0 = off)"},
                        describe=_describe_temp("bed", wait=False)),
    "M190": CommandInfo("Set bed temperature and wait",
                        "Heat the bed and wait until it reaches the target.", "",
                        {"S": "Target temperature in °C"},
                        describe=_describe_temp("bed", wait=True)),
    "M141": CommandInfo("Set chamber temperature", "Set the enclosure air temperature (X1E/H2 series).",
                        "", {"S": "Target temperature in °C"},
                        describe=_describe_temp("chamber", wait=False)),
    "M191": CommandInfo("Set chamber temperature and wait",
                        "Heat the enclosure air and wait (X1E/H2 series).", "",
                        {"S": "Target temperature in °C"},
                        describe=_describe_temp("chamber", wait=True)),
    "M142": CommandInfo(
        "Chamber air control (Bambu)", "Automatic chamber-fan control based on temperature.",
        "Not publicly documented. It appears in the filament start code for PLA on "
        "enclosed printers; R and S look like low and high temperature thresholds (°C) "
        "that keep the chamber from getting too warm for PLA.",
        {"P": "Mode (believed)", "R": "Lower temperature (°C, believed)",
         "S": "Upper temperature (°C, believed)"}, C),
    "M106": CommandInfo(
        "Fan on", "Set a fan's speed.",
        "Speed S runs from 0 (off) to 255 (full). Bambu has up to three fans: "
        "P1 part-cooling on the toolhead (the default), P2 the big auxiliary side fan, "
        "P3 the chamber exhaust fan.",
        {"P": "Which fan: 1 part-cooling, 2 auxiliary, 3 chamber",
         "S": "Speed 0–255 (255 = 100%)"}, describe=_describe_fan),
    "M107": CommandInfo("Fan off", "Turn a fan off.", "",
                        {"P": "Which fan (default: part-cooling)"}, describe=_describe_fan),
    "M201": CommandInfo("Max acceleration", "Set the highest acceleration each axis may use.",
                        "Acceleration is how quickly a motor gets up to speed (mm/s²).",
                        {"X": "mm/s²", "Y": "mm/s²", "Z": "mm/s²", "E": "mm/s²"}),
    "M201.2": CommandInfo("Acceleration scale (Bambu)",
                          "Set a multiplier on all accelerations (1.0 = normal).", "",
                          {"K": "Multiplier"}, C),
    "M203": CommandInfo("Max speed", "Set the top speed allowed for each axis (mm/s).", "",
                        {"X": "mm/s", "Y": "mm/s", "Z": "mm/s", "E": "mm/s"}),
    "M204": CommandInfo(
        "Acceleration", "Set how quickly the printer speeds up and slows down.",
        "Lower acceleration gives cleaner outer walls; higher is faster. Bambu Studio "
        "changes this often — e.g. 500 for outer walls, 6000+ for travel.",
        {"S": "Acceleration for all moves (mm/s²)", "P": "Printing moves (mm/s²)",
         "R": "Retractions (mm/s²)", "T": "Travel moves (mm/s²)"}),
    "M205": CommandInfo(
        "Jerk / corner speed", "Set how abruptly the printer may change direction.",
        "The speed (mm/s) at which the printer can change direction without slowing "
        "to a stop.", {"X": "mm/s", "Y": "mm/s", "Z": "mm/s", "E": "mm/s"}),
    "M220": CommandInfo("Speed multiplier", "Scale all print speeds by a percentage.", "",
                        {"S": "Percent (100 = normal)", "B": "Back up current value",
                         "R": "Restore backed-up value"},
                        describe=_describe_percent("speed")),
    "M221": CommandInfo(
        "Flow multiplier / soft endstops",
        "Normally: scale the amount of plastic extruded. Bambu also uses it for travel limits.",
        "With S and a number it sets the flow percentage. Bambu firmware also uses M221 "
        "to turn software travel limits on/off (X0 Y0 Z0), save them (bare S) and "
        "restore them (R).",
        {"S": "Flow percent — or, with no number, save soft-endstop state",
         "R": "Restore soft-endstop state", "X": "X limit on/off", "Y": "Y limit on/off",
         "Z": "Z limit on/off"}, describe=_describe_percent("flow")),
    "M290": CommandInfo(
        "Baby-step / reset (Bambu)", "Small position adjustment; Bambu uses it in startup reset.",
        "In Marlin M290 nudges the position by tiny amounts. Bambu's start code calls it "
        "in its “reset machine status” section; the exact meaning of its values isn't public.",
        {}, C),
    "M400": CommandInfo("Wait for moves to finish",
                        "Pause reading the file until all queued moves are done.",
                        "The printer normally reads ahead. M400 forces it to catch up — "
                        "useful before taking a photo or changing settings.",
                        {"S": "Extra wait in seconds", "P": "Extra wait in milliseconds"},
                        describe=_describe_wait),
    "M412": CommandInfo("Filament runout sensor", "Turn filament runout detection on (S1) or off (S0).",
                        "When on, the printer pauses if the filament runs out.",
                        {"S": "1 = on, 0 = off"}, describe=_switch("filament runout detection")),
    "M500": CommandInfo("Save settings", "Save calibration/settings to the printer's memory.",
                        "Here it stores the fresh bed-leveling map."),
    "M620": CommandInfo(
        "AMS filament change start (Bambu)",
        "Begin an AMS (automatic filament changer) sequence.",
        "Everything between M620 and the matching M621 is the filament swap: cut the "
        "filament, move to the purge chute, load the new slot.",
        {"S": "Target filament (255 = unload)", "A": "Only if an AMS is connected",
         "M": "Setup/prepare"}, C, _describe_ams_start),
    "M620.1": CommandInfo("AMS feed settings (Bambu)",
                          "Set speeds/temperature used when the AMS feeds filament.", "",
                          {"E": "Extruder setting flag", "F": "Feed speed (mm/min)",
                           "T": "Temperature (°C)"}, C),
    "M620.11": CommandInfo("AMS retract/feed amount (Bambu)",
                           "Set how much filament to pull back or feed during the swap.", "",
                           {"S": "Enable", "I": "Filament index", "E": "Length in mm (− = retract)",
                            "F": "Speed (mm/min)"}, C),
    "M621": CommandInfo("AMS filament change end (Bambu)",
                        "End of the AMS filament change sequence started by M620.", "",
                        {"S": "Target filament (matches M620)", "A": "Only if an AMS is connected"}, C),
    "M622": CommandInfo("Conditional block start (Bambu)",
                        "Only run the following lines if the last M1002 check matched.",
                        "Lets one file adapt to the options you pick when starting the "
                        "print (bed leveling, timelapse, …). The block ends at M623.",
                        {"J": "Required answer: 1 = yes, 0 = no",
         "S": "Same as J (A1 firmware)"}, C, _describe_conditional),
    "M622.1": CommandInfo("Conditional default (Bambu)",
                          "Default answer for the next check, for older firmware.",
                          "Bambu's comment: “for prev firmware, default turned on”.",
                          {"S": "Default value"}, C),
    "M623": CommandInfo("Conditional block end (Bambu)",
                        "End of the block that started at M622.", "", {}, C),
    "M624": CommandInfo(
        "Object start (Bambu)", "The following lines print one specific object.",
        "Used for “skip object”: if you cancel one part on the printer's screen, it "
        "skips everything between this M624 and the matching M625. The odd text is an "
        "encoded object ID.", {"_args": "Encoded object ID"}, C),
    "M625": CommandInfo("Object end (Bambu)", "End of the lines that belong to one object.",
                        "Pairs with M624 for the skip-object feature.", {}, C),
    "M628": CommandInfo("Filament feed step start (Bambu)",
                        "Marks the start of a filament feed step during an AMS change.",
                        "Not publicly documented.", {"S": "Mode"}, C),
    "M629": CommandInfo("Filament feed step end (Bambu)",
                        "Marks the end of a filament feed step during an AMS change.",
                        "Not publicly documented.", {"S": "Mode"}, C),
    "M710": CommandInfo("Controller board fan (Bambu)",
                        "Control the fan that cools the printer's electronics.",
                        "Bambu's comment: “turn on MC fan by default (P1S)”.",
                        {"A": "Automatic mode", "S": "Speed 0–255"}, C),
    "M960": CommandInfo("Lights and lasers (Bambu)", "Turn one of the printer's lights or lasers on or off.", "",
                        {"S": "Which light (1/2 = lasers, 4 = nozzle, 5 = logo)", "P": "1 = on, 0 = off"},
        C, _describe_lamp),
    "M970.3": CommandInfo(
        "Vibration test (Bambu)", "Shake an axis to measure how the printer vibrates.",
        "Part of the “mech mode fast check”: the results let the printer cancel out "
        "vibrations (see M975), which allows faster printing with fewer ripples.",
        {"Q": "Axis (1 = X, 0 = Y, believed)"}, C),
    "M974": CommandInfo("Apply vibration test result (Bambu)",
                        "Process the results of the M970.3 vibration test.", "",
                        {"Q": "Axis"}, C),
    "M975": CommandInfo(
        "Vibration suppression (Bambu)", "Turn vibration compensation on (S1) or off (S0).",
        "Also called input shaping: the printer shapes its moves to cancel out "
        "its own vibrations, giving cleaner walls at high speed.", {"S": "1 = on, 0 = off"}, C, _switch("vibration suppression (input shaping)")),
    "M971": CommandInfo("Camera capture (Bambu)", "Trigger the printer camera (timelapse/AI checks).",
                        "Not publicly documented; appears at every layer change.", {}, C),
    "M981": CommandInfo("Spaghetti detection (Bambu)",
                        "Turn the camera's failed-print (“spaghetti”) detection on or off.",
                        "", {"S": "1 = on, 0 = off", "P": "Setting (believed sensitivity)"}, C, _switch("spaghetti (failed print) detection")),
    "M991": CommandInfo("Layer change notice (Bambu)",
                        "Tell the printer a new layer started (used for timelapse).", "",
                        {"S": "Mode", "P": "Layer number (−1 = end)"}, C),
    "M1002": CommandInfo(
        "Bambu control command", "Bambu-specific: status messages, option checks, and settings.",
        "M1002 takes a word instead of letters. “gcode_claim_action” shows a status "
        "on the screen, “judge_flag” checks an option you chose when sending the print "
        "(used by M622), and “set_…” values tell the printer about the job.",
        {"_args": "Sub-command and value"}, C, _describe_m1002),
    "M1003": CommandInfo("Power-loss recovery (Bambu)",
                         "Turn power-loss recovery on (S1) or off (S0).",
                         "When on, the printer can resume after a power cut.",
                         {"S": "1 = on, 0 = off"}, C, _switch("power-loss recovery")),
    "M1004": CommandInfo("External camera shutter (Bambu)",
                         "Trigger an external camera shutter (Bambu's comment).", "", {}, C),
    "G39": CommandInfo(
        "Nozzle clump check (Bambu A1)",
        "Check whether plastic has built up around the nozzle.",
        "Runs inside the “enable nozzle clog detect at 3rd layer” block. The A1 uses "
        "its nozzle sensor to detect a blob of plastic (“clump”) stuck to the nozzle, "
        "which can wreck a print. Exact method isn't public.",
        {"S": "Mode (S1 seen in Bambu Studio files)"}, C),
    "G39.3": CommandInfo(
        "Nozzle clump re-check (Bambu A1)",
        "A follow-up nozzle clump check.",
        "Runs only when the printer's mass estimate (M1007) says too much plastic "
        "may be stuck to the nozzle (flag g39_mass_exceed_flag). Clog detection "
        "(G392) is switched off around it.", {"S": "Mode"}, C),
    "G39.4": CommandInfo(
        "Build plate detection (Bambu)", "Check that a build plate is on the bed.",
        "Runs only if build-plate detection is enabled (build_plate_detect_flag). "
        "OpenBambuAPI: “fires a canned command to detect build plate”.", {}, C),
    "G29.4": CommandInfo(
        "Leveling-related (Bambu A1)", "Last command of the A1 start code; purpose isn't public.",
        "It belongs to the G29 bed-leveling family and runs right after mass "
        "estimation is turned on (M1007 S1), just before the model starts.", {}, C,
        _unknown_purpose("It's the last line of the A1 start code and belongs to the "
                         "G29 bed-leveling family.")),
    "G392": CommandInfo(
        "Nozzle clog detection (Bambu)", "Turn nozzle clog detection on (S1) or off (S0).",
        "Bambu's comment: “turn off nozzle clog detect”. The printer watches for signs "
        "that the nozzle is blocked. Bambu turns it off during startup and around "
        "steps that would trigger it falsely.", {"S": "1 = on, 0 = off"}, C,
        _switch("nozzle clog detection")),
    "G2814": CommandInfo(
        "Z calibration step (Bambu A1)", "Purpose isn't public.",
        "Appears once, right after the nozzle is lowered to Z 0.3 at the front of the "
        "bed and just before the extrusion calibration line. The Z value matches the "
        "first-layer height, so it is believed to be a first-layer height check.",
        {"Z": "Height in mm"}, C,
        _unknown_purpose("It runs with the nozzle just above the bed before the "
                         "calibration line; believed to be a first-layer height check.")),
    "M211": CommandInfo(
        "Soft endstops", "Turn the software travel limits on or off.",
        "In Marlin, M211 S1/S0 turns “soft endstops” on/off — limits that stop the "
        "printer moving past its edges. A1 firmware also uses X0 Y0 Z0 to turn them "
        "off per axis, bare S to save the setting and R to restore it (Bambu's "
        "comments: “push” and “pop”).",
        {"S": "1/0 = on/off; no number = save setting", "R": "Restore saved setting",
         "X": "X limit on/off", "Y": "Y limit on/off", "Z": "Z limit on/off"},
        describe=_describe_soft_endstops),
    "M900": CommandInfo(
        "Pressure advance", "Tune how the extruder anticipates speed changes.",
        "Pressure advance (Marlin calls it linear advance) compensates for pressure "
        "building up in the nozzle. K is the strength. Bambu also uses bare S, C and "
        "R around its calibration test; those aren't documented.",
        {"K": "Pressure-advance factor", "L": "Bambu: unknown", "M": "Bambu: unknown",
         "S": "Bambu: save (believed)", "C": "Bambu: clear (believed)",
         "R": "Bambu: restore (believed)"}, describe=_describe_pressure_advance),
    "M983": CommandInfo(
        "Extrusion calibration (Bambu A1)", "Measure how the filament flows to tune pressure advance.",
        "Bambu's comment: “cali dynamic extrusion compensation”. This is the automatic "
        "flow-dynamics calibration you can tick when sending a print. The printer "
        "extrudes and measures the result to choose a pressure-advance value.",
        {"F": "Flow rate used for the test (from the outer-wall volumetric speed)",
         "A": "Test parameter (believed acceleration/amplitude)",
         "H": "Nozzle diameter (mm)"}, C),
    "M984": CommandInfo(
        "Extrusion calibration step 2 (Bambu A1)", "Second part of the extrusion calibration.",
        "Runs after M983 in the block Bambu labels “draw extrinsic para cali paint”. "
        "Exact parameters aren't public.",
        {"A": "Test parameter", "E": "Test parameter", "S": "Enable",
         "F": "Flow rate used for the test", "H": "Nozzle diameter (mm)"}, C),
    "M970.2": CommandInfo(
        "Vibration test (Bambu)", "Another vibration measurement in the motion-system check.",
        "Runs next to M970.3 in the “mech mode fast check”. Results feed vibration "
        "suppression (M975).", {"Q": "Axis (1 = X, 0 = Y, believed)"}, C),
    "M982.2": CommandInfo(
        "Motor noise reduction (Bambu)", "Turn motor cogging-noise reduction on (S1) or off (S0).",
        "Bambu's comment: “turn on cog noise reduction”. Stepper motors hum because of "
        "small bumps in their rotation (“cogging”); this tunes the motor drive to "
        "quiet them.", {"S": "1 = on, 0 = off"}, C, _switch("motor noise reduction")),
    "M620.3": CommandInfo(
        "Filament tangle detection (Bambu)", "Turn filament tangle detection on (W1) or off.",
        "Bambu's comment: “turn on filament tangle detection”. The printer pauses if the "
        "filament snags on the spool instead of feeding freely.", {"W": "1 = on, 0 = off"}, C),
    "M630": CommandInfo(
        "Reset step (Bambu)", "Purpose isn't public.",
        "Appears in the “reset machine status” part of the A1 start code. OpenBambuAPI "
        "lists it as “unknown purpose”.", {"S": "Unknown", "P": "Unknown"}, C,
        _unknown_purpose("It sits in the “reset machine status” part of the start code.")),
    "M1007": CommandInfo(
        "Mass estimation (Bambu)", "Turn nozzle mass estimation on (S1) or off (S0).",
        "Bambu's comment: “turn on mass estimation”. The printer estimates whether "
        "plastic is building up on the nozzle; if so, the clump re-check (G39.3) runs.",
        {"S": "1 = on, 0 = off"}, C, _switch("nozzle mass estimation")),
    "M9833.2": CommandInfo(
        "Unknown startup command (Bambu A1)", "Purpose isn't public.",
        "Appears near the very top of the A1 start code, right after clog detection "
        "is turned off (G392 S0). Bambu doesn't document it and OpenBambuAPI lists "
        "it as “unknown purpose”. One community start script labels it “set "
        "noise/mech params”, but that is a guess.", {}, C,
        _unknown_purpose("It runs right after clog detection is turned off at the very "
                         "start of the print. One community script calls it “set "
                         "noise/mech params” — unconfirmed.")),
    "M1006": CommandInfo("Buzzer / music (Bambu)", "Play notes on the printer's speaker (A1 series).",
                         "", {}, C),
    "T": CommandInfo(
        "Change filament", "Switch which filament feeds the nozzle.",
        "On Bambu printers T0–T15 select a filament from the AMS. T255 unloads. "
        "T1000 and T1100 are special internal selections Bambu uses in its start code.",
        {}, C, _describe_tool),
}

# ---------------------------------------------------------------- comments

_FEATURES = {
    "Outer wall": "The outside surface of the part — what you see and touch. Printed "
                  "slowly and carefully for a clean finish.",
    "Inner wall": "Walls just inside the outer wall. They give the part strength and "
                  "support the outer wall.",
    "Overhang wall": "A wall that leans out over empty space. Printed slower with extra "
                     "cooling so it doesn't droop.",
    "Sparse infill": "The hollow inner pattern (grid, gyroid…) that fills the inside "
                     "cheaply while keeping the part rigid.",
    "Internal solid infill": "Fully solid layers inside the part, usually just under a "
                             "top surface so it has something to sit on.",
    "Solid infill": "Fully solid layers of plastic.",
    "Top surface": "The last, visible layers on top of the part. Printed for a smooth finish.",
    "Bottom surface": "The solid layers on the bottom of the part, touching the bed or support.",
    "Bridge": "A line stretched across empty air between two supports, like a bridge. "
              "Printed with extra cooling.",
    "Gap infill": "Small lines that fill tiny gaps too narrow for a normal wall.",
    "Support": "Temporary scaffolding holding up parts of the model that hang in the air. "
               "You remove it after printing.",
    "Support interface": "The top of the support, right under the part — designed to "
                         "peel away cleanly.",
    "Support transition": "Layers that help support switch between types.",
    "Prime tower": "A small tower next to the part used to clean the nozzle after a "
                   "color change, so old color doesn't end up on the model.",
    "Skirt": "A loop around the part (not touching it) that primes the nozzle before printing.",
    "Brim": "Extra rings around the bottom of the part that help it stick to the bed.",
    "Ironing": "The hot nozzle passes over the top surface again with very little "
               "plastic to smooth it.",
    "Floating vertical shell": "Walls that are not resting on anything below.",
    "Custom": "Code written by Bambu or the user (start/end or filament code), not "
              "generated from the model.",
}


def _m(pattern: str, title: str, explanation: str) -> CommentMarker:
    return CommentMarker(re.compile(pattern, re.I), title, explanation)


COMMENT_MARKERS = [
    *(_m(rf"^FEATURE:\s*{re.escape(name)}\s*$", f"Section: {name}",
         f"Slicer note: the following lines print the “{name}”. {text} "
         "The printer itself ignores comments.")
      for name, text in _FEATURES.items()),
    _m(r"^FEATURE:\s*(.+)$", "Section: {0}",
       "Slicer note: the following lines print the “{0}” part of the model."),
    _m(r"^CHANGE_LAYER\b", "Layer change",
       "Slicer note: a new layer starts here. Everything until the next layer change "
       "is printed at one height."),
    _m(r"^layer num/total_layer_count:\s*(\d+)\s*/\s*(\d+)", "Layer {0} of {1}",
       "Slicer note: this is layer {0} out of {1} in the whole print."),
    _m(r"^Z_HEIGHT:\s*([-\d.]+)", "Layer height marker",
       "Slicer note: this layer's top is {0} mm above the bed."),
    _m(r"^LAYER_HEIGHT:\s*([-\d.]+)", "Layer thickness",
       "Slicer note: lines here are {0} mm thick."),
    _m(r"^LINE_WIDTH:\s*([-\d.]+)", "Line width",
       "Slicer note: lines here are {0} mm wide (the nozzle is usually 0.4 mm)."),
    _m(r"^WIPE_START", "Wipe starts",
       "Slicer note: the nozzle now drags back along the line it just printed while "
       "pulling filament in, to avoid a blob or string."),
    _m(r"^WIPE_END", "Wipe ends", "Slicer note: end of the wipe move."),
    _m(r"^OBJECT_ID:\s*(\d+)", "Object #{0}",
       "Slicer note: the following lines belong to object #{0} on the plate."),
    _m(r"^(start|stop) printing object", "Object boundary",
       "Slicer note: marks where printing of one object begins or ends (used to skip "
       "objects mid-print)."),
    _m(r"^SKIPTYPE:\s*(.+)", "Skippable section: {0}",
       "Slicer note: the printer may skip this “{0}” section if that feature is off."),
    _m(r"^SKIPPABLE_(START|END)", "Skippable section",
       "Slicer note: start/end of a section the printer may skip (e.g. timelapse moves)."),
    _m(r"^FLUSH_START", "Flush starts",
       "Slicer note: after a filament change the old color is pushed out through the "
       "nozzle into the waste chute (“poop”) until the new color comes out clean."),
    _m(r"^FLUSH_END", "Flush ends", "Slicer note: end of the color flush."),
    _m(r"^WIPE_TOWER_(START|END)", "Prime tower",
       "Slicer note: start/end of printing on the prime tower, which cleans the "
       "nozzle after a color change."),
    _m(r"^CP TOOLCHANGE (START|END)", "Filament change",
       "Slicer note: start/end of a filament (color) change."),
    _m(r"^toolchange #(\d+)", "Filament change #{0}",
       "Slicer note: this is filament change number {0} in the print."),
    _m(r"^material\s*:\s*(.+?)\s*->\s*(.+)$", "Material change",
       "Slicer note: switching from {0} to {1}."),
    _m(r"^MACHINE_START_GCODE_END", "Start code ends",
       "Slicer note: the printer's startup routine (heating, homing, leveling, purge "
       "line) is finished. The model itself starts printing after this."),
    _m(r"^MACHINE_END_GCODE_START", "End code starts",
       "Slicer note: the model is done. What follows parks the nozzle, cools down and "
       "unloads filament."),
    _m(r"^filament (start|end) gcode", "Filament {0} code",
       "Slicer note: commands specific to the filament profile follow."),
    _m(r"^HEADER_BLOCK_(START|END)", "File header",
       "Slicer note: the header holds a summary of the print (time, filament, layers)."),
    _m(r"^CONFIG_BLOCK_(START|END)", "Slicer settings block",
       "Slicer note: a record of every slicer setting used. The printer ignores it."),
    _m(r"^EXECUTABLE_BLOCK_(START|END)", "Printable section",
       "Slicer note: start/end of the commands the printer actually runs."),
    _m(r"^THUMBNAIL_BLOCK|^thumbnail", "Preview image",
       "Slicer note: an encoded preview picture of the model for the printer's screen."),
    _m(r"^BambuStudio\s+(\S+)", "Made by Bambu Studio {0}",
       "This file was sliced with Bambu Studio version {0}."),
    _m(r"^total layer number:\s*(\d+)", "Total layers",
       "Slicer note: the print has {0} layers."),
    _m(r"^model printing time:\s*(.+?);\s*total estimated time:\s*(.+)$", "Print time",
       "Slicer estimate: the model takes {0}; with startup and changes, {1}."),
    _m(r"^([GMT]\d+(?:\.\d+)?\b.*)$", "Disabled command",
       "This looks like a command (“{0}”) that has been switched off by putting a "
       "semicolon in front of it. The printer ignores it."),
    _m(r"^enable nozzle clog detect at 3rd layer", "Layer-3 nozzle check",
       "Bambu note: on layer 3 the printer checks whether plastic has built up on the "
       "nozzle (G39), if that option is enabled."),
    _m(r"^Slow Down (Start|End)", "Cooling slowdown",
       "Slicer note: start/end of a section slowed down so the layer has enough time "
       "to cool before the next one goes on top."),
    _m(r"^update layer progress", "Layer progress",
       "Slicer note: the next lines tell the printer's screen which layer it is on."),
    _m(r"^timelapse", "Timelapse",
       "Slicer note: camera/timelapse handling for this layer follows."),
    _m(r"^object ids of (?:this )?layer\s*(\d+)", "Objects on layer {0}",
       "Slicer note: lists which objects have lines on layer {0}."),
    _m(r"^([A-Za-z_ ]+(?:\[[^\]]+\])?)\s*:\s*(.+)$", "Header info: {0}",
       "Summary written by the slicer: {0} = {1}. Where there are several values, "
       "there is one per filament or object. The printer ignores it."),
    _m(r"^[-=]+$", "Divider", "A divider line to make the file easier to read."),
    _m(r"^=+\s*(.*?)\s*=*$", "Section label",
       "A heading written by Bambu in its start/end code: “{0}”. The printer ignores it."),
]


def _detect(sample: str) -> float:
    if "BambuStudio" in sample or "M1002" in sample or "M620" in sample:
        return 1.0
    return 0.1


PROFILE = Profile(
    key="bambu",
    name="Bambu Lab",
    description="Bambu Lab X1, P1 and A1 series 3D printers (Bambu Studio G-code)",
    commands=COMMANDS,
    comment_markers=COMMENT_MARKERS,
    detect=_detect,
)
