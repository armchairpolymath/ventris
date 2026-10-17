import tempfile
import unittest
from pathlib import Path

from ventris import ruida
from ventris.dialects import detect_profile, get_profile
from ventris.explain import explain
from ventris.fileio import FileFormatError, load, save
from ventris.parser import parse_line
from ventris.state import MachineState


def enc35(value: int) -> bytes:
    value &= 0x7FFFFFFFF
    return bytes((value >> s) & 0x7F for s in (28, 21, 14, 7, 0))


def enc14(value: int) -> bytes:
    value &= 0x3FFF
    return bytes([(value >> 7) & 0x7F, value & 0x7F])


def mm(v: float) -> bytes:
    return enc35(round(v * 1000))


def rel(v: float) -> bytes:
    return enc14(round(v * 1000))


def pct(v: float) -> bytes:
    return enc14(round(v * 0x4000 / 100))


# A small job built from scratch: 30 mm/s, 40–70 % power, travel then two cuts.
JOB = [
    b"\xd8\x12",
    b"\xd8\x00",
    b"\xca\x01\x00",
    b"\xca\x02\x00",
    b"\xca\x01\x13",
    b"\xc9\x02" + mm(30),
    b"\xc6\x01" + pct(40),
    b"\xc6\x02" + pct(70),
    b"\x88" + mm(10) + mm(5),
    b"\xa8" + mm(60) + mm(5),
    b"\xa9" + rel(3) + rel(-2.5),
    b"\xca\x06\x00" + enc35(0x0000FF),
    b"\xe7\x01" + b"square\x00",
    b"\xd7",
]


def job_bytes(key: int = 0x88) -> bytes:
    return ruida.scramble(b"".join(JOB), key)


def explain_line(text: str, before: MachineState | None = None):
    before = before or MachineState()
    after = MachineState(**vars(before))
    line = parse_line(text)
    after.apply(line)
    return explain(line, before, after, get_profile("ruida"))


class RuidaDecoderTest(unittest.TestCase):
    def test_scramble_round_trip(self):
        data = bytes(range(256))
        for key in (0x88, 0x11, 0x38):
            self.assertEqual(ruida.unscramble(ruida.scramble(data, key), key), data)

    def test_decodes_job(self):
        doc = ruida.decode(job_bytes())
        lines = [c.to_line().split(" ; ")[0] for c in doc.commands]
        self.assertEqual(lines, [
            "ORIGIN_MODE M0", "START_PROCESS", "LAYER_END", "LAYER L0", "AIR_ASSIST_ON",
            "SPEED F30", "MIN_POWER S40", "MAX_POWER S70", "MOVE_ABS X10 Y5",
            "CUT_ABS X60 Y5", "CUT_REL X3 Y-2.5", "LAYER_COLOR L0 R255 G0 B0",
            "FILENAME square", "END_OF_FILE"])
        self.assertEqual(doc.key, 0x88)

    def test_raw_bytes_kept_on_each_line(self):
        doc = ruida.decode(job_bytes())
        self.assertTrue(doc.commands[0].to_line().endswith("; bytes: d8 12"))

    def test_finds_other_scramble_keys(self):
        self.assertEqual(ruida.decode(job_bytes(0x11)).key, 0x11)

    def test_power_matches_rdworks_settings(self):
        # Byte sequences and the % set in RDWorks, from jnweiger/ruida-laser's
        # laser_percentages test (example-files/laser_percentages/codes.txt).
        for raw, expected in [("c6 31 00 01 23", 1), ("c6 42 03 14 3d", 16),
                              ("c6 31 00 58 28", 69), ("c6 38 03 7f 7f", 100),
                              ("c6 01 58 28", 69)]:
            command = ruida.decode_command(bytes.fromhex(raw))
            self.assertEqual(round(float(dict(command.params)["S"])), expected, raw)

    def test_rejects_non_ruida_data(self):
        with self.assertRaises(ruida.RuidaError):
            ruida.decode(b"G1 X10 Y10\nG1 X20\n" * 20)
        with self.assertRaises(ruida.RuidaError):
            ruida.decode(b"")

    def test_unknown_and_truncated_commands(self):
        self.assertEqual(ruida.decode_command(b"\xe7\x99\x01").mnemonic, "UNKNOWN_E799")
        self.assertEqual(ruida.decode_command(b"\xa8\x00\x00").mnemonic, "INCOMPLETE_CUT_ABS")


class RuidaProfileTest(unittest.TestCase):
    def test_every_decoded_command_is_explained(self):
        profile = get_profile("ruida")
        for mnemonic, _fields in ruida._COMMANDS.values():
            self.assertIsNotNone(profile.lookup(mnemonic), mnemonic)

    def test_detected_from_decoded_text(self):
        text = ruida.decode(job_bytes()).to_text()
        self.assertEqual(detect_profile(text[:20000]).key, "ruida")

    def test_cut_uses_current_speed_and_power(self):
        before = MachineState(feed=1800, power_max=70)
        e = explain_line("CUT_ABS X60 Y5 ; bytes: a8", before)
        self.assertEqual(e.source, "community")
        self.assertIn("30 mm/s", e.sentence)
        self.assertIn("70%", e.sentence)
        self.assertIn("laser on", e.sentence)

    def test_travel_and_settings(self):
        self.assertIn("beam off", explain_line("MOVE_ABS X10 Y5").sentence)
        self.assertIn("40%", explain_line("MIN_POWER S40").sentence)
        self.assertIn("Layer 0", explain_line("LAYER_MIN_POWER L0 S40").sentence)
        self.assertIn("#ff0000", explain_line("LAYER_COLOR L0 R255 G0 B0").sentence)

    def test_header_comments(self):
        e = explain_line("; Ruida laser job (.rd) decoded by Ventris — read-only")
        self.assertIn("don't use G-code", e.sentence)


class RuidaFileTest(unittest.TestCase):
    def test_load_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "square.rd"
            path.write_bytes(job_bytes())
            doc = load(path)
            self.assertTrue(doc.read_only)
            self.assertIn("CUT_ABS X60 Y5", doc.text)
            with self.assertRaises(FileFormatError):
                save(doc, doc.text, Path(tmp) / "copy.gcode")
            self.assertEqual(path.read_bytes(), job_bytes())

    def test_bad_rd_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.rd"
            path.write_bytes(b"not a laser job" * 10)
            with self.assertRaises(FileFormatError):
                load(path)

    def test_state_through_decoded_job(self):
        s = MachineState()
        for line in ruida.decode(job_bytes()).to_text().splitlines():
            s.apply(parse_line(line))
        self.assertEqual((s.x, s.y), (63, 2.5))
        self.assertEqual((s.feed, s.power_min, s.power_max, s.air_assist, s.layer),
                         (1800, 40, 70, True, 0))
        self.assertEqual(s.laser, "off")  # END_OF_FILE


if __name__ == "__main__":
    unittest.main()
