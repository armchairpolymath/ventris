"""Prusa Research printers: CORE One, MK4/MK4S, MK3.5, MINI, XL (Buddy firmware)
and MK3/MK3S (8-bit Prusa firmware), sliced with PrusaSlicer.

Prusa documents its firmware-specific G-codes:
  https://help.prusa3d.com/article/buddy-firmware-specific-g-code-commands_633112
  https://help.prusa3d.com/article/prusa-firmware-specific-g-code-commands_112173
Those entries are marked "vendor". Where the docs are silent, the text leans on
the comments Prusa writes in PrusaSlicer's own printer profiles; anything still
uncertain says "believed".
"""

from __future__ import annotations

import re

from ..parser import ParsedLine
from ..reference import CommandInfo, Profile, num
from ..state import MachineState
from . import common
from .common import VENDOR as V, marker

_FANS = {1: "print fan (it cools the freshly printed plastic)"}


def _args(line: ParsedLine) -> str:
    return line.params.get("_args", "")


def _quoted(line: ParsedLine) -> str:
    """Value from forms like  P "MK4S"  or  P"Input shaper"."""
    raw = _args(line) or line.raw
    m = re.search(r'"([^"]*)"', raw)
    if m:
        return m.group(1)
    return line.params.get("P", "") or raw.strip()


def _area(line: ParsedLine) -> str:
    if not all(line.has(a) for a in "XYWH"):
        return ""
    return (f"the area starting at X {num(line.number('X'))}, Y {num(line.number('Y'))}, "
            f"{num(line.number('W'))} × {num(line.number('H'))} mm")


# ---------------------------------------------------------------- describers


def _describe_home(line, before, after) -> str:
    axes = [a for a in "XYZ" if line.has(a)]
    text = ("Home " + (" and ".join(axes) + " only" if axes else "all axes") +
            ": move until the printer finds its reference position, so it knows "
            "exactly where the nozzle is.")
    if line.has("W"):
        text += (" W (MK3) means “home without mesh bed leveling” — leveling is done "
                 "separately by G80.")
    return text


def _describe_g29(line, before, after) -> str:
    p = line.params.get("P", "")
    area = _area(line)
    if line.has("A") and not line.params["A"] and not p:
        return ("Turn on mesh bed leveling: from here on the nozzle rises and falls "
                "slightly to follow the measured shape of the bed.")
    if line.has("G") and not p:
        return ("Prusa's comment: “absorb heat”. The printer pauses so the bed's heat can "
                "soak in and it stops expanding, so the leveling measurement stays accurate.")
    if p == "1" and area:
        extra = (" Prusa's comment on this line is “probe near purge place”: the purge "
                 "line is printed outside the model, so that spot needs measuring too."
                 if line.has("C") else "")
        return f"Also measure the bed in {area} and add it to the mesh.{extra}"
    if p == "1":
        return ("Throw away the old bed measurements and probe the print area (the area "
                "given earlier by M555), building a fresh mesh of bed heights.")
    if p == "3.2":
        return ("Fill in (interpolate) mesh points between the spots that were actually "
                "probed, so the bed map is smooth.")
    if p == "3.13":
        return ("Extend (extrapolate) the bed map beyond the probed area, so moves outside "
                "it still get a sensible height correction.")
    if p == "9":
        where = f" in {area}" if area else ""
        return ("Believed to be the nozzle cleaning step: the nozzle wipes itself on the "
                f"bed edge{where} before the bed is measured. Prusa doesn't document P9, "
                "but PrusaSlicer's own start code calls the retraction just before this "
                "line “the initial one before nozzle cleaning”, and this is the only "
                "command between that retraction and bed leveling.")
    return ("Mesh bed leveling: measure the bed at many points so the printer can follow "
            "its shape.")


def _describe_g80(line, before, after) -> str:
    area = _area(line)
    where = f", limited to {area}" if area else ""
    return ("MK3 mesh bed leveling: touch the bed at a grid of points with the probe and "
            f"remember the heights{where}. The nozzle then follows the bed's real shape.")


