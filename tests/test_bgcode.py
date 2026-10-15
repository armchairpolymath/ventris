import struct
import unittest
import zlib
from pathlib import Path

from gcode_analyzer.bgcode import BgcodeError, decode, heatshrink_decode, meatpack_decode

FIXTURES = Path(__file__).parent / "fixtures"


class BgcodeTest(unittest.TestCase):
    def test_real_file_gcode_matches_reference(self):
        doc = decode((FIXTURES / "prusa_mk4s_cube.bgcode").read_bytes())
        reference = (FIXTURES / "prusa_mk4s_cube_ref.gcode").read_text()
        self.assertTrue(doc.gcode.startswith("M73 P0 R3\nM73 Q0 S3\n"))
        self.assertGreater(len(doc.gcode), 30000)
        self.assertIn(doc.gcode, reference)

    def test_metadata_and_full_text(self):
        doc = decode((FIXTURES / "prusa_mk4s_cube.bgcode").read_bytes())
        self.assertEqual(doc.printer_metadata.get("printer_model"), "MK4S")
        self.assertIn("PrusaSlicer", doc.file_metadata.get("Producer", ""))
        text = doc.to_text()
        self.assertIn("; printer_model = MK4S", text)
        self.assertIn("; prusaslicer_config = begin", text)
        self.assertIn("thumbnail", text)

    def test_rejects_non_bgcode(self):
        with self.assertRaises(BgcodeError):
            decode(b"G1 X1\n")

    def test_detects_corruption(self):
        data = bytearray((FIXTURES / "prusa_mk4s_cube.bgcode").read_bytes())
        data[200] ^= 0xFF
        with self.assertRaises(BgcodeError):
            decode(bytes(data))

    def test_uncompressed_plain_block(self):
        payload = b"G1 X1\n"
        header = struct.pack("<HHI", 1, 0, len(payload))
        params = struct.pack("<H", 0)
        crc = struct.pack("<I", zlib.crc32(header + params + payload))
        data = b"GCDE" + struct.pack("<IH", 1, 1) + header + params + payload + crc
        self.assertEqual(decode(data).gcode, "G1 X1\n")

    def test_heatshrink_literals_and_backref(self):
        # tag 1 + 'A' (0x41), tag 1 + 'B', then backref: tag 0, index 1 (offset 2), count 3 (4 bytes)
        bits = "1" + "01000001" + "1" + "01000010" + "0" + format(1, "012b") + format(3, "04b")
        bits += "0" * (-len(bits) % 8)
        data = int(bits, 2).to_bytes(len(bits) // 8, "big")
        self.assertEqual(heatshrink_decode(data, 12, 4), b"ABABAB")

    def test_meatpack_packed_pair_and_full_char(self):
        # enable packing; "G1" packed as one byte (G=0xD low, 1=0x1 high);
        # then " " (0xB) + full-width 'Y' (low nibble packed, high nibble 0xF)
        data = bytes([0xFF, 0xFF, 251, 0x1D, 0xFB, ord("Y"), 0xC1])  # '1','\n'
        self.assertEqual(meatpack_decode(data), "G1 Y1\n")


if __name__ == "__main__":
    unittest.main()
