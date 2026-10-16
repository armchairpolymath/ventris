import unittest

from gcode_analyzer.dialects import get_profile
from gcode_analyzer.explain import explain
from gcode_analyzer.parser import parse_line
from gcode_analyzer.presentation import (STATE_ROWS, details, file_note, param_rows,
                                         source_badge)
from gcode_analyzer.state import MachineState


def ex(text, profile="bambu"):
    line = parse_line(text)
    after = MachineState()
    after.apply(line)
    return explain(line, MachineState(), after, get_profile(profile))


class PresentationTest(unittest.TestCase):
    def test_badges(self):
        self.assertEqual(source_badge(ex("G1 X1")).text, "Standard G-code")
        self.assertEqual(source_badge(ex("M1002 judge_flag x")).kind, "community")
        self.assertIn("documented by Prusa", source_badge(ex("M572 S0.04", "prusa")).text)
        self.assertEqual(source_badge(ex("; hi")).kind, "note")
        self.assertEqual(source_badge(ex("M9999")).kind, "unknown")

    def test_param_rows(self):
        self.assertEqual(param_rows(ex("G28 X"))[0][0], "X (no value)")
        self.assertEqual(param_rows(ex("G1 X5"))[0], ("X = 5", "Left/right position (mm)"))

    def test_file_note_and_details(self):
        self.assertIn("set nozzle", file_note(ex("M104 S200 ; set nozzle")))
        self.assertIsNone(file_note(ex("; just a comment")))
        label, body = details(ex("G1 X1"))
        self.assertEqual(label, "More about G1")
        self.assertIn("workhorse", body)

    def test_state_rows_format_default_state(self):
        for _group, rows in STATE_ROWS:
            for _label, _fields, fmt, _tip in rows:
                self.assertIsInstance(fmt(MachineState()), str)


if __name__ == "__main__":
    unittest.main()
