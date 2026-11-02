#!/usr/bin/env python3
"""One-click batch entry point for the KiCad DRL -> GRBL TAP converter."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import traceback

from drl_to_tap import DrillFileError, add_arguments, convert
from settings import (SETTINGS_NAME, SettingsError, apply_cli, converter_kwargs,
                      load_settings)

ROOT = Path(__file__).resolve().parent
REPORT_NAME = "conversion_report.txt"


def find_inputs(paths: list[Path], root: Path = ROOT) -> list[Path]:
    """Find DRLs without accidentally processing the bundled example files."""
    found: dict[str, Path] = {}

    def add_file(path: Path) -> None:
        if path.is_file() and path.suffix.lower() == ".drl":
            path = path.resolve()
            found[str(path).casefold()] = path

    if paths:
        for source in paths:
            source = source.expanduser()
            if source.is_file():
                if source.suffix.lower() != ".drl":
                    raise DrillFileError(f"Ожидается файл .drl: {source}")
                add_file(source)
            elif source.is_dir():
                for candidate in source.rglob("*"):
                    add_file(candidate)
            else:
                raise DrillFileError(f"Файл или папка не найдены: {source}")
    else:
        # Quick use: drop .drl files beside start.bat, or into its input folder.
        for candidate in root.iterdir():
            add_file(candidate)
        inbox = root / "input"
        if inbox.is_dir():
            for candidate in inbox.rglob("*"):
                add_file(candidate)

    return sorted(found.values(), key=lambda p: str(p).casefold())


def run(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(
        description="Автоматическая конвертация DRL в один непрерывный TAP на файл с высверливанием контура"
    )
    parser.add_argument("paths", nargs="*", type=Path,
                        help="Необязательно: файлы DRL или папки. Без аргументов: папка программы и input/")
    add_arguments(parser)
    args = parser.parse_args(argv)

    report = [f"DRL -> TAP, {datetime.now().isoformat(timespec='seconds')}",
              f"Python: {sys.version.split()[0]}", f"Каталог программы: {root}"]
    success = failed = generated = 0
    try:
        config_path = args.config if args.config is not None else root / SETTINGS_NAME
        settings, output_dir = apply_cli(load_settings(config_path), args, root)
        search_paths = list(args.paths)
        if not search_paths and settings["source_path"].strip():
            selected = Path(settings["source_path"]).expanduser()
            if not selected.is_absolute():
                selected = root / selected
            search_paths = [selected]
        files = find_inputs(search_paths, root)
        report.append(f"Настройки: {config_path}")
    except (DrillFileError, OSError, SettingsError) as exc:
        files = []
        failed += 1
        report.append(f"ОШИБКА: {exc}")
    else:
        if not files:
            report.append("DRL-файлы не найдены. Положите их рядом с start.bat "
                          "или в папку input, затем повторно запустите start.bat.")
        else:
            report.append(f"Найдено DRL-файлов: {len(files)}")
            if output_dir and len({p.stem.casefold() for p in files}) != len(files):
                failed += 1
                report.append("ОШИБКА: одинаковые имена DRL из разных папок при --output-dir "
                              "могут перезаписать TAP. Уберите --output-dir либо переименуйте файлы.")
            else:
                for source in files:
                    try:
                        stats: dict[str, int | float] = {}
                        outputs = convert(
                            source, output_dir or source.parent,
                            **converter_kwargs(settings),
                            dwell=args.dwell or 0,
                            stats=stats,
                        )
                        success += 1
                        generated += len(outputs)
                        detail = (f"; обычных отверстий: {stats['holes']}; "
                                  f"режущих сегментов: {stats['slots']}; "
                                  f"точек контура: {stats['contour_points']}; "
                                  f"всего уникальных позиций: {stats['drill_positions']}; "
                                  f"холостые XY: {stats['xy_before_mm']:.1f} -> "
                                  f"{stats['xy_after_mm']:.1f} мм") if "holes" in stats else ""
                        report.append(f"OK: {source} -> {len(outputs)} TAP{detail}")
                        if stats.get("diameters", 0) > 1:
                            report.append(
                                "ВНИМАНИЕ: в DRL несколько номинальных диаметров. "
                                "В одном TAP физически одно сверло: все отверстия "
                                "получатся по диаметру установленного инструмента."
                            )
                    except (DrillFileError, OSError, UnicodeError, ValueError) as exc:
                        failed += 1
                        report.append(f"ОШИБКА: {source}\n    {exc}")
                    except Exception as exc:
                        failed += 1
                        report.append(f"НЕОЖИДАННАЯ ОШИБКА: {source}\n    {exc}\n"
                                      + traceback.format_exc())

    report.append(f"ИТОГО: обработано {success}, ошибок {failed}, создано TAP {generated}")
    result_text = "\n".join(report) + "\n"
    print(result_text)
    report_path = root / REPORT_NAME
    try:
        report_path.write_text(result_text, encoding="utf-8-sig")
        print(f"Отчёт: {report_path}")
    except OSError as exc:
        print(f"Не удалось сохранить отчёт: {exc}", file=sys.stderr)
    if failed:
        return 1
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(run())
