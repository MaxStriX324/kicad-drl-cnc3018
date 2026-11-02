"""Run: python -m unittest discover -s tests -v"""
import tempfile
import unittest
from pathlib import Path

from drl_to_tap import DrillFileError, convert, read_drills, segment_points

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
    def test_one_tap_all_diameters_without_pauses_or_tool_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "demo.drl"
            source.write_text(DRL)
            stats = {}
            files = convert(source, Path(tmp) / "out", stats=stats)
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, "demo.tap")
            code = files[0].read_text()
            self.assertIn("G0 X5.000 Y-5.000", code)
            self.assertIn("G0 X7.540 Y-5.000", code)
            self.assertIn("G0 X10.000 Y-9.000", code)
            self.assertEqual(code.count("M3 S"), 1)
            self.assertEqual(code.count("\nM5\n"), 1)
            for line in code.splitlines():
                if line.startswith(";"):
                    continue
                self.assertFalse(line.startswith(("G4", "M0", "M1", "M6", "T")))
            self.assertEqual(stats["holes"], 3)
            self.assertEqual(stats["drill_positions"], 3)
            self.assertEqual(stats["diameters"], 2)

    def test_perforates_only_cutting_route_not_g00_reposition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "route.drl"
            path.write_text(DRL.replace(
                "M30", "G00X003000Y-003000\nM15\nG01X003000Y-006000\nM16\nG05\nM30"))
            stats = {}
            files = convert(path, Path(tmp) / "out", contour_step=1, stats=stats)
            code = files[0].read_text()
            for y in (3, 4, 5, 6):
                self.assertIn(f"G0 X3.000 Y-{y:.3f}", code)
            self.assertNotIn("G1 X", code)
            self.assertEqual(stats["slots"], 1)
            self.assertEqual(stats["holes"], 3)
            self.assertEqual(stats["contour_points"], 4)
            self.assertEqual(stats["drill_positions"], 7)

    def test_g00_without_g01_does_not_make_drilling_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "travel.drl"
            path.write_text(DRL.replace("M30", "G00X099000Y-099000\nG05\nM30"))
            code = convert(path, Path(tmp) / "out")[0].read_text()
            self.assertNotIn("X99.000", code)

    def test_g85_contour_generates_start_middle_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g85.drl"
            path.write_text(DRL.replace(
                "M30", "X006000Y-006000G85X008000Y-006000\nM30"))
            stats = {}
            code = convert(path, Path(tmp) / "out", stats=stats)[0].read_text()
            self.assertEqual(stats["slots"], 1)
            for x in (6, 7, 8):
                self.assertIn(f"G0 X{x:.3f} Y-6.000", code)

    def test_only_contour_generates_tap_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contour_only.drl"
            path.write_text(DRL.replace("X005000Y-005000\nX007540Y-005000\n", "")
                               .replace("X010000Y-009000\n", "")
                               .replace("M30", "G00X003000Y-003000\nM15\nG01X003000Y-006000\nM16\nG05\nM30"))
            code = convert(path, Path(tmp) / "out")[0].read_text()
            self.assertIn("G0 X3.000 Y-4.000", code)
            with self.assertRaisesRegex(DrillFileError, "Найдены только"):
                convert(path, Path(tmp) / "skip", skip_slots=True)
            with self.assertRaisesRegex(DrillFileError, "сегментов пазов"):
                convert(path, Path(tmp) / "strict", skip_slots=False)

    def test_invalid_contour_step_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.drl"
            path.write_text(DRL)
            with self.assertRaisesRegex(DrillFileError, "contour-step"):
                convert(path, Path(tmp), contour_step=0)
            with self.assertRaisesRegex(DrillFileError, "Слишком длинный"):
                segment_points((0, 0), (100, 0), 0.0001)

    def test_rejects_ambiguous_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ambiguous.drl"
            path.write_text(DRL.replace("; FORMAT={3:3/ absolute / metric / keep zeros}\n", ""))
            with self.assertRaisesRegex(DrillFileError, "FORMAT"):
                read_drills(path)

    def test_rejects_imperial(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inch.drl"
            path.write_text(DRL.replace("METRIC", "INCH"))
            with self.assertRaisesRegex(DrillFileError, "метрические"):
                read_drills(path)


if __name__ == "__main__":
    unittest.main()
