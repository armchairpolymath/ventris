import unittest
from pathlib import Path

from ventris.bgcode import decode
from ventris.dialects import detect_profile, get_profile, profiles
from ventris.explain import explain
from ventris.parser import parse_line
from ventris.state import MachineState

FIXTURES = Path(__file__).parent / "fixtures"


def ex(text, before=None):
    before = before or MachineState()
    after = MachineState(**vars(before))
    line = parse_line(text)
    after.apply(line)
    return explain(line, before, after, get_profile("prusa"))


class PrusaProfileTest(unittest.TestCase):
    def test_registered(self):
        self.assertIn("prusa", [p.key for p in profiles()])

    def test_detects_prusaslicer_files(self):
        text = decode((FIXTURES / "prusa_mk4s_cube.bgcode").read_bytes()).to_text()
        self.assertEqual(detect_profile(text[:20000]).key, "prusa")
        self.assertEqual(detect_profile("; BambuStudio 02.08\nM1002 x").key, "bambu")

    def test_every_command_in_real_file_is_known(self):
        text = decode((FIXTURES / "prusa_mk4s_cube.bgcode").read_bytes()).gcode
        unknown = {parse_line(l).code for l in text.splitlines()
                   if parse_line(l).code and ex(l).kind == "unknown"}
        self.assertEqual(unknown, set())

    def test_mesh_bed_leveling_variants(self):
        self.assertIn("print area", ex("G29 P1").sentence)
        self.assertIn("interpolat", ex("G29 P3.2").sentence)
        self.assertIn("Turn on", ex("G29 A").sentence)
        self.assertIn("nozzle cleaning", ex("G29 P9 X10 Y-4 W32 H4").sentence)

    def test_printer_checks(self):
        self.assertIn("MK4S", ex('M862.3 P "MK4S"').sentence)
        self.assertIn("0.4", ex("M862.1 P0.4 A0 F0").sentence)

    def test_prusa_specific_is_vendor_documented(self):
        e = ex("M572 S0.04")
        self.assertEqual(e.source, "vendor")
        self.assertIn("0.04", e.sentence)

    def test_standard_command_is_documented(self):
        self.assertEqual(ex("G1 X1 E1").source, "documented")

    def test_wait_with_r(self):
        self.assertIn("cooling", ex("M109 T0 R170").sentence)

    def test_object_labels(self):
        self.assertIn("object 0", ex("M486 S0").sentence)
        self.assertIn("Shape-Box", ex("M486 AShape-Box").sentence)
        self.assertIn("no longer", ex("M486 S-1").sentence)

    def test_mmu_tool(self):
        self.assertIn("slot 2", ex("T1").sentence)

    def test_comment_markers(self):
        self.assertIn("outside", ex(";TYPE:External perimeter").sentence.lower())
        self.assertEqual(ex(";LAYER_CHANGE").title, "Layer change")
        self.assertIn("0.2", ex(";Z:0.2").sentence)
        self.assertIn("0.2", ex(";0.2").sentence)


if __name__ == "__main__":
    unittest.main()
