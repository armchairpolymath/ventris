import unittest

from gcode_analyzer.dialects import get_profile, profiles
from gcode_analyzer.explain import explain
from gcode_analyzer.parser import parse_line
from gcode_analyzer.state import MachineState


def ex(text, before=None):
    before = before or MachineState()
    after = MachineState(**vars(before))
    line = parse_line(text)
    after.apply(line)
    return explain(line, before, after, get_profile("bambu"))


class ExplainTest(unittest.TestCase):
    def test_profile_registry(self):
        self.assertIn("bambu", [p.key for p in profiles()])

    def test_extruding_move(self):
        e = ex("G1 X145.2 Y72.256 E.03832")
        self.assertEqual(e.kind, "command")
        self.assertEqual(e.title, "G1 — Move")
        self.assertIn("X 145.2", e.sentence)
        self.assertIn("pushing out 0.038 mm of filament", e.sentence)
        self.assertEqual([p.letter for p in e.params], ["X", "Y", "E"])

    def test_travel_move(self):
        self.assertIn("without printing", ex("G1 X10 Y10 F30000").sentence)

    def test_retract(self):
        self.assertIn("pulls", ex("G1 E-.8 F1800").sentence)

    def test_feed_only(self):
        self.assertIn("50 mm/s", ex("G1 F3000").sentence)

    def test_temperature_wait(self):
        e = ex("M109 S220")
        self.assertIn("220 °C", e.sentence)
        self.assertIn("wait", e.sentence.lower())

    def test_fan_percent(self):
        self.assertIn("50%", ex("M106 P2 S128").sentence)
        self.assertIn("auxiliary", ex("M106 P2 S128").sentence)

    def test_bambu_specific_is_community_sourced(self):
        e = ex("M1002 gcode_claim_action : 14")
        self.assertEqual(e.source, "community")
        self.assertIn("nozzle", e.sentence.lower())

    def test_tool_change(self):
        self.assertIn("slot 2", ex("T1").sentence)
        self.assertIn("unload", ex("T255").sentence.lower())

    def test_switch_commands(self):
        self.assertEqual(ex("M975 S1").sentence, "Turn on vibration suppression (input shaping).")
        self.assertIn("off", ex("M412 S0").sentence)

    def test_z_only_move(self):
        self.assertTrue(ex("G1 Z1").sentence.startswith("Change the nozzle height to Z 1 mm"))

    def test_unknown_command(self):
        e = ex("M9999 S1")
        self.assertEqual(e.kind, "unknown")
        self.assertIn("M9999", e.title)

    def test_comment_marker(self):
        e = ex("; FEATURE: Outer wall")
        self.assertEqual(e.kind, "comment")
        self.assertIn("outside", e.sentence.lower())

    def test_config_comment(self):
        e = ex("; nozzle_diameter = 0.4")
        self.assertEqual(e.kind, "comment")
        self.assertIn("nozzle_diameter", e.sentence)

    def test_commented_out_command(self):
        self.assertEqual(ex("; G28 ; home again").title, "Disabled command")

    def test_header_info(self):
        self.assertIn("1.75", ex("; filament_diameter: 1.75,1.75").sentence)

    def test_section_label(self):
        e = ex(";===== wipe nozzle =====")
        self.assertIn("wipe nozzle", e.sentence)

    def test_plain_comment(self):
        self.assertIn("ignores", ex("; hello").sentence)

    def test_blank(self):
        self.assertEqual(ex("").kind, "blank")

    def test_trailing_comment_noted(self):
        self.assertEqual(ex("M104 S220 ; set nozzle").comment, "set nozzle")

    def test_every_command_has_text(self):
        for code, info in get_profile("bambu").commands.items():
            self.assertTrue(info.summary, code)
            self.assertIn(info.source, ("documented", "community"), code)


if __name__ == "__main__":
    unittest.main()
