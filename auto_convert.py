#!/usr/bin/env python3
"""One-click batch entry point for the KiCad DRL -> GRBL TAP converter."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
import traceback

from drl_to_tap import DrillFileError, convert

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
        description="Автоматическая конвертация всех .drl в .tap (отдельно на каждый диаметр)"
    )
    parser.add_argument("paths", nargs="*", type=Path,
                        help="Необязательно: файлы DRL или папки. Без аргументов: папка программы и input/")
    parser.add_argument("--output-dir", type=Path,
                        help="Папка результата (по умолчанию TAP рядом с каждым DRL)")
    parser.add_argument("--z-safe", type=float, default=5.0)
    parser.add_argument("--z-approach", type=float, default=0.5)
    parser.add_argument("--z-drill", type=float, default=-2.4)
    parser.add_argument("--feed", type=float, default=50)
    parser.add_argument("--spindle", type=int, default=10000)
    parser.add_argument("--dwell", type=float, default=2)
    slot_options = parser.add_mutually_exclusive_group()
    slot_options.add_argument("--skip-slots", dest="skip_slots", action="store_true",
                              help="Пропускать фрезеруемые пазы (по умолчанию)")
    slot_options.add_argument("--strict-slots", dest="skip_slots", action="store_false",
                              help="Останавливать конвертацию при наличии фрезеруемых пазов")
    parser.set_defaults(skip_slots=True)
    args = parser.parse_args(argv)

    report = [f"DRL -> TAP, {datetime.now().isoformat(timespec='seconds')}",
              f"Python: {sys.version.split()[0]}", f"Каталог программы: {root}"]
    success = failed = generated = 0
    try:
        files = find_inputs(args.paths, root)
    except (DrillFileError, OSError) as exc:
        files = []
        failed += 1
        report.append(f"ОШИБКА: {exc}")
    else:
        if not files:
            report.append("DRL-файлы не найдены. Положите их рядом с start.bat "
                          "или в папку input, затем повторно запустите start.bat.")
        else:
            report.append(f"Найдено DRL-файлов: {len(files)}")
            if args.output_dir and len({p.stem.casefold() for p in files}) != len(files):
                failed += 1
                report.append("ОШИБКА: одинаковые имена DRL из разных папок при --output-dir "
                              "могут перезаписать TAP. Уберите --output-dir либо переименуйте файлы.")
            else:
                for source in files:
                    try:
                        stats: dict[str, int] = {}
                        outputs = convert(
                            source, args.output_dir or source.parent,
                            safe_z=args.z_safe, approach_z=args.z_approach,
                            drill_z=args.z_drill, feed=args.feed,
                            spindle=args.spindle, dwell=args.dwell,
                            skip_slots=args.skip_slots,
                            stats=stats,
                        )
                        success += 1
                        generated += len(outputs)
                        detail = (f"; круглых отверстий: {stats['holes']}; "
                                  f"пропущено сегментов пазов: {stats['slots']}") if "holes" in stats else ""
                        report.append(f"OK: {source} -> {len(outputs)} TAP{detail}")
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
