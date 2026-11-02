"""Tests for the automatic one-click Windows launcher backend."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auto_convert
from drl_to_tap import DrillFileError


class AutoConvertTests(unittest.TestCase):
    def test_autodetect_root_and_input_but_not_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.DRL").write_text("drill")
            (root / "input" / "nested").mkdir(parents=True)
            (root / "input" / "nested" / "b.drl").write_text("drill")
            (root / "examples").mkdir()
            (root / "examples" / "sample.drl").write_text("example")
            files = auto_convert.find_inputs([], root)
            self.assertEqual({p.name for p in files}, {"a.DRL", "b.drl"})

    def test_explicit_directory_recursively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nested").mkdir()
            (root / "nested" / "board.drl").write_text("drill")
            self.assertEqual([p.name for p in auto_convert.find_inputs([root])], ["board.drl"])

    def test_auto_converts_all_and_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.drl").write_text("x")
            (root / "b.drl").write_text("x")
            with patch.object(auto_convert, "convert", side_effect=lambda src, out, **kwargs: [out / (src.stem + ".tap")]) as fn:
                code = auto_convert.run([], root)
            self.assertEqual(code, 0)
            self.assertEqual(fn.call_count, 2)
            self.assertIn("обработано 2, ошибок 0, создано TAP 2", (root / "conversion_report.txt").read_text(encoding="utf-8-sig"))

    def test_real_kicad_sample_generates_one_tap_without_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = (Path(__file__).resolve().parents[1] / "examples" / "sample_board.drl")
            (root / "board.drl").write_bytes(sample.read_bytes())
            code = auto_convert.run([], root)
            self.assertEqual(code, 0)
            self.assertEqual([p.name for p in root.glob("*.tap")], ["board.tap"])
            code = (root / "board.tap").read_text()
            self.assertIn("G0 X5.000 Y-5.000", code)
            self.assertIn("G0 X7.540 Y-5.000", code)
            self.assertIn("G0 X10.000 Y-9.000", code)
            self.assertIn("M5", code)
            self.assertNotIn("G4 P", code)

    def test_real_drill_file_with_routed_slot_generates_taps_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = (Path(__file__).resolve().parents[1] / "examples" / "sample_board.drl")
            content = sample.read_text()
            content = content.replace("M30", "G00X003000Y-003000\nM15\nG01X003000Y-006000\nM16\nG05\nM30")
            (root / "routed.drl").write_text(content)
            code = auto_convert.run([], root)
            self.assertEqual(code, 0)
            taps = sorted(root.glob("routed_*.tap"))
            self.assertEqual([p.name for p in taps], ["routed.tap"])
            gcode = taps[0].read_text()
            self.assertIn("X3.000 Y-3.000", gcode)
            self.assertIn("X3.000 Y-4.000", gcode)
            self.assertIn("X3.000 Y-6.000", gcode)
            report = (root / "conversion_report.txt").read_text(encoding="utf-8-sig")
            self.assertIn("обычных отверстий: 3", report)
            self.assertIn("режущих сегментов: 1", report)
            self.assertIn("точек контура: 4", report)
            self.assertIn("всего уникальных позиций: 7", report)

    def test_strict_slots_opt_in_rejects_routed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = (Path(__file__).resolve().parents[1] / "examples" / "sample_board.drl")
            (root / "strict.drl").write_text(
                sample.read_text().replace("M30", "G00X003000Y-003000\nM15\nG01X003000Y-006000\nM16\nG05\nM30")
            )
            self.assertEqual(auto_convert.run(["--strict-slots"], root), 1)
            self.assertEqual(list(root.glob("*.tap")), [])

    def test_bad_file_does_not_abort_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("bad.drl", "good.drl"):
                (root / name).write_text("x")
            def converter(src, out, **kwargs):
                if src.name == "bad.drl":
                    raise DrillFileError("Пазы запрещены")
                return [out / "good.tap"]
            with patch.object(auto_convert, "convert", side_effect=converter):
                code = auto_convert.run([], root)
            self.assertEqual(code, 1)
            report = (root / "conversion_report.txt").read_text(encoding="utf-8-sig")
            self.assertIn("Пазы запрещены", report)
            self.assertIn("обработано 1, ошибок 1", report)

    def test_no_files_gives_instructions_not_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(auto_convert.run([], root), 2)
            self.assertIn("Положите их рядом", (root / "conversion_report.txt").read_text(encoding="utf-8-sig"))

    def test_two_same_stems_cannot_overwrite_shared_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dirname in ("a", "b"):
                directory = root / dirname
                directory.mkdir()
                (directory / "board.drl").write_text("x")
            with patch.object(auto_convert, "convert") as fn:
                code = auto_convert.run([str(root), "--output-dir", str(root / "out")], root)
            self.assertEqual(code, 1)
            fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
