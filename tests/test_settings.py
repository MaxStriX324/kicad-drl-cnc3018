"""Regression tests for shared settings and the Tkinter GUI form/backend."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest

import auto_convert
from drl_to_tap import add_arguments, main as converter_main
from gui import parse_fields, read_positions
from settings import (DEFAULTS, SettingsError, apply_cli, converter_kwargs,
                      load_settings, save_settings, validate_settings)


SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_board.drl"


class SettingsTests(unittest.TestCase):
    def test_repository_defaults_match_config(self):
        path = Path(__file__).resolve().parents[1] / "settings.json"
        self.assertEqual(load_settings(path), validate_settings(DEFAULTS))

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            values = dict(DEFAULTS, feed=37.5, spindle=1000,
                          contour_step=0.75, slot_mode="skip",
                          source_path="input", output_dir="results")
            save_settings(path, values)
            self.assertEqual(load_settings(path), values)
            self.assertFalse(path.with_suffix(".json.tmp").exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["feed"], 37.5)

    def test_missing_config_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_settings(Path(tmp) / "missing.json"),
                             validate_settings(DEFAULTS))

    def test_invalid_config_does_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(SettingsError):
                load_settings(path)
            path.write_text('{"feed": -3}', encoding="utf-8")
            with self.assertRaisesRegex(SettingsError, "feed"):
                load_settings(path)
            path.write_text('{"spindle": "wrong"}', encoding="utf-8")
            with self.assertRaisesRegex(SettingsError, "spindle"):
                load_settings(path)

    def test_safety_checks(self):
        for change in ({"z_approach": 8}, {"z_drill": 0},
                       {"column_width": 0}, {"contour_step": -1},
                       {"spindle": True}, {"slot_mode": "bogus"},
                       {"feed": float("nan")}, {"spindle": 10000.5},
                       {"typo": 1}):
            with self.subTest(change=change):
                with self.assertRaises(SettingsError):
                    validate_settings(change)

    def test_cli_overrides_json_without_modifying_it(self):
        parser = argparse.ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args(["--feed", "42", "--column-width", "2",
                                  "--drill-slots", "--output-dir", "tempdir"])
        data = dict(DEFAULTS, feed=23.0, slot_mode="strict")
        resolved, output = apply_cli(data, args, Path("/test_root"))
        self.assertEqual(resolved["feed"], 42)
        self.assertEqual(resolved["column_width"], 2)
        self.assertEqual(resolved["slot_mode"], "drill")
        self.assertEqual(converter_kwargs(resolved)["skip_slots"], None)
        self.assertEqual(str(output), "tempdir")
        self.assertEqual(data["feed"], 23.0)

    def test_batch_uses_saved_source_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "input").mkdir()
            (root / "input" / "sample.drl").write_bytes(SAMPLE.read_bytes())
            save_settings(root / "settings.json",
                          dict(DEFAULTS, source_path="input",
                               output_dir="tap_output", feed=31.0, spindle=1200))
            self.assertEqual(auto_convert.run([], root), 0)
            tap = root / "tap_output" / "sample.tap"
            self.assertTrue(tap.exists())
            contents = tap.read_text()
            self.assertIn("M3 S1200", contents)
            self.assertIn("F31", contents)
            self.assertNotIn("G4 P", contents)
            report = (root / "conversion_report.txt").read_text(encoding="utf-8-sig")
            self.assertIn("одно сверло", report)

    def test_explicit_cli_override_takes_priority_over_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "board.drl").write_bytes(SAMPLE.read_bytes())
            save_settings(root / "settings.json",
                          dict(DEFAULTS, spindle=1200, feed=22, output_dir="saved"))
            self.assertEqual(auto_convert.run(["--spindle", "1600", "--feed", "49",
                                               "--output-dir", str(root / "override")], root), 0)
            text = (root / "override" / "board.tap").read_text()
            self.assertIn("M3 S1600", text)
            self.assertIn("F49", text)
            self.assertFalse((root / "saved").exists())
            self.assertEqual(load_settings(root / "settings.json")["spindle"], 1200)

    def test_invalid_batch_config_fails_with_report_not_unsafe_gcode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "board.drl").write_bytes(SAMPLE.read_bytes())
            (root / "settings.json").write_text('{"z_drill": 5}', encoding="utf-8")
            self.assertEqual(auto_convert.run([], root), 1)
            self.assertFalse((root / "board.tap").exists())
            self.assertIn("ОШИБКА:", (root / "conversion_report.txt").read_text(encoding="utf-8-sig"))

    def test_single_file_cli_reads_custom_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "board.drl"
            source.write_bytes(SAMPLE.read_bytes())
            config = root / "my_settings.json"
            save_settings(config, dict(DEFAULTS, spindle=1200, column_width=2))
            self.assertEqual(converter_main([str(source), "--config", str(config)]), 0)
            self.assertIn("M3 S1200", (root / "board.tap").read_text())

    def test_gui_form_parser_uses_comma_and_validates(self):
        fields = {key: str(value) for key, value in DEFAULTS.items()}
        fields["feed"] = "42,5"
        parsed = parse_fields(fields)
        self.assertEqual(parsed["feed"], 42.5)
        fields["z_drill"] = "NaN"
        with self.assertRaises(SettingsError):
            parse_fields(fields)

    def test_preview_reads_drill_positions_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tap = Path(tmp) / "board.tap"
            tap.write_text("G21\nM3 S1000\nG0 X1.000 Y-2.000\n"
                           "G0 Z0.5\nG1 Z-2 F50\nG0 X3.000 Y4.000\nM5\n")
            self.assertEqual(read_positions(tap), [(1.0, -2.0), (3.0, 4.0)])


if __name__ == "__main__":
    unittest.main()
