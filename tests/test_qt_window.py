"""Qt window tests. Run without a display (offscreen); skipped if PySide6 is missing."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = """; BambuStudio 02.08.02.61
G90
M83
M104 S220
G1 Z.6 F30000
; FEATURE: Outer wall
G1 X10 Y10 E.5 F3000
G1 X20 Y10 E.5
"""


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class QtWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from gcode_analyzer.qt.window import MainWindow
        cls.app = QApplication.instance() or QApplication([])
        cls.MainWindow = MainWindow

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.dir.name)
        self.window = self.MainWindow()
        self.window.show()

    def tearDown(self):
        self.window.editor.document().setModified(False)
        self.window.close()
        self.dir.cleanup()

    def settle(self, ms=400):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def write_sample(self) -> Path:
        path = self.tmp / "part.gcode"
        path.write_text(SAMPLE)
        return path

    def sentence(self) -> str:
        return self.window.explain_view.sentence.text()

    def state_value(self, field: str) -> str:
        for _row, value, fields, _fmt in self.window.explain_view._state_widgets:
            if field in fields:
                return value.text()
        raise KeyError(field)

    def test_open_explains_current_line(self):
        self.window.open_path(self.write_sample())
        self.assertEqual(self.window.profile.key, "bambu")
        self.window.editor.go_to_line(6)
        self.settle(100)
        self.assertIn("X 10 mm", self.sentence())
        self.assertEqual(self.state_value("feature"), "Outer wall")
        self.assertEqual(self.state_value("hotend_target"), "220 °C")

    def test_edit_updates_explanation_and_save_writes_it(self):
        path = self.write_sample()
        self.window.open_path(path)
        editor = self.window.editor
        editor.go_to_line(4)
        cursor = editor.textCursor()
        cursor.select(cursor.SelectionType.LineUnderCursor)
        cursor.insertText("G1 Z7 F600")
        self.assertTrue(self.window.isWindowModified())
        self.settle()
        self.assertIn("Z 7 mm", self.sentence())
        self.assertEqual(self.state_value("z"), "7 mm")
        self.assertTrue(self.window._save_to(path))
        self.assertFalse(self.window.isWindowModified())
        self.assertIn("G1 Z7 F600", path.read_text())

    def test_bgcode_opens_as_prusa_and_saves_as_gcode(self):
        src = self.tmp / "cube.bgcode"
        shutil.copy(FIXTURES / "prusa_mk4s_cube.bgcode", src)
        original = src.read_bytes()
        self.window.open_path(self.write_sample())  # start on a Bambu file
        self.window.open_path(src)  # switching profile while opening must not crash
        self.assertEqual(self.window.profile.key, "prusa")
        self.assertEqual(self.window.profile_combo.currentText(), "Prusa")
        self.window.editor.go_to_line(57)
        self.settle(100)
        self.assertIn("nozzle cleaning", self.sentence())

        with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as warning:
            self.assertFalse(self.window._save_to(src))
        warning.assert_called_once()
        self.assertEqual(src.read_bytes(), original)
        out = self.tmp / "cube.gcode"
        self.assertTrue(self.window._save_to(out))
        self.assertFalse(self.window.document.is_bgcode)
        self.assertIn("M862.3", out.read_text())

    def test_lazy_highlighter_colors_visible_lines(self):
        self.window.open_path(self.write_sample())
        self.settle(100)
        block = self.window.editor.document().findBlockByNumber(6)  # G1 X10 Y10 E.5 F3000
        self.assertGreaterEqual(len(block.layout().formats()), 9)  # G1 + 4 letter/number pairs

    def test_highlighter_ranges(self):
        ranges = self.window.editor.highlighter.ranges_for("M104 S220 ; heat")
        spans = [(r.start, r.length) for r in ranges]
        self.assertIn((10, 6), spans)  # comment
        self.assertIn((0, 4), spans)  # M104
        self.assertIn((5, 1), spans)  # S
        self.assertIn((6, 3), spans)  # 220


if __name__ == "__main__":
    unittest.main()
