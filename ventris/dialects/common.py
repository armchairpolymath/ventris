"""Pieces shared by every machine profile.

`marlin_commands()` returns plain-language entries for the standard Marlin
G-codes that most 3D printers understand. A profile starts from these and
overrides or adds entries for its own firmware.
"""

from __future__ import annotations

import re

from ..parser import ParsedLine
from ..reference import CommandInfo, CommentMarker, num
from ..state import MachineState

DOCUMENTED, VENDOR, COMMUNITY = "documented", "vendor", "community"

# ---------------------------------------------------------------- describers


def speed_text(feed: float | None) -> str:
    return f"{num(feed / 60, digits=1)} mm/s" if feed else ""


def describe_move(line: ParsedLine, before: MachineState, after: MachineState) -> str:
    relative = before.positioning == "relative"
    axes = [(a, line.number(a)) for a in "XYZ" if line.number(a) is not None]
    e = line.number("E")
    if e is not None and before.extrusion == "absolute" and not relative:
        e = (after.e - before.e) if before.e is not None else e
    feed = line.number("F")

    if not axes and e is None:
        if feed is not None:
            return (f"Set the speed for the next moves to {speed_text(feed)} "
                    f"({num(feed)} mm/min). Nothing moves on this line.")
        return "A move command with nothing to move. The printer does nothing."

    if not axes:
        if e > 0:
            text = (f"Push {num(e)} mm of filament out of the nozzle without moving. "
                    "This refills the nozzle after a retraction (or primes it).")
        else:
            text = (f"Retract: the printer pulls the filament back {num(-e)} mm so "
                    "molten plastic doesn't ooze or string while the nozzle travels.")
        return text + (f" Speed {speed_text(feed)}." if feed else "")

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
    speed = f" at {speed_text(feed)}" if feed else ""
    return f"{where}{what}{speed}."


def describe_arc(line: ParsedLine, before: MachineState, after: MachineState) -> str:
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


def target_temperature(line: ParsedLine) -> float | None:
    """M109/M190 accept S (heat to) or R (heat or cool to)."""
    value = line.number("S")
    return line.number("R") if value is None else value


def describe_temp(heater: str, wait: bool):
    def describe(line: ParsedLine, before: MachineState, after: MachineState) -> str:
        target = target_temperature(line)
        tool = f" (tool T{line.params['T']})" if line.params.get("T") else ""
        if target is None:
            return f"Change the {heater} temperature{tool} (no target given)."
        if target == 0:
            return f"Turn the {heater} heater{tool} off."
        if wait and line.number("S") is None and line.has("R"):
            return (f"Set the {heater}{tool} to {num(target)} °C and wait until it gets "
                    "there — heating up or cooling down. (R waits in both directions; "
                    "S only waits while heating.)")
        if wait:
            return (f"Set the {heater}{tool} to {num(target)} °C and wait until it gets "
                    "there. The printer pauses here until the temperature is reached.")
        return (f"Set the {heater}{tool} to {num(target)} °C and carry on right away — "
                "it heats in the background.")
    return describe


def describe_fan(fans: dict[int, str]):
    def describe(line: ParsedLine, before: MachineState, after: MachineState) -> str:
        index = int(line.number("P") or 1)
        fan = fans.get(index, f"fan #{index}")
        if line.code == "M107":
            return f"Turn off the {fan}."
        speed = line.number("S")
        speed = 255 if speed is None else speed
        pct = round(speed / 255 * 100)
        return f"Turn off the {fan}." if pct == 0 else f"Set the {fan} to {pct}% speed."
    return describe


def describe_dwell(line: ParsedLine, before: MachineState, after: MachineState) -> str:
    if line.has("S") and line.params["S"]:
        return f"Pause for {num(line.number('S'))} seconds."
    if line.has("P") and line.params["P"]:
        return f"Pause for {num(line.number('P'))} milliseconds."
    return ("Wait for all queued moves to finish (G4 with no time just lets the "
            "printer catch up).")


