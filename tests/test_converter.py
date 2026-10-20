"""Run: python -m unittest discover -s tests -v"""
import tempfile
import unittest
from pathlib import Path

from drl_to_tap import DrillFileError, convert, read_drills


DRL = """M48
; FORMAT={3:3/ absolute / metric / keep zeros}
METRIC
T1C0.800
T2C1.000
%
G90
G05
T1
X005000Y-005000
X007540Y-005000
T2
X010000Y-009000
M30
"""


class ConverterTests(unittest.TestCase):
    def test_separates_drill_diameters_and_preserves_signs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "demo.drl"
            p.write_text(DRL)
            files = convert(p, Path(tmp) / "out")
            self.assertEqual(len(files), 2)
            self.assertIn("G0 X5.000 Y-5.000", files[0].read_text())
            self.assertIn("G0 X7.540 Y-5.000", files[0].read_text())
            self.assertIn("G0 X10.000 Y-9.000", files[1].read_text())
            self.assertIn("M5", files[0].read_text())

    def test_slots_are_blocked_unless_explicitly_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "slots.drl"
            p.write_text(DRL.replace("M30", "G00X003000Y-003000\nM15\nG01X003000Y-006000\nM16\nG05\nM30"))
            self.assertEqual(read_drills(p)[1], 1)
            with self.assertRaisesRegex(DrillFileError, "пазы"):
                convert(p, Path(tmp) / "out")
            self.assertEqual(len(convert(p, Path(tmp) / "out", skip_slots=True)), 2)

    def test_rejects_ambiguous_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ambiguous.drl"
            p.write_text(DRL.replace("; FORMAT={3:3/ absolute / metric / keep zeros}\n", ""))
            with self.assertRaisesRegex(DrillFileError, "FORMAT"):
                read_drills(p)

    def test_rejects_imperial(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "inch.drl"
            p.write_text(DRL.replace("METRIC", "INCH"))
            with self.assertRaisesRegex(DrillFileError, "метрические"):
                read_drills(p)


if __name__ == "__main__":
    unittest.main()