def _describe_check(kind: str):
    def describe(line, before, after) -> str:
        value = _quoted(line)
        if kind == "nozzle":
            parts = [f"Check that the printer has a {value} mm nozzle"]
            if line.params.get("A") == "1":
                parts.append("that is abrasion-resistant")
            if line.params.get("F") == "1":
                parts.append("and high-flow")
            return (" ".join(parts) + ". If the nozzle set on the printer doesn't match "
                    "what the file was sliced for, it warns you before printing.")
        if kind == "model":
            return (f"Check that this file was sliced for a {value}. If you send it to a "
                    "different model the printer warns you.")
        if kind == "level":
            return (f"Check that the printer understands G-code level {value} (a version "
                    "number for the G-code “language” this file uses).")
        if kind == "feature":
            return f"Check that the printer's firmware supports “{value}”."
        if kind == "firmware":
            return f"Check the printer's firmware version against {value}."
        return f"Printer compatibility check ({_args(line) or line.raw.strip()})."
    return describe


def _describe_fw_version(line, before, after) -> str:
    if line.has("U"):
        return (f"Tell the printer the slicer expects firmware {line.params['U']}. If the "
                "printer's firmware is older, it shows a message suggesting an update.")
    return "Ask the printer which firmware it runs."


def _describe_print_area(line, before, after) -> str:
    area = _area(line)
    if not area:
        return "Tell the printer which part of the bed this print uses."
    return (f"Tell the printer the first layer covers {area}. Mesh bed leveling then "
            "probes just that area, which is faster.")


def _describe_stealthchop(line, before, after) -> str:
    axes = [a for a in "XYZE" if line.has(a)] or ["all axes"]
    names = {"E": "extruder"}
    who = ", ".join(names.get(a, a) for a in axes)
    if line.number("S") == 0:
        return (f"Switch the {who} motor driver to SpreadCycle mode: stronger and more "
                "precise but a little louder.")
    return f"Switch the {who} motor driver to StealthChop mode: very quiet."


def _describe_pressure_advance(line, before, after) -> str:
    value = line.params.get("S")
    if value in (None, ""):
        return "Change pressure-advance settings."
    if line.number("S") == 0:
        return "Turn pressure advance off."
    return (f"Set pressure advance to {value}. It pushes filament slightly earlier when "
            "the nozzle speeds up and eases off sooner when it slows down, so corners and "
            "line ends come out even.")


def _describe_stuck(line, before, after) -> str:
    if line.has("R"):
        return "Restore the stuck-filament detection setting that was saved earlier."
    if line.number("S") == 0:
        return ("Turn off stuck-filament detection for now (so the purge line doesn't "
                "trigger a false alarm).")
    if line.number("S") == 1:
        return "Turn on stuck-filament detection."
    return "Change stuck-filament detection settings."


def _describe_mass(line, before, after) -> str:
    return (f"Tell the printer about {line.params.get('W', '?')} g of plastic is on the bed "
            "so far. The bed moves back and forth on this printer, so its weight changes "
            "how it vibrates; the input shaper uses this to keep cancelling vibrations "
            "accurately as the print grows.")


def _describe_input_shaper(line, before, after) -> str:
    parts = []
    if line.has("T"):
        parts.append(f"shaper type {line.params['T']}")
    if line.has("F"):
        parts.append(f"frequency {line.params['F']} Hz")
    if line.has("D"):
        parts.append(f"damping {line.params['D']}")
    axes = [a for a in "XYZ" if line.has(a) and not line.params[a]]
    on = f" for {', '.join(axes)}" if axes else ""
    detail = ": " + ", ".join(parts) if parts else ""
    return (f"Configure the input shaper{on}{detail}. The input shaper cancels the "
            "printer's own vibrations so walls stay smooth at high speed.")


def _describe_heatbreak(line, before, after) -> str:
    return (f"Set the heatbreak cooling target to {line.params.get('S', '?')} °C. The "
            "heatbreak is the part just above the hot nozzle that must stay cool so "
            "filament doesn't soften too early and jam.")


def _describe_vent(line, before, after) -> str:
    if line.has("O"):
        return "Open the chamber vent (lets warm air out — good for PLA)."
    if line.has("C"):
        return "Close the chamber vent (keeps heat in — good for ABS/ASA)."
    return "Control the chamber vent."


def _describe_object(line, before, after) -> str:
    args = _args(line)
    if args.startswith("A"):
        return (f"Name the current object “{args[1:].strip()}”. The name appears in the "
                "printer's cancel-object menu.")
    if line.has("S"):
        n = line.params["S"]
        if n == "-1":
            return ("The following lines are no longer part of any object (shared moves "
                    "between objects).")
        return (f"The following lines print object {n}. If you cancel that object on the "
                "printer's screen, it skips these lines.")
    if line.has("T"):
        return f"This print contains {line.params['T']} objects that can be cancelled one by one."
    if line.has("P"):
        return f"Cancel object {line.params['P']} — skip it from now on."
    if line.has("U"):
        return f"Un-cancel object {line.params['U']}."
    if line.has("C"):
        return "Cancel the object being printed right now."
    return "Cancel-object command."