def describe_wait(line: ParsedLine, before: MachineState, after: MachineState) -> str:
    text = ("Wait until every move already queued has finished before reading the "
            "next line.")
    if line.has("S"):
        text += f" Then wait another {num(line.number('S'))} seconds."
    elif line.has("P"):
        text += f" Then wait another {num(line.number('P'))} ms."
    return text


def describe_set_position(line, before, after) -> str:
    parts = [f"{a} = {num(line.number(a))}" for a in "XYZE" if line.number(a) is not None]
    if parts == ["E = 0"]:
        return ("Reset the filament counter to zero. Nothing moves; the printer just "
                "starts counting extrusion from 0 again.")
    return ("Tell the printer its current position is " + ", ".join(parts) +
            ". Nothing moves — it just relabels where it is.")


def describe_progress(line, before, after) -> str:
    parts = []
    if line.has("P"):
        parts.append(f"the print is {num(line.number('P'))}% done")
    if line.has("R"):
        parts.append(f"about {num(line.number('R'))} minutes remain")
    if line.has("Q"):
        parts.append(f"in quiet mode it would be {num(line.number('Q'))}% done")
    if line.has("S"):
        parts.append(f"with about {num(line.number('S'))} minutes left in quiet mode")
    if line.has("L"):
        parts.append(f"it is now on layer {num(line.number('L'))}")
    if not parts:
        return "Update the progress shown on the printer's screen."
    return "Update the printer's screen: " + ", ".join(parts) + "."


def describe_motors_off(line, before, after) -> str:
    axes = [a for a in "XYZE" if line.has(a)]
    if not axes:
        return "Turn all motors off so the axes can be moved by hand."
    names = {"X": "X", "Y": "Y", "Z": "Z", "E": "extruder"}
    return "Turn off the " + ", ".join(names[a] for a in axes) + " motor" + \
        ("s" if len(axes) > 1 else "") + "."


def describe_speed_factor(line, before, after) -> str:
    if line.has("B") and not line.params["B"]:
        return "Remember the current speed multiplier so it can be restored later."
    if line.has("R") and not line.params["R"]:
        return "Restore the speed multiplier saved earlier with M220 B."
    return _percent_sentence("speed", line.number("S"))


def describe_flow_factor(line, before, after) -> str:
    return _percent_sentence("flow", line.number("S"))


def _percent_sentence(what: str, value: float | None) -> str:
    if value is None:
        return f"Adjust the {what} multiplier."
    note = "normal" if value == 100 else "not normal"
    return f"Set the {what} multiplier to {num(value)}% ({note})."


def switch(feature: str, letter: str = "S"):
    """Describer for commands where S1/S0 turns something on/off."""
    def describe(line, before, after) -> str:
        value = line.number(letter)
        if value is None:
            return f"Change the {feature} setting."
        return f"Turn {'on' if value else 'off'} {feature}."
    return describe


def unknown_purpose(vendor: str, context: str):
    def describe(line, before, after) -> str:
        return f"{vendor} command whose exact purpose isn't public. {context}"
    return describe


# ---------------------------------------------------------------- base reference


def move_params(z_note: str = "") -> dict[str, str]:
    return {
        "X": "Left/right position (mm)",
        "Y": "Front/back position (mm)",
        "Z": "Height (mm)" + (f". {z_note}" if z_note else ""),
        "E": "Filament to push (positive) or pull back (negative), in mm",
        "F": "Speed in mm per minute (divide by 60 for mm/s). Stays in effect for later moves.",
    }


_ARC_PARAMS = {"I": "Center offset in X from the start point (mm)",
               "J": "Center offset in Y from the start point (mm)",
               "P": "Number of full turns", "R": "Radius (mm), instead of I/J"}


