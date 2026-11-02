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

    def test_real_kicad_sample_generates_one_tap_per_diameter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = (Path(__file__).resolve().parents[1] / "examples" / "sample_board.drl")
            (root / "board.drl").write_bytes(sample.read_bytes())
            code = auto_convert.run([], root)
            self.assertEqual(code, 0)
            first = (root / "board_0p800mm.tap").read_text()
            second = (root / "board_1p000mm.tap").read_text()
            self.assertIn("G0 X5.000 Y-5.000", first)
            self.assertIn("G0 X7.540 Y-5.000", first)
            self.assertIn("G0 X10.000 Y-9.000", second)
            self.assertIn("M5", second)

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