def _describe_tool(line, before, after) -> str:
    if not line.code[1:].isdigit():
        return "Tool change command without a tool number."
    n = int(line.code[1:])
    return (f"Switch to T{n}: on a printer with an MMU3 this loads filament slot {n + 1}; "
            f"on an XL it picks up toolhead {n + 1}.")


def _describe_motor_current(line, before, after) -> str:
    parts = [f"{a} {line.params[a]}" for a in "XYZE" if line.params.get(a)]
    unit = "mA" if line.code == "M906" else "(firmware units)"
    return ("Set motor current for " + ", ".join(parts) + f" {unit}. More current = more "
            "pushing force but more heat.") if parts else "Set motor current."


_describe_temp = common.describe_temp

# ---------------------------------------------------------------- reference

_PRUSA_COMMANDS: dict[str, CommandInfo] = {
    "G10": CommandInfo("Retract (firmware)", "Pull the filament back by the firmware's set amount.",
                       "The retraction length is set in the printer (M207) instead of the file.",
                       source=V),
    "G11": CommandInfo("Un-retract (firmware)", "Push the filament back after a G10 retract.",
                       source=V),
    "G12": CommandInfo(
        "Clean nozzle", "Run the nozzle cleaning routine.",
        "Standard Marlin “clean the nozzle”. In Prusa's CORE One INDX profile it moves "
        "the nozzle into the cleaner (comment “enter cleaner”) and ejects purged "
        "plastic (comment “eject poop”).", {"S": "Cleaning step/mode"}, V),
    "G427": CommandInfo(
        "Calibrate tools (INDX)", "Calibrate the toolheads used in the print.",
        "Prusa's comment in the CORE One INDX profile: “Calibrate all used and mapped "
        "tools”.", {"R": "Mode", "P": "Mode"}, V),
    "M92": CommandInfo("Steps per mm", "Tell the motor how many steps move 1 mm.",
                       "Prusa's comment: “E-steps per filament millimeter”. Only changed "
                       "for special extruders.", {"X": "Steps/mm", "Y": "Steps/mm",
                                                  "Z": "Steps/mm", "E": "Steps/mm"}, V),
    "M708": CommandInfo(
        "Write MMU setting", "Change a setting inside the MMU3 (filament changer).",
        "Prusa: “Write value to MMU register.” PrusaSlicer's comments name each register, "
        "e.g. load feedrate or pulley current.",
        {"A": "Register address (hex)", "X": "Value"}, V),
    "G26": CommandInfo("First layer calibration", "Print the first-layer calibration pattern.",
                       "Prusa: run only from the printer's selftest/calibration menu.", source=V),
    "G27": CommandInfo("Park", "Move the print head to its parking position.", source=V),
    "G28": CommandInfo(
        "Home", "Find the printer's reference position (home).",
        "After power-on the printer doesn't know where the nozzle is. Homing moves each "
        "axis until it finds its endpoint. On MK4/MINI/XL/CORE One the nozzle itself "
        "senses the bed (a load cell on MK4/CORE One).",
        {"X": "Home X", "Y": "Home Y", "Z": "Home Z",
         "W": "MK3: home without mesh bed leveling", "C": "Home Z only (Buddy)",
         "P": "MMU: invalidate selector homing", "I": "MMU: invalidate idler homing"},
        V, _describe_home),
    "G29": CommandInfo(
        "Mesh bed leveling (Buddy)", "Measure the bed's shape so the nozzle can follow it.",
        "No bed is perfectly flat. The printer probes the print area in a grid, then "
        "fills in (P3.2) and extends (P3.13) the map, and finally turns compensation on "
        "(A). The P values are phases of the leveling routine; PrusaSlicer's start code "
        "labels each one with a comment.",
        {"P": "Phase: 1 probe, 3.2 interpolate, 3.13 extrapolate, 9 nozzle cleaning (believed)",
         "A": "Activate the mesh", "G": "Absorb heat (wait for the bed to settle)",
         "C": "Probe near the purge place (Prusa's comment)",
         "X": "Area start X (mm)", "Y": "Area start Y (mm)", "W": "Area width (mm)",
         "H": "Area height (mm)"}, V, _describe_g29),
    "G64": CommandInfo("Measure Z axis", "Measure the Z axis length and save it.", "",
                       {"D": "Extra Z offset"}, V),
    "G80": CommandInfo(
        "Mesh bed leveling (MK3)", "Probe the bed in a grid so the nozzle can follow its shape.",
        "The MK3 measures the bed with its inductive (PINDA) probe. With X/Y/W/H it only "
        "probes the area the print will use.",
        {"X": "Area start X", "Y": "Area start Y", "W": "Area width", "H": "Area height",
         "N": "Grid size"}, V, _describe_g80),
    "G81": CommandInfo("Show bed mesh (MK3)", "Report the measured bed mesh.", source=V),
    "G162": CommandInfo("Calibrate Z", "Level the Z axis (gantry) mechanically.", "",
                        {"Z": "Calibrate Z"}, V),
    "G163": CommandInfo("Measure axis length", "Measure how long the X or Y axis is.", "",
                        {"X": "Measure X", "Y": "Measure Y"}, V),
    "M50": CommandInfo("Selftest", "Run the printer's self test.", "",
                       {"X": "X axis", "Y": "Y axis", "Z": "Z axis", "F": "Fans", "H": "Heaters"}, V),
    "M73": CommandInfo(
        "Progress update", "Update the progress bar and time remaining on the screen.",
        "PrusaSlicer writes two sets of numbers: normal mode (P/R) and quiet or "
        "“stealth” mode (Q/S, used on MK3), because the print takes longer when the "
        "printer runs quietly.",
        {"P": "Percent done (normal mode)", "R": "Minutes remaining (normal mode)",
         "Q": "Percent done (quiet mode)", "S": "Minutes remaining (quiet mode)",
         "C": "Minutes to next color change", "D": "Minutes to next color change (quiet)",
         "T": "Minutes to next pause"}, V, common.describe_progress),
    "M74": CommandInfo("Mass on bed", "Tell the printer how heavy the print is so far.",
                       "Prusa: “Set mass (input shaper related).” PrusaSlicer updates this "
                       "every layer on bed-slinger printers like the MK4.",
                       {"W": "Grams of plastic on the bed"}, V, _describe_mass),
    "M109": CommandInfo("Set nozzle temperature and wait",
                        "Heat (or cool) the nozzle and wait until it reaches the target.",
                        "PrusaSlicer often uses R so the printer also waits while cooling — "
                        "e.g. cool to 170 °C so oozing filament doesn't smear the bed "
                        "during leveling.",
                        {"S": "Target °C (wait only while heating)",
                         "R": "Target °C (wait while heating or cooling)",
                         "T": "Which tool/nozzle"}, V, _describe_temp("nozzle", wait=True)),
    "M115": CommandInfo("Firmware version check",
                        "Tell the printer which firmware version the slicer expects.",
                        "Prusa's comment: “tell printer latest fw version”.",
                        {"U": "Firmware version the slicer expects"}, V, _describe_fw_version),
    "M118": CommandInfo("Echo message", "Send a message to a connected computer.", "",
                        {"_args": "The message"}, V),
    "M142": CommandInfo("Heatbreak cooling temperature",
                        "Set the target temperature of the heatbreak cooling.",
                        "Prusa: “Set target heatbreak cooling temperature.”",
                        {"S": "Temperature °C"}, V, _describe_heatbreak),
    "M150": CommandInfo("LED color", "Set the color of the printer's LEDs.", "",
                        {"R": "Red 0–255", "G": "Green 0–255", "B": "Blue 0–255"}, V),
    "M151": CommandInfo("Side LEDs", "Control the side LED strip.", "", {}, V),
    "M201": CommandInfo("Max acceleration", "Set the highest acceleration each axis may use.",
                        "PrusaSlicer for MK4/CORE One lowers X/Y acceleration as the print "
                        "gets taller or heavier, to keep tall prints from wobbling.",
                        {"X": "mm/s²", "Y": "mm/s²", "Z": "mm/s²", "E": "mm/s²"}, V),
    "M217": CommandInfo("MMU toolchange settings", "Set filament swap parameters (MMU3).", "",
                        {"S": "Swap length", "E": "Purge length", "P": "Prime speed",
                         "R": "Retract speed", "Z": "Z raise"}, V),
    "M218": CommandInfo("Toolhead offset (XL)", "Set the position offset of one XL toolhead.",
                        source=V),
    "M403": CommandInfo("Filament type for MMU", "Tell the MMU what material is in a slot.",
                        "", {"E": "Slot", "F": "Material type"}, V),
    "M486": CommandInfo(
        "Cancel object / object label", "Mark which object the following lines belong to.",
        "Lets you cancel a single failed object from the printer's menu while the rest "
        "keep printing. S starts an object, S-1 ends it, A names it.",
        {"S": "Object number (−1 = none)", "T": "Number of objects", "P": "Cancel object",
         "U": "Un-cancel object", "C": "Cancel current object", "_args": "Object name (A…)"},
        V, _describe_object),
    "M555": CommandInfo(
        "Print area", "Tell the printer which part of the bed this print uses.",
        "Prusa: “Set print area for detailed MBL.” Leveling then only probes this area.",
        {"X": "Start X (mm)", "Y": "Start Y (mm)", "W": "Width (mm)", "H": "Height (mm)"},
        V, _describe_print_area),
    "M569": CommandInfo(
        "Motor driver mode", "Switch a motor driver between quiet and strong mode.",
        "S1 = StealthChop (very quiet), S0 = SpreadCycle (stronger, a bit louder). "
        "PrusaSlicer's comment: “set spreadcycle mode for extruder”.",
        {"S": "1 = StealthChop, 0 = SpreadCycle", "X": "X motor", "Y": "Y motor",
         "Z": "Z motor", "E": "Extruder motor"}, V, _describe_stealthchop),
    "M572": CommandInfo(
        "Pressure advance", "Tune how the extruder anticipates speed changes.",
        "Pressure in the nozzle lags behind the extruder. Pressure advance pushes a bit "
        "earlier and eases off sooner so lines stay even. The value comes from the "
        "filament profile.", {"S": "Pressure-advance value (0 = off)",
                              "D": "Which extruder", "W": "Smoothing time (s)"},
        V, _describe_pressure_advance),
    "M591": CommandInfo(
        "Stuck filament detection", "Turn stuck-filament detection on or off.",
        "The printer notices when the extruder can't push filament. PrusaSlicer turns it "
        "off for the purge line and restores it afterwards.",
        {"S": "1 = on, 0 = off", "R": "Restore saved setting"}, V, _describe_stuck),
    "M593": CommandInfo(
        "Input shaper settings", "Configure vibration cancelling (input shaping).",
        "The printer shapes its moves so they don't make the frame ring, which keeps walls "
        "smooth at high speed.",
        {"T": "Shaper type (0–5)", "F": "Frequency (Hz)", "D": "Damping ratio",
         "X": "Apply to X", "Y": "Apply to Y", "Z": "Apply to Z",
         "A": "Weight-adjust frequency change", "M": "Weight-adjust mass limit",
         "W": "Save to memory"}, V, _describe_input_shaper),
    "M601": CommandInfo("Pause print", "Pause the print (as if you pressed Pause).",
                        "PrusaSlicer inserts this for a pause you add in the preview.", source=V),
    "M602": CommandInfo("Resume print", "Resume a paused print.", source=V),
    "M603": CommandInfo("Stop print / filament change settings",
                        "MK3: stop the print. Buddy: configure filament-change lengths.", source=V),
    "M604": CommandInfo("Abort print", "Abort the print (used as an end-of-print command).",
                        source=V),
    "M701": CommandInfo("Load filament", "Load filament into the nozzle.", "",
                        {"T": "Extruder", "L": "Extrude length", "P": "MMU slot"}, V),
    "M702": CommandInfo("Unload filament", "Unload the filament from the nozzle.", "",
                        {"T": "Extruder", "U": "Retract length"}, V),
    "M704": CommandInfo("Preload to MMU", "Preload filament into an MMU slot.", "", {"P": "Slot"}, V),
    "M705": CommandInfo("Eject filament (MMU)", "Eject filament from an MMU slot.", "", {"P": "Slot"}, V),
    "M706": CommandInfo("Cut filament (MMU)", "Cut the filament in an MMU slot.", "", {"P": "Slot"}, V),
    "M863": CommandInfo("Tool remapping", "Redefine which tool prints which part.", source=V),
    "M864": CommandInfo("Spool join", "Configure automatic switching to a new spool.", source=V),
    "M870": CommandInfo("Chamber vent (CORE One)", "Open (O) or close (C) the chamber vent.",
                        "", {"O": "Open", "C": "Close"}, V, _describe_vent),
    "M900": CommandInfo(
        "Linear advance (MK3)", "Tune how the extruder anticipates speed changes.",
        "MK3 name for pressure advance. Newer Prusa printers use M572 but still accept "
        "M900 for compatibility.", {"K": "Strength (0 = off)"}, V),
    "M906": CommandInfo("Motor current", "Set motor current in milliamps.", "",
                        {"X": "mA", "Y": "mA", "Z": "mA", "E": "mA"}, V, _describe_motor_current),
    "M907": CommandInfo("Motor current (MK3)", "Set motor current.",
                        "PrusaSlicer lowers the extruder current for detailed prints and "
                        "resets it at the end.", {"E": "Extruder current"}, V,
                        _describe_motor_current),
    "M862.1": CommandInfo("Check nozzle", "Check the nozzle matches the file.",
                          "Part of Prusa's “print checking”: the printer verifies the file "
                          "fits the machine before starting.",
                          {"P": "Nozzle diameter (mm)", "A": "1 = abrasive-resistant needed",
                           "F": "1 = high-flow nozzle", "T": "Which tool"},
                          V, _describe_check("nozzle")),
    "M862.2": CommandInfo("Check model code", "Check the file was sliced for this printer model.",
                          "", {"P": "Model code"}, V, _describe_check("other")),
    "M862.3": CommandInfo("Check printer model", "Check the file was sliced for this printer model.",
                          "PrusaSlicer's comment: “printer model check”.",
                          {"_args": "Model name"}, V, _describe_check("model")),
    "M862.4": CommandInfo("Check firmware version", "Check the printer's firmware version.",
                          "", {"P": "Version"}, V, _describe_check("firmware")),
    "M862.5": CommandInfo("Check G-code level", "Check the printer understands this G-code version.",
                          "PrusaSlicer's comment: “g-code level check”.",
                          {"P": "G-code level"}, V, _describe_check("level")),
    "M862.6": CommandInfo("Check firmware feature", "Check the firmware supports a feature.",
                          "PrusaSlicer's comment: “FW feature check”.",
                          {"_args": "Feature name"}, V, _describe_check("feature")),
    "T": CommandInfo(
        "Change filament / tool", "Pick a filament slot (MMU3) or toolhead (XL).",
        "T0–T4 select MMU3 filament slots 1–5 or XL toolheads 1–5. Tx asks you to pick "
        "a slot; Tc loads the filament into the nozzle.", {}, V, _describe_tool),
    "TX": CommandInfo("Choose filament (MMU3)", "Ask you which filament slot to use.", source=V),
    "TC": CommandInfo("Load to nozzle (MMU3)", "Load the filament tip into the nozzle.", source=V),
    "P0": CommandInfo("Park tool (XL)", "Put the current toolhead back in its dock.", source=V),
}

