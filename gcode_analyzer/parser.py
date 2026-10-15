"""Turn one line of G-code text into a structured ParsedLine. No GTK here."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_LINE_NUMBER = re.compile(r"^\s*[Nn]\d+\s*")
_CHECKSUM = re.compile(r"\*\d+\s*$")
_CODE = re.compile(r"^([GMTgmt])(\d+)(?:\.(\d+))?")
_MACRO = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)")
_PARAM = re.compile(r"\s*([A-Za-z])([-+]?(?:\d+\.?\d*|\.\d+))?")


@dataclass
class ParsedLine:
    raw: str
    code: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    comment: str | None = None

    @property
    def is_blank(self) -> bool:
        return self.code is None and self.comment is None

    def has(self, letter: str) -> bool:
        return letter in self.params

    def number(self, letter: str) -> float | None:
        value = self.params.get(letter)
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None


def parse_line(text: str) -> ParsedLine:
    result = ParsedLine(raw=text)
    body = text
    if ";" in body:
        body, comment = body.split(";", 1)
        result.comment = comment.strip()
    body = _CHECKSUM.sub("", _LINE_NUMBER.sub("", body)).strip()
    if not body:
        return result

    match = _CODE.match(body)
    if match:
        letter, number, sub = match.groups()
        result.code = f"{letter.upper()}{int(number)}" + (f".{sub}" if sub else "")
        rest = body[match.end():]
        result.params = _parse_params(rest)
        return result

    match = _MACRO.match(body)
    if match:
        result.code = match.group(1).upper()
        rest = body[match.end():].strip()
        if rest:
            result.params = {"_args": rest}
        return result

    result.params = {"_args": body}
    return result


def _parse_params(rest: str) -> dict[str, str]:
    """Parse 'X1 Y2 E.5' style words; fall back to raw text for anything else."""
    params: dict[str, str] = {}
    pos = 0
    stripped = rest.rstrip()
    while pos < len(stripped):
        match = _PARAM.match(stripped, pos)
        if not match:
            return {"_args": rest.strip()}
        letter, value = match.groups()
        end = match.end()
        # A bare letter must stand alone, otherwise this is a word like "judge_flag".
        if value is None and end < len(stripped) and not stripped[end].isspace():
            return {"_args": rest.strip()}
        params[letter.upper()] = value or ""
        pos = end
    return params
