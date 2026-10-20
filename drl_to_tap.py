#!/usr/bin/env python3
"""Convert KiCad decimal-format Excellon drill files into GRBL drill programs.

No third-party dependencies. Intended for CNC 3018-class GRBL controllers.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import re
import sys

TOOL_DEF = re.compile(r"^T(\d+)C(\d+(?:\.\d+)?)$", re.I)
TOOL_CHANGE = re.compile(r"^T(\d+)$", re.I)
XY_MOVE = re.compile(r"^X([+-]?\d+(?:\.\d+)?)Y([+-]?\d+(?:\.\d+)?)$", re.I)
FORMAT = re.compile(r"FORMAT=\{\s*\d+\s*:\s*(\d+)", re.I)


class DrillFileError(ValueError):
    """Unsupported or invalid Excellon drill file."""


def decode_coordinate(raw: str, digits_after_decimal: int) -> float:
    if "." in raw:
        return float(raw)
    return int(raw) / (10 ** digits_after_decimal)


def read_drills(path: Path) -> tuple[dict[float, list[tuple[float, float]]], int]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    tools: dict[int, float] = {}
    holes: dict[float, list[tuple[float, float]]] = defaultdict(list)
    decimals: int | None = None
    current_tool: int | None = None
    in_body = False
    routing = False
    slots = 0
    units = None
    zero_suppression = False

    for number, original in enumerate(lines, start=1):
        line = original.strip()
        if not line:
            continue
        fmt = FORMAT.search(line)
        if fmt:
            decimals = int(fmt.group(1))
        if line.startswith(";"):
            continue
        uline = line.upper()
        if uline.startswith("METRIC") or uline == "M71":
            units = "mm"
            if ",TZ" in uline or ",LZ" in uline:
                zero_suppression = True
            continue
        if uline.startswith("INCH") or uline == "M72":
            units = "inch"
            continue
        if uline == "%":
            in_body = True
            continue
        tool_definition = TOOL_DEF.fullmatch(line)
        if tool_definition:
            tools[int(tool_definition.group(1))] = float(tool_definition.group(2))
            continue
        if not in_body:
            continue
        if uline == "M30":
            break
        if uline == "G91":
            raise DrillFileError(f"Строка {number}: относительные координаты G91 не поддерживаются")
        if uline == "G90":
            continue
        if uline == "G05":
            routing = False
            continue
        tool_change = TOOL_CHANGE.fullmatch(line)
        if tool_change:
            current_tool = int(tool_change.group(1))
            if current_tool not in tools:
                raise DrillFileError(f"Строка {number}: неизвестный инструмент T{current_tool}")
            continue
        if uline.startswith("G00") or uline.startswith("G0X"):
            routing = True
            continue
        if uline.startswith("G01") or uline.startswith("G1X"):
            if not routing:
                raise DrillFileError(f"Строка {number}: непредвиденная команда фрезерования {line}")
            slots += 1
            continue
        if uline in ("M15", "M16", "M48", "G04"):
            continue
        xy = XY_MOVE.fullmatch(line)
        if xy:
            if routing:
                raise DrillFileError(f"Строка {number}: координаты маршрута без G05")
            if current_tool is None:
                raise DrillFileError(f"Строка {number}: координата без выбранного инструмента")
            if decimals is None and ("." not in xy.group(1) or "." not in xy.group(2)):
                raise DrillFileError("В DRL отсутствует FORMAT={3:3/...}; масштаб координат неизвестен")
            d = decimals if decimals is not None else 0
            holes[tools[current_tool]].append((decode_coordinate(xy.group(1), d), decode_coordinate(xy.group(2), d)))
            continue
        # Reject unimplemented drilling commands, rather than silently drop coordinates.
        if any(uline.startswith(x) for x in ("X", "Y", "G", "T")):
            raise DrillFileError(f"Строка {number}: неподдерживаемая команда {line}")

    if units != "mm":
        raise DrillFileError("Поддерживаются только метрические DRL (METRIC / M71)")
    if zero_suppression:
        raise DrillFileError("LZ/TZ с подавлением нулей пока не поддерживается; в KiCad включите keep zeros")
    if not tools or not holes:
        raise DrillFileError("Не найдены определения инструментов или сверления")
    return dict(holes), slots


def make_gcode(points: list[tuple[float, float]], safe_z: float, approach_z: float,
               drill_z: float, feed: float, spindle: int, dwell: float) -> str:
    lines = [
        "; KiCad Excellon -> GRBL | units: mm | origin: KiCad coordinates, unchanged",
        "G21", "G90", "G94", f"G0 Z{safe_z:.3f}",
        f"M3 S{spindle}", f"G4 P{dwell:.2f}",
    ]
    for x, y in sorted(points, key=lambda p: (p[0], p[1])):
        lines.extend((
            f"G0 X{x:.3f} Y{y:.3f}",
            f"G0 Z{approach_z:.3f}",
            f"G1 Z{drill_z:.3f} F{feed:g}",
            f"G0 Z{safe_z:.3f}",
        ))
    lines.extend(("M5", "M2", ""))
    return "\n".join(lines)


def convert(source: Path, output_dir: Path, *, safe_z: float = 5.0,
            approach_z: float = 0.5, drill_z: float = -2.4,
            feed: float = 50.0, spindle: int = 10000, dwell: float = 2.0,
            skip_slots: bool = False) -> list[Path]:
    if not (safe_z > approach_z > drill_z and drill_z < 0):
        raise DrillFileError("Требуется z-safe > z-approach > z-drill и z-drill < 0")
    if feed <= 0 or spindle <= 0 or dwell < 0:
        raise DrillFileError("Feed, spindle должны быть положительными, dwell >= 0")
    if not source.is_file():
        raise DrillFileError(f"Файл не найден: {source}")
    holes, slots = read_drills(source)
    if slots and not skip_slots:
        raise DrillFileError(
            f"Обнаружены фрезеруемые пазы/слоты ({slots}). "
            "Для генерации только круглых отверстий добавьте --skip-slots. "
            "Слоты не превратятся в сверление!"
        )
    if slots:
        print(f"ВНИМАНИЕ: пропущено {slots} сегментов пазов; обрабатываются только круглые отверстия.")
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for diameter, points in sorted(holes.items()):
        # Same diameter across several T numbers can be machined with one drill bit.
        diameter_label = f"{diameter:.3f}".replace(".", "p")
        out = output_dir / f"{source.stem}_{diameter_label}mm.tap"
        out.write_text(make_gcode(points, safe_z, approach_z, drill_z, feed, spindle, dwell),
                       encoding="ascii", newline="\n")
        print(f"{out.name}: диаметр {diameter:.3f} мм, отверстий {len(points)}")
        files.append(out)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="KiCad DRL -> GRBL TAP для CNC3018; отдельный TAP на диаметр сверла"
    )
    parser.add_argument("drl", type=Path, help="Входной KiCad Excellon .drl")
    parser.add_argument("--output-dir", type=Path, help="Каталог с TAP (по умолчанию рядом с DRL)")
    parser.add_argument("--z-safe", type=float, default=5.0, help="Безопасная Z, мм [5]")
    parser.add_argument("--z-approach", type=float, default=0.5, help="Z перед погружением, мм [0.5]")
    parser.add_argument("--z-drill", type=float, default=-2.4, help="Глубина сверления, мм [-2.4]")
    parser.add_argument("--feed", type=float, default=50, help="Подача по Z, мм/мин [50]")
    parser.add_argument("--spindle", type=int, default=10000, help="Команда GRBL S [10000], сверить с $30")
    parser.add_argument("--dwell", type=float, default=2, help="Пауза раскрутки шпинделя, сек [2]")
    parser.add_argument("--skip-slots", action="store_true", help="Пропустить фрезеруемые пазы с предупреждением")
    args = parser.parse_args(argv)
    try:
        outputs = convert(args.drl, args.output_dir or args.drl.parent,
                          safe_z=args.z_safe, approach_z=args.z_approach,
                          drill_z=args.z_drill, feed=args.feed,
                          spindle=args.spindle, dwell=args.dwell,
                          skip_slots=args.skip_slots)
    except (DrillFileError, OSError, UnicodeError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    print(f"Готово: {len(outputs)} TAP-файлов. Проверьте траектории в Candle/UGS ДО запуска станка.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
