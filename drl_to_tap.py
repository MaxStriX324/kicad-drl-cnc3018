#!/usr/bin/env python3
"""Convert KiCad Excellon drills and routed contours into a single GRBL TAP.

One continuous spindle run and one *physical* drill bit. Original Excellon
tool diameters are annotations, NOT automatic tool changes.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from math import ceil, hypot, isfinite
from pathlib import Path
import re
import sys


def configure_console_encoding() -> None:
    """Keep Cyrillic diagnostics usable on Windows consoles and CI pipes."""
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            else:
                stream.reconfigure(errors="backslashreplace")
        except (OSError, ValueError):
            pass


configure_console_encoding()

TOOL_DEF = re.compile(r"^T(\d+)C(\d+(?:\.\d+)?)$", re.I)
TOOL_CHANGE = re.compile(r"^T(\d+)$", re.I)
XY_MOVE = re.compile(r"^X([+-]?\d+(?:\.\d+)?)Y([+-]?\d+(?:\.\d+)?)$", re.I)
FORMAT = re.compile(r"FORMAT=\{\s*\d+\s*:\s*(\d+)", re.I)
ROUTE_MOVE = re.compile(r"^G0?([01])((?:[XY][+-]?\d+(?:\.\d+)?){0,2})$", re.I)
AXIS = re.compile(r"([XY])([+-]?\d+(?:\.\d+)?)", re.I)
MAX_CONTOUR_POINTS = 20000


class DrillFileError(ValueError):
    """Unsupported or invalid Excellon drill file."""


def decode_coordinate(raw: str, digits_after_decimal: int) -> float:
    if "." in raw:
        return float(raw)
    return int(raw) / (10 ** digits_after_decimal)


def parse_axes(raw: str, previous: tuple[float, float] | None,
               decimals: int | None, lineno: int) -> tuple[float, float]:
    """Resolve Excellon modal X/Y with scale validation."""
    tokens = AXIS.findall(raw)
    if not tokens or "".join(a + v for a, v in tokens).upper() != raw.upper():
        raise DrillFileError(f"Строка {lineno}: неправильные координаты: {raw}")
    values: dict[str, float] = {}
    for axis, value in tokens:
        axis = axis.upper()
        if axis in values:
            raise DrillFileError(f"Строка {lineno}: повторена ось {axis}")
        if decimals is None and "." not in value:
            raise DrillFileError("В DRL отсутствует FORMAT={3:3/...}; масштаб координат неизвестен")
        values[axis] = decode_coordinate(value, decimals or 0)
    x = values.get("X", previous[0] if previous is not None else None)
    y = values.get("Y", previous[1] if previous is not None else None)
    if x is None or y is None:
        raise DrillFileError(f"Строка {lineno}: не задана исходная координата X/Y")
    if not isfinite(x) or not isfinite(y):
        raise DrillFileError(f"Строка {lineno}: недопустимые координаты")
    return x, y


def segment_points(start: tuple[float, float], end: tuple[float, float],
                   step: float) -> list[tuple[float, float]]:
    """Sample *cutting* segments only, including both endpoints."""
    distance = hypot(end[0] - start[0], end[1] - start[1])
    count = max(1, ceil(distance / step))
    if count + 1 > MAX_CONTOUR_POINTS:
        raise DrillFileError("Слишком длинный контур/слишком мелкий шаг сверления")
    return [(start[0] + (end[0] - start[0]) * i / count,
             start[1] + (end[1] - start[1]) * i / count)
            for i in range(count + 1)]


def read_drills(path: Path, *,
                contour_step: float | None = None,
                stats: dict[str, int] | None = None
                ) -> tuple[dict[float, list[tuple[float, float]]], int]:
    """Return points grouped by declared diameter; optional contour perforation."""
    if contour_step is not None and (not isfinite(contour_step) or contour_step <= 0):
        raise DrillFileError("Шаг сверления контура должен быть положительным числом")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    tools: dict[int, float] = {}
    holes: dict[float, list[tuple[float, float]]] = defaultdict(list)
    decimals: int | None = None
    current_tool: int | None = None
    in_body = False
    routing = False
    route_pos: tuple[float, float] | None = None
    last_drill: tuple[float, float] | None = None
    slots = 0
    round_holes = 0
    contour_points = 0
    units = None
    zero_suppression = False

    def add_slot(start: tuple[float, float], end: tuple[float, float], line_no: int) -> None:
        nonlocal slots, contour_points
        if current_tool is None:
            raise DrillFileError(f"Строка {line_no}: фрезеровка без выбранного инструмента")
        slots += 1
        if contour_step is None:
            return
        points = segment_points(start, end, contour_step)
        # Limit the total program size, not just individual route segments.
        if contour_points + len(points) > MAX_CONTOUR_POINTS:
            raise DrillFileError(f"Более {MAX_CONTOUR_POINTS} точек контура: увеличьте --contour-step")
        holes[tools[current_tool]].extend(points)
        contour_points += len(points)

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
            route_pos = None
            continue
        tool_change = TOOL_CHANGE.fullmatch(line)
        if tool_change:
            current_tool = int(tool_change.group(1))
            if current_tool not in tools:
                raise DrillFileError(f"Строка {number}: неизвестный инструмент T{current_tool}")
            routing = False
            route_pos = None
            continue

        route = ROUTE_MOVE.fullmatch(uline)
        if route:
            kind, coords = route.groups()
            if kind == "0":
                routing = True
                route_pos = parse_axes(coords, route_pos, decimals, number) if coords else None
            else:
                if not routing or route_pos is None or not coords:
                    raise DrillFileError(f"Строка {number}: G01 без начальной точки G00")
                end = parse_axes(coords, route_pos, decimals, number)
                add_slot(route_pos, end, number)
                route_pos = end
            continue

        # Excellon G85 slots: XstartYstartG85XendYend; or G85XendYend
        if "G85" in uline:
            if uline.count("G85") != 1:
                raise DrillFileError(f"Строка {number}: неподдерживаемая команда {line}")
            raw_start, raw_end = uline.split("G85")
            if not raw_end:
                raise DrillFileError(f"Строка {number}: G85 без конечной точки")
            start = parse_axes(raw_start, last_drill, decimals, number) if raw_start else last_drill
            if start is None:
                raise DrillFileError(f"Строка {number}: G85 без начальной точки")
            end = parse_axes(raw_end, start, decimals, number)
            add_slot(start, end, number)
            last_drill = end
            continue

        if uline in ("M15", "M16", "M48", "G04"):
            continue
        xy = XY_MOVE.fullmatch(line)
        if xy:
            if routing:
                raise DrillFileError(f"Строка {number}: координаты маршрута без G05")
            if current_tool is None:
                raise DrillFileError(f"Строка {number}: координата без выбранного инструмента")
            point = parse_axes(uline, last_drill, decimals, number)
            holes[tools[current_tool]].append(point)
            last_drill = point
            round_holes += 1
            continue
        if uline.startswith(("X", "Y", "G", "T")):
            raise DrillFileError(f"Строка {number}: неподдерживаемая команда {line}")

    if units != "mm":
        raise DrillFileError("Поддерживаются только метрические DRL (METRIC / M71)")
    if zero_suppression:
        raise DrillFileError("LZ/TZ с подавлением нулей пока не поддерживается; в KiCad включите keep zeros")
    if not tools or not holes:
        if slots:
            raise DrillFileError(f"Найдены только {slots} сегментов пазов. "
                                 "Включите сверление контура или добавьте круглые отверстия")
        raise DrillFileError("Не найдены определения инструментов или круглые отверстия")
    if stats is not None:
        stats["holes"] = round_holes
        stats["slots"] = slots
        stats["contour_points"] = contour_points
        stats["diameters"] = len(holes)
    return dict(holes), slots


def xy_travel_length(points: list[tuple[float, float]]) -> float:
    """XY-only air travel between drill positions (excluding an unknown work origin)."""
    return sum(hypot(x2 - x1, y2 - y1)
               for (x1, y1), (x2, y2) in zip(points, points[1:]))


def order_vertical(points: list[tuple[float, float]],
                   column_width: float = 1.0) -> list[tuple[float, float]]:
    """Sweep left-to-right in vertical X stripes, minimizing Y turnarounds.

    Within each stripe the Y sequence is monotonic, either bottom-up or
    top-down. Dynamic programming chooses the orientations that minimize the
    sum of XY travel within and between stripes. Never increases travel
    compared with the basic X-then-Y vertical order.
    """
    if not isfinite(column_width) or column_width <= 0:
        raise DrillFileError("Ширина вертикальной полосы должна быть положительной")
    if len(points) < 2:
        return list(points)

    min_x = min(x for x, _ in points)
    columns: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for point in points:
        idx = int((point[0] - min_x) // column_width)
        columns[idx].append(point)
    stripes = [
        sorted(columns[idx], key=lambda p: (p[1], p[0]))
        for idx in sorted(columns)
    ]
    internal = [xy_travel_length(stripe) for stripe in stripes]
    # Direction 0 = bottom-up, 1 = top-down.
    scores = [internal[0], internal[0]]
    parents: list[list[int]] = [[-1, -1]]
    for idx in range(1, len(stripes)):
        previous, current = stripes[idx - 1], stripes[idx]
        current_scores: list[float] = []
        current_parents: list[int] = []
        for direction in (0, 1):
            start = current[0] if direction == 0 else current[-1]
            choices: list[float] = []
            for prev_dir in (0, 1):
                end = previous[-1] if prev_dir == 0 else previous[0]
                choices.append(scores[prev_dir] +
                               hypot(start[0] - end[0], start[1] - end[1]))
            winner = min(range(2), key=lambda prev_dir: (choices[prev_dir], prev_dir))
            current_parents.append(winner)
            current_scores.append(choices[winner] + internal[idx])
        scores = current_scores
        parents.append(current_parents)

    direction = min(range(2), key=lambda d: (scores[d], d))
    directions = [0] * len(stripes)
    for idx in range(len(stripes) - 1, -1, -1):
        directions[idx] = direction
        direction = parents[idx][direction]

    optimized: list[tuple[float, float]] = []
    for stripe, direction in zip(stripes, directions):
        optimized.extend(stripe if direction == 0 else reversed(stripe))

    # A narrow stripe can contain slanted contour points. Keep the vertical
    # X-major ordering when it happens to require less XY movement.
    x_major = sorted(points, key=lambda p: (p[0], p[1]))
    if xy_travel_length(x_major) + 1e-9 < xy_travel_length(optimized):
        return x_major
    return optimized


def make_gcode(points: list[tuple[float, float]], safe_z: float, approach_z: float,
               drill_z: float, feed: float, spindle: int, dwell: float = 0) -> str:
    """One spindle start and stop; no M0/M1/M6, no G4 dwell."""
    lines = [
        "; KiCad Excellon -> GRBL | DRILL-ONLY, one physical bit",
        "; Different original drill diameters are NOT automatic tool changes.",
        "; Verify the selected bit against EVERY requested diameter.",
        "G21", "G90", "G94", f"G0 Z{safe_z:.3f}",
        f"M3 S{spindle}",
    ]
    for x, y in points:
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
            feed: float = 50.0, spindle: int = 10000, dwell: float = 0.0,
            skip_slots: bool | None = None, contour_step: float = 1.0,
            column_width: float = 1.0,
            stats: dict[str, int | float] | None = None) -> list[Path]:
    if not all(isfinite(v) for v in (safe_z, approach_z, drill_z, feed, dwell, contour_step)):
        raise DrillFileError("Параметры перемещений должны быть конечными числами")
    if not (safe_z > approach_z > drill_z and drill_z < 0):
        raise DrillFileError("Требуется z-safe > z-approach > z-drill и z-drill < 0")
    if feed <= 0 or spindle <= 0 or contour_step <= 0:
        raise DrillFileError("Feed, spindle и contour-step должны быть положительными")
    if not isfinite(column_width) or column_width <= 0:
        raise DrillFileError("Ширина вертикальной полосы должна быть положительной")
    if dwell < 0:
        raise DrillFileError("Dwell должен быть неотрицательным; G4 в TAP не добавляется")
    if not source.is_file():
        raise DrillFileError(f"Файл не найден: {source}")

    # None: drill G01/G85 route contours; True: ignore; False: error.
    values: dict[str, int] = {}
    holes, slots = read_drills(source, contour_step=contour_step if skip_slots is None else None,
                               stats=values)
    if slots and skip_slots is False:
        raise DrillFileError(f"Обнаружены фрезеруемые пазы/слоты ({slots}); задан --strict-slots")

    # Merge all diameters into ONE output and deduplicate exact millimetre positions.
    points: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for diameter, coords in sorted(holes.items()):
        if not isfinite(diameter) or diameter <= 0:
            raise DrillFileError("Некорректный диаметр инструмента")
        for x, y in sorted(coords, key=lambda p: (p[0], p[1])):
            position = (round(x, 3), round(y, 3))
            if position not in seen:
                seen.add(position)
                points.append(position)
    if not points:
        raise DrillFileError("Нет точек сверления")

    # Optimize all round holes and perforation points together. Sorting does
    # not change positions, depth, number of drills, or the generated G-code.
    previous_xy = xy_travel_length(points)
    points = order_vertical(points, column_width=column_width)
    optimized_xy = xy_travel_length(points)
    if stats is not None:
        stats.update(values)
        stats["drill_positions"] = len(points)
        stats["xy_before_mm"] = round(previous_xy, 3)
        stats["xy_after_mm"] = round(optimized_xy, 3)
    print(f"Вертикальный проход: полосы по X шириной {column_width:g} мм; "
          f"холостые XY: {previous_xy:.1f} -> {optimized_xy:.1f} мм")
    if len(holes) > 1:
        print(f"ВНИМАНИЕ: в DRL {len(holes)} диаметров. В одном TAP нет смены инструмента!"
              " Фактический диаметр отверстий определяется установленным сверлом.")
    if slots:
        if skip_slots is None:
            print(f"Контур: {slots} режущих сегментов, {values['contour_points']} точек до удаления дублей"
                  f" (шаг не более {contour_step:g} мм)")
        else:
            print(f"Пазы пропущены: {slots} сегментов")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{source.stem}.tap"
    temp = output.with_suffix(".tap.tmp")
    try:
        temp.write_text(make_gcode(points, safe_z, approach_z, drill_z, feed, spindle),
                        encoding="ascii", newline="\n")
        temp.replace(output)
    finally:
        if temp.exists():
            temp.unlink()
    print(f"{output.name}: {len(points)} позиций, 1 TAP, без G4/M6/M0")
    return [output]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", type=Path, help="Каталог с TAP (по умолчанию рядом с DRL)")
    parser.add_argument("--z-safe", type=float, default=5.0)
    parser.add_argument("--z-approach", type=float, default=0.5)
    parser.add_argument("--z-drill", type=float, default=-2.4)
    parser.add_argument("--feed", type=float, default=50.0)
    parser.add_argument("--spindle", type=int, default=10000)
    parser.add_argument("--dwell", type=float, default=0.0,
                        help="Совместимость: параметр игнорируется, пауз G4 нет")
    parser.add_argument("--contour-step", type=float, default=1.0,
                        help="Максимальный шаг отверстий вдоль G01/G85 (мм), по умолчанию 1")
    parser.add_argument("--column-width", type=float, default=1.0,
                        help="Ширина вертикальных полос для сортировки по Y, мм [1]")
    route_mode = parser.add_mutually_exclusive_group()
    route_mode.add_argument("--skip-slots", dest="skip_slots", action="store_true",
                            help="Игнорировать все пазы/контуры")
    route_mode.add_argument("--strict-slots", dest="skip_slots", action="store_false",
                            help="Отменять конвертацию, если есть пазы/контуры")
    parser.set_defaults(skip_slots=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="KiCad DRL -> один GRBL TAP без смен сверла и пауз, с высверливанием контура"
    )
    parser.add_argument("drl", type=Path, help="Входной KiCad Excellon .drl")
    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        outputs = convert(args.drl, args.output_dir or args.drl.parent,
                          safe_z=args.z_safe, approach_z=args.z_approach,
                          drill_z=args.z_drill, feed=args.feed, spindle=args.spindle,
                          dwell=args.dwell, skip_slots=args.skip_slots,
                          contour_step=args.contour_step,
                          column_width=args.column_width)
    except (DrillFileError, OSError, UnicodeError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    print(f"Готово: {len(outputs)} TAP. Проверьте траекторию, установку сверла и глубину в Candle/UGS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
