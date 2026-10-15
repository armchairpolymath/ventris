"""Combine a parsed line, the machine state, and a profile into an Explanation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .parser import ParsedLine
from .reference import Profile
from .state import MachineState

_SETTING = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*(.*)$")


@dataclass
class ParamExplanation:
    letter: str
    value: str
    meaning: str


@dataclass
class Explanation:
    kind: str  # "command", "comment", "unknown", "blank"
    title: str
    sentence: str
    summary: str = ""
    details: str = ""
    source: str = ""
    params: list[ParamExplanation] = field(default_factory=list)
    comment: str | None = None  # a trailing comment written next to a command


def explain(line: ParsedLine, before: MachineState, after: MachineState,
            profile: Profile) -> Explanation:
    if line.code is None:
        if line.comment is None:
            return Explanation("blank", "Blank line",
                               "An empty line. The printer skips it; it only makes "
                               "the file easier for people to read.")
        return _explain_comment(line.comment, profile)

    info = profile.lookup(line.code)
    if info is None:
        return Explanation(
            "unknown", f"{line.code} — Not in the {profile.name} reference",
            f"This app doesn't know what {line.code} does on {profile.name} machines. "
            "It may be an undocumented firmware command, a command meant for a "
            "different machine, or a typo.",
            params=[ParamExplanation(k, v, "") for k, v in line.params.items()],
            comment=line.comment)

    sentence = info.describe(line, before, after) if info.describe else info.summary
    params = []
    for letter, value in line.params.items():
        if letter == "_args":
            params.append(ParamExplanation("", value, info.params.get("_args", "")))
        else:
            params.append(ParamExplanation(letter, value, info.params.get(letter, "")))
    return Explanation("command", f"{line.code} — {info.name}", sentence,
                       summary=info.summary, details=info.details, source=info.source,
                       params=params, comment=line.comment)


def _explain_comment(comment: str, profile: Profile) -> Explanation:
    for marker in profile.comment_markers:
        match = marker.pattern.search(comment)
        if match:
            return Explanation("comment", marker.title,
                               marker.explanation.format(*match.groups(),
                                                         **match.groupdict()),
                               comment=comment)
    if m := _SETTING.match(comment):
        return Explanation(
            "comment", "Slicer setting",
            f"The slicer wrote down that its setting “{m.group(1)}” was “{m.group(2)}” "
            "when this file was made. The printer ignores it; it is a record for people "
            "and tools.", comment=comment)
    return Explanation("comment", "Comment",
                       "Everything after a semicolon is a note for humans. The printer "
                       "ignores it.", comment=comment)
