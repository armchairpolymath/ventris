import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from gcode_analyzer.fileio import FileFormatError, load, save


class FileIOTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def make_3mf(self, gcode="G1 X1\n"):
        path = self.tmp / "part.gcode.3mf"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", "<types/>")
            z.writestr("Metadata/plate_1.png", b"\x89PNG")
            z.writestr("Metadata/plate_1.gcode", gcode)
            z.writestr("Metadata/plate_1.gcode.md5", hashlib.md5(gcode.encode()).hexdigest())
        return path

    def test_plain_round_trip(self):
        path = self.tmp / "a.gcode"
        path.write_text("G28\nG1 X5\n")
        doc = load(path)
        self.assertEqual(doc.text, "G28\nG1 X5\n")
        save(doc, "G28\nG1 X6\n", path)
        self.assertEqual(path.read_text(), "G28\nG1 X6\n")

    def test_3mf_load(self):
        doc = load(self.make_3mf("G1 X1\n"))
        self.assertEqual(doc.text, "G1 X1\n")
        self.assertEqual(doc.inner_name, "Metadata/plate_1.gcode")

    def test_3mf_save_updates_md5_and_keeps_other_entries(self):
        path = self.make_3mf()
        doc = load(path)
        save(doc, "G1 X2\n", path)
        with zipfile.ZipFile(path) as z:
            self.assertEqual(z.read("Metadata/plate_1.gcode").decode(), "G1 X2\n")
            self.assertEqual(z.read("Metadata/plate_1.gcode.md5").decode(),
                             hashlib.md5(b"G1 X2\n").hexdigest())
            self.assertEqual(z.read("Metadata/plate_1.png"), b"\x89PNG")
            self.assertEqual(z.namelist().count("Metadata/plate_1.gcode"), 1)

    def test_3mf_save_as_plain_gcode(self):
        doc = load(self.make_3mf())
        out = self.tmp / "out.gcode"
        save(doc, "G1 X3\n", out)
        self.assertEqual(out.read_text(), "G1 X3\n")

    def test_3mf_without_gcode(self):
        path = self.tmp / "model.3mf"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("3D/3dmodel.model", "<model/>")
        with self.assertRaises(FileFormatError):
            load(path)

    def test_non_utf8_is_tolerated(self):
        path = self.tmp / "b.gcode"
        path.write_bytes(b"; caf\xe9\nG1 X1\n")
        self.assertIn("G1 X1", load(path).text)


if __name__ == "__main__":
    unittest.main()
