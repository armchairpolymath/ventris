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

    def test_a1_codes_are_known(self):
        for line in ["G392 S0", "M9833.2", "G39 S1", "G39.3 S1", "G39.4", "G29.4",
                     "G2814 Z0.32", "M211 X0 Y0 Z0", "M900 S", "M983 F6.8 A0.3 H0.6",
                     "M984 A0.1 E1 S1 F6.8 H0.6", "M970.2 Q1 K1 W58 Z0.1", "M630 S0 P0",
                     "M982.2 S1", "M620.3 W1", "M1007 S1"]:
            self.assertEqual(ex(line).kind, "command", line)

    def test_clog_detection_switch(self):
        self.assertEqual(ex("G392 S0").sentence, "Turn off nozzle clog detection.")
        self.assertEqual(ex("G392 S1").sentence, "Turn on nozzle clog detection.")

    def test_unknown_purpose_is_said_plainly(self):
        self.assertIn("isn't public", ex("M9833.2").sentence)

    def test_m211_soft_endstops(self):
        self.assertIn("travel limits", ex("M211 X0 Y0 Z0").sentence)
        self.assertIn("M211 R", ex("M211 S").sentence)

    def test_m900_pressure_advance(self):
        self.assertIn("0.02", ex("M900 K0.02").sentence)

    def test_conditional_accepts_s(self):
        self.assertIn("yes", ex("M622 S1").sentence)

    def test_m109_with_h(self):
        self.assertIn("H140", ex("M109 S25 H140").sentence)

    def test_new_flags_and_claims(self):
        self.assertIn("clump", ex("M1002 judge_flag g39_3rd_layer_detect_flag").sentence)
        self.assertIn("calibration succeeded",
                      ex("M1002 judge_last_extrude_cali_success").sentence)
        self.assertIn("“Calibrating extrusion”", ex("M1002 gcode_claim_action : 8").sentence)

    def test_laser_lights(self):
        self.assertIn("laser", ex("M960 S1 P0").sentence)

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