def marlin_commands(slicer: str, fans: dict[int, str], fan_help: str,
                    z_note: str = "") -> dict[str, CommandInfo]:
    """Standard commands shared by Marlin-family firmware, in beginner language."""
    move = move_params(z_note)
    return {
        "G0": CommandInfo(
            "Move", "Move the nozzle in a straight line.",
            "G0 is the “rapid move”. On 3D printers it behaves like G1; slicers use "
            "it mostly for travel moves.", move, describe=describe_move),
        "G1": CommandInfo(
            "Move", "Move the nozzle in a straight line, optionally extruding plastic.",
            "G1 is the workhorse of a print — usually over 95% of the lines. Each G1 "
            "moves to a new point. If it has an E value, the extruder pushes filament at "
            "the same time, laying down a line of plastic. Without E it is a “travel” "
            "move. A negative E pulls filament back (“retraction”) to stop dripping. "
            "Whether the numbers are absolute positions or relative distances depends "
            "on G90/G91 and M82/M83 — see the machine state panel.",
            move, describe=describe_move),
        "G2": CommandInfo(
            "Arc (clockwise)", "Move along a clockwise curve.",
            "Arcs let one line describe a smooth curve instead of many tiny straight "
            "segments. I and J give the curve's center relative to the start point.",
            {**move, **_ARC_PARAMS}, describe=describe_arc),
        "G3": CommandInfo(
            "Arc (counter-clockwise)", "Move along a counter-clockwise curve.",
            "Same as G2, but turning the other way.",
            {**move, **_ARC_PARAMS}, describe=describe_arc),
        "G4": CommandInfo("Dwell (pause)", "Do nothing for a set time.", "",
                          {"S": "Seconds", "P": "Milliseconds"}, describe=describe_dwell),
        "G17": CommandInfo("Select XY plane for arcs",
                           "Arcs (G2/G3) will curve flat, in the left/right + front/back plane.",
                           "This is the normal setting for 3D printers."),
        "G20": CommandInfo("Use inches", "Numbers from here on are in inches.",
                           "Almost never used on 3D printers."),
        "G21": CommandInfo("Use millimetres", "Numbers from here on are in millimetres.",
                           "This is the normal setting; slicers write it to be explicit."),
        "G28": CommandInfo(
            "Home", "Find the printer's reference position (home).",
            "After power-on the printer doesn't know where the nozzle is. Homing moves "
            "each axis until a sensor triggers, then sets that point as known. With "
            "axis letters only those axes are homed.",
            {"X": "Home X", "Y": "Home Y", "Z": "Home Z"}),
        "G90": CommandInfo(
            "Absolute positioning", "Coordinates from here on are exact positions.",
            "With G90, “X100” means “go to the spot 100 mm from the origin”. Compare G91."),
        "G91": CommandInfo(
            "Relative positioning",
            "Coordinates from here on are distances from where the nozzle is now.",
            "With G91, “X10” means “move 10 mm to the right of here”."),
        "G92": CommandInfo(
            "Set position", "Tell the printer “consider your current position to be …”.",
            "No motion happens. The most common use is G92 E0, which zeroes the "
            "extruder's counter.",
            {"X": "New X value", "Y": "New Y value", "Z": "New Z value",
             "E": "New extruder value"}, describe=describe_set_position),
        "M0": CommandInfo("Stop and wait", "Pause until someone presses a button on the printer.",
                          "", {"P": "Milliseconds to wait instead", "S": "Seconds to wait instead"}),
        "M1": CommandInfo("Stop and wait", "Pause until someone presses a button on the printer."),
        "M17": CommandInfo("Motors on", "Turn the stepper motors on (they hold their position firmly)."),
        "M18": CommandInfo("Motors off", "Turn motors off so the axes can be moved by hand.",
                           "", {"X": "X motor", "Y": "Y motor", "Z": "Z motor", "E": "Extruder motor"},
                           describe=describe_motors_off),
        "M84": CommandInfo("Motors off", "Turn motors off so the axes can be moved by hand.",
                           "", {"X": "X motor", "Y": "Y motor", "Z": "Z motor", "E": "Extruder motor"},
                           describe=describe_motors_off),
        "M73": CommandInfo(
            "Progress update", "Update the progress bar and time remaining on the screen.",
            "The slicer sprinkles these through the file so the printer can show "
            "accurate progress.", {"P": "Percent done", "R": "Minutes remaining"},
            describe=describe_progress),
        "M75": CommandInfo("Start print timer", "Start the print-job timer shown on the screen."),
        "M76": CommandInfo("Pause print timer", "Pause the print-job timer."),
        "M77": CommandInfo("Stop print timer", "Stop the print-job timer."),
        "M82": CommandInfo(
            "Absolute extrusion", "E values from here on are a running total of filament used.",
            f"Compare M83. {slicer} normally uses M83 (relative)."),
        "M83": CommandInfo(
            "Relative extrusion", "Each E value is the amount of filament for that move only.",
            f"This is what {slicer} uses: “E.5” means “push 0.5 mm during this move”, "
            "rather than a running total."),
        "M104": CommandInfo("Set nozzle temperature",
                            "Start heating (or cooling) the nozzle; don't wait.", "",
                            {"S": "Target temperature in °C (0 = off)", "T": "Which tool/nozzle"},
                            describe=describe_temp("nozzle", wait=False)),
        "M109": CommandInfo("Set nozzle temperature and wait",
                            "Heat the nozzle and wait until it reaches the target.", "",
                            {"S": "Target °C (wait only while heating)",
                             "R": "Target °C (wait while heating or cooling)",
                             "T": "Which tool/nozzle"},
                            describe=describe_temp("nozzle", wait=True)),
        "M140": CommandInfo("Set bed temperature", "Start heating the bed; don't wait.",
                            "A warm bed helps the first layer stick.",
                            {"S": "Target temperature in °C (0 = off)"},
                            describe=describe_temp("bed", wait=False)),
        "M190": CommandInfo("Set bed temperature and wait",
                            "Heat the bed and wait until it reaches the target.", "",
                            {"S": "Target °C (wait only while heating)",
                             "R": "Target °C (wait while heating or cooling)"},
                            describe=describe_temp("bed", wait=True)),
        "M141": CommandInfo("Set chamber temperature", "Set the enclosure air temperature.",
                            "", {"S": "Target temperature in °C (0 = off)"},
                            describe=describe_temp("chamber", wait=False)),
        "M191": CommandInfo("Set chamber temperature and wait",
                            "Heat the enclosure air and wait until it reaches the target.", "",
                            {"S": "Target °C", "R": "Target °C (heating or cooling)"},
                            describe=describe_temp("chamber", wait=True)),
        "M106": CommandInfo("Fan on", "Set a fan's speed.", fan_help,
                            {"P": "Which fan", "S": "Speed 0–255 (255 = 100%)"},
                            describe=describe_fan(fans)),
        "M107": CommandInfo("Fan off", "Turn a fan off.", "",
                            {"P": "Which fan (default: part cooling)"},
                            describe=describe_fan(fans)),
        "M115": CommandInfo("Firmware info", "Ask the printer which firmware it runs.", ""),
        "M117": CommandInfo("Show message", "Show a text message on the printer's screen.", "",
                            {"_args": "The message"}),
        "M201": CommandInfo("Max acceleration", "Set the highest acceleration each axis may use.",
                            "Acceleration is how quickly a motor gets up to speed (mm/s²).",
                            {"X": "mm/s²", "Y": "mm/s²", "Z": "mm/s²", "E": "mm/s²"}),
        "M203": CommandInfo("Max speed", "Set the top speed allowed for each axis (mm/s).", "",
                            {"X": "mm/s", "Y": "mm/s", "Z": "mm/s", "E": "mm/s"}),
        "M204": CommandInfo(
            "Acceleration", "Set how quickly the printer speeds up and slows down.",
            "Lower acceleration gives cleaner outer walls; higher is faster. Slicers "
            "change this often — gentle for outer walls, aggressive for travel.",
            {"S": "Acceleration for all moves (mm/s²)", "P": "Printing moves (mm/s²)",
             "R": "Retractions (mm/s²)", "T": "Travel moves (mm/s²)"}),
        "M205": CommandInfo(
            "Jerk / corner speed", "Set how abruptly the printer may change direction.",
            "X/Y/Z/E are the speeds (mm/s) at which the printer can change direction "
            "without slowing to a stop.",
            {"X": "mm/s", "Y": "mm/s", "Z": "mm/s", "E": "mm/s",
             "S": "Minimum printing speed (mm/s)", "T": "Minimum travel speed (mm/s)"}),
        "M211": CommandInfo("Soft endstops", "Turn the software travel limits on (S1) or off (S0).",
                            "Soft endstops stop the printer moving past its edges.",
                            {"S": "1 = on, 0 = off"}, describe=switch("software travel limits")),
        "M220": CommandInfo("Speed multiplier", "Scale all print speeds by a percentage.", "",
                            {"S": "Percent (100 = normal)", "B": "Back up current value",
                             "R": "Restore backed-up value"}, describe=describe_speed_factor),
        "M221": CommandInfo("Flow multiplier", "Scale the amount of plastic extruded by a percentage.",
                            "", {"S": "Percent (100 = normal)", "T": "Which tool/nozzle"},
                            describe=describe_flow_factor),
        "M300": CommandInfo("Beep", "Play a beep on the printer's speaker.", "",
                            {"S": "Pitch (Hz)", "P": "Length (ms)"}),
        "M302": CommandInfo(
            "Cold extrusion limit", "Allow extruding below the usual safe temperature.",
            "Printers refuse to push filament through a cold nozzle (it would grind). "
            "S sets the lowest temperature allowed.",
            {"S": "Minimum temperature °C", "P": "1 = allow any temperature"}),
        "M400": CommandInfo("Wait for moves to finish",
                            "Pause reading the file until all queued moves are done.",
                            "The printer normally reads ahead. M400 forces it to catch up — "
                            "useful before changing settings or taking a photo.",
                            {"S": "Extra wait in seconds", "P": "Extra wait in milliseconds"},
                            describe=describe_wait),
        "M412": CommandInfo("Filament runout sensor",
                            "Turn filament runout detection on (S1) or off (S0).",
                            "When on, the printer pauses if the filament runs out.",
                            {"S": "1 = on, 0 = off"}, describe=switch("filament runout detection")),
        "M500": CommandInfo("Save settings", "Save calibration/settings to the printer's memory."),
        "M600": CommandInfo(
            "Filament change", "Pause and ask you to swap the filament (e.g. a color change).",
            "The printer parks, unloads the filament and waits. After you load the new "
            "one it continues printing.",
            {"X": "Park X", "Y": "Park Y", "Z": "Lift Z", "E": "Retract (mm)"}),
        "M900": CommandInfo(
            "Linear advance", "Tune how the extruder anticipates speed changes.",
            "Linear advance (also called pressure advance) compensates for pressure "
            "building up in the nozzle, so corners and line ends come out even. "
            "K is the strength; 0 turns it off.", {"K": "Strength"}),
    }


# ---------------------------------------------------------------- comments


def marker(pattern: str, title: str, explanation: str) -> CommentMarker:
    return CommentMarker(re.compile(pattern, re.I), title, explanation)


GENERIC_MARKERS = [
    marker(r"^([GMT]\d+(?:\.\d+)?\b.*)$", "Disabled command",
           "This looks like a command (“{0}”) that has been switched off by putting a "
           "semicolon in front of it. The printer ignores it."),
    marker(r"^[-=]+$", "Divider", "A divider line to make the file easier to read."),
    marker(r"^=+\s*(.*?)\s*=*$", "Section label",
           "A heading written in the start/end code: “{0}”. The printer ignores it."),
]
