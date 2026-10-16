import unittest

from ventris.parser import parse_line


class ParseLineTest(unittest.TestCase):
    def test_simple_move(self):
        p = parse_line("G1 X10.5 Y-2 E0.03 F1200")
        self.assertEqual(p.code, "G1")
        self.assertEqual(p.params, {"X": "10.5", "Y": "-2", "E": "0.03", "F": "1200"})
        self.assertIsNone(p.comment)

    def test_normalises_case_and_leading_zeros(self):
        self.assertEqual(parse_line("g01 x5").code, "G1")
        self.assertEqual(parse_line("m0104 s200").code, "M104")
        self.assertEqual(parse_line("g01 x5").params, {"X": "5"})

    def test_decimal_subcode(self):
        p = parse_line("G29.1 Z-0.02")
        self.assertEqual(p.code, "G29.1")
        self.assertEqual(p.params, {"Z": "-0.02"})

    def test_trailing_comment(self):
        p = parse_line("M104 S220 ; set nozzle")
        self.assertEqual(p.code, "M104")
        self.assertEqual(p.comment, "set nozzle")

    def test_comment_only_line(self):
        p = parse_line("; FEATURE: Outer wall")
        self.assertIsNone(p.code)
        self.assertEqual(p.comment, "FEATURE: Outer wall")

    def test_blank_line(self):
        p = parse_line("   ")
        self.assertIsNone(p.code)
        self.assertIsNone(p.comment)
        self.assertTrue(p.is_blank)

    def test_flag_without_value(self):
        p = parse_line("G28 X Y")
        self.assertEqual(p.params, {"X": "", "Y": ""})

    def test_compact_params(self):
        p = parse_line("G1X1Y2")
        self.assertEqual(p.code, "G1")
        self.assertEqual(p.params, {"X": "1", "Y": "2"})

    def test_word_arguments_kept_raw(self):
        p = parse_line("M1002 gcode_claim_action : 2")
        self.assertEqual(p.code, "M1002")
        self.assertEqual(p.params, {"_args": "gcode_claim_action : 2"})

    def test_tool_change(self):
        p = parse_line("T1000")
        self.assertEqual(p.code, "T1000")

    def test_klipper_style_macro(self):
        p = parse_line("EXCLUDE_OBJECT_START NAME=part_1")
        self.assertEqual(p.code, "EXCLUDE_OBJECT_START")
        self.assertEqual(p.params, {"_args": "NAME=part_1"})

    def test_hex_value(self):
        self.assertEqual(parse_line("M708 A0x1e X12").params, {"A": "0x1e", "X": "12"})

    def test_number_value(self):
        p = parse_line("G1 X10.5 F")
        self.assertEqual(p.number("X"), 10.5)
        self.assertIsNone(p.number("F"))
        self.assertIsNone(p.number("Z"))
        self.assertTrue(p.has("F"))


if __name__ == "__main__":
    unittest.main()
