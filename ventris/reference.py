"""Data types that describe a machine's G-code dialect.

A Profile is everything the app knows about one family of machines. Adding a
new machine type means writing a new module in dialects/ that builds a Profile.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .parser import ParsedLine
from .state import MachineState

# describe(line, state_before, state_after) -> one sentence about *this* line
Describer = Callable[[ParsedLine, MachineState, MachineState], str]


@dataclass
class CommandInfo:
    name: str
    summary: str
    details: str = ""
    params: dict[str, str] = field(default_factory=dict)
    source: str = "documented"  # "documented" or "community"
    describe: Describer | None = None


@dataclass
class CommentMarker:
    pattern: re.Pattern
    title: str
    explanation: str


@dataclass
class Profile:
    key: str
    name: str
    description: str
    commands: dict[str, CommandInfo]
    comment_markers: list[CommentMarker]
    detect: Callable[[str], float]
    vendor: str = ""  # short maker name for labels ("Bambu", "Prusa")
    kind: str = "printer"  # "printer" or "laser": picks the machine-state panel
    fan_slots: dict[int, str] | None = None  # M106 P -> state field; None = Bambu-style

    def lookup(self, code: str) -> CommandInfo | None:
        if code in self.commands:
            return self.commands[code]
        if code.startswith("T") and code[1:].isdigit():
            return self.commands.get("T")
        return None


def num(value: float | None, unit: str = "", digits: int = 3) -> str:
    """Format a number compactly: 10.0 -> '10', 0.03832 -> '0.038'."""
    if value is None:
        return "?"
    text = f"{round(value, digits):g}"
    return f"{text} {unit}".strip() if unit else text
