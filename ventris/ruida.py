"""Decode Ruida laser controller job files (.rd) into readable lines.

Ruida controllers (Thunder Laser Nova, many Chinese CO2 lasers) don't run G-code.
LightBurn and RDWorks send them a scrambled binary command stream. This module
unscrambles it and writes one line per command, e.g.

    CUT_ABS X50 Y0 ; bytes: a8 00 00 03 06 50 00 00 00 00 00

Units are converted for people: positions in mm, speeds in mm/s, power in %.
The byte layout and command meanings come from community reverse-engineering,
mainly MeerK40t (MIT, meerk40t/ruida/rdjob.py) and jnweiger/ruida-laser.
Read-only: Ventris never writes .rd files.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_KEY = 0x88  # used by RDWorks and LightBurn's generic RD export

# First bytes of commands we recognise; used to pick the scramble key.
_OPCODES = {0x80, 0x88, 0x89, 0x8A, 0x8B, 0xA0, 0xA8, 0xA9, 0xAA, 0xAB, 0xC0, 0xC1, 0xC2,
            0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xD0, 0xD7, 0xD8, 0xD9, 0xDA,
            0xE5, 0xE6, 0xE7, 0xE8, 0xEA, 0xEB, 0xF0, 0xF1, 0xF2}


class RuidaError(Exception):
    pass


# ---------------------------------------------------------------- scrambling


def _unscramble_byte(b: int, key: int) -> int:
    b = (b - 1) & 0xFF
    b ^= key
    b ^= (b >> 7) & 0xFF
    b ^= (b << 7) & 0xFF
    b ^= (b >> 7) & 0xFF
    return b


def _scramble_byte(b: int, key: int) -> int:
    b ^= (b >> 7) & 0xFF
    b ^= (b << 7) & 0xFF
    b ^= (b >> 7) & 0xFF
    b ^= key
    return (b + 1) & 0xFF


def unscramble(data: bytes, key: int = DEFAULT_KEY) -> bytes:
    table = bytes(_unscramble_byte(i, key) for i in range(256))
    return data.translate(table)


def scramble(data: bytes, key: int = DEFAULT_KEY) -> bytes:
    """Inverse of unscramble (used by the tests to build sample files)."""
    table = bytes(_scramble_byte(i, key) for i in range(256))
    return data.translate(table)


def _plausibility(data: bytes) -> float:
    """Share of command bytes (high bit set) that are known Ruida opcodes."""
    starts = [b for b in data if b >= 0x80]
    if not starts:
        return 0.0
    return sum(b in _OPCODES for b in starts) / len(starts)


def find_key(data: bytes) -> tuple[int, float]:
    """Pick the scramble key whose decoding looks most like Ruida commands.

    Different controller models use different keys. Most files use 0x88, which
    wins ties. Guessing from byte frequencies (as some tools do) picks the wrong
    key on long engraving files, so every key is scored instead.
    """
    sample = data[:20000]
    best_key, best = DEFAULT_KEY, _plausibility(unscramble(sample, DEFAULT_KEY))
    for key in range(256):
        score = _plausibility(unscramble(sample, key))
        if score > best + 0.02:
            best_key, best = key, score
    return best_key, best


def split_commands(data: bytes) -> list[bytes]:
    """Every command starts with a byte >= 0x80; parameter bytes are all < 0x80."""
    commands, mark = [], 0
    for i, b in enumerate(data):
        if b >= 0x80 and i != mark:
            commands.append(data[mark:i])
            mark = i
    if mark < len(data):
        commands.append(data[mark:])
    return commands


# ---------------------------------------------------------------- values


def _u35(b: bytes) -> int:
    v = 0
    for x in b[:5]:
        v = (v << 7) | (x & 0x7F)
    return v


def _s32(b: bytes) -> int:
    v = _u35(b) & 0xFFFFFFFF
    return v - 0x100000000 if v > 0x7FFFFFFF else v


def _u14(b: bytes) -> int:
    return ((b[0] & 0x7F) << 7) | (b[1] & 0x7F)


def _s14(b: bytes) -> int:
    v = _u14(b)
    return v - 0x4000 if v > 0x1FFF else v


def _fmt(value: float, digits: int = 3) -> str:
    return f"{round(value, digits):g}"


# Each parameter spec: (letter, kind). Kinds and their sizes in bytes:
#   abs 5 (µm -> mm), rel 2 (signed µm -> mm), speed 5 (µm/s -> mm/s),
#   power 2 (-> %), time 5 (-> ms), freq 5 (Hz), byte 1, u35 5, rgb 5, str (rest)
_SIZES = {"abs": 5, "rel": 2, "speed": 5, "power": 2, "time": 5, "freq": 5, "byte": 1,
          "u35": 5, "rgb": 5, "u14": 2, "str": None}


def _value(kind: str, raw: bytes) -> str:
    if kind == "abs":
        return _fmt(_s32(raw) / 1000)
    if kind == "rel":
        return _fmt(_s14(raw) / 1000)
    if kind == "speed":
        return _fmt(_u35(raw) / 1000)
    if kind == "power":
        return _fmt(_u14(raw) * 100 / 0x4000, 2)
    if kind == "time":
        return _fmt(_u35(raw) / 1000)
    if kind in ("freq", "u35"):
        return str(_u35(raw))
    if kind == "u14":
        return str(_s14(raw))
    if kind == "byte":
        return str(raw[0])
    raise ValueError(kind)


# (opcode bytes) -> (mnemonic, [(letter, kind), ...])
_COMMANDS: dict[bytes, tuple[str, list[tuple[str, str]]]] = {
    b"\x88": ("MOVE_ABS", [("X", "abs"), ("Y", "abs")]),
    b"\x89": ("MOVE_REL", [("X", "rel"), ("Y", "rel")]),
    b"\x8a": ("MOVE_REL_X", [("X", "rel")]),
    b"\x8b": ("MOVE_REL_Y", [("Y", "rel")]),
    b"\xa8": ("CUT_ABS", [("X", "abs"), ("Y", "abs")]),
    b"\xa9": ("CUT_REL", [("X", "rel"), ("Y", "rel")]),
    b"\xaa": ("CUT_REL_X", [("X", "rel")]),
    b"\xab": ("CUT_REL_Y", [("Y", "rel")]),
    b"\x80\x00": ("AXIS_MOVE_X", [("X", "abs")]),
    b"\x80\x08": ("AXIS_MOVE_Z", [("Z", "abs")]),
    b"\xa0\x00": ("AXIS_MOVE_Y", [("Y", "abs")]),
    b"\xa0\x08": ("AXIS_MOVE_U", [("U", "abs")]),
    b"\xc7": ("IMMEDIATE_POWER", [("S", "power")]),
    b"\xc0": ("IMMEDIATE_POWER_2", [("S", "power")]),
    b"\xc2": ("IMMEDIATE_POWER_3", [("S", "power")]),
    b"\xc3": ("IMMEDIATE_POWER_4", [("S", "power")]),
    b"\xc8": ("END_POWER", [("S", "power")]),
    b"\xc1": ("END_POWER_2", [("S", "power")]),
    b"\xc4": ("END_POWER_3", [("S", "power")]),
    b"\xc5": ("END_POWER_4", [("S", "power")]),
    b"\xc6\x01": ("MIN_POWER", [("S", "power")]),
    b"\xc6\x02": ("MAX_POWER", [("S", "power")]),
    b"\xc6\x21": ("MIN_POWER_2", [("S", "power")]),
    b"\xc6\x22": ("MAX_POWER_2", [("S", "power")]),
    b"\xc6\x05": ("MIN_POWER_3", [("S", "power")]),
    b"\xc6\x06": ("MAX_POWER_3", [("S", "power")]),
    b"\xc6\x07": ("MIN_POWER_4", [("S", "power")]),
    b"\xc6\x08": ("MAX_POWER_4", [("S", "power")]),
    b"\xc6\x10": ("LASER_INTERVAL", [("T", "time")]),
    b"\xc6\x11": ("ADD_DELAY", [("T", "time")]),
    b"\xc6\x12": ("LASER_ON_DELAY", [("T", "time")]),
    b"\xc6\x13": ("LASER_OFF_DELAY", [("T", "time")]),
    b"\xc6\x15": ("LASER_ON_DELAY_2", [("T", "time")]),
    b"\xc6\x16": ("LASER_OFF_DELAY_2", [("T", "time")]),
    b"\xc6\x31": ("LAYER_MIN_POWER", [("L", "byte"), ("S", "power")]),
    b"\xc6\x32": ("LAYER_MAX_POWER", [("L", "byte"), ("S", "power")]),
    b"\xc6\x41": ("LAYER_MIN_POWER_2", [("L", "byte"), ("S", "power")]),
    b"\xc6\x42": ("LAYER_MAX_POWER_2", [("L", "byte"), ("S", "power")]),
    b"\xc6\x35": ("LAYER_MIN_POWER_3", [("L", "byte"), ("S", "power")]),
    b"\xc6\x36": ("LAYER_MAX_POWER_3", [("L", "byte"), ("S", "power")]),
    b"\xc6\x37": ("LAYER_MIN_POWER_4", [("L", "byte"), ("S", "power")]),
    b"\xc6\x38": ("LAYER_MAX_POWER_4", [("L", "byte"), ("S", "power")]),
    b"\xc6\x50": ("THROUGH_POWER", [("S", "power")]),
    b"\xc6\x51": ("THROUGH_POWER_2", [("S", "power")]),
    b"\xc6\x55": ("THROUGH_POWER_3", [("S", "power")]),
    b"\xc6\x56": ("THROUGH_POWER_4", [("S", "power")]),
    b"\xc6\x60": ("LAYER_FREQUENCY", [("P", "byte"), ("L", "byte"), ("F", "freq")]),
    b"\xc9\x02": ("SPEED", [("F", "speed")]),
    b"\xc9\x03": ("AXIS_SPEED", [("F", "speed")]),
    b"\xc9\x04": ("LAYER_SPEED", [("L", "byte"), ("F", "speed")]),
    b"\xc9\x05": ("FORCE_ENGRAVE_SPEED", [("F", "speed")]),
    b"\xc9\x06": ("AXIS_MOVE_SPEED", [("F", "speed")]),
    b"\xca\x01\x00": ("LAYER_END", []),
    b"\xca\x01\x01": ("WORK_MODE", [("M", "const1")]),
    b"\xca\x01\x02": ("WORK_MODE", [("M", "const2")]),
    b"\xca\x01\x03": ("WORK_MODE", [("M", "const3")]),
    b"\xca\x01\x04": ("WORK_MODE", [("M", "const4")]),
    b"\xca\x01\x55": ("WORK_MODE", [("M", "const5")]),
    b"\xca\x01\x05": ("WORK_MODE", [("M", "const6")]),
    b"\xca\x01\x10": ("LAYER_DEVICE", [("N", "const0")]),
    b"\xca\x01\x11": ("LAYER_DEVICE", [("N", "const1")]),
    b"\xca\x01\x12": ("AIR_ASSIST_OFF", []),
    b"\xca\x01\x13": ("AIR_ASSIST_ON", []),
    b"\xca\x01\x14": ("DOUBLE_HEAD", []),
    b"\xca\x01\x30": ("LASER2_OFFSET", [("S", "const0")]),
    b"\xca\x01\x31": ("LASER2_OFFSET", [("S", "const1")]),
    b"\xca\x02": ("LAYER", [("L", "byte")]),
    b"\xca\x03": ("LASER_TUBE_ENABLE", [("N", "byte")]),
    b"\xca\x04": ("X_SIGN_MAP", [("N", "byte")]),
    b"\xca\x05": ("LAYER_COLOR", [("C", "rgb")]),
    b"\xca\x06": ("LAYER_COLOR", [("L", "byte"), ("C", "rgb")]),
    b"\xca\x10": ("EXTERNAL_IO", [("N", "byte")]),
    b"\xca\x22": ("LAYER_COUNT", [("L", "byte")]),
    b"\xca\x30": ("U_FILE_ID", [("N", "u14")]),
    b"\xca\x40": ("ZU_MAP", [("N", "byte")]),
    b"\xca\x41": ("LAYER_WORK_MODE", [("L", "byte"), ("M", "byte")]),
    b"\xd0": ("INHALE_ZONE", [("N", "byte")]),
    b"\xd7": ("END_OF_FILE", []),
    b"\xd8\x00": ("START_PROCESS", []),
    b"\xd8\x10": ("ORIGIN_MODE", [("M", "const2")]),
    b"\xd8\x11": ("ORIGIN_MODE", [("M", "const1")]),
    b"\xd8\x12": ("ORIGIN_MODE", [("M", "const0")]),
    b"\xd9\x00": ("RAPID_MOVE_X", [("O", "byte"), ("X", "abs")]),
    b"\xd9\x01": ("RAPID_MOVE_Y", [("O", "byte"), ("Y", "abs")]),
    b"\xd9\x02": ("RAPID_MOVE_Z", [("O", "byte"), ("Z", "abs")]),
    b"\xd9\x03": ("RAPID_MOVE_U", [("O", "byte"), ("U", "abs")]),
    b"\xd9\x10": ("RAPID_MOVE_XY", [("O", "byte"), ("X", "abs"), ("Y", "abs")]),
    b"\xda\x00": ("GET_SETTING", [("A", "u14")]),
    b"\xda\x01": ("SET_SETTING", [("A", "u14"), ("V", "u35"), ("W", "u35")]),
    b"\xe5\x00": ("DOCUMENT_PAGE", [("N", "byte")]),
    b"\xe5\x02": ("DOCUMENT_DATA_END", []),
    b"\xe5\x05": ("FILE_CHECKSUM", [("N", "u35")]),
    b"\xe6\x01": ("SET_ABSOLUTE", []),
    b"\xe7\x00": ("BLOCK_END", []),
    b"\xe7\x01": ("FILENAME", [("", "str")]),
    b"\xe7\x03": ("JOB_TOP_LEFT", [("X", "abs"), ("Y", "abs")]),
    b"\xe7\x04": ("JOB_REPEAT", []),
    b"\xe7\x05": ("ARRAY_DIRECTION", [("N", "byte")]),
    b"\xe7\x06": ("FEED_REPEAT", [("A", "u35"), ("B", "u35")]),
    b"\xe7\x07": ("JOB_BOTTOM_RIGHT", [("X", "abs"), ("Y", "abs")]),
    b"\xe7\x08": ("ARRAY_REPEAT", []),
    b"\xe7\x09": ("FEED_LENGTH", [("N", "u35")]),
    b"\xe7\x13": ("ARRAY_MIN_POINT", [("X", "abs"), ("Y", "abs")]),
    b"\xe7\x17": ("ARRAY_MAX_POINT", [("X", "abs"), ("Y", "abs")]),
    b"\xe7\x23": ("ARRAY_ADD", [("X", "abs"), ("Y", "abs")]),
    b"\xe7\x24": ("ARRAY_MIRROR", [("N", "byte")]),
    b"\xe7\x50": ("JOB_MIN_POINT", [("X", "abs"), ("Y", "abs")]),
    b"\xe7\x51": ("JOB_MAX_POINT", [("X", "abs"), ("Y", "abs")]),
    b"\xe7\x52": ("LAYER_MIN_POINT", [("L", "byte"), ("X", "abs"), ("Y", "abs")]),
    b"\xe7\x53": ("LAYER_MAX_POINT", [("L", "byte"), ("X", "abs"), ("Y", "abs")]),
    b"\xe7\x54": ("PEN_OFFSET", [("N", "byte"), ("V", "abs")]),
    b"\xe7\x55": ("LAYER_OFFSET", [("N", "byte"), ("V", "abs")]),
    b"\xe7\x60": ("ELEMENT_INDEX", [("N", "byte")]),
    b"\xe7\x61": ("LAYER_MIN_POINT_EX", [("L", "byte"), ("X", "abs"), ("Y", "abs")]),
    b"\xe7\x62": ("LAYER_MAX_POINT_EX", [("L", "byte"), ("X", "abs"), ("Y", "abs")]),
    b"\xe8\x02": ("FILE_TRANSFER", []),
    b"\xea": ("ARRAY_START", [("N", "byte")]),
    b"\xeb": ("ARRAY_END", []),
    b"\xf0": ("REFERENCE_POINT", []),
    b"\xf1\x00": ("ELEMENT_MAX_INDEX", [("N", "byte")]),
    b"\xf1\x01": ("ELEMENT_NAME_MAX_INDEX", [("N", "byte")]),
    b"\xf1\x02": ("BLOCK_CUTTING", [("N", "byte")]),
    b"\xf1\x03": ("DISPLAY_OFFSET", [("X", "abs"), ("Y", "abs")]),
    b"\xf1\x04": ("FEED_AUTO_CALC", [("N", "byte")]),
    b"\xf2\x00": ("ELEMENT", [("N", "byte")]),
    b"\xf2\x01": ("ELEMENT_NAME_INDEX", [("N", "byte")]),
    b"\xf2\x02": ("ELEMENT_NAME", []),
    b"\xf2\x03": ("ELEMENT_MIN_POINT", [("X", "abs"), ("Y", "abs")]),
    b"\xf2\x04": ("ELEMENT_MAX_POINT", [("X", "abs"), ("Y", "abs")]),
    b"\xf2\x05": ("ELEMENT_ARRAY", []),
    b"\xf2\x06": ("ELEMENT_ARRAY_ADD", [("X", "abs"), ("Y", "abs")]),
    b"\xf2\x07": ("ELEMENT_ARRAY_MIRROR", [("N", "byte")]),
}
_PREFIX_LENGTHS = sorted({len(k) for k in _COMMANDS}, reverse=True)


@dataclass
class Command:
    raw: bytes
    mnemonic: str
    params: list[tuple[str, str]]

    def to_line(self) -> str:
        parts = [self.mnemonic]
        for letter, value in self.params:
            parts.append(f"{letter}{value}" if letter else value)
        return f"{' '.join(parts)} ; bytes: {self.raw.hex(' ')}"


def decode_command(raw: bytes) -> Command:
    for n in _PREFIX_LENGTHS:
        spec = _COMMANDS.get(raw[:n])
        if spec is None:
            continue
        mnemonic, fields = spec
        params, pos = [], n
        try:
            for letter, kind in fields:
                if kind.startswith("const"):
                    params.append((letter, kind[5:]))
                    continue
                if kind == "str":
                    text = raw[pos:].split(b"\x00", 1)[0].decode("latin-1")
                    params.append(("", text))
                    pos = len(raw)
                    continue
                if kind == "rgb":
                    value = _u35(raw[pos:pos + 5])
                    r, g, b = value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
                    params += [("R", str(r)), ("G", str(g)), ("B", str(b))]
                    pos += 5
                    continue
                size = _SIZES[kind]
                chunk = raw[pos:pos + size]
                if len(chunk) < size:
                    raise IndexError
                params.append((letter, _value(kind, chunk)))
                pos += size
        except (IndexError, ValueError):
            return Command(raw, "INCOMPLETE_" + mnemonic, [])
        return Command(raw, mnemonic, params)
    if raw and raw[0] < 0x80:
        return Command(raw, "DATA", [])
    return Command(raw, "UNKNOWN_" + raw[:2].hex().upper(), [])


@dataclass
class RdDocument:
    key: int
    commands: list[Command]

    def to_text(self) -> str:
        header = [
            "; Ruida laser job (.rd) decoded by Ventris — read-only",
            f"; scramble key: 0x{self.key:02x}, {len(self.commands)} commands",
            "; Each line is one controller command; its raw bytes follow “bytes:”.",
        ]
        return "\n".join(header + [c.to_line() for c in self.commands]) + "\n"


def _recognised(commands: list[Command]) -> float:
    ok = sum(not c.mnemonic.startswith(("UNKNOWN_", "INCOMPLETE_", "DATA")) for c in commands)
    return ok / len(commands) if commands else 0.0


def decode(data: bytes) -> RdDocument:
    if not data:
        raise RuidaError("The file is empty.")
    key, score = find_key(data)
    plain = unscramble(data, key)
    commands = [decode_command(c) for c in split_commands(plain)]
    # Opcode bytes alone can look right by chance (e.g. text unscrambled with some key);
    # real jobs start with a command and almost every command parses completely.
    if score < 0.9 or plain[0] < 0x80 or _recognised(commands) < 0.9:
        raise RuidaError("This doesn't look like a Ruida .rd job file (couldn't unscramble it).")
    return RdDocument(key, commands)