COMMANDS: dict[str, CommandInfo] = {
    **common.marlin_commands(
        "PrusaSlicer", _FANS,
        "Speed S runs from 0 (off) to 255 (full). This controls the print fan that "
        "blows on the freshly printed plastic.",
        "On the MK3/MK4 the whole print head moves up and down; on the CORE One and "
        "XL the bed moves down instead."),
    **_PRUSA_COMMANDS,
}

# ---------------------------------------------------------------- comments

_FEATURES = {
    "Perimeter": "Inner walls of the part — they give it strength and support the "
                 "outer wall.",
    "External perimeter": "The outside surface of the part — what you see and touch. "
                          "Printed slowly and carefully for a clean finish.",
    "Overhang perimeter": "A wall leaning out over empty space. Printed slower with "
                          "extra cooling so it doesn't droop.",
    "Internal infill": "The hollow inner pattern (grid, gyroid…) that fills the inside "
                       "cheaply while keeping the part rigid.",
    "Solid infill": "Fully solid layers inside the part, e.g. just below the top surface.",
    "Top solid infill": "The last, visible layers on top of the part.",
    "Bridge infill": "Lines stretched across empty air between two supports, like a "
                     "bridge. Printed with extra cooling.",
    "Gap fill": "Small lines that fill gaps too narrow for a normal wall.",
    "Ironing": "The hot nozzle passes over the top surface again with very little "
               "plastic to smooth it.",
    "Skirt/Brim": "Loops around the part: a skirt primes the nozzle; a brim helps the "
                  "part stick to the bed.",
    "Skirt": "A loop around the part that primes the nozzle before printing.",
    "Support material": "Temporary scaffolding holding up overhanging parts. You "
                        "remove it after printing.",
    "Support material interface": "The top of the support, right under the part — "
                                  "designed to peel away cleanly.",
    "Wipe tower": "A small tower used to clean the nozzle after a filament change.",
    "Custom": "Code from the printer profile (start/end code), not generated from the model.",
    "Mixed": "A mix of several kinds of lines.",
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
    marker(r"^BEFORE_LAYER_CHANGE$", "Before layer change",
           "Slicer note: the printer profile's “before layer change” code follows."),
    marker(r"^AFTER_LAYER_CHANGE$", "After layer change",
           "Slicer note: the printer profile's “after layer change” code follows."),
    marker(r"^Z:([-\d.]+)$", "Layer height marker",
           "Slicer note: this layer is printed at Z = {0} mm."),
    marker(r"^HEIGHT:([-\d.]+)$", "Layer thickness",
           "Slicer note: lines here are {0} mm thick."),
    marker(r"^WIDTH:([-\d.]+)$", "Line width",
           "Slicer note: lines here are {0} mm wide (the nozzle is usually 0.4 mm)."),
    marker(r"^([-\d.]+)$", "Layer height",
           "Slicer note: the height of this layer (Z = {0} mm), written by the layer-change code."),
    marker(r"^WIPE_START", "Wipe starts",
           "Slicer note: the nozzle drags back along the line it just printed while "
           "pulling filament in, to avoid a blob or string."),
    marker(r"^WIPE_END", "Wipe ends", "Slicer note: end of the wipe move."),
    marker(r"^printing object (.+?)(?: id:(\d+))?(?: copy \d+)?$", "Object: {0}",
           "Slicer note: the following lines print the object “{0}”."),
    marker(r"^stop printing object", "Object ends",
           "Slicer note: the lines for this object end here."),
    marker(r"^generated by (PrusaSlicer \S+)", "Made by {0}",
           "This file was sliced with {0}."),
    marker(r"^thumbnail\w* (?:begin|end|\d+x\d+)", "Preview image",
           "Slicer note: an encoded preview picture of the model for the printer's screen."),
    marker(r"^prusaslicer_config = (begin|end)", "Slicer settings block",
           "Slicer note: a record of every slicer setting used. The printer ignores it."),
    marker(r"^(COLOR_CHANGE|PAUSE_PRINT|CUSTOM_GCODE)", "{0}",
           "Slicer note: a color change, pause or custom code you added in the slicer's "
           "preview follows."),
    marker(r"^MBL$", "Mesh bed leveling",
           "Prusa's heading: the mesh bed leveling steps follow."),
    marker(r"^prepare for purge", "Prepare for purge",
           "Prusa's heading: heat up and move to where the purge line will be printed."),
    marker(r"^Extrude purge line", "Purge line",
           "Prusa's heading: a short line at the front edge primes the nozzle so the "
           "model starts with plastic flowing evenly."),
    marker(r"^Min chamber temp section", "Chamber warm-up",
           "Prusa's heading: wait for the enclosure to warm up (for materials like ABS/ASA)."),
    marker(r"^Filament-specific (start|end) gcode", "Filament {0} code",
           "Slicer note: commands from the filament profile follow."),
    marker(r"^max_layer_z = ([-\d.]+)", "Print height",
           "Slicer note: the print is {0} mm tall."),
    *common.GENERIC_MARKERS,
    marker(r"^([A-Za-z][A-Za-z0-9 _()\[\]^/%.-]*?)\s*=\s*(.*)$", "Slicer info: {0}",
           "Written by the slicer: {0} = {1}. The printer ignores it."),
]


def _detect(sample: str) -> float:
    if "PrusaSlicer" in sample:
        return 1.0
    if "M862.3" in sample or "M862.1" in sample:
        return 0.9
    return 0.1


PROFILE = Profile(
    key="prusa",
    name="Prusa",
    description="Prusa CORE One, MK4/MK4S, MK3.5, MINI, XL and MK3/MK3S (PrusaSlicer G-code)",
    commands=COMMANDS,
    comment_markers=COMMENT_MARKERS,
    detect=_detect,
    vendor="Prusa",
)
