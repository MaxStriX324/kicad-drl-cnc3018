"""Shared persistent configuration for Windows batch and Tkinter UI."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path

SETTINGS_NAME = "settings.json"
DEFAULTS = {
    "z_safe": 5.0,
    "z_approach": 0.5,
    "z_drill": -2.4,
    "feed": 50.0,
    "spindle": 10000,
    "contour_step": 1.0,
    "column_width": 1.0,
    "slot_mode": "drill",
    "source_path": "",
    "output_dir": "",
}
NUMBER_FIELDS = ("z_safe", "z_approach", "z_drill", "feed",
                 "contour_step", "column_width")


class SettingsError(ValueError):
    """Invalid settings format or unsafe/inconsistent input."""


def validate_settings(data: dict) -> dict:
    """Validate, normalize and return a complete configuration."""
    if not isinstance(data, dict):
        raise SettingsError("Корень settings.json должен быть JSON-объектом")
    unknown = set(data) - set(DEFAULTS)
    if unknown:
        raise SettingsError(f"Неизвестные настройки: {', '.join(sorted(unknown))}")
    result = dict(DEFAULTS)
    result.update(data)
    for key in NUMBER_FIELDS:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettingsError(f"Параметр {key}: требуется число")
        result[key] = float(value)
        if not isfinite(result[key]):
            raise SettingsError(f"Параметр {key}: число должно быть конечным")
    spindle = result["spindle"]
    if isinstance(spindle, bool) or not isinstance(spindle, int) or spindle <= 0:
        raise SettingsError("Параметр spindle: требуется целое положительное число")
    if not (result["z_safe"] > result["z_approach"] > result["z_drill"]
            and result["z_drill"] < 0):
        raise SettingsError("Требуется z_safe > z_approach > z_drill и z_drill < 0")
    for key in ("feed", "contour_step", "column_width"):
        if result[key] <= 0:
            raise SettingsError(f"Параметр {key} должен быть положительным")
    if result["slot_mode"] not in ("drill", "skip", "strict"):
        raise SettingsError("slot_mode: используйте drill, skip или strict")
    for key in ("source_path", "output_dir"):
        if not isinstance(result[key], str):
            raise SettingsError(f"Параметр {key} должен быть строкой")
    return result


def load_settings(path: Path) -> dict:
    """Missing config means defaults; malformed config must not be ignored."""
    if not path.is_file():
        return validate_settings({})
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f, parse_constant=lambda value: (_ for _ in ()).throw(
                SettingsError(f"Недопустимое значение JSON: {value}")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SettingsError(f"Не удалось прочитать {path}: {exc}") from exc
    return validate_settings(data)


def save_settings(path: Path, data: dict) -> None:
    validated = validate_settings(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(validated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def apply_cli(settings: dict, args, root: Path) -> tuple[dict, Path | None]:
    """CLI flags override settings.json; relative configured paths are app-relative."""
    values = dict(settings)
    for key in NUMBER_FIELDS + ("spindle",):
        flag = getattr(args, key, None)
        if flag is not None:
            values[key] = flag
    flag_mode = getattr(args, "slot_mode", None)
    if flag_mode is not None:
        values["slot_mode"] = flag_mode
    output_arg = getattr(args, "output_dir", None)
    if output_arg is not None:
        values["output_dir"] = str(output_arg)
    values = validate_settings(values)
    output = values["output_dir"].strip()
    if not output:
        return values, None
    target = Path(output).expanduser()
    # Config-relative locations are resolved from the app directory;
    # explicit --output-dir is resolved from the current working directory.
    if output_arg is None and not target.is_absolute():
        target = root / target
    return values, target


def converter_kwargs(settings: dict) -> dict:
    """Convert settings to parameters expected by the unchanged CNC core."""
    modes = {"drill": None, "skip": True, "strict": False}
    return {
        "safe_z": settings["z_safe"],
        "approach_z": settings["z_approach"],
        "drill_z": settings["z_drill"],
        "feed": settings["feed"],
        "spindle": settings["spindle"],
        "contour_step": settings["contour_step"],
        "column_width": settings["column_width"],
        "skip_slots": modes[settings["slot_mode"]],
    }
