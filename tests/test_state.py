import unittest

from gcode_analyzer.parser import parse_line
from gcode_analyzer.state import MachineState, StateTracker


def run(*lines):
    state = MachineState()
    for line in lines:
        state.apply(parse_line(line))
    return state


class MachineStateTest(unittest.TestCase):
    def test_absolute_moves(self):
        s = run("G90", "G1 X10 Y20 Z0.2 F3000")
        self.assertEqual((s.x, s.y, s.z), (10, 20, 0.2))
        self.assertEqual(s.feed, 3000)

    def test_relative_moves(self):
        s = run("G92 X5 Y5", "G91", "G1 X1 Y-2")
        self.assertEqual((s.x, s.y), (6, 3))
        self.assertEqual(s.positioning, "relative")

    def test_relative_extrusion_accumulates(self):
        s = run("M83", "G92 E0", "G1 E1.5", "G1 X1 E0.5")
        self.assertEqual(s.e, 2.0)
        self.assertEqual(s.extrusion, "relative")

    def test_absolute_extrusion(self):
        s = run("M82", "G92 E0", "G1 E1.5", "G1 E2")
        self.assertEqual(s.e, 2.0)

    def test_g91_makes_extruder_relative_too(self):
        s = run("M82", "G92 E0", "G91", "G1 E1", "G1 E1")
        self.assertEqual(s.e, 2.0)

    def test_home_marks_position_unknown(self):
        s = run("G1 X10 Y10 Z10", "G28")
        self.assertIsNone(s.x)
        self.assertTrue(s.homed)

    def test_temperatures(self):
        s = run("M104 S220", "M140 S60", "M191 S40")
        self.assertEqual((s.hotend_target, s.bed_target, s.chamber_target), (220, 60, 40))

    def test_fans(self):
        s = run("M106 S255", "M106 P2 S128", "M106 P3 S0")
        self.assertEqual(s.part_fan, 100)
        self.assertEqual(s.aux_fan, 50)
        self.assertEqual(s.chamber_fan, 0)
        self.assertEqual(run("M106 S255", "M107").part_fan, 0)

    def test_progress(self):
        s = run("M73 P25 R40", "M73 L7")
        self.assertEqual((s.progress, s.remaining_min, s.layer), (25, 40, 7))

    def test_slicer_comments(self):
        s = run("; layer num/total_layer_count: 3/120", "; Z_HEIGHT: 0.6",
                "; FEATURE: Outer wall")
        self.assertEqual((s.layer, s.total_layers), (3, 120))
        self.assertEqual(s.z_height, 0.6)
        self.assertEqual(s.feature, "Outer wall")

    def test_filament_slot(self):
        self.assertEqual(run("T2").filament, 2)
        self.assertEqual(run("T2", "T1000").filament, 2)

    def test_units(self):
        self.assertEqual(run("G20").units, "inch")

    def test_unknown_command_is_ignored(self):
        s = run("M9999 S1")
        self.assertEqual(s, MachineState())


class StateTrackerTest(unittest.TestCase):
    def make_lines(self, n):
        return ["M83", "G90"] + [f"G1 X{i} E1" for i in range(n)]

    def test_state_after_line(self):
        tracker = StateTracker(self.make_lines(2000), interval=100)
        before, after = tracker.states_around(1501)  # "G1 X1499 E1"
        self.assertEqual(after.x, 1499)
        self.assertEqual(after.e, 1500)
        self.assertEqual(before.x, 1498)
        self.assertEqual(tracker.changed_fields(before, after), {"x", "e"})

    def test_matches_full_replay(self):
        lines = self.make_lines(1000)
        tracker = StateTracker(lines, interval=64)
        expected = run(*lines[:778])
        self.assertEqual(tracker.states_around(777)[1], expected)

    def test_edit_invalidates_later_checkpoints(self):
        lines = self.make_lines(1000)
        tracker = StateTracker(lines, interval=100)
        tracker.states_around(900)
        lines = list(lines)
        lines[10] = "G1 X0 E100"
        tracker.update_lines(lines, first_changed=10)
        self.assertEqual(tracker.states_around(900)[1], run(*lines[:901]))

    def test_first_line_before_state_is_default(self):
        tracker = StateTracker(["G1 X5"])
        before, after = tracker.states_around(0)
        self.assertEqual(before, MachineState())
        self.assertEqual(after.x, 5)


if __name__ == "__main__":
    unittest.main()
